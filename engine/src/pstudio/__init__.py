"""PROMPT STUDIO engine."""

from __future__ import annotations

import argparse

__version__ = "0.1.0"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pstudio", description="Motor de PROMPT STUDIO")
    parser.add_argument("--version", action="version", version=f"pstudio {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rpc", help="servidor JSON-RPC 2.0 sobre stdio (lo usa la app)")
    args = parser.parse_args(argv)

    if args.command == "rpc":
        from pstudio.rpc import serve

        serve()
