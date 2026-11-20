import { describe, expect, it } from "vitest";
import { whenOpened } from "./time";

const now = new Date("2026-11-20T15:00:00Z");

describe("cuándo se abrió", () => {
  it("en palabras simples", () => {
    expect(whenOpened("2026-11-20T14:59:30+00:00", now)).toBe("Recién");
    expect(whenOpened("2026-11-20T14:20:00+00:00", now)).toBe("Hace 40 min");
    expect(whenOpened("2026-11-20T10:00:00+00:00", now)).toBe("Hace 5 h");
    expect(whenOpened("2026-11-19T10:00:00+00:00", now)).toBe("Ayer");
    expect(whenOpened("2026-11-15T10:00:00+00:00", now)).toBe("Hace 5 días");
    expect(whenOpened("2026-09-01T10:00:00+00:00", now)).toMatch(/2026|sept/);
    expect(whenOpened("cualquier cosa", now)).toBe("");
  });
});
