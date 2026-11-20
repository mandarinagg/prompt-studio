import { describe, expect, it } from "vitest";
import { frameFor, moveFrame, ratioOf, reframe, rotateDegrees, rotateRect } from "./crop";

const close = (r: { x: number; y: number; width: number; height: number }) =>
  [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 1000) / 1000);

describe("marco de recorte", () => {
  it("una proporción en una foto apaisada ocupa todo el alto y queda centrada", () => {
    expect(close(frameFor(3000, 2000, { op: "crop", aspect_ratio: "1:1" }))).toEqual([0.167, 0, 0.667, 1]);
  });

  it("respeta los anclajes como el engine; subject_or_center arranca centrado", () => {
    expect(close(frameFor(3000, 2000, { op: "crop", aspect_ratio: "1:1", anchor: "left" }))).toEqual([0, 0, 0.667, 1]);
    expect(close(frameFor(2000, 3000, { op: "crop", aspect_ratio: "16:9", anchor: "bottom" }))).toEqual([
      0, 0.625, 1, 0.375,
    ]);
    expect(close(frameFor(3000, 2000, { op: "crop", aspect_ratio: "1:1", anchor: "subject_or_center" }))).toEqual([
      0.167, 0, 0.667, 1,
    ]);
  });

  it("un recorte con rect se muestra tal cual", () => {
    const rect = { x: 0.1, y: 0.2, width: 0.5, height: 0.5 };
    expect(frameFor(3000, 2000, { op: "crop", rect })).toEqual(rect);
  });

  it("arrastrar no saca el marco de la foto", () => {
    const f = { x: 0.2, y: 0, width: 0.6, height: 1 };
    expect(close(moveFrame(f, 0.1, 0.3))).toEqual([0.3, 0, 0.6, 1]);
    expect(close(moveFrame(f, 0.9, 0))).toEqual([0.4, 0, 0.6, 1]);
    expect(close(moveFrame(f, -0.9, 0))).toEqual([0, 0, 0.6, 1]);
  });

  it("con la foto girada 90° la proporción usa las medidas ya giradas", () => {
    // 3000×2000 girada → 2000×3000 (vertical): un 4:5 ocupa todo el ancho.
    expect(close(frameFor(2000, 3000, { op: "crop", aspect_ratio: "4:5" }))).toEqual([0, 0.083, 1, 0.833]);
  });

  it("cambiar de proporción mantiene el centro del marco anterior", () => {
    const prev = { x: 0, y: 0, width: 0.5, height: 1 }; // centro en x = 0.25
    const next = reframe(3000, 2000, "16:9", prev);
    expect(close(next)).toEqual([0, 0.078, 1, 0.844]);
    const sq = reframe(3000, 2000, "1:1", { x: 0.5, y: 0, width: 0.5, height: 1 });
    expect(close(sq)).toEqual([0.333, 0, 0.667, 1]);
  });

  it("reconoce la proporción de un rect", () => {
    expect(ratioOf(3000, 2000, { op: "crop", rect: { x: 0, y: 0, width: 2 / 3, height: 1 } })).toBe("1:1");
    expect(ratioOf(3000, 2000, { op: "crop", aspect_ratio: "9:16" })).toBe("9:16");
    expect(ratioOf(3000, 2000, { op: "crop", rect: { x: 0, y: 0, width: 0.3, height: 0.9 } })).toBeNull();
    expect(ratioOf(3000, 2000, undefined)).toBeNull();
  });

  it("girar 90° lleva el marco con la foto", () => {
    const r = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 };
    expect(close(rotateRect(r, 90))).toEqual([0.4, 0.1, 0.4, 0.3]);
    expect(close(rotateRect(r, -90))).toEqual([0.2, 0.6, 0.4, 0.3]);
    expect(close(rotateRect(rotateRect(r, 90), -90))).toEqual(close(r));
  });

  it("los grados de giro quedan entre -180 y 180", () => {
    expect(rotateDegrees(0, 90)).toBe(90);
    expect(rotateDegrees(90, 90)).toBe(180);
    expect(rotateDegrees(180, 90)).toBe(-90);
    expect(rotateDegrees(-90, -90)).toBe(180);
    expect(rotateDegrees(-90, 90)).toBe(0);
  });
});
