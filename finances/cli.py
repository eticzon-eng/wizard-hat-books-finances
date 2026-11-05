from __future__ import annotations

import argparse
import sys

from . import db


def cmd_init(_: argparse.Namespace) -> None:
    db.init_db()
    print(f"Initialized {db.db_path()}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .api import app

    db.init_db()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="finances",
        description="Wizard Hat Books finances: expenses, royalties, and inventory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Create the local database and seed locations")
    init.set_defaults(func=cmd_init)

    serve = sub.add_parser("serve", help="Run the local finances site")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8791)
    serve.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except Exception as exc:  # noqa: BLE001 — CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1
