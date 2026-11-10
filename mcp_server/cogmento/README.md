# CogMento CRM tool server

An MCP server (fastmcp, streamable HTTP) with idempotent tools for the CogMento / FreeCRM REST API (`/api/1/`), for
PinionAI agents: `upsert_contact`, `upsert_product`, `upsert_deal`, `set_deal_products`, `upsert_case`, `upsert_task`,
`upsert_event`, `update_record`, `add_note`, `sync_notes`, `attach_document`, `delete_contact`, `find_record`, `search`,
`apply_operations`, `apply_schema`.

- **Keys, not ids.** Every record is addressed by the integration's own key in the CRM's `aux_id` field (products by
  `sku`); a write finds the key and creates or updates, so replaying an event changes nothing new. Links (a deal's
  contact, a case's deal, a document's task) are given by keys too. A contact without the key but with the same e-mail
  (then phone) is taken over, so a visitor who later signs up stays one contact. Notes are idempotent with `ref`;
  `sync_notes` keeps a whole set (a timeline, a conversation) with one read of the record's notes.
- **Links must exist** by default: a write linked to a key the CRM does not have yet fails, so an event that arrives
  before its contact or deal is retried. `soft_links` (cases, tasks) leaves such a link out instead; `create=False`
  (deals, tasks) only updates a record that is already there (closing a review task that was never opened).
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
