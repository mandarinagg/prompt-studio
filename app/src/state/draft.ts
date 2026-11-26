// El plan de un pedido mientras se revisa: filas que se incluyen o no, valores editados y el
// borrador (pila ⊕ plan) que calcula el engine con `plan.draft`. Lógica pura, sin la API.
import type { EditPlan, PlanCreated, Resize } from "../engine/client";
import { ADJUSTMENTS, type Adjustment } from "../lib/adjustments";
import type { Operation } from "../lib/stack";

export interface PlanRow {
  /** Posición de la op en el plan original. */
  index: number;
  op: Operation;
  included: boolean;
  /** El cambio editado, en unidades del slider; sin valor, el del plan. */
  edited?: number;
}

export interface PlanState {
  prompt: string;
  status: "thinking" | "ready" | "error";
  result?: PlanCreated;
  rows: PlanRow[];
  /** Lo que se ve mientras el plan está abierto; null: no hay cambio visible (se ve la pila). */
  draft: EditPlan | null;
  /** El plan trae `resize`: va al export, no a la pila. */
  exportHint?: Resize | null;
  error?: string;
}

export function rowsOf(plan: EditPlan | null | undefined): PlanRow[] {
  return (plan?.operations ?? []).map((op, index) => ({ index, op, included: true }));
}

/**
 * El slider equivalente de la op, si tiene. Balance de blancos: la temperatura, salvo que el plan
 * traiga solo matiz. Recorte, rotación, auto y resize no tienen valor editable.
 */
export function rowAdjustment(op: Operation): Adjustment | undefined {
  const matches = ADJUSTMENTS.filter((a) => a.op === op.op);
  if (matches.length <= 1) return matches[0];
  const fields = op as unknown as Record<string, unknown>;
  return matches.find((a) => typeof fields[a.field] === "number" && fields[a.field] !== 0) ?? matches[0];
}

/** El cambio del plan en unidades del slider (reducción de ruido: 0–1 → 0–100). */
export function planValue(op: Operation, a: Adjustment): number {
  const raw = (op as unknown as Record<string, unknown>)[a.field];
  const v = typeof raw === "number" ? raw : 0;
  return Math.round((v / (a.scale ?? 1)) * 1e6) / 1e6;
}

/**
 * Recorta al rango del slider y ajusta a su paso (los campos enteros del esquema rechazan
 * decimales); vacío o inválido → undefined (vuelve al valor del plan).
 */
export function clampEdit(a: Adjustment, value: number): number | undefined {
  if (!Number.isFinite(value)) return undefined;
  const snapped = Math.round(Math.round(value / a.step) * a.step * 1e6) / 1e6;
  return Math.min(a.max, Math.max(a.min, snapped));
}

function withEdit(row: PlanRow): Operation {
  const a = row.edited === undefined ? undefined : rowAdjustment(row.op);
  if (!a || row.edited === undefined) return row.op;
  const v = Math.round(row.edited * (a.scale ?? 1) * 1e6) / 1e6;
  return { ...row.op, [a.field]: v } as unknown as Operation;
}

/** El plan con solo las filas incluidas y los valores editados: lo que se fusiona al aplicar. */
export function effectivePlan(plan: PlanState): EditPlan {
  const source = plan.result?.plan?.source_prompt ?? plan.prompt;
  return {
    source_prompt: source,
    operations: plan.rows.filter((r) => r.included).map(withEdit),
  };
}

/** Hay algo que aplicar (aunque sea solo una sugerencia de export). */
export function hasIncluded(plan: PlanState | null | undefined): boolean {
  return !!plan && plan.status === "ready" && plan.rows.some((r) => r.included);
}

/** Hay algo que se vería en la foto: sin esto no se muestra borrador. */
export function visibleOps(plan: PlanState | null | undefined): boolean {
  return !!plan && plan.status === "ready" && plan.rows.some((r) => r.included && r.op.op !== "resize");
}

/** Incluye o excluye una fila del plan; no toca un plan que no está listo. */
export function toggleRowIn(plan: PlanState, index: number): PlanState {
  if (plan.status !== "ready") return plan;
  return { ...plan, rows: plan.rows.map((r) => (r.index === index ? { ...r, included: !r.included } : r)) };
}

/** Cambia el valor de una fila (unidades del slider); NaN vuelve al valor del plan. */
export function editRowIn(plan: PlanState, index: number, value: number): PlanState {
  const row = plan.rows.find((r) => r.index === index);
  const a = row && rowAdjustment(row.op);
  if (plan.status !== "ready" || !row || !a) return plan;
  const edited = clampEdit(a, value);
  return { ...plan, rows: plan.rows.map((r) => (r.index === index ? { ...r, edited } : r)) };
}
