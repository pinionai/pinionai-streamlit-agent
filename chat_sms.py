"""SMS chat service for PinionAI: inbound Telnyx texts are answered by an agent and the reply is sent back by SMS.

Usage:
    Set agent_id, host_url, client_id, client_secret, TELNYX_API_KEY and TELNYX_PUBLIC_KEY in your environment.
    python chat_sms.py
    Then point the Telnyx messaging profile's inbound webhook at https://<public host>/webhooks/sms/telnyx.

One AsyncPinionAIClient per conversation (our number, their number), locked per conversation because the SDK is not
re-entrant. The host API keeps the authoritative session (`update_pinion_session` after each turn) and a small SQLite
file maps each conversation to its session id, so after a restart the session is re-hydrated from the host for
SMS_CONVERSATION_TTL_HOURS. Idle clients are closed after SMS_IDLE_SECONDS. See docs/SMS_Channel.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
from aiohttp import web
from dotenv import load_dotenv

from pinionai import AsyncPinionAIClient, telnyx_sms_message
from pinionai.file_type_detection import is_text_file_type

# Load environment variables
load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_NEXT_INTENTS = 6
SMS_MAX_CHARS = 1600  # Telnyx's limit for one message; longer text is split into several.
EVENT_RETENTION_SECONDS = 86400
# Carrier opt-out keywords: Telnyx enforces opt-out on the messaging profile, so the agent never sees these.
OPT_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "START", "UNSTOP"}
HELP_KEYWORDS = {"HELP", "INFO"}


def _env_json(name: str) -> dict[str, Any]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


@dataclass
class SmsConfig:
    host_url: str
    client_id: str
    client_secret: str
    agent_id: str
    telnyx_api_key: str
    telnyx_public_key: str
    version: str | None = None
    url_params: str | None = None
    agent_map: dict[str, str] = field(default_factory=dict)  # receiving number -> agent id
    session_vars: dict[str, Any] = field(default_factory=dict)  # seeded into every new session's var
    state_db: str = "sms_state.db"
    conversation_ttl_hours: float = 24
    idle_seconds: int = 1800
    turn_timeout: float = 90
    rate_per_hour: int = 30
    max_parts: int = 3
    max_concurrent: int = 8
    help_text: str = "Reply with your question and we'll text you back. Reply STOP to opt out."
    handoff_text: str = "A member of our team will follow up with you shortly."
    error_text: str = "Sorry, we couldn't answer that just now. Please try again in a few minutes."
    dry_run: bool = False
    host: str = "127.0.0.1"
    port: int = 8086

    @classmethod
    def from_env(cls) -> SmsConfig:
        env = os.environ.get
        config = cls(
            host_url=env("host_url", "").rstrip("/"),
            client_id=env("client_id", ""),
            client_secret=env("client_secret", ""),
            agent_id=env("agent_id", ""),
            telnyx_api_key=env("TELNYX_API_KEY", ""),
            telnyx_public_key=env("TELNYX_PUBLIC_KEY", ""),
            version=env("version") or None,
            url_params=env("URL_PARAMS") or env("url_params") or None,
            agent_map=_env_json("SMS_AGENT_MAP"),
            session_vars=_env_json("SMS_SESSION_VARS"),
            state_db=env("SMS_STATE_DB", "sms_state.db"),
            conversation_ttl_hours=float(env("SMS_CONVERSATION_TTL_HOURS", "24")),
            idle_seconds=int(env("SMS_IDLE_SECONDS", "1800")),
            turn_timeout=float(env("SMS_TURN_TIMEOUT", "90")),
            rate_per_hour=int(env("SMS_RATE_PER_HOUR", "30")),
            max_parts=int(env("SMS_MAX_PARTS", "3")),
            max_concurrent=int(env("SMS_MAX_CONCURRENT", "8")),
            help_text=env("SMS_HELP_TEXT") or cls.help_text,
            handoff_text=env("SMS_HANDOFF_TEXT") or cls.handoff_text,
            error_text=env("SMS_ERROR_TEXT") or cls.error_text,
            dry_run=env("SMS_DRY_RUN", "").lower() in ("1", "true", "yes"),
            host=env("SMS_HOST", "127.0.0.1"),
            port=int(env("PORT", "8086")),
        )
        missing = [name for name, value in (
            ("host_url", config.host_url), ("client_id", config.client_id), ("client_secret", config.client_secret),
            ("agent_id", config.agent_id or config.agent_map), ("TELNYX_PUBLIC_KEY", config.telnyx_public_key),
        ) if not value]
        if not config.dry_run and not config.telnyx_api_key:
            missing.append("TELNYX_API_KEY")
        if missing:
            raise ValueError(f"Missing SMS service settings: {', '.join(missing)}")
        return config


def mask_number(number: str) -> str:
    """Logs show only the last four digits of a phone number."""
    return f"…{number[-4:]}" if number else "?"


def to_sms_text(text: str) -> str:
    """Flattens an agent's markdown/HTML reply into plain SMS text, keeping line breaks and link URLs."""
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1 (\2)", text)
    text = re.sub(r"<br\s*/?>|</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\*\*|__|`", "", text)
    text = re.sub(r"^[ \t]{0,3}#{1,6}[ \t]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_sms(text: str, limit: int = SMS_MAX_CHARS, max_parts: int = 3) -> list[str]:
    """Splits text into messages of at most `limit` characters on paragraph, line, sentence or word boundaries.

    Anything beyond `max_parts` messages is cut, and the last message ends with an ellipsis.
    """
    parts: list[str] = []
    rest = text.strip()
    while rest:
        if len(rest) <= limit:
            parts.append(rest)
            break
        window = rest[:limit]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(". "), window.rfind("? "), window.rfind("! "))
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit - 1
        parts.append(rest[:cut + 1].strip())
        rest = rest[cut + 1:].strip()
    if len(parts) > max_parts:
        parts = parts[:max_parts]
        parts[-1] = parts[-1][:limit - 1].rstrip() + "…"
    return parts


