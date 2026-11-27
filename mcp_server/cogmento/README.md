# CogMento CRM tool server

An MCP server (fastmcp, streamable HTTP) with idempotent tools for the CogMento / FreeCRM REST API (`/api/1/`), for
PinionAI agents: `upsert_contact`, `upsert_product`, `upsert_deal`, `set_deal_products`, `upsert_case`, `upsert_task`,
`upsert_event`, `upsert_call`, `update_record`, `add_note`, `sync_notes`, `attach_document`, `delete_contact`, `find_record`,
`search`, `apply_operations`, `apply_schema`.

- **Keys, not ids.** Every record is addressed by the integration's own key in the CRM's `aux_id` field (products by
  `sku`); a write finds the key and creates or updates, so replaying an event changes nothing new. Links (a deal's
  contact, a case's deal, a document's task) are given by keys too. A contact without the key but with the same e-mail
  (then phone) is taken over, so a visitor who later signs up stays one contact. Notes are idempotent with `ref`;
  `sync_notes` keeps a whole set (a timeline, a conversation) with one read of the record's notes.
- **Links must exist** by default: a write linked to a key the CRM does not have yet fails, so an event that arrives
  before its contact or deal is retried. `soft_links` (cases, tasks) leaves such a link out instead; `create=False`
  (deals, tasks) only updates a record that is already there (closing a review task that was never opened).
- **Events** (`upsert_event`) are calendar events, keyed like everything else. Two things the CRM does that its API
  description does not say, both handled here: `GET events/` is the calendar (events in a date range, with a filter of
  its own; it answers 500 to a search by key), so an event is found through the events grid, `GET events/query/`; and
  `start_date` / `end_date` are read as wall-clock time in the API user's time zone whatever offset is sent, so `start`
  and `end` must carry their UTC offset and the tool sends them shifted. The shift is taken from the event itself when
  the CRM already has it, else from the last event written with the same key of the same CRM, and is put right from the
  times the CRM answers it kept: one more write for the first new event after a start, and for one that lies across a
  daylight-saving change. Kept times the CRM does not answer are read back; an event whose kept times cannot be
  checked fails. One instant cannot be kept: a time in the hour a clock change repeats (01:00 to 02:00 on the night
  the clocks go back) is read as the first of its two occurrences, so the second is kept an hour early, where the
  CRM's calendar shows the same clock time, and the answer says so in `time_note` (the batch goes on).
- **One CRM user for events.** The events grid lists an event only to its creator, its participants and the members
  of its calendar, unless the user may see all data (the CRM's *Data Administrator* role, `accounts.view_all_data`).
  The tool finds its own events, since it created them. A key of another CRM user without that role would not find
  them and would create each event a second time: keep one API user for the integration, or give the new one the role
  before changing keys. Other records are found by any user as long as they are not private.
- **Calls** (`upsert_call`) are real call records on the contact's Calls tab, keyed like everything else. Four things
  the CRM does that its API description does not say, all handled here: a write needs the `assigned_to` key (empty means
  the API user); `call_time` is read as wall-clock time in the API user's time zone whatever offset is sent, so the
  tool sends it shifted and learns the shift from the time the CRM stored; a participant is attached through the
  contact's phone number, and a contact without one is silently left out (reported as a failure, so the event is tried
  again); `duration` is kept only when the API user has the `telephony_bypass` setting, so the seconds also go in
  custom fields. Sending participants replaces them, which is how a phone lead's call moves to the customer's contact.
  `delete_contact` purges the contact's calls itself, because the CRM's own purge leaves them, and takes them and the
  contact's documents from the contact record (the CRM answers 500 to a search of documents by contact). The older `log_call`
  (a call as a note on the contact) is superseded and kept only for installs that still send it.
- **Batches:** `apply_operations` runs a list of `{"op": "<tool>", ...arguments}` in order and stops at the first
  failure with its position. A PinionAI merger (output type json) builds the list from an event and a direct MCP step
  (`"_tool": "apply_operations"`) sends it, with no model in between; see City Auto's `deploy/pinion-bootstrap/crm_sync/`.
- **No credentials of its own.** Each request names the CRM with `X-CRM-Base-Url` (default `COGMENTO_BASE_URL`) and
  sends the caller's `Authorization: Token <key>`; a PinionAI MCP row fills it from an API Key connector with auth
  scheme `Token`.
- **Documents** are downloaded by `attach_document` from hosts in `COGMENTO_FILE_HOSTS` only (default
  `127.0.0.1:4000,localhost:4000`), at most 25 MB, and uploaded to the CRM. A document already under its key keeps its
  file and gets its title and fields (a review status) updated; `skip_unavailable` reports a file that is gone (404) or
  too large instead of failing the batch.
- **Retries:** CRM 5xx answers and network errors are retried with backoff; 4xx answers fail the call.

Run it on the loopback (the `pinionai-crm-tools` container uses the Studio image):

```bash
python -m mcp_server.cogmento serve  # COGMENTO_HOST=127.0.0.1 COGMENTO_PORT=8090
COGMENTO_BASE_URL=http://127.0.0.1:8002 COGMENTO_TOKEN=... python -m mcp_server.cogmento apply-schema spec.json [--dry-run]
```

`apply-schema` adds or edits template fields (custom fields, option lists such as deal stages) and creates named calendars; see City Auto's `deploy/pinion-bootstrap/crm_schema.json` for an example. Tests: `tests/test_cogmento_tools.py`.
