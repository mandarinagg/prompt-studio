"""Evals de prompts (#16): casos en evals/prompts/*.toml, puntaje por proveedor.

Cada caso (`[[cases]]`) tiene `id`, `prompt`, `descriptors` y `expect`, más criterios
opcionales. Ver docs/PROMPT_ENGINE.md § Evaluación. Métricas:
- válido al primer intento / válido tras el reintento (lo que mide el pipeline sin respaldo);
- correcto: válido y sin fallas semánticas según los criterios del caso;
- latencia por pedido (todos los intentos sumados): mediana, p90 y máximo.

Los proveedores se evalúan **sin** respaldo a reglas: si no, un LLM malo parecería bueno.
"""

from __future__ import annotations

import statistics
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pstudio.prompting.provider import PlanProvider, PlanRequest, make_plan
from pstudio.schema import EditPlan

EXPECTS = {
    "ops",  # tiene que haber ops que cumplan `require`
    "unsupported",  # tiene que declarar `unsupported`
    "clarification",  # tiene que pedir aclaración
    "clarification_or_ops",  # aclaración, o las ops de `require_if_ops`
    "unsupported_or_ops",  # unsupported, o al menos alguna op
    "any",  # cualquier plan válido
}
CRITERIA = {"require", "require_if_ops", "forbid", "sign", "values", "abs", "max", "min", "max_ops"}
REPO_EVALS = Path(__file__).resolve().parents[4] / "evals" / "prompts"


class CaseError(ValueError):
    pass


def load_cases(paths: list[Path]) -> list[dict]:
    """Lee los .toml (archivos o carpetas). Valida la forma de cada caso y que los ids no se
    repitan, para que un error de tipeo en un caso no lo vuelva "siempre correcto"."""
    files: list[Path] = []
    for p in paths:
        files.extend(sorted(p.glob("*.toml")) if p.is_dir() else [p])
    cases, seen = [], set()
    for f in files:
        with f.open("rb") as fh:
            data = tomllib.load(fh)
        for i, case in enumerate(data.get("cases", [])):
            where = f"{f.name} caso {i + 1}"
            for key in ("id", "prompt", "expect"):
                if key not in case:
                    raise CaseError(f"{where}: falta `{key}`")
            if case["expect"] not in EXPECTS:
                raise CaseError(f"{where}: expect {case['expect']!r} no existe")
            unknown = set(case) - CRITERIA - {"id", "prompt", "expect", "descriptors", "tags"}
            if unknown:
                raise CaseError(f"{where}: claves desconocidas {sorted(unknown)}")
            if case["id"] in seen:
                raise CaseError(f"{where}: id repetido {case['id']!r}")
            seen.add(case["id"])
            cases.append({**case, "file": f.name})
    return cases


def _field(plan: EditPlan, path: str) -> list:
    op, attr = path.split(".")
    if op == "export":
        value = getattr(plan.export, attr) if plan.export else None
        return [] if value is None else [value]
    return [getattr(o, attr) for o in plan.operations if o.op == op]


def grade(plan: EditPlan, case: dict) -> list[str]:
    """Fallas semánticas del plan para el caso (lista vacía = correcto)."""
    ops = {o.op for o in plan.operations}
    fails: list[str] = []
    expect = case["expect"]
    has_unsup, has_clar = bool(plan.unsupported), bool(plan.clarification)
    if expect == "unsupported" and not has_unsup:
        fails.append("esperaba unsupported")
    if expect == "clarification" and not has_clar:
        fails.append("esperaba una pregunta de aclaración")
    needed = set(case.get("require_if_ops", []))
    if expect == "clarification_or_ops" and not has_clar and not (ops and needed <= ops):
        fails.append("ni aclaración ni las ops esperadas")
    if expect == "unsupported_or_ops" and not (has_unsup or ops):
        fails.append("plan vacío sin unsupported")
    if expect == "ops":
        for req in case.get("require", []):
            alts = req if isinstance(req, list) else [req]
            if not ops & set(alts):
                fails.append(f"falta {'|'.join(alts)}")
    for op in case.get("forbid", []):
        if op in ops:
            fails.append(f"no debía usar {op}")
    for path, sign in case.get("sign", {}).items():
        for v in _field(plan, path):
            if (sign == "+" and v <= 0) or (sign == "-" and v >= 0):
                fails.append(f"{path}={v}, esperaba signo {sign}")
    for path, want in case.get("values", {}).items():
        got = _field(plan, path)
        if want not in got:
            fails.append(f"{path}={got}, esperaba {want}")
    for path, want in case.get("abs", {}).items():
        got = _field(plan, path)
        if not any(abs(abs(v) - want) <= 0.5 for v in got):
            fails.append(f"{path}={got}, esperaba ±{want}")
    for path, limit in case.get("max", {}).items():
        if any(v > limit for v in _field(plan, path)):
            fails.append(f"{path}={_field(plan, path)}, esperaba ≤ {limit}")
    for path, limit in case.get("min", {}).items():
        if any(v < limit for v in _field(plan, path)):
            fails.append(f"{path}={_field(plan, path)}, esperaba ≥ {limit}")
    if "max_ops" in case and len(plan.operations) > case["max_ops"]:
        fails.append(f"{len(plan.operations)} ops, esperaba ≤ {case['max_ops']}")
    return fails


@dataclass
class CaseResult:
    id: str
    file: str
    valid: bool
    valid_first_try: bool
    correct: bool
    seconds: float
    attempts: int
    fails: list[str] = field(default_factory=list)
    plan: dict | None = None


@dataclass
class Report:
    provider: str
    results: list[CaseResult]

    @property
    def summary(self) -> dict:
        n = len(self.results)
        lat = sorted(1000 * r.seconds for r in self.results) or [0.0]
        p90 = statistics.quantiles(lat, n=10, method="inclusive")[8] if len(lat) > 1 else lat[0]

        def pct(k: int) -> float:
            return round(100 * k / n, 1) if n else 0.0

        return {
            "provider": self.provider,
            "cases": n,
            "valid_first_try_pct": pct(sum(r.valid_first_try for r in self.results)),
            "valid_pct": pct(sum(r.valid for r in self.results)),
            "correct_pct": pct(sum(r.correct for r in self.results)),
            "latency_ms": {
                "median": round(statistics.median(lat), 1),
                "p90": round(p90, 1),
                "max": round(lat[-1], 1),
            },
        }

    def to_dict(self) -> dict:
        return {"summary": self.summary, "results": [asdict(r) for r in self.results]}


def run_eval(provider: PlanProvider, cases: list[dict]) -> Report:
    results = []
    for case in cases:
        request = PlanRequest(case["prompt"], case.get("descriptors", {}))
        res = make_plan(request, provider)  # sin respaldo: se mide el proveedor solo
        if res.plan is None:
            fails = [f"inválido: {res.errors[-1] if res.errors else '?'}"]
            results.append(
                CaseResult(
                    case["id"], case["file"], False, False, False, res.seconds, res.attempts, fails
                )  # fmt: skip
            )
            continue
        fails = grade(res.plan, case)
        results.append(
            CaseResult(
                case["id"],
                case["file"],
                True,
                res.valid_first_try,
                not fails,
                res.seconds,
                res.attempts,
                fails,
                res.plan.model_dump(mode="json", exclude_none=True),
            )
        )
    return Report(provider.name, results)
