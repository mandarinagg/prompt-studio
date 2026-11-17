"""PROMPT STUDIO engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

__version__ = "0.1.0"


def _cmd_schema(args: argparse.Namespace) -> int:
    from pstudio.schema import json_schema

    text = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from pstudio.schema import EditPlan

    path = Path(args.plan)
    try:
        plan = EditPlan.model_validate_json(path.read_bytes())
    except OSError as e:
        print(f"no se pudo leer {path.name}: {e.strerror}", file=sys.stderr)
        return 2
    except ValidationError as e:
        print(f"{path.name}: plan inválido ({e.error_count()} errores)", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "(plan)"
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
        return 1
    ops = ", ".join(o.op for o in plan.operations) or "sin operaciones"
    print(f"{path.name}: plan válido ({ops})")
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    from pstudio.analysis import analyze
    from pstudio.render import decode

    path = Path(args.image)
    import pyvips

    try:
        img, info = decode(path)
    except (OSError, ValueError, pyvips.Error) as e:
        print(f"no se pudo abrir {path.name}: {e}", file=sys.stderr)
        return 2
    out = {"source": {"width": info.width, "height": info.height}, **analyze(img).to_dict()}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> None:
    # En Windows, con la salida redirigida, Python usa cp1252: se fuerza UTF-8 (acentos).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="pstudio", description="Motor de PROMPT STUDIO")
    parser.add_argument("--version", action="version", version=f"pstudio {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("rpc", help="servidor JSON-RPC 2.0 sobre stdio (lo usa la app)")
    p_schema = sub.add_parser("schema", help="imprime el JSON Schema del EditPlan")
    p_schema.add_argument("--out", help="escribir en un archivo en lugar de stdout")
    p_validate = sub.add_parser("validate", help="valida un plan JSON contra el esquema")
    p_validate.add_argument("plan", help="archivo .json con el EditPlan")
    p_analyze = sub.add_parser(
        "analyze", help="histograma, recorte y balance de blancos estimado (JSON)"
    )
    p_analyze.add_argument("image", help="imagen a analizar (no se modifica)")
    args = parser.parse_args(argv)

    if args.command == "rpc":
        from pstudio.rpc import serve

        serve()
    elif args.command == "schema":
        sys.exit(_cmd_schema(args))
    elif args.command == "validate":
        sys.exit(_cmd_validate(args))
    elif args.command == "analyze":
        sys.exit(_cmd_analyze(args))