class ConversationStore:
    """SQLite map of (our number, their number) -> session, plus the webhook event ids already handled."""

    def __init__(self, path: str) -> None:
        self._db = sqlite3.connect(path)
        self._db.execute("""CREATE TABLE IF NOT EXISTS conversations (
            our_number TEXT NOT NULL, their_number TEXT NOT NULL, session_id TEXT NOT NULL, agent_id TEXT NOT NULL,
            last_used REAL NOT NULL, handed_off INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (our_number, their_number))""")
        self._db.execute("CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, received REAL NOT NULL)")
        self._db.commit()

    def get(self, our: str, their: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT session_id, agent_id, last_used, handed_off FROM conversations WHERE our_number = ? AND their_number = ?",
            (our, their)).fetchone()
        if not row:
            return None
        return {"session_id": row[0], "agent_id": row[1], "last_used": row[2], "handed_off": bool(row[3])}

    def save(self, our: str, their: str, session_id: str, agent_id: str, handed_off: bool = False) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO conversations (our_number, their_number, session_id, agent_id, last_used, handed_off) VALUES (?, ?, ?, ?, ?, ?)",
            (our, their, session_id, agent_id, time.time(), int(handed_off)))
        self._db.commit()

    def first_sighting(self, event_id: str) -> bool:
        """Records a webhook event id; False when it was already handled (a Telnyx retry)."""
        cursor = self._db.execute("INSERT OR IGNORE INTO events (event_id, received) VALUES (?, ?)", (event_id, time.time()))
        self._db.commit()
        return cursor.rowcount == 1

    def prune_events(self) -> None:
        self._db.execute("DELETE FROM events WHERE received < ?", (time.time() - EVENT_RETENTION_SECONDS,))
        self._db.commit()

    def close(self) -> None:
        self._db.close()


class TokenManager:
    """One client-credentials token for the host API, refreshed a minute before it expires."""

    def __init__(self, config: SmsConfig) -> None:
        self._config = config
        self._token = ""
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires - 60:
                return self._token
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.post(f"{self._config.host_url}/token", data={
                    "grant_type": "client_credentials", "client_id": self._config.client_id, "client_secret": self._config.client_secret})
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._expires = time.time() + float(body.get("expires_in", 3600))
            return self._token


@dataclass
class Conversation:
    our: str
    their: str
    client: AsyncPinionAIClient
    agent_id: str
    last_used: float = field(default_factory=time.time)


SendFn = Callable[[str, str, str], Awaitable[str | None]]


