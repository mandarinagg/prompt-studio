import { describe, expect, it } from "vitest";
import { parseNumber, snap } from "./numbers";

describe("números de los controles", () => {
  it("acepta coma o punto, signo y ajusta al rango", () => {
    expect(parseNumber("0,4", -5, 5)).toBe(0.4);
    expect(parseNumber(" +1.25 ", -5, 5)).toBe(1.25);
    expect(parseNumber("-9", -5, 5)).toBe(-5);
    expect(parseNumber("120", 0, 100)).toBe(100);
    expect(parseNumber("", 0, 100)).toBeNull();
    expect(parseNumber("abc", 0, 100)).toBeNull();
  });

  it("redondea al paso sin errores de coma flotante", () => {
    expect(snap(0.30000000000000004, 0.05)).toBe(0.3);
    expect(snap(17.4, 1)).toBe(17);
    expect(snap(-0.126, 0.01)).toBe(-0.13);
  });
});
