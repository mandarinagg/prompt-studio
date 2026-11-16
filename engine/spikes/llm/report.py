"""Resume los results_*.json del spike #5 en tablas Markdown (para RESULTS.md).

Uso (desde engine/): uv run python spikes/llm/report.py
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    files = sorted(HERE.glob("results_*.json"))
    if not files:
        print("no hay results_*.json; correr bench.py", file=sys.stderr)
        return 1
    print(
        "| corrida | prompt | modo | ngl | ctx | JSON ok | válido 1º | válido c/reintento "
        "| correcto | mediana s | p90 s | máx s | > 8 s | tok/s |"
    )
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    fails: dict[str, list[str]] = {}
    for f in files:
        d = json.loads(f.read_text(encoding="utf-8"))
        for mode, m in d["modes"].items():
            s = m["summary"]
            # recalcular desde las filas: los results viejos sumaban intentos por separado
            walls = sorted(sum(a["wall_s"] for a in r["attempts"]) for r in m["rows"])
            s["latency_median_s"] = round(statistics.median(walls), 1)
            s["latency_p90_s"] = round(statistics.quantiles(walls, n=10, method="inclusive")[-1], 1)
            s["latency_max_s"] = round(walls[-1], 1)
            n = s["n"]
            print(f"| {f.stem[8:]} | {d.get('prompt', 'v1')} | {mode} | {d['ngl']} | {d['ctx']} "
                  f"| {s['json_ok_first']}/{n} | {s['valid_first']}/{n} "
                  f"| {s['valid_after_retry']}/{n} | **{s['correct']}/{n}** "
                  f"| {s['latency_median_s']} | {s['latency_p90_s']} | {s['latency_max_s']} "
                  f"| {sum(w > 8 for w in walls)}/{n} "
                  f"| {round(s['gen_tok_s_median'])} |")  # fmt: skip
            key = f"{f.stem[8:]} · {mode}"
            for r in m["rows"]:
                if r.get("fails") is None:
                    err = (r["attempts"][-1]["error"] or "")[:120]
                    fails.setdefault(key, []).append(f"`{r['id']}`: inválido ({err})")
                elif r["fails"]:
                    fails.setdefault(key, []).append(f"`{r['id']}`: {'; '.join(r['fails'])}")
    print()
    for key, items in fails.items():
        if len(items) > 10:
            print(f"- **{key}**: {len(items)} fallos (ver JSON)")
            continue
        print(f"- **{key}**:")
        for it in items:
            print(f"  - {it}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