class SmsService:
    def __init__(self, config: SmsConfig, store: ConversationStore, send: SendFn | None = None) -> None:
        self.config = config
        self.store = store
        self._send_fn = send or self._telnyx_send
        self._tokens = TokenManager(config)
        self._conversations: dict[tuple[str, str], Conversation] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._recent: dict[str, deque[float]] = {}
        self._turn_slots = asyncio.Semaphore(config.max_concurrent)
        self._tasks: set[asyncio.Task] = set()

    # ----- webhook entry -----
    def dispatch(self, event: dict[str, Any]) -> None:
        """Handles a verified webhook event in the background; Telnyx wants its 2xx within two seconds."""
        task = asyncio.create_task(self._handle_safely(event))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_safely(self, event: dict[str, Any]) -> None:
        try:
            await self.handle_event(event)
        except Exception:
            logger.exception("SMS event %s failed", (event.get("data") or {}).get("id"))

    async def handle_event(self, event: dict[str, Any]) -> None:
        data = event.get("data") or {}
        if data.get("event_type") != "message.received":
            return
        event_id = data.get("id")
        if event_id and not self.store.first_sighting(event_id):
            logger.info("SMS event %s already handled; ignoring the retry", event_id)
            return
        payload = data.get("payload") or {}
        their = ((payload.get("from") or {}).get("phone_number") or "").strip()
        to_list = payload.get("to") or []
        our = ((to_list[0] if to_list else {}).get("phone_number") or "").strip()
        text = (payload.get("text") or "").strip()
        if not their or not our or not text:
            return

        keyword = text.upper().strip(" .!")
        if keyword in OPT_KEYWORDS:
            return
        if keyword in HELP_KEYWORDS:
            await self._reply(our, their, self.config.help_text)
            return
        if not self._within_rate(their):
            logger.warning("SMS from %s is over SMS_RATE_PER_HOUR; not answered", mask_number(their))
            return

        key = (our, their)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock, self._turn_slots:
            try:
                conversation = await self._conversation(our, their)
                if conversation is None:
                    return
                reply, transfer = await self._turn(conversation, text)
            except Exception:
                # Drop the client so the next text re-hydrates from the host's copy of the session.
                logger.exception("SMS turn for %s failed", mask_number(their))
                await self._close(key)
                await self._reply(our, their, self.config.error_text)
                return
            if reply:
                await self._reply(our, their, reply)
            if transfer:
                self.store.save(our, their, conversation.client.session_id or "", conversation.agent_id, handed_off=True)
                await self._close(key)
                logger.info("SMS conversation with %s handed off to a person", mask_number(their))
                await self._reply(our, their, self.config.handoff_text)

    def _within_rate(self, their: str) -> bool:
        now = time.time()
        recent = self._recent.setdefault(their, deque())
        while recent and now - recent[0] > 3600:
            recent.popleft()
        if len(recent) >= self.config.rate_per_hour:
            return False
        recent.append(now)
        return True

    # ----- sessions -----
    async def _conversation(self, our: str, their: str) -> Conversation | None:
        key = (our, their)
        conversation = self._conversations.get(key)
        if conversation:
            return conversation
        saved = self.store.get(our, their)
        fresh = saved and time.time() - saved["last_used"] < self.config.conversation_ttl_hours * 3600
        if fresh and saved["handed_off"]:
            logger.info("SMS from %s ignored: the conversation is with a person", mask_number(their))
            return None
        client = None
        agent_id = self.config.agent_map.get(our, self.config.agent_id)
        if fresh and saved["agent_id"] == agent_id:
            try:
                client = await self._rehydrate(saved["session_id"], agent_id)
            except Exception as e:
                logger.warning("Could not re-hydrate SMS session %s; starting a new one: %s", saved["session_id"], e)
        if client is None:
            client = await self._new_client(their, agent_id)
        conversation = Conversation(our=our, their=their, client=client, agent_id=agent_id)
        self._conversations[key] = conversation
        self.store.save(our, their, client.session_id or "", agent_id)
        return conversation

    async def _new_client(self, their: str, agent_id: str) -> AsyncPinionAIClient:
        client = await AsyncPinionAIClient.create(
            agent_id=agent_id,
            host_url=self.config.host_url,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            version=self.config.version,
            url_params=self.config.url_params,
        )
        client.var.update(self.config.session_vars)
        client.var["phone_number"] = their
        client.var["channel"] = "sms"
        if not client.chat_messages and client.var.get("agentStart"):
            client.add_message_to_history("assistant", client.var["agentStart"])
        return client

    async def _rehydrate(self, session_id: str, agent_id: str) -> AsyncPinionAIClient | None:
        """A session the host knows but this process does not: rebuild the client from the host's copy."""
        token = await self._tokens.get()
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get(f"{self.config.host_url}/session/{session_id}", headers={"authorization": f"Bearer {token}"})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return await AsyncPinionAIClient.create(
            agent_id=agent_id,
            host_url=self.config.host_url,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
            version=self.config.version,
            token=f"bearer {token}",
            session_id=session_id,
            raw_session_data=r.json(),
        )

    async def _turn(self, conversation: Conversation, text: str) -> tuple[str, bool]:
        """One inbound text: runs the intent flow (and any chained next_intent) and saves the session."""
        client = conversation.client
        replies: list[str] = []
        client.add_message_to_history("user", text)
        response = await asyncio.wait_for(client.process_user_input(text, sender="user"), self.config.turn_timeout)
        replies.append(self._reply_text(response))
        hops = 0
        while client.next_intent and hops < MAX_NEXT_INTENTS:
            hops += 1
            response = await asyncio.wait_for(client.process_user_input("", sender="user"), self.config.turn_timeout)
            replies.append(self._reply_text(response))
        try:
            await client.update_pinion_session()
        except Exception as e:  # the host copy lags one turn; the conversation goes on
            logger.warning("SMS session %s: update_pinion_session failed: %s", client.session_id, e)
        conversation.last_used = time.time()
        self.store.save(conversation.our, conversation.their, client.session_id or "", conversation.agent_id)
        return "\n\n".join(r for r in replies if r), bool(client.transfer_requested)

    @staticmethod
    def _reply_text(response: Any) -> str:
        content, file_type = response if isinstance(response, tuple) else (response, "text/plain")
        content = "" if content is None else str(content)
        file_type = file_type or "text/plain"
        if is_text_file_type(file_type) and file_type != "text/csv":
            return to_sms_text(content)
        if content.startswith(("http://", "https://")):
            return content
        return "I have a file for you, but it can't be sent by text message."

    # ----- replies -----
    async def _reply(self, our: str, their: str, text: str) -> None:
        for part in split_sms(text, max_parts=self.config.max_parts):
            if self.config.dry_run:
                logger.info("SMS_DRY_RUN reply to %s: %s", mask_number(their), part)
                continue
            if not await self._send_fn(part, their, our):
                logger.error("SMS reply to %s was not sent", mask_number(their))
                return

    async def _telnyx_send(self, text: str, to: str, from_: str) -> str | None:
        return await asyncio.to_thread(telnyx_sms_message, text, to, from_, api_key=self.config.telnyx_api_key)

    # ----- lifecycle -----
    async def evict_idle(self) -> int:
        now = time.time()
        idle = [key for key, c in self._conversations.items()
                if now - c.last_used > self.config.idle_seconds and not self._locks.get(key, asyncio.Lock()).locked()]
        for key in idle:
            await self._close(key)
        for key, lock in list(self._locks.items()):
            if key not in self._conversations and not lock.locked():
                del self._locks[key]
        for number, recent in list(self._recent.items()):
            if not recent or now - recent[-1] > 3600:
                del self._recent[number]
        self.store.prune_events()
        return len(idle)

    async def _close(self, key: tuple[str, str]) -> None:
        conversation = self._conversations.pop(key, None)
        if conversation is None:
            return
        try:
            await conversation.client.end_grpc_chat_session(send_goodbye=False)
        except Exception:
            pass
        await conversation.client.close()

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for key in list(self._conversations):
            await self._close(key)

    def count(self) -> int:
        return len(self._conversations)


