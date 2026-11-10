"""python -m mcp_server.cogmento serve | apply-schema <spec.json> [--dry-run]"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m mcp_server.cogmento")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the MCP tool server (streamable HTTP)")
    schema = sub.add_parser("apply-schema", help="add/edit CRM fields and calendars from a JSON spec")
    schema.add_argument("spec")
    schema.add_argument("--dry-run", action="store_true", help="show what the spec contains; write nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.command == "serve":
        from .server import mcp
        mcp.run(transport="http", host=os.environ.get("COGMENTO_HOST", "127.0.0.1"),
                port=int(os.environ.get("COGMENTO_PORT", "8090")), show_banner=False)
        return 0

    with open(args.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    if args.dry_run:
        for record_type, fields in (spec.get("fields") or {}).items():
            print(record_type, ", ".join(f["name"] for f in fields))
        print("calendars:", ", ".join(spec.get("calendars") or []) or "-")
        return 0
    from .client import CogmentoClient
    from .operations import apply_schema

    async def run() -> dict:
        async with CogmentoClient(os.environ.get("COGMENTO_BASE_URL", ""), os.environ.get("COGMENTO_TOKEN", "")) as client:
            return await apply_schema(client, spec)

    print(json.dumps(asyncio.run(run()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
