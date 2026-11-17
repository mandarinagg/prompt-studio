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


def _load_plan(path: Path):
    from pydantic import ValidationError

    from pstudio.schema import EditPlan

    try:
        return EditPlan.model_validate_json(path.read_bytes())
    except OSError as e:
        print(f"no se pudo leer {path.name}: {e.strerror}", file=sys.stderr)
    except ValidationError as e:
        print(f"{path.name}: plan inválido ({e.error_count()} errores)", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"]) or "(plan)"
            print(f"  {loc}: {err['msg']}", file=sys.stderr)
    return None


def _cmd_apply(args: argparse.Namespace) -> int:
    from pydantic import ValidationError

    from pstudio.export import collect, run_batch
    from pstudio.schema import Export

    plan = _load_plan(Path(args.plan))
    if plan is None:
        return 2
    try:
        cli = Export(
            preset=args.preset,
            format=args.format,
            quality=args.quality,
            color_space=args.color_space,
            metadata=args.metadata,
        )
    except ValidationError as e:
        print(f"opciones de export inválidas: {e.errors()[0]['msg']}", file=sys.stderr)
        return 2
    inputs = [Path(p) for p in args.inputs]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        print(f"no existe: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2
    batch = collect(inputs, Path(args.out), recursive=args.recursive)
    for f in batch.skipped:
        print(f"omitido (no es JPEG/PNG/WebP/TIFF): {f}", file=sys.stderr)
    if not batch.jobs:
        print("no hay imágenes para procesar", file=sys.stderr)
        return 2

    def report(r) -> None:
        if r.error:
            print(f"error  {r.source.name}: {r.error}", file=sys.stderr)
        else:
            print(f"ok     {r.source.name} → {r.dest} ({r.seconds:.1f} s)")

    results = run_batch(plan, batch, cli=cli, overwrite=args.overwrite, on_result=report)
    failed = sum(1 for r in results if r.error)
    total = sum(r.seconds for r in results)
    print(f"{len(results) - failed}/{len(results)} exportadas en {total:.1f} s")
    return 1 if failed else 0


def _cmd_compare(args: argparse.Namespace) -> int:
    import pyvips

    from pstudio.compare import build_html, render_entry, write_report
    from pstudio.export import collect

    plan = _load_plan(Path(args.plan))
    if plan is None:
        return 2
    if args.size < 64:
        print("--size debe ser al menos 64", file=sys.stderr)
        return 2
    inputs = [Path(p) for p in args.inputs]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        print(f"no existe: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2
    out = Path(args.out)
    batch = collect(inputs, out.parent, recursive=args.recursive)
    for f in batch.skipped:
        print(f"omitido (no es JPEG/PNG/WebP/TIFF): {f}", file=sys.stderr)
    if not batch.jobs:
        print("no hay imágenes para procesar", file=sys.stderr)
        return 2
    sources = [job.source for job in batch.jobs]
    if out.exists() and not args.overwrite:
        print(f"{out} ya existe (usá --overwrite para reemplazarlo)", file=sys.stderr)
        return 2
    if any(out.exists() and out.samefile(s) for s in sources):
        print(f"{out.name} es una de las imágenes de entrada", file=sys.stderr)
        return 2
    entries = []
    for src in sources:
        e = render_entry(plan, src, args.size)
        entries.append(e)
        if e.error:
            print(f"error  {e.name}: {e.error}", file=sys.stderr)
        else:
            print(f"ok     {e.name} ({e.seconds:.1f} s)")
    try:
        write_report(
            out, build_html(plan, entries, args.size), inputs=sources, overwrite=args.overwrite
        )
    except (OSError, pyvips.Error) as e:
        print(f"no se pudo escribir el informe: {e}", file=sys.stderr)
        return 2
    failed = sum(1 for e in entries if e.error)
    print(f"{len(entries) - failed}/{len(entries)} fotos → {out}")
    return 1 if failed else 0


def _announce_cloud(text: str) -> None:
    print(
        "aviso: se envía a Anthropic SOLO este texto (nunca la foto ni su nombre):", file=sys.stderr
    )
    for line in text.splitlines():
        print(f"  | {line}", file=sys.stderr)


def _cmd_plan(args: argparse.Namespace) -> int:
    import pyvips

    from pstudio.prompting import ProviderUnavailable
    from pstudio.prompting.planner import plan_for

    image = Path(args.image) if args.image else None
    if image is not None and not image.exists():
        print(f"no existe: {image}", file=sys.stderr)
        return 2
    try:
        result = plan_for(args.prompt, image, args.provider, before_send=_announce_cloud)
    except ProviderUnavailable as e:
        print(str(e), file=sys.stderr)
        return 2
    except (OSError, ValueError, pyvips.Error) as e:
        print(f"no se pudo analizar {image.name if image else 'la foto'}: {e}", file=sys.stderr)
        return 2
    for w in result.warnings:
        print(f"aviso: {w}", file=sys.stderr)
    plan = result.plan
    if plan is None:
        print(f"{result.provider} no produjo un plan válido: {result.errors[-1]}", file=sys.stderr)
        return 1
    text = plan.model_dump_json(indent=2, exclude_none=True) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    if args.json:
        sys.stdout.write(text)
        return 0
    print(f"proveedor: {result.provider} ({1000 * result.seconds:.0f} ms)")
    if plan.explanation:
        print(plan.explanation)
    for op in plan.operations:
        params = op.model_dump(mode="json", exclude_none=True)
        name = params.pop("op")
        print(f"  · {name} " + " ".join(f"{k}={v}" for k, v in params.items()))
    if plan.export:
        print("  export: " + json.dumps(plan.export.model_dump(exclude_none=True)))
    for u in plan.unsupported:
        alt = f" — {u.alternative}" if u.alternative else ""
        print(f"  no disponible: {u.request} ({u.reason}){alt}")
    if plan.clarification:
        print(f"  pregunta: {plan.clarification}")
    if args.out:
        print(
            f"plan guardado en {args.out} (aplicalo con: pstudio apply {args.out} <foto> -o <dir>)"
        )
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from pstudio.prompting import ProviderUnavailable, get_provider
    from pstudio.prompting.evals import REPO_EVALS, CaseError, load_cases, run_eval

    paths = [Path(p) for p in args.cases] or [REPO_EVALS]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"no existe: {', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2
    try:
        cases = load_cases(paths)
        provider = get_provider(args.provider)
    except (CaseError, ProviderUnavailable) as e:
        print(str(e), file=sys.stderr)
        return 2
    report = run_eval(provider, cases)
    for r in report.results:
        if args.verbose or not r.correct:
            mark = "ok   " if r.correct else "FALLA"
            detail = "" if r.correct else "  " + "; ".join(r.fails)
            print(f"{mark} {r.id:28s} {1000 * r.seconds:7.1f} ms{detail}")
    s = report.summary
    lat = s["latency_ms"]
    print(
        f"{s['provider']}: {s['cases']} casos · válido al primer intento "
        f"{s['valid_first_try_pct']}% · válido {s['valid_pct']}% · correcto "
        f"{s['correct_pct']}% · latencia mediana {lat['median']} ms, p90 {lat['p90']} ms, "
        f"máx {lat['max']} ms"
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
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
    p_apply = sub.add_parser(
        "apply", help="aplica un plan a imágenes o carpetas y exporta copias (nunca el original)"
    )
    p_apply.add_argument("plan", help="archivo .json con el EditPlan")
    p_apply.add_argument("inputs", nargs="+", help="imágenes y/o carpetas (modo lote)")
    p_apply.add_argument("-o", "--out", required=True, help="carpeta de salida")
    p_apply.add_argument(
        "--preset",
        choices=["original", "high_quality", "web", "catalog_square", "social_vertical",
                 "story_9x16"],
    )  # fmt: skip
    p_apply.add_argument("--format", choices=["jpeg", "png", "webp", "tiff"])
    p_apply.add_argument("--quality", type=int, help="1–100 (WebP 100 = sin pérdida)")
    p_apply.add_argument("--color-space", choices=["sRGB", "Display P3"])
    p_apply.add_argument("--metadata", choices=["keep", "strip", "strip_gps"])
    p_apply.add_argument("-r", "--recursive", action="store_true", help="incluir subcarpetas")
    p_apply.add_argument(
        "--overwrite",
        action="store_true",
        help="reemplazar exportaciones previas (nunca originales)",
    )
    p_compare = sub.add_parser(
        "compare", help="informe HTML antes/después de un plan (herramienta de prueba)"
    )
    p_compare.add_argument("plan", help="archivo .json con el EditPlan")
    p_compare.add_argument("inputs", nargs="+", help="imágenes y/o carpetas")
    p_compare.add_argument("-o", "--out", required=True, help="archivo .html de salida")
    p_compare.add_argument("--size", type=int, default=1600, help="lado largo de la vista (px)")
    p_compare.add_argument("-r", "--recursive", action="store_true", help="incluir subcarpetas")
    p_compare.add_argument("--overwrite", action="store_true", help="reemplazar el informe")
    p_plan = sub.add_parser("plan", help="pedido en lenguaje natural → plan de edición (JSON)")
    p_plan.add_argument("prompt", help='qué querés hacer, p. ej. "aclarala y hacela más cálida"')
    p_plan.add_argument("image", nargs="?", help="foto a analizar (opcional; no se modifica)")
    p_plan.add_argument(
        "--provider", default="auto", help="auto (LLM local si está, si no reglas), rules, cloud"
    )
    p_plan.add_argument("-o", "--out", help="guardar el plan en un archivo .json")
    p_plan.add_argument("--json", action="store_true", help="imprimir solo el JSON del plan")
    p_eval = sub.add_parser("eval", help="corre los evals de prompts contra un proveedor")
    p_eval.add_argument("cases", nargs="*", help="archivos .toml o carpetas (def. evals/prompts)")
    p_eval.add_argument("--provider", default="rules", help="proveedor a evaluar (def. rules)")
    p_eval.add_argument("--json", help="guardar el reporte completo en un archivo JSON")
    p_eval.add_argument("-v", "--verbose", action="store_true", help="listar también los ok")
    args = parser.parse_args(argv)

    if args.command == "rpc":
        from pstudio.rpc import serve

        serve()
    elif args.command == "schema":
        sys.exit(_cmd_schema(args))
    elif args.command == "validate":
        sys.exit(_cmd_validate(args))
    elif args.command == "apply":
        sys.exit(_cmd_apply(args))
    elif args.command == "compare":
        sys.exit(_cmd_compare(args))
    elif args.command == "plan":
        sys.exit(_cmd_plan(args))
    elif args.command == "eval":
        sys.exit(_cmd_eval(args))
    elif args.command == "analyze":
        sys.exit(_cmd_analyze(args))
