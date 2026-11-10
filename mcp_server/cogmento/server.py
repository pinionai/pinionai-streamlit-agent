"""PinionAI CogMento (FreeCRM) tool server: idempotent CRM tools for agents, over MCP (streamable HTTP).

The server keeps no credentials of its own: each request names the CRM with `X-CRM-Base-Url` (or the
COGMENTO_BASE_URL default) and authenticates with the caller's `Authorization: Token <key>`, which a PinionAI MCP row
fills from its connector. Run it on the loopback:

    python -m mcp_server.cogmento serve            # COGMENTO_HOST / COGMENTO_PORT (127.0.0.1:8090)
    python -m mcp_server.cogmento apply-schema spec.json   # COGMENTO_BASE_URL + COGMENTO_TOKEN
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from . import operations as ops
from .client import CogmentoClient

mcp = FastMCP("cogmento", instructions="Idempotent CogMento CRM writes keyed by external ids (aux_id; products by sku).")


def client_from_request() -> CogmentoClient:
    headers = get_http_headers(include={"authorization"})
    base = headers.get("x-crm-base-url") or os.environ.get("COGMENTO_BASE_URL", "")
    token = headers.get("authorization") or headers.get("x-crm-token") or os.environ.get("COGMENTO_TOKEN", "")
    return CogmentoClient(base, token)


async def _run(fn, **kwargs: Any) -> dict[str, Any]:
    async with client_from_request() as client:
        return await fn(client, **kwargs)


@mcp.tool
async def upsert_contact(key: str, first_name: str = "", last_name: str = "", email: str | None = None, phone: str | None = None,
                         category: str | None = None, do_not_call: bool | None = None, do_not_text: bool | None = None,
                         do_not_email: bool | None = None, tags: list[str] | None = None,
                         fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or update the contact with external key `key` (matched by key, then e-mail, then phone)."""
    return await _run(ops.upsert_contact, key=key, first_name=first_name, last_name=last_name, email=email, phone=phone,
                      category=category, do_not_call=do_not_call, do_not_text=do_not_text, do_not_email=do_not_email,
                      tags=tags, fields=fields)


