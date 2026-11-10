"""A small async client for the CogMento (FreeCRM) REST API, `/api/1/`, with idempotent writes.

The CRM has no upsert: a record written by an integration carries its own key in `aux_id` (products, which have no
`aux_id`, in `sku`), and every write searches for that key first and then creates or updates. Server errors and
network failures are retried with backoff; 4xx answers raise `CrmError` at once.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# record type -> URL collection
COLLECTIONS = {
    "contact": "contacts", "company": "companies", "deal": "deals", "case": "cases", "task": "tasks",
    "event": "events", "call": "calls", "document": "documents", "product": "products",
}
AI_AGENT_SOURCE = 9  # aux_sources fixture: "AI Agent"
RETRIES = 4


class CrmError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def collection(record_type: str) -> str:
    try:
        return COLLECTIONS[record_type]
    except KeyError as e:
        raise CrmError(f"unknown record type {record_type!r}; one of {sorted(COLLECTIONS)}") from e


class CogmentoClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        if not base_url or not token:
            raise CrmError("the CRM base URL and token are required")
        base = base_url.rstrip("/")
        if not base.endswith("/api/1"):
            base += "/api/1"
        auth = token if token.lower().startswith(("token ", "bearer ")) else f"Token {token}"
        self._http = httpx.AsyncClient(base_url=base + "/", headers={"Authorization": auth, "Accept": "application/json"},
                                       timeout=timeout, transport=transport, follow_redirects=False)

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "CogmentoClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ----- transport -----
    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        delay = 0.5
        for attempt in range(1, RETRIES + 1):
            try:
                response = await self._http.request(method, path.lstrip("/"), **kwargs)
            except httpx.TransportError as e:
                if attempt == RETRIES:
                    raise CrmError(f"the CRM could not be reached: {e}") from e
            else:
                if response.status_code < 500:
                    return self._result(response)
                if attempt == RETRIES:
                    raise CrmError(f"the CRM answered {response.status_code} on {method} {path}", response.status_code)
            logger.warning("CRM %s %s failed (attempt %d); retrying", method, path, attempt)
            await asyncio.sleep(delay)
            delay *= 2
        raise CrmError("unreachable")  # pragma: no cover

    @staticmethod
    def _result(response: httpx.Response) -> Any:
        try:
            body = response.json()
        except ValueError:
            body = None
        payload = body.get("response", body) if isinstance(body, dict) else body
        if response.status_code >= 400 or (isinstance(payload, dict) and payload.get("success") is False):
            message = payload.get("error") or payload.get("detail") if isinstance(payload, dict) else None
            raise CrmError(f"the CRM refused the request ({response.status_code}): {message or response.text[:300]}", response.status_code)
        return payload

    # ----- reads -----
    async def find(self, record_type: str, field: str, value: Any, limit: int = 2) -> list[dict[str, Any]]:
        flt = json.dumps([{"and": [{"name": field, "operator": "eq", "value": value}]}])
        payload = await self.request("GET", f"{collection(record_type)}/", params={"filter": flt, "limit": limit})
        return list(payload.get("results") or []) if isinstance(payload, dict) else []

    async def find_one(self, record_type: str, field: str, value: Any) -> dict[str, Any] | None:
        found = await self.find(record_type, field, value)
        return found[0] if found else None

    async def get(self, record_type: str, record_id: str) -> dict[str, Any]:
        payload = await self.request("GET", f"{collection(record_type)}/{record_id}/")
        return payload.get("results") or payload.get("result") or {}

    async def search(self, query: str, record_type: str | None = None, limit: int = 10) -> Any:
        path = f"search/{record_type}/" if record_type else "search/"
        return await self.request("GET", path, params={"q": query, "limit": limit})

    # ----- writes -----
    async def create(self, record_type: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload = await self.request("POST", f"{collection(record_type)}/", json=fields)
        self._log_report(record_type, payload)
        return payload.get("result") or {}

    async def update(self, record_type: str, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        payload = await self.request("POST", f"{collection(record_type)}/{record_id}/", json=fields)
        self._log_report(record_type, payload)
        return payload.get("result") or {}

    async def delete(self, record_type: str, record_id: str, purge: bool = True) -> None:
        await self.request("DELETE", f"{collection(record_type)}/{record_id}/", params={"purge": "true"} if purge else None)

    async def upsert(self, record_type: str, key_field: str, key: str, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Creates or updates the record whose `key_field` equals `key`. Returns (record, created)."""
        existing = await self.find_one(record_type, key_field, key)
        body = {**fields, key_field: key}
        if existing:
            return await self.update(record_type, existing["id"], body), False
        return await self.create(record_type, body), True

    async def add_note(self, record_type: str, record_id: str, content: str, note_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content}
        if note_id:
            body["note_id"] = note_id
        payload = await self.request("POST", f"{collection(record_type)}/{record_id}/notes/", json=body)
        return payload.get("results") or payload.get("result") or {}

    async def notes(self, record_type: str, record_id: str) -> list[dict[str, Any]]:
        """The record's notes; each note's text is in `note`."""
        payload = await self.request("GET", f"{collection(record_type)}/{record_id}/notes/")
        return list(payload.get("results") or []) if isinstance(payload, dict) else []

    async def calendars(self) -> list[dict[str, Any]]:
        payload = await self.request("GET", "events/calendars/")
        return list(payload.get("results") or []) if isinstance(payload, dict) else []

    async def create_calendar(self, name: str) -> dict[str, Any]:
        payload = await self.request("POST", "events/calendars/", json={"name": name})
        created = payload.get("result") or payload.get("results") or {}
        return (created[0] if created else {}) if isinstance(created, list) else created  # the CRM answers with a list

    async def deal_products(self, deal_id: str) -> list[dict[str, Any]]:
        payload = await self.request("GET", f"deals/{deal_id}/products/")
        return list(payload.get("results") or [])

    async def add_deal_product(self, deal_id: str, product_id: str, amount: float | None = None, note: str | None = None) -> None:
        body: dict[str, Any] = {"quantity": 1}
        if amount is not None:
            body["amount"] = amount
        if note:
            body["note"] = note
        await self.request("POST", f"deals/{deal_id}/products/add/{product_id}/", json=body)

    async def remove_deal_product(self, deal_id: str, deal_product_id: str) -> None:
        await self.request("POST", f"deals/{deal_id}/products/remove/", json={"deal_product_id": deal_product_id})

    async def upload_document(self, fields: dict[str, Any], filename: str, content: bytes, content_type: str) -> dict[str, Any]:
        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in fields.items() if v is not None}
        payload = await self.request("POST", "documents/", data=data, files={"file": (filename, content, content_type)})
        return payload.get("result") or {}

    # ----- templates (custom fields, option lists) -----
    async def templates(self) -> dict[str, Any]:
        payload = await self.request("GET", "templates/")
        return payload.get("results") or payload.get("result") or {}

    async def put_field(self, record_type: str, field: dict[str, Any]) -> None:
        await self.request("POST", f"templates/{record_type}/", json={"field": field})

    @staticmethod
    def _log_report(record_type: str, payload: Any) -> None:
        report = payload.get("report") if isinstance(payload, dict) else None
        if report:
            logger.info("CRM %s write report: %s", record_type, json.dumps(report, default=str)[:500])
