import { describe, expect, it } from "vitest";
import type { EditPlan, PlanCreated } from "../engine/client";
import { clampEdit, effectivePlan, hasIncluded, rowAdjustment, rowsOf, visibleOps, type PlanState } from "./draft";

const plan: EditPlan = {
  source_prompt: "más luz",
  explanation: "Subo la exposición",
  operations: [
    { op: "exposure", ev: 0.4 },
    { op: "vibrance", amount: 20 },
    { op: "denoise", strength: 0.3 },
    { op: "resize", width: 800 },
  ],
};

const created = (p: EditPlan | null): PlanCreated => ({
  plan: p,
  provider: "rules",
  ms: 1,
  warnings: [],
  errors: [],
  draft: null,
  export_hint: null,
});

const ready = (p: EditPlan): PlanState => ({ prompt: "más luz", status: "ready", result: created(p), rows: rowsOf(p), draft: null });

describe("borrador del plan", () => {
  it("una fila por op, todas incluidas", () => {
    expect(rowsOf(plan).map((r) => [r.index, r.op.op, r.included])).toEqual([
      [0, "exposure", true],
      [1, "vibrance", true],
      [2, "denoise", true],
      [3, "resize", true],
    ]);
    expect(rowsOf(null)).toEqual([]);
  });

  it("effectivePlan deja solo las filas incluidas y aplica los valores editados", () => {
    const s = ready(plan);
    s.rows[1] = { ...s.rows[1], included: false };
    s.rows[0] = { ...s.rows[0], edited: 0.7 };
    s.rows[2] = { ...s.rows[2], edited: 50 }; // en unidades del slider (0–100) → 0.5
    expect(effectivePlan(s)).toEqual({
      source_prompt: "más luz",
      operations: [
        { op: "exposure", ev: 0.7 },
        { op: "denoise", strength: 0.5 },
        { op: "resize", width: 800 },
      ],
    });
  });

  it("balance de blancos edita la temperatura, o el matiz si es lo único que trae", () => {
    expect(rowAdjustment({ op: "white_balance", temperature_shift: 10 })?.key).toBe("temperature");
    expect(rowAdjustment({ op: "white_balance", tint_shift: -5 })?.key).toBe("tint");
    expect(rowAdjustment({ op: "crop", aspect: "1:1" } as any)).toBeUndefined();
    expect(rowAdjustment({ op: "auto_exposure" })).toBeUndefined();
    expect(rowAdjustment({ op: "rotate", degrees: 90 } as any)).toBeUndefined();
  });

  it("valor editado: se recorta al rango del slider; vacío o inválido vuelve al plan", () => {
    const ev = rowAdjustment({ op: "exposure", ev: 0.4 })!;
    expect(clampEdit(ev, 9)).toBe(5);
    expect(clampEdit(ev, -9)).toBe(-5);
    expect(clampEdit(ev, Number.NaN)).toBeUndefined();
    const sharpen = rowAdjustment({ op: "sharpen", amount: 10 })!;
    expect(clampEdit(sharpen, -3)).toBe(0);
  });

  it("solo unsupported o solo clarification: nada que aplicar ni que mostrar", () => {
    const onlyUnsupported = ready({ operations: [], unsupported: [{ request: "quitar el fondo", reason: "no hay" }] });
    expect(hasIncluded(onlyUnsupported)).toBe(false);
    expect(visibleOps(onlyUnsupported)).toBe(false);
    const resizeOnly = ready({ operations: [{ op: "resize", width: 800 }] });
    expect(hasIncluded(resizeOnly)).toBe(true); // aplicarlo deja la sugerencia de export
    expect(visibleOps(resizeOnly)).toBe(false); // pero en la foto no cambia nada
    expect(visibleOps(ready(plan))).toBe(true);
  });
});
