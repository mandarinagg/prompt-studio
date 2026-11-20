// Los sliders del editor: qué campo de qué op mueve cada uno, su rango y cómo se lee su valor.
// Los rangos son los del esquema (engine/src/pstudio/schema/plan.py).
import type { EditPlan } from "../engine/client";
import { findOp, opsOf, setOp, type OpName, type Operation } from "./stack";

export type GroupId = "light" | "color" | "detail" | "effects" | "geometry";

export const GROUPS: { id: GroupId; label: string }[] = [
  { id: "light", label: "Luz" },
  { id: "color", label: "Color" },
  { id: "detail", label: "Detalle" },
  { id: "effects", label: "Efectos" },
  { id: "geometry", label: "Geometría" },
];

export interface Adjustment {
  key: string;
  label: string;
  group: GroupId;
  op: OpName;
  field: string;
  min: number;
  max: number;
  step: number;
  /** Valor guardado = valor del slider × scale (reducción de ruido: 0–100 → 0–1). */
  scale?: number;
  unit?: string;
}

const amount = (key: string, label: string, group: GroupId, op: OpName, min = -100): Adjustment => ({
  key,
  label,
  group,
  op,
  field: "amount",
  min,
  max: 100,
  step: 1,
});

export const ADJUSTMENTS: Adjustment[] = [
  { key: "exposure", label: "Exposición", group: "light", op: "exposure", field: "ev", min: -5, max: 5, step: 0.05, unit: "EV" },
  amount("contrast", "Contraste", "light", "contrast"),
  amount("highlights", "Altas luces", "light", "highlights"),
  amount("shadows", "Sombras", "light", "shadows"),
  amount("whites", "Blancos", "light", "whites"),
  amount("blacks", "Negros", "light", "blacks"),
  { key: "temperature", label: "Temperatura", group: "color", op: "white_balance", field: "temperature_shift", min: -100, max: 100, step: 1 },
  { key: "tint", label: "Matiz", group: "color", op: "white_balance", field: "tint_shift", min: -100, max: 100, step: 1 },
  amount("saturation", "Saturación", "color", "saturation"),
  amount("vibrance", "Vibrancia", "color", "vibrance"),
  amount("sharpen", "Nitidez", "detail", "sharpen", 0),
  { key: "denoise", label: "Reducción de ruido", group: "detail", op: "denoise", field: "strength", min: 0, max: 100, step: 1, scale: 0.01 },
  amount("vignette", "Viñeta", "effects", "vignette"),
  { key: "straighten", label: "Enderezar", group: "geometry", op: "straighten", field: "degrees", min: -45, max: 45, step: 0.1, unit: "°" },
];

/** Botón Auto de cada grupo. */
export const AUTO: Partial<Record<GroupId, "auto_exposure" | "auto_white_balance">> = {
  light: "auto_exposure",
  color: "auto_white_balance",
};

function round(v: number): number {
  return Math.round(v * 1e6) / 1e6;
}

export function getValue(stack: EditPlan | null | undefined, a: Adjustment): number {
  const op = findOp(stack, a.op) as Record<string, unknown> | undefined;
  const raw = typeof op?.[a.field] === "number" ? (op[a.field] as number) : 0;
  return round(raw / (a.scale ?? 1));
}

export function setValue(stack: EditPlan, a: Adjustment, value: number): EditPlan {
  const current = (findOp(stack, a.op) ?? { op: a.op }) as Record<string, unknown>;
  // setOp normaliza: si la op queda neutra (p. ej. temperatura y matiz en 0) sale de la pila.
  return setOp(stack, { ...current, [a.field]: round(value * (a.scale ?? 1)) } as unknown as Operation);
}

/** "+0.3 EV", "−12", "+1.5°": signo tipográfico y sin ceros de más. */
export function formatValue(a: Adjustment, v: number): string {
  const digits = a.step < 0.1 ? 2 : a.step < 1 ? 1 : 0;
  const n = Number(Math.abs(v).toFixed(digits));
  const sign = v > 0 && a.min < 0 ? "+" : v < 0 ? "−" : "";
  const unit = a.unit === "EV" ? " EV" : (a.unit ?? "");
  return `${sign}${n}${unit}`;
}

export function adjustmentLabel(a: Adjustment, v: number): string {
  return `${a.label} ${formatValue(a, v)}`;
}

export function groupChanged(stack: EditPlan | null | undefined, group: GroupId): boolean {
  const names = new Set<OpName>(ADJUSTMENTS.filter((a) => a.group === group).map((a) => a.op));
  const auto = AUTO[group];
  if (auto) names.add(auto);
  if (group === "geometry") {
    names.add("crop");
    names.add("rotate");
  }
  return opsOf(stack).some((o) => names.has(o.op));
}
