import { describe, expect, it } from "vitest";
import { ADJUSTMENTS, adjustmentLabel, getValue, groupChanged, setValue } from "./adjustments";
import { hasGeometry, normalize, opsOf, removeOp, setOp, toggleAuto, withoutCrop } from "./stack";

const adj = (key: string) => ADJUSTMENTS.find((a) => a.key === key)!;

describe("pila de ajustes", () => {
  it("ordena como el engine y quita lo neutro y el resize", () => {
    const s = normalize({
      operations: [
        { op: "vignette", amount: -10 },
        { op: "contrast", amount: 0 },
        { op: "resize", width: 100 },
        { op: "exposure", ev: 0.3 },
        { op: "crop", aspect_ratio: "1:1" },
      ],
    });
    expect(opsOf(s).map((o) => o.op)).toEqual(["crop", "exposure", "vignette"]);
  });

  it("setOp reemplaza la op del mismo tipo y removeOp la saca", () => {
    let s = setOp({}, { op: "contrast", amount: 10 });
    s = setOp(s, { op: "contrast", amount: 25 });
    expect(opsOf(s)).toEqual([{ op: "contrast", amount: 25 }]);
    expect(opsOf(removeOp(s, "contrast"))).toEqual([]);
  });

  it("el slider manual suma encima de la op auto sin borrarla", () => {
    let s = toggleAuto({}, "auto_exposure");
    s = setValue(s, adj("exposure"), 0.4);
    expect(opsOf(s).map((o) => o.op)).toEqual(["auto_exposure", "exposure"]);
    s = setValue(s, adj("exposure"), 0);
    expect(opsOf(s).map((o) => o.op)).toEqual(["auto_exposure"]);
    expect(opsOf(toggleAuto(s, "auto_exposure"))).toEqual([]);
  });

  it("temperatura y matiz comparten la op y la conservan mientras uno no sea 0", () => {
    let s = setValue({}, adj("temperature"), 20);
    s = setValue(s, adj("tint"), -5);
    expect(opsOf(s)).toEqual([{ op: "white_balance", temperature_shift: 20, tint_shift: -5 }]);
    s = setValue(s, adj("temperature"), 0);
    expect(getValue(s, adj("tint"))).toBe(-5);
    s = setValue(s, adj("tint"), 0);
    expect(opsOf(s)).toEqual([]);
  });

  it("reducción de ruido se muestra de 0 a 100 y se guarda de 0 a 1", () => {
    const s = setValue({}, adj("denoise"), 30);
    expect(opsOf(s)).toEqual([{ op: "denoise", strength: 0.3 }]);
    expect(getValue(s, adj("denoise"))).toBe(30);
  });

  it("geometría: detecta recorte, giro y enderezado; withoutCrop deja el resto", () => {
    expect(hasGeometry({ operations: [{ op: "exposure", ev: 1 }] })).toBe(false);
    const s = normalize({ operations: [{ op: "rotate", degrees: 90 }, { op: "crop", aspect_ratio: "1:1" }] });
    expect(hasGeometry(s)).toBe(true);
    expect(opsOf(withoutCrop(s))).toEqual([{ op: "rotate", degrees: 90 }]);
  });

  it("etiquetas para el historial", () => {
    expect(adjustmentLabel(adj("exposure"), 0.3)).toBe("Exposición +0.3 EV");
    expect(adjustmentLabel(adj("contrast"), -12)).toBe("Contraste −12");
    expect(adjustmentLabel(adj("straighten"), 1.5)).toBe("Enderezar +1.5°");
  });

  it("marca los grupos modificados", () => {
    const s = setValue({}, adj("vibrance"), 10);
    expect(groupChanged(s, "color")).toBe(true);
    expect(groupChanged(s, "light")).toBe(false);
    expect(groupChanged(toggleAuto({}, "auto_exposure"), "light")).toBe(true);
  });

  it("auto_exposure con fuerza 0 es neutra, como en el engine", () => {
    expect(opsOf(normalize({ operations: [{ op: "auto_exposure", strength: 0 }] }))).toEqual([]);
    expect(opsOf(normalize({ operations: [{ op: "auto_exposure" }] }))).toEqual([{ op: "auto_exposure" }]);
  });
});
