// Marco de recorte por proporción fija (diseño §7): se arrastra para encuadrar, sin manijas.
// Las medidas son las de la foto ya girada y enderezada (el recorte va después en la pila), en
// fracciones de 0 a 1 como el `Rect` del esquema.
import type { Crop, Rect } from "../engine/client";

export type Ratio = "1:1" | "4:5" | "9:16" | "16:9" | "3:2";

export const RATIOS: { id: Ratio; label: string }[] = [
  { id: "1:1", label: "1:1" },
  { id: "4:5", label: "4:5" },
  { id: "9:16", label: "9:16" },
  { id: "16:9", label: "16:9" },
  { id: "3:2", label: "3:2" },
];

const ALL_RATIOS: Record<NonNullable<Crop["aspect_ratio"]>, number> = {
  "1:1": 1,
  "4:5": 4 / 5,
  "5:4": 5 / 4,
  "3:2": 3 / 2,
  "2:3": 2 / 3,
  "4:3": 4 / 3,
  "3:4": 3 / 4,
  "16:9": 16 / 9,
  "9:16": 9 / 16,
};

/** Tamaño del marco más grande con esa proporción, en fracciones. */
function fit(w: number, h: number, ratio: number): { width: number; height: number } {
  return w / h > ratio ? { width: (h * ratio) / w, height: 1 } : { width: 1, height: w / ratio / h };
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

/** Dónde está hoy el recorte. Igual que `crop_box` del engine; `subject_or_center` arranca centrado. */
export function frameFor(w: number, h: number, crop: Crop): Rect {
  if (crop.rect) return crop.rect;
  const { width, height } = fit(w, h, ALL_RATIOS[crop.aspect_ratio ?? "1:1"]);
  let x = 0.5 - width / 2;
  let y = 0.5 - height / 2;
  if (crop.anchor === "left") x = 0;
  else if (crop.anchor === "right") x = 1 - width;
  else if (crop.anchor === "top") y = 0;
  else if (crop.anchor === "bottom") y = 1 - height;
  return { x: clamp(x, 0, 1 - width), y: clamp(y, 0, 1 - height), width, height };
}

/** Mueve el marco (dx, dy en fracciones) sin que se salga de la foto. */
export function moveFrame(f: Rect, dx: number, dy: number): Rect {
  return { ...f, x: clamp(f.x + dx, 0, 1 - f.width), y: clamp(f.y + dy, 0, 1 - f.height) };
}

/** Marco nuevo con otra proporción, centrado donde estaba el anterior (o en la foto). */
export function reframe(w: number, h: number, ratio: Ratio, prev?: Rect | null): Rect {
  const { width, height } = fit(w, h, ALL_RATIOS[ratio]);
  const cx = prev ? prev.x + prev.width / 2 : 0.5;
  const cy = prev ? prev.y + prev.height / 2 : 0.5;
  return { x: clamp(cx - width / 2, 0, 1 - width), y: clamp(cy - height / 2, 0, 1 - height), width, height };
}

/** La proporción de la lista que corresponde al recorte, o null si es otra o no hay. */
export function ratioOf(w: number, h: number, crop: Crop | undefined): Ratio | null {
  if (!crop) return null;
  if (crop.aspect_ratio) return RATIOS.some((r) => r.id === crop.aspect_ratio) ? (crop.aspect_ratio as Ratio) : null;
  if (!crop.rect) return null;
  return matchRatio((crop.rect.width * w) / (crop.rect.height * h));
}

/** La proporción de la lista más cercana a ancho/alto (con un 1% de tolerancia), o null. */
export function matchRatio(px: number): Ratio | null {
  return RATIOS.find((r) => Math.abs(ALL_RATIOS[r.id] / px - 1) < 0.01)?.id ?? null;
}

/** El mismo encuadre después de girar la foto ±90° (positivo = horario, como `rotate`). */
export function rotateRect(r: Rect, quarter: 90 | -90): Rect {
  return quarter === 90
    ? { x: 1 - r.y - r.height, y: r.x, width: r.height, height: r.width }
    : { x: r.y, y: 1 - r.x - r.width, width: r.height, height: r.width };
}

/** Suma un cuarto de vuelta y deja el resultado en (-180, 180] como pide el esquema. */
export function rotateDegrees(current: number, delta: 90 | -90): number {
  const d = (((current + delta) % 360) + 360) % 360; // 0…359
  return d > 180 ? d - 360 : d;
}
