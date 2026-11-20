// La pila de ajustes de una foto, del lado de la UI. Es un espejo de `pstudio.project.stack`:
// como mucho una op de cada tipo, en el orden canónico del engine, sin ops neutras ni resize.
import type { EditPlan } from "../engine/client";

export type Operation = NonNullable<EditPlan["operations"]>[number];
export type OpName = Operation["op"];
export type OpOf<N extends OpName> = Extract<Operation, { op: N }>;

/** Mismo orden que `CANONICAL_ORDER` en engine/src/pstudio/project/stack.py. */
export const CANONICAL_ORDER: readonly OpName[] = [
  "straighten",
  "rotate",
  "crop",
  "denoise",
  "auto_white_balance",
  "white_balance",
  "auto_exposure",
  "exposure",
  "contrast",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "saturation",
  "vibrance",
  "sharpen",
  "vignette",
];

const GEOMETRY: ReadonlySet<OpName> = new Set(["straighten", "rotate", "crop"]);

export function opsOf(stack: EditPlan | null | undefined): Operation[] {
  return stack?.operations ?? [];
}

export function findOp<N extends OpName>(stack: EditPlan | null | undefined, name: N): OpOf<N> | undefined {
  return opsOf(stack).find((o) => o.op === name) as OpOf<N> | undefined;
}

export function isNoop(op: Operation): boolean {
  switch (op.op) {
    case "exposure":
      return (op.ev ?? 0) === 0;
    case "white_balance":
      return (op.temperature_shift ?? 0) === 0 && (op.tint_shift ?? 0) === 0;
    case "rotate":
    case "straighten":
      return (op.degrees ?? 0) === 0;
    case "denoise":
      return (op.strength ?? 0) === 0;
    case "contrast":
    case "highlights":
    case "shadows":
    case "whites":
    case "blacks":
    case "saturation":
    case "vibrance":
    case "sharpen":
    case "vignette":
      return (op.amount ?? 0) === 0;
    default:
      return false; // auto y recorte siempre hacen algo
  }
}

/** Orden canónico, una op por tipo (gana la última), sin neutras ni resize (es del export). */
export function normalize(stack: EditPlan): EditPlan {
  const byName = new Map<OpName, Operation>();
  for (const op of opsOf(stack)) byName.set(op.op, op);
  const operations = CANONICAL_ORDER.flatMap((name) => {
    const op = byName.get(name);
    return op && !isNoop(op) ? [op] : [];
  });
  return { operations };
}

export function setOp(stack: EditPlan, op: Operation): EditPlan {
  return normalize({ operations: [...opsOf(stack).filter((o) => o.op !== op.op), op] });
}

export function removeOp(stack: EditPlan, name: OpName): EditPlan {
  return normalize({ operations: opsOf(stack).filter((o) => o.op !== name) });
}

/** Agrega o quita la op automática. El slider manual del grupo queda y suma encima. */
export function toggleAuto(stack: EditPlan, name: "auto_exposure" | "auto_white_balance"): EditPlan {
  return findOp(stack, name) ? removeOp(stack, name) : setOp(stack, { op: name } as Operation);
}

export function hasGeometry(stack: EditPlan | null | undefined): boolean {
  return opsOf(stack).some((o) => GEOMETRY.has(o.op));
}

/** La pila sin recorte: lo que se muestra mientras se encuadra (el marco va encima). */
export function withoutCrop(stack: EditPlan): EditPlan {
  return removeOp(stack, "crop");
}

export function sameStack(a: EditPlan | null | undefined, b: EditPlan | null | undefined): boolean {
  return JSON.stringify(normalize(a ?? {})) === JSON.stringify(normalize(b ?? {}));
}
