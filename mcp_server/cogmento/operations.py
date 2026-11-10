"""Idempotent CRM operations behind the CogMento tool server.

Every record an integration writes is addressed by its own key (`aux_id`; for products the `sku`), so replaying an
event changes nothing new. Links between records (a deal's contact, a case's deal, a document's task…) are given by
those keys as well and resolved to CRM ids here.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .client import CogmentoClient, CrmError

logger = logging.getLogger(__name__)

MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
REF_RE = re.compile(r"\[ref:([^\]]+)\]")


def allowed_file_hosts() -> set[str]:
    """Hosts `attach_document` may download from (host:port), e.g. the City Auto platform on the loopback."""
    raw = os.environ.get("COGMENTO_FILE_HOSTS", "127.0.0.1:4000,localhost:4000")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


# a key that turned out to name another record (a ca:phone:<n> lead key whose number a customer's contact carries): later
# operations in the batch with that key reach the record it named; apply_operations starts every batch with an empty map
KEY_ALIASES: dict[str, str] = {}
PLACEHOLDER_NAMES = {"anonymous", "caller", "customer", "visitor", "-", ""}


async def record_id(client: CogmentoClient, record_type: str, key: str | None) -> str | None:
    """The CRM id of the record with this key (products: sku), or None."""
    if not key:
        return None
    key = KEY_ALIASES.get(f"{record_type}:{key}", key)
    found = await client.find_one(record_type, "sku" if record_type == "product" else "aux_id", key)
    return found["id"] if found else None


async def _require(client: CogmentoClient, record_type: str, key: str | None, soft: bool = False) -> str | None:
    """The CRM id of a linked record. A missing one raises (the event is retried once the record has been written),
    unless `soft`, when the link is left out."""
    if not key:
        return None
    rid = await record_id(client, record_type, key)
    if not rid and not soft:
        raise CrmError(f"no {record_type} with key {key!r} in the CRM yet")
    return rid


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fields.items() if v is not None}


# ----- contacts -----
async def upsert_contact(client: CogmentoClient, key: str, first_name: str, last_name: str = "", email: str | None = None,
                         phone: str | None = None, category: str | None = None, do_not_call: bool | None = None,
                         do_not_text: bool | None = None, do_not_email: bool | None = None, tags: list[str] | None = None,
                         fields: dict[str, Any] | None = None, name_if_placeholder: bool = False, merge_tags: bool = False) -> dict[str, Any]:
    """Creates or updates the contact with this key. A contact without the key but with the same e-mail (then phone) is
    taken over and given the key, so a visitor who later signs up stays one contact — except that a phone key
    (ca:phone:<number>, a lead) never takes over a contact that has a person key (ca:person:<e-mail>, a customer):
    that contact keeps its name and key, gains the tags and fields, and the key is aliased to it for the rest of the
    batch (`kept_key` in the answer). `name_if_placeholder`: an existing name that is not a placeholder ("Anonymous",
    "Caller", …) is kept, so a specialist's edit survives a sync; `merge_tags`: the tags are added to the contact's, not
    replaced."""
    existing = await client.find_one("contact", "aux_id", key)
    if not existing and email:
        existing = await client.find_one("contact", "email", email.lower())
    found_by_phone = False
    if not existing and phone:
        existing = await client.find_one("contact", "phone", phone)
        found_by_phone = existing is not None
    kept_key = None
    if found_by_phone and key.startswith("ca:phone:") and str(existing.get("aux_id") or "").startswith("ca:person:"):
        kept_key = existing["aux_id"]
        KEY_ALIASES[f"contact:{key}"] = kept_key
    body = _clean({
        "first_name": first_name or (email.split("@")[0] if email else "Customer"), "last_name": last_name or "-",
        "email": email.lower() if email else None, "phone": phone, "category": category, "do_not_call": do_not_call,
        "do_not_text": do_not_text, "do_not_email": do_not_email, "tags": tags, **(fields or {}), "aux_id": key,
    })
    if existing:
        if kept_key:
            for k in ("first_name", "last_name", "email", "aux_id"):
                body.pop(k, None)
        elif name_if_placeholder and str(existing.get("first_name") or "").strip().lower() not in PLACEHOLDER_NAMES:
            body.pop("first_name", None); body.pop("last_name", None)
        if (merge_tags or kept_key) and tags is not None:
            have = [t.get("name") if isinstance(t, dict) else t for t in (existing.get("tags") or [])]
            body["tags"] = list(dict.fromkeys([*[h for h in have if h], *tags]))
        record = await client.update("contact", existing["id"], body)
        return {"id": existing["id"], "created": False, "record": record, **({"kept_key": kept_key} if kept_key else {})}
    record = await client.create("contact", body)
    return {"id": record.get("id"), "created": True, "record": record}


# ----- products -----
async def upsert_product(client: CogmentoClient, sku: str, name: str, list_price: float | None = None, description: str | None = None,
                         category: str | None = None, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _clean({"name": name, "list_price": list_price, "description": description, "category": category, **(fields or {})})
    record, created = await client.upsert("product", "sku", sku, body)
    return {"id": record.get("id"), "created": created}


# ----- deals -----
async def upsert_deal(client: CogmentoClient, key: str, title: str | None = None, contact_key: str | None = None, stage: str | None = None,
                      amount: float | None = None, closed: bool | None = None, close_date: str | None = None,
                      description: str | None = None, tags: list[str] | None = None, fields: dict[str, Any] | None = None,
                      create: bool = True, other_contact_keys: list[str] | None = None) -> dict[str, Any]:
    """Creates or updates the deal with this key; with `create=False` only an existing deal is updated (e.g. closing a
    customer's interest deal when they buy, if there is one). `other_contact_keys` link more people (a co-buyer)."""
    if not create and not await record_id(client, "deal", key):
        return {"id": None, "created": False, "skipped": True}
    if create and not title:
        raise CrmError("a new deal needs a title")
    contact_ids = [await _require(client, "contact", k) for k in [contact_key, *(other_contact_keys or [])] if k]
    body = _clean({"title": title, "stage": stage, "amount": amount, "closed": closed, "close_date": close_date,
                   "description": description, "tags": tags, **(fields or {})})
    if contact_ids:
        body["contacts"] = [{"id": cid} for cid in dict.fromkeys(contact_ids)]
    record, created = await client.upsert("deal", "aux_id", key, body)
    return {"id": record.get("id"), "created": created}


async def set_deal_products(client: CogmentoClient, deal_key: str, skus: list[str], replace: bool = False,
                            amounts: dict[str, float] | None = None, new_products: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Links products (by sku) to the deal. Missing links are added; with `replace`, links not in `skus` are removed.
    A sku with no product yet is created from `new_products[sku]` (e.g. {"name": ...}) when given, else reported."""
    deal_id = await _require(client, "deal", deal_key)
    current = await client.deal_products(deal_id)
    linked = {str((dp.get("product") or {}).get("sku") or ""): dp for dp in current}
    added, missing = [], []
    for sku in dict.fromkeys(s for s in skus if s):
        if sku in linked:
            continue
        product_id = await record_id(client, "product", sku)
        if not product_id and (new_products or {}).get(sku):
            product_id = (await client.create("product", {**_clean(new_products[sku]), "sku": sku})).get("id")
        if not product_id:
            missing.append(sku)
            continue
        await client.add_deal_product(deal_id, product_id, amount=(amounts or {}).get(sku))
        added.append(sku)
    removed = []
    if replace:
        wanted = set(skus)
        for sku, dp in linked.items():
            if sku not in wanted:
                await client.remove_deal_product(deal_id, dp["id"])
                removed.append(sku)
    return {"deal_id": deal_id, "added": added, "removed": removed, "missing": missing}


# ----- cases, tasks, events -----
async def upsert_case(client: CogmentoClient, key: str, title: str, contact_key: str | None = None, deal_key: str | None = None,
                      status: str | None = None, case_type: str | None = None, priority: str | None = None,
                      description: str | None = None, close_date: str | None = None, deadline: str | None = None,
                      fields: dict[str, Any] | None = None, soft_links: bool = False) -> dict[str, Any]:
    """Creates or updates the case with this key; with `soft_links`, a contact or deal not in the CRM is left unlinked."""
    contact_id = await _require(client, "contact", contact_key, soft_links)
    deal_id = await _require(client, "deal", deal_key, soft_links)
    body = _clean({"title": title, "status": status, "type": case_type, "priority": priority, "description": description,
                   "close_date": close_date, "deadline": deadline, **(fields or {})})
    if contact_id:
        body["contact"] = {"id": contact_id}
    if deal_id:
        body["deal"] = {"id": deal_id}
    record, created = await client.upsert("case", "aux_id", key, body)
    return {"id": record.get("id"), "created": created}


async def upsert_task(client: CogmentoClient, key: str, title: str, contact_key: str | None = None, deal_key: str | None = None,
                      case_key: str | None = None, due_date: str | None = None, status: str | None = None,
                      task_type: str | None = None, priority: str | None = None, description: str | None = None,
                      done: bool = False, fields: dict[str, Any] | None = None, create: bool = True,
                      soft_links: bool = False) -> dict[str, Any]:
    """Creates or updates the task with this key, completed when `done`. With `create=False` only an existing task is
    updated (closing a review task that may never have been opened); with `soft_links`, missing linked records are
    left unlinked."""
    if not create and not await record_id(client, "task", key):
        return {"id": None, "created": False, "skipped": True}
    contact_id = await _require(client, "contact", contact_key, soft_links)
    deal_id = await _require(client, "deal", deal_key, soft_links)
    case_id = await _require(client, "case", case_key, soft_links)
    body = _clean({"title": title, "due_date": due_date, "status": status, "type": task_type, "priority": priority,
                   "description": description, **(fields or {})})
    for name, rid in (("contact", contact_id), ("deal", deal_id), ("case", case_id)):
        if rid:
            body[name] = {"id": rid}
    record, created = await client.upsert("task", "aux_id", key, body)
    task_id = record.get("id")
    if done and task_id and not record.get("close_date"):
        await client.request("POST", f"tasks/{task_id}/complete/")
    return {"id": task_id, "created": created}


async def calendar_id(client: CogmentoClient, name: str | None) -> str:
    calendars = await client.calendars()
    if name:
        for cal in calendars:
            if (cal.get("name") or "").strip().lower() == name.strip().lower():
                return cal["id"]
        created = await client.create_calendar(name)
        if created.get("id"):
            return created["id"]
        calendars = await client.calendars()
        for cal in calendars:
            if (cal.get("name") or "").strip().lower() == name.strip().lower():
                return cal["id"]
    if not calendars:
        raise CrmError("the CRM user has no calendar")
    return calendars[0]["id"]


async def upsert_event(client: CogmentoClient, key: str, title: str, start: str, end: str, calendar: str | None = None,
                       deal_key: str | None = None, case_key: str | None = None, description: str | None = None,
                       location: str | None = None, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    body = _clean({"title": title, "start_date": start, "end_date": end, "description": description, "location": location,
                   "calendar": await calendar_id(client, calendar), **(fields or {})})
    for name, rtype, k in (("deal", "deal", deal_key), ("case", "case", case_key)):
        rid = await _require(client, rtype, k)
        if rid:
            body[name] = {"id": rid}
    record, created = await client.upsert("event", "aux_id", key, body)
    return {"id": record.get("id"), "created": created}


async def update_record(client: CogmentoClient, record_type: str, key: str, fields: dict[str, Any], soft: bool = False) -> dict[str, Any]:
    """Sets fields on the record with this key and nothing else (e.g. a triage agent's own fields on a case another
    flow wrote). A missing record fails, or with `soft` is skipped; fields with a null value are left as they are."""
    rid = await _require(client, record_type, key, soft)
    if not rid:
        return {"id": None, "updated": False, "skipped": True}
    changes = _clean(fields or {})
    if changes:
        await client.update(record_type, rid, changes)
    return {"id": rid, "updated": bool(changes)}


# ----- notes -----
async def add_note(client: CogmentoClient, record_type: str, key: str, text: str, ref: str | None = None) -> dict[str, Any]:
    """Adds a note to the record with this key. With `ref`, the note carries `[ref:<ref>]` and a note with the same ref is
    updated instead of duplicated."""
    rid = await _require(client, record_type, key)
    content = f"{text}\n[ref:{ref}]" if ref else text
    if ref:
        for note in await client.notes(record_type, rid):
            body = note.get("note") or note.get("content") or ""
            if f"[ref:{ref}]" in body:
                if body != content:
                    await client.add_note(record_type, rid, content, note_id=note["id"])
                return {"id": note["id"], "created": False}
    note = await client.add_note(record_type, rid, content)
    return {"id": note.get("id"), "created": True}


async def sync_notes(client: CogmentoClient, record_type: str, key: str, notes: list[dict[str, Any]], soft: bool = False) -> dict[str, Any]:
    """Keeps a set of notes on the record, each `{"ref": ..., "text": ...}`: missing ones are added and changed ones
    updated, with one read of the record's notes (a timeline or a conversation, replayed on every change). With `soft`,
    a record the CRM does not have is skipped instead of failing."""
    rid = await _require(client, record_type, key, soft)
    if not rid:
        return {"added": 0, "updated": 0, "skipped": True}
    existing: dict[str, dict[str, Any]] = {}
    for note in await client.notes(record_type, rid):
        match = REF_RE.search(note.get("note") or note.get("content") or "")
        if match:
            existing.setdefault(match.group(1), note)
    added = updated = 0
    for item in notes or []:
        if not item or not item.get("ref") or not item.get("text"):
            continue
        content = f"{item['text']}\n[ref:{item['ref']}]"
        note = existing.get(str(item["ref"]))
        if note is None:
            await client.add_note(record_type, rid, content)
            added += 1
        elif (note.get("note") or note.get("content") or "") != content:
            await client.add_note(record_type, rid, content, note_id=note["id"])
            updated += 1
    return {"added": added, "updated": updated}


# ----- documents -----
async def attach_document(client: CogmentoClient, key: str, url: str, title: str, filename: str | None = None,
                          contact_key: str | None = None, deal_key: str | None = None, case_key: str | None = None,
                          task_key: str | None = None, replace: bool = False, fields: dict[str, Any] | None = None,
                          skip_unavailable: bool = False) -> dict[str, Any]:
    """Copies a file into the CRM as a document linked to the given records. The file is downloaded from `url`, which must
    be on an allowed host. A document already stored under this key keeps its file unless `replace`; its title and
    `fields` (a review status) are brought up to date. With `skip_unavailable`, a file that is gone (404) or too large
    is reported as skipped instead of failing, so one lost file does not hold back the rest of a record."""
    existing = await client.find_one("document", "aux_id", key)
    if existing and not replace:
        changes = {k: v for k, v in _clean({"title": title, **(fields or {})}).items() if existing.get(k) != v}
        if changes:
            await client.update("document", existing["id"], changes)
        return {"id": existing["id"], "created": False, "updated": bool(changes)}
    host = urlsplit(url).netloc.lower()
    if host not in allowed_file_hosts():
        raise CrmError(f"downloads from {host!r} are not allowed (COGMENTO_FILE_HOSTS)")
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as http:
        response = await http.get(url)
    if response.status_code == 404 and skip_unavailable:
        return {"id": None, "created": False, "skipped": "file not found"}
    if response.status_code != 200:
        raise CrmError(f"the file could not be downloaded ({response.status_code})", response.status_code)
    content = response.content
    if len(content) > MAX_DOCUMENT_BYTES:
        if skip_unavailable:
            return {"id": None, "created": False, "skipped": "file too large"}
        raise CrmError(f"the file is larger than {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB")
    name = filename or urlsplit(url).path.rsplit("/", 1)[-1] or "document"
    content_type = response.headers.get("content-type", "").split(";")[0] or mimetypes.guess_type(name)[0] or "application/octet-stream"
    links: dict[str, Any] = {}
    for link, rtype, k in (("contact", "contact", contact_key), ("deal", "deal", deal_key), ("case", "case", case_key), ("task", "task", task_key)):
        rid = await _require(client, rtype, k)
        if rid:
            links[link] = rid
    if existing:
        await client.delete("document", existing["id"])
    record = await client.upload_document({"title": title, "aux_id": key, **links, **(fields or {})}, name, content, content_type)
    return {"id": record.get("id"), "created": True}


# ----- privacy -----
async def delete_contact(client: CogmentoClient, key: str) -> dict[str, Any]:
    """Purges the contact with this key and the documents, tasks, cases and deals linked only to it."""
    contact_id = await record_id(client, "contact", key)
    if not contact_id:
        return {"deleted": False}
    removed: dict[str, int] = {}
    for record_type, field in (("document", "contact"), ("task", "contact"), ("case", "contact")):
        for rec in await client.find(record_type, field, contact_id, limit=1000):
            await client.delete(record_type, rec["id"])
            removed[record_type] = removed.get(record_type, 0) + 1
    for deal in await client.find("deal", "contacts", contact_id, limit=1000):
        others = [c for c in (deal.get("contacts") or []) if (c.get("id") if isinstance(c, dict) else c) != contact_id]
        if not others:
            await client.delete("deal", deal["id"])
            removed["deal"] = removed.get("deal", 0) + 1
    await client.delete("contact", contact_id)
    return {"deleted": True, "removed": removed}


# ----- schema -----
async def apply_schema(client: CogmentoClient, spec: dict[str, Any]) -> dict[str, Any]:
    """Adds or edits template fields (custom fields, option lists) and makes sure the named calendars exist.

    spec = {"fields": {"deal": [{"name": "deal_kind", "label": "Kind", "type": "options", "options": [...]}, ...]},
            "calendars": ["City Auto appointments"]}
    """
    applied: dict[str, list[str]] = {}
    for record_type, fields in (spec.get("fields") or {}).items():
        for field in fields:
            await client.put_field(record_type, field)
            applied.setdefault(record_type, []).append(field["name"])
    calendars = [await calendar_id(client, name) for name in spec.get("calendars") or []]
    return {"fields": applied, "calendars": calendars}


# ----- phone calls -----
def _pretty_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        return f"+1 {digits[1:4]}-{digits[4:7]}-{digits[7:]}"
    return phone


async def log_call(client: CogmentoClient, phone: str, ref: str, text: str, name: str | None = None) -> dict[str, Any]:
    """A phone call as a note on the caller's contact: the contact this phone's key (ca:phone:<number>) names, else one with
    this phone (a known customer's), else a new one ("Caller", the number). An existing contact keeps its name and key;
    the same call (`ref`) updates its note instead of adding another."""
    key = f"ca:phone:{phone}"
    contact = await client.find_one("contact", "aux_id", key) or await client.find_one("contact", "phone", phone)
    created = False
    if not contact:
        contact = await client.create("contact", _clean({"first_name": (name or "Caller")[:80], "last_name": _pretty_phone(phone),
                                                         "phone": phone, "aux_id": key}))
        created = True
    cid = contact["id"]
    content = f"{text}\n[ref:{ref}]"
    for note in await client.notes("contact", cid):
        body = note.get("note") or note.get("content") or ""
        if f"[ref:{ref}]" in body:
            if body != content:
                await client.add_note("contact", cid, content, note_id=note["id"])
            return {"contact_id": cid, "created": created, "note_id": note["id"]}
    note = await client.add_note("contact", cid, content)
    return {"contact_id": cid, "created": created, "note_id": note.get("id")}


# ----- batches -----
OPERATIONS = {
    "upsert_contact": upsert_contact, "upsert_product": upsert_product, "upsert_deal": upsert_deal,
    "set_deal_products": set_deal_products, "upsert_case": upsert_case, "upsert_task": upsert_task,
    "upsert_event": upsert_event, "update_record": update_record, "add_note": add_note, "sync_notes": sync_notes,
    "attach_document": attach_document, "delete_contact": delete_contact, "log_call": log_call,
}


async def apply_operations(client: CogmentoClient, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs a list of operations in order, each `{"op": "<name>", ...arguments}`, e.g. built by a PinionAI merger from an
    event. Operations are idempotent, so a batch that fails part way is simply run again. The first failure stops the
    batch and raises with its position; `null` entries (a template's optional items) are skipped."""
    if not isinstance(operations, list):
        raise CrmError("operations must be a list of {op, ...} objects")
    KEY_ALIASES.clear()
    results = []
    for index, item in enumerate(operations):
        if item is None:
            continue
        if not isinstance(item, dict) or item.get("op") not in OPERATIONS:
            raise CrmError(f"operation {index}: unknown or missing op {item.get('op') if isinstance(item, dict) else item!r}")
        args = {k: v for k, v in item.items() if k != "op"}
        try:
            result = await OPERATIONS[item["op"]](client, **args)
        except TypeError as e:
            raise CrmError(f"operation {index} ({item['op']}): {e}") from e
        except CrmError as e:
            raise CrmError(f"operation {index} ({item['op']}): {e}", e.status) from e
        results.append({"op": item["op"], **{k: v for k, v in result.items() if k != "record"}})
    return {"applied": len(results), "results": results}