def make_verifier(config: SmsConfig) -> Callable[[str, Mapping[str, str]], None]:
    """Ed25519 check of a Telnyx webhook (and its five-minute timestamp window); raises ValueError when it fails."""
    from telnyx import Telnyx

    telnyx_client = Telnyx(api_key=config.telnyx_api_key or "unused", public_key=config.telnyx_public_key)

    def verify(raw_body: str, headers: Mapping[str, str]) -> None:
        telnyx_client.webhooks.unwrap(raw_body, headers=headers)

    return verify


SERVICE_KEY = web.AppKey("service", SmsService)
EVICT_TASK_KEY = web.AppKey("evict_task", asyncio.Task)


def create_app(config: SmsConfig, send: SendFn | None = None,
               verify: Callable[[str, Mapping[str, str]], None] | None = None) -> web.Application:
    verify = verify or make_verifier(config)
    service = SmsService(config, ConversationStore(config.state_db), send=send)

    async def telnyx_webhook(request: web.Request) -> web.Response:
        raw_body = await request.text()
        try:
            verify(raw_body, dict(request.headers))
            event = json.loads(raw_body)
        except ValueError as e:
            logger.warning("Rejected Telnyx webhook: %s", e)
            return web.Response(status=401)
        service.dispatch(event)
        return web.Response(status=200)

    async def health(_request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "conversations": service.count(), "dryRun": config.dry_run})

    async def evict_loop() -> None:
        while True:
            await asyncio.sleep(300)
            try:
                evicted = await service.evict_idle()
                if evicted:
                    logger.info("Closed %d idle SMS conversation(s)", evicted)
            except Exception:
                logger.exception("SMS idle eviction failed")

    async def on_startup(app: web.Application) -> None:
        app[EVICT_TASK_KEY] = asyncio.create_task(evict_loop())

    async def on_cleanup(app: web.Application) -> None:
        app[EVICT_TASK_KEY].cancel()
        await service.close()
        service.store.close()

    app = web.Application()
    app[SERVICE_KEY] = service
    app.router.add_post("/webhooks/sms/telnyx", telnyx_webhook)
    app.router.add_get("/healthz", health)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    sms_config = SmsConfig.from_env()
    web.run_app(create_app(sms_config), host=sms_config.host, port=sms_config.port)
