"""`pstudio project …`: el proyecto desde la terminal (CLI-first, antes que la app).

Códigos de salida: 0 bien; 1 entrada inválida (plan inválido, nada que deshacer); 2 error de
archivo o de proyecto. Todo comando que cambia algo guarda al terminar.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path

from pstudio.schema.plan import ExportPreset

_PRESETS = ExportPreset.__args__  # type: ignore[attr-defined]


def add_parser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("project", help="proyectos: fotos, ajustes, historial y export")
    ps = p.add_subparsers(dest="project_command", required=True)

    new = ps.add_parser("new", help="crea <DIR>/<NOMBRE>.pstudio")
    new.add_argument("dir")
    new.add_argument("name")

    add = ps.add_parser("add", help="importa fotos (por referencia, no se copian)")
    add.add_argument("project")
    add.add_argument("paths", nargs="+")
    add.add_argument("--recursive", action="store_true", help="incluir subcarpetas")

    ls = ps.add_parser("list", help="fotos del proyecto")
    ls.add_argument("project")
    ls.add_argument("--json", action="store_true")

    show = ps.add_parser("show", help="pila de ajustes e historial de una foto")
    show.add_argument("project")
    show.add_argument("asset")
    show.add_argument("--json", action="store_true")

    edit = ps.add_parser("edit", help="fusiona un plan en la pila de una foto")
    edit.add_argument("project")
    edit.add_argument("asset")
    edit.add_argument("--plan", required=True, help="archivo .json con el EditPlan")
    edit.add_argument("--replace", action="store_true", help="reemplaza la pila en vez de sumar")
    edit.add_argument("--label", help="texto de la entrada del historial")

    for name, text in (("undo", "deshace"), ("redo", "rehace")):
        c = ps.add_parser(name, help=f"{text} el último cambio de una foto")
        c.add_argument("project")
        c.add_argument("asset")

    rc = ps.add_parser("recent", help="proyectos abiertos hace poco en la app")
    rc.add_argument("--json", action="store_true")

    rl = ps.add_parser("relink", help="ubica una foto que se movió (verifica el hash)")
    rl.add_argument("project")
    rl.add_argument("asset")
    rl.add_argument("path")

    ex = ps.add_parser("export", help="exporta copias con sus ajustes (todas si no se indican)")
    ex.add_argument("project")
    ex.add_argument("assets", nargs="*")
    ex.add_argument("-o", "--out", required=True, help="carpeta destino")
    ex.add_argument("--preset", choices=_PRESETS, default="original")


def run(args: argparse.Namespace) -> int:
    from pstudio.project.store import ProjectError

    try:
        return _COMMANDS[args.project_command](args)
    except (ProjectError, KeyError) as e:
        msg = e.args[0] if isinstance(e, KeyError) else str(e)
        print(msg, file=sys.stderr)
        return 2
    except OSError as e:
        name = Path(e.filename).name if e.filename else ""
        print(
            f"no se pudo {_VERBS[args.project_command]} {name}: {e.strerror or e}", file=sys.stderr
        )
        return 2


_VERBS = {
    "new": "crear el proyecto en",
    "add": "importar",
    "list": "leer",
    "show": "leer",
    "edit": "guardar",
    "undo": "guardar",
    "redo": "guardar",
    "relink": "ubicar",
    "recent": "leer",
    "export": "exportar a",
}


def _new(args: argparse.Namespace) -> int:
    from pstudio.project.store import create

    print(create(Path(args.dir), args.name))
    return 0


def _add(args: argparse.Namespace) -> int:
    from pstudio.project.store import add_assets, open_project, save

    project = open_project(Path(args.project))
    r = add_assets(project, [Path(p) for p in args.paths], recursive=args.recursive)
    save(Path(args.project), project)
    dup = "duplicada" if len(r.duplicates) == 1 else "duplicadas"
    print(
        f"{len(r.added)} agregadas, {len(r.duplicates)} {dup}, {len(r.unsupported)} no soportadas"
    )
    for p in r.unsupported:
        print(f"  no soportado: {p.name}")
    return 0


def _list(args: argparse.Namespace) -> int:
    from pstudio.project.store import missing, open_project

    project = open_project(Path(args.project))
    gone = set(missing(project))
    rows = [
        {
            "id": a.id,
            "file": Path(a.path).name,
            "edited": bool(a.stack.operations),
            "missing": a.id in gone,
        }
        for a in project.assets
    ]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    for r in rows:
        flags = " ".join(f for f, on in (("editada", r["edited"]), ("falta", r["missing"])) if on)
        print(f"{r['id']}  {r['file']}  {flags}".rstrip())
    return 0


def _recent(args: argparse.Namespace) -> int:
    from pstudio import recent

    items = recent.list_recent()
    if args.json:
        print(json.dumps([i.model_dump() for i in items], ensure_ascii=False, indent=2))
        return 0
    if not items:
        print("no hay proyectos recientes")
    for i in items:
        print(f"{i.name}  {i.path}" + ("" if i.exists else "  (no encontrado)"))
    return 0


def _show(args: argparse.Namespace) -> int:
    from pstudio.project.store import open_project

    asset = open_project(Path(args.project)).asset(args.asset)
    if args.json:
        data = {
            "id": asset.id,
            "path": asset.path,
            "stack": asset.stack.model_dump(mode="json", include={"operations"}),
            "history": [
                {"label": e.label, "group_id": e.group_id, "at": e.at.isoformat()}
                for e in asset.history
            ],
            "cursor": asset.cursor,
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(asset.stack.model_dump_json(include={"operations"}, indent=2))
    for i, e in enumerate(asset.history):
        print(f"{'▶' if i == asset.cursor else ' '} {i:3d}  {e.label}")
    return 0


def _edit(args: argparse.Namespace) -> int:
    from pstudio import _load_plan
    from pstudio.project.history import push
    from pstudio.project.stack import merge
    from pstudio.project.store import open_project, save

    project = open_project(Path(args.project))
    asset = project.asset(args.asset)
    plan = _load_plan(Path(args.plan))
    if plan is None:
        return 1
    if args.replace:
        stack, hint = plan, None
    else:
        merged = merge(asset.stack, plan)
        stack, hint = merged.stack, merged.export_hint
    label = args.label or (
        f"Pedido: {plan.source_prompt}" if plan.source_prompt else "Plan aplicado"
    )
    changed = push(asset, stack, label)
    save(Path(args.project), project)
    print("pila actualizada" if changed else "sin cambios")
    if hint is not None:
        size = f"{hint.width or '?'}×{hint.height or '?'}"
        print(f"el plan pedía resize {size}: se aplica al exportar (elegí un preset)")
    return 0


def _step(args: argparse.Namespace) -> int:
    from pstudio.project.history import redo, undo
    from pstudio.project.store import open_project, save

    project = open_project(Path(args.project))
    asset = project.asset(args.asset)
    fn = undo if args.project_command == "undo" else redo
    if not fn(asset):
        print("nada que deshacer" if fn is undo else "nada que rehacer", file=sys.stderr)
        return 1
    save(Path(args.project), project)
    print(asset.history[asset.cursor].label)
    return 0


def _relink(args: argparse.Namespace) -> int:
    from pstudio.project.store import open_project, relink, save

    project = open_project(Path(args.project))
    relink(project, args.asset, Path(args.path))
    save(Path(args.project), project)
    print(f"ubicada: {Path(args.path).name}")
    return 0


def _wait(worker: threading.Thread) -> None:
    """Espera al hilo en el hilo principal, con timeout, para que Ctrl+C llegue acá."""
    while worker.is_alive():
        worker.join(0.1)


def _export(args: argparse.Namespace) -> int:
    from pstudio.project import export as project_export
    from pstudio.project.store import open_project

    project = open_project(Path(args.project))
    ids = args.assets or [a.id for a in project.assets]
    names = {a.id: Path(a.path).name for a in project.assets}
    tty = sys.stderr.isatty()

    def on_progress(i: int, total: int, asset_id: str, fraction: float) -> None:
        line = f"[{i + 1}/{total}] {names.get(asset_id, asset_id)} {int(fraction * 100)}%"
        if tty:
            end = "\n" if fraction >= 1 else ""
            print(f"\r{line}", end=end, file=sys.stderr, flush=True)
        elif fraction >= 1:
            print(line, file=sys.stderr, flush=True)

    cancel = threading.Event()
    box: dict = {}

    def work() -> None:
        try:
            box["results"] = project_export.export_assets(
                project, ids, Path(args.out), args.preset, on_progress=on_progress, cancel=cancel
            )
        except BaseException as e:  # se re-lanza en el hilo principal
            box["error"] = e

    # El export corre en un hilo y el principal espera: Ctrl+C llega al principal, que activa
    # `cancel` y deja que el export termine por su camino normal (sin temporales).
    worker = threading.Thread(target=work, name="export")
    worker.start()
    interrupted = False
    try:
        _wait(worker)
    except KeyboardInterrupt:
        interrupted = True
        cancel.set()
        worker.join()
    if "error" in box:
        raise box["error"]
    results = box["results"]
    failed = 0
    done = 0
    for r in results:
        if r.cancelled:
            continue
        if r.error:
            failed += 1
            print(f"error: {r.error}", file=sys.stderr)
        else:
            done += 1
            print(f"{r.dest}  ({r.seconds:.1f} s)")
    if interrupted or any(r.cancelled for r in results):
        print(f"cancelado: {done} exportadas, el resto no", file=sys.stderr)
        return 130
    return 2 if failed else 0


_COMMANDS = {
    "new": _new,
    "add": _add,
    "list": _list,
    "show": _show,
    "edit": _edit,
    "undo": _step,
    "redo": _step,
    "relink": _relink,
    "recent": _recent,
    "export": _export,
}