@mcp.tool
async def upsert_product(sku: str, name: str, list_price: float | None = None, description: str | None = None,
                         category: str | None = None, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or update the product with this sku."""
    return await _run(ops.upsert_product, sku=sku, name=name, list_price=list_price, description=description,
                      category=category, fields=fields)


@mcp.tool
async def upsert_deal(key: str, title: str | None = None, contact_key: str | None = None, stage: str | None = None, amount: float | None = None,
                      closed: bool | None = None, close_date: str | None = None, description: str | None = None,
                      tags: list[str] | None = None, fields: dict[str, Any] | None = None, create: bool = True,
                      other_contact_keys: list[str] | None = None) -> dict[str, Any]:
    """Create or update the deal with external key `key`, linked to the contact with `contact_key` (and
    `other_contact_keys`); `create=False` only updates."""
    return await _run(ops.upsert_deal, key=key, title=title, contact_key=contact_key, stage=stage, amount=amount,
                      closed=closed, close_date=close_date, description=description, tags=tags, fields=fields, create=create,
                      other_contact_keys=other_contact_keys)


@mcp.tool
async def set_deal_products(deal_key: str, skus: list[str], replace: bool = False,
                            amounts: dict[str, float] | None = None, new_products: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Link products (by sku) to the deal; with `replace`, unlink the ones not listed. Products missing from the CRM are
    created from `new_products[sku]` when given."""
    return await _run(ops.set_deal_products, deal_key=deal_key, skus=skus, replace=replace, amounts=amounts,
                      new_products=new_products)


@mcp.tool
async def upsert_case(key: str, title: str, contact_key: str | None = None, deal_key: str | None = None, status: str | None = None,
                      case_type: str | None = None, priority: str | None = None, description: str | None = None,
                      close_date: str | None = None, deadline: str | None = None,
                      fields: dict[str, Any] | None = None, soft_links: bool = False) -> dict[str, Any]:
    """Create or update the case with external key `key`; `soft_links` leaves out links to records not in the CRM."""
    return await _run(ops.upsert_case, key=key, title=title, contact_key=contact_key, deal_key=deal_key, status=status,
                      case_type=case_type, priority=priority, description=description, close_date=close_date,
                      deadline=deadline, fields=fields, soft_links=soft_links)


@mcp.tool
async def upsert_task(key: str, title: str, contact_key: str | None = None, deal_key: str | None = None, case_key: str | None = None,
                      due_date: str | None = None, status: str | None = None, task_type: str | None = None,
                      priority: str | None = None, description: str | None = None, done: bool = False,
                      fields: dict[str, Any] | None = None, create: bool = True, soft_links: bool = False) -> dict[str, Any]:
    """Create or update the task with external key `key`; `done` completes it, `create=False` only updates."""
    return await _run(ops.upsert_task, key=key, title=title, contact_key=contact_key, deal_key=deal_key, case_key=case_key,
                      due_date=due_date, status=status, task_type=task_type, priority=priority, description=description,
                      done=done, fields=fields, create=create, soft_links=soft_links)


@mcp.tool
async def upsert_event(key: str, title: str, start: str, end: str, calendar: str | None = None, deal_key: str | None = None,
                       case_key: str | None = None, description: str | None = None, location: str | None = None,
                       fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or update the calendar event with external key `key` (start/end ISO 8601)."""
    return await _run(ops.upsert_event, key=key, title=title, start=start, end=end, calendar=calendar, deal_key=deal_key,
                      case_key=case_key, description=description, location=location, fields=fields)


@mcp.tool
async def update_record(record_type: str, key: str, fields: dict[str, Any], soft: bool = False) -> dict[str, Any]:
    """Set `fields` on the existing record (contact, deal, case, task, …) with external key `key`, nothing else."""
    return await _run(ops.update_record, record_type=record_type, key=key, fields=fields, soft=soft)


@mcp.tool
async def add_note(record_type: str, key: str, text: str, ref: str | None = None) -> dict[str, Any]:
    """Add a note to the record (contact, deal, case, task, …) with external key `key`; `ref` makes it idempotent."""
    return await _run(ops.add_note, record_type=record_type, key=key, text=text, ref=ref)


@mcp.tool
async def sync_notes(record_type: str, key: str, notes: list[dict[str, Any]], soft: bool = False) -> dict[str, Any]:
    """Keep the notes `[{"ref": ..., "text": ...}]` on the record with external key `key` (adds missing, updates changed);
    `soft` skips a record the CRM does not have."""
    return await _run(ops.sync_notes, record_type=record_type, key=key, notes=notes, soft=soft)


@mcp.tool
async def attach_document(key: str, url: str, title: str, filename: str | None = None, contact_key: str | None = None,
                          deal_key: str | None = None, case_key: str | None = None, task_key: str | None = None,
                          replace: bool = False, fields: dict[str, Any] | None = None, skip_unavailable: bool = False) -> dict[str, Any]:
    """Copy the file at `url` (an allowed host) into the CRM as a document linked to the given records; with
    `skip_unavailable`, a missing or oversized file is skipped."""
    return await _run(ops.attach_document, key=key, url=url, title=title, filename=filename, contact_key=contact_key,
                      deal_key=deal_key, case_key=case_key, task_key=task_key, replace=replace, fields=fields,
                      skip_unavailable=skip_unavailable)


@mcp.tool
async def delete_contact(key: str) -> dict[str, Any]:
    """Purge the contact with external key `key` and the records linked only to it (privacy deletion)."""
    return await _run(ops.delete_contact, key=key)


@mcp.tool
async def find_record(record_type: str, key: str) -> dict[str, Any]:
    """The CRM record with this external key (products: sku), or {} when there is none."""
    async with client_from_request() as client:
        rid = await ops.record_id(client, record_type, key)
        return await client.get(record_type, rid) if rid else {}


@mcp.tool
async def search(query: str, record_type: str | None = None, limit: int = 10) -> Any:
    """Free-text CRM search (supports email:, phone:, tag: modifiers)."""
    async with client_from_request() as client:
        return await client.search(query, record_type, limit)


@mcp.tool
async def apply_operations(operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Run CRM operations in order, each {"op": "upsert_contact" | "upsert_product" | "upsert_deal" | "set_deal_products" |
    "upsert_case" | "upsert_task" | "upsert_event" | "add_note" | "attach_document" | "delete_contact" | "log_call", ...arguments};
    the first failure stops the batch."""
    return await _run(ops.apply_operations, operations=operations)


@mcp.tool
async def apply_schema(spec: dict[str, Any]) -> dict[str, Any]:
    """Add or edit template fields and option lists, and make sure named calendars exist."""
    return await _run(ops.apply_schema, spec=spec)
