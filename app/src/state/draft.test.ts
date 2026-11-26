import { describe, expect, it } from "vitest";
import type { EditPlan, PlanCreated } from "../engine/client";
import { clampEdit, editRowIn, effectivePlan, hasIncluded, rowAdjustment, rowsOf, toggleRowIn, visibleOps, type PlanState } from "./draft";

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

  it("clampEdit ajusta al paso del slider: los enteros del esquema no reciben decimales", () => {
    const vibrance = rowAdjustment({ op: "vibrance", amount: 10 })!;
    expect(clampEdit(vibrance, 12.5)).toBe(13);
    expect(clampEdit(vibrance, 12.4)).toBe(12);
    const denoise = rowAdjustment({ op: "denoise", strength: 0.3 })!;
    expect(clampEdit(denoise, 33.3)).toBe(33);
    const ev = rowAdjustment({ op: "exposure", ev: 0.4 })!;
    expect(clampEdit(ev, 0.42)).toBe(0.4);
    expect(clampEdit(ev, 0.15)).toBe(0.15); // sin basura de coma flotante (0.15000000000000002)
    const straighten = rowAdjustment({ op: "straighten", degrees: 1 })!;
    expect(clampEdit(straighten, 1.23)).toBe(1.2);
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

describe("toggleRowIn / editRowIn", () => {
  it("toggleRowIn alterna una fila y no toca un plan que no está listo", () => {
    const p = ready(plan);
    const off = toggleRowIn(p, 1);
    expect(off.rows.map((r) => r.included)).toEqual([true, false, true, true]);
    expect(toggleRowIn(off, 1).rows[1].included).toBe(true);
    const thinking: PlanState = { ...p, status: "thinking" };
    expect(toggleRowIn(thinking, 1)).toBe(thinking);
  });

  it("editRowIn recorta al rango, NaN vuelve al valor del plan y las filas sin slider no cambian", () => {
    const p = ready(plan);
    expect(editRowIn(p, 0, 9).rows[0].edited).toBe(5);
    expect(editRowIn(editRowIn(p, 0, 2), 0, Number.NaN).rows[0].edited).toBeUndefined();
    expect(editRowIn(p, 3, 5)).toBe(p); // resize: sin slider
    expect(editRowIn(p, 42, 1)).toBe(p);
    const thinking: PlanState = { ...p, status: "thinking" };
    expect(editRowIn(thinking, 0, 1)).toBe(thinking);
  });
});
