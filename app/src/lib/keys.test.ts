import { describe, expect, it } from "vitest";
import { isExportShortcut, isTyping } from "./keys";

const el = (tagName: string, isContentEditable = false) => ({ tagName, isContentEditable }) as unknown as EventTarget;
const key = (over: Partial<KeyboardEvent> = {}) =>
  ({ key: "e", ctrlKey: true, altKey: false, metaKey: false, repeat: false, target: el("DIV"), ...over }) as KeyboardEvent;

describe("atajos de teclado", () => {
  it("isTyping: campos de texto y contenido editable", () => {
    expect(isTyping(el("INPUT"))).toBe(true);
    expect(isTyping(el("TEXTAREA"))).toBe(true);
    expect(isTyping(el("DIV", true))).toBe(true);
    expect(isTyping(el("BUTTON"))).toBe(false);
    expect(isTyping(null)).toBe(false);
  });

  it("Ctrl+E exporta, salvo escribiendo, con la tecla repetida o con otros modificadores", () => {
    expect(isExportShortcut(key())).toBe(true);
    expect(isExportShortcut(key({ key: "E" }))).toBe(true);
    expect(isExportShortcut(key({ target: el("INPUT") }))).toBe(false);
    expect(isExportShortcut(key({ target: el("TEXTAREA") }))).toBe(false);
    expect(isExportShortcut(key({ repeat: true }))).toBe(false);
    expect(isExportShortcut(key({ altKey: true }))).toBe(false); // AltGr
    expect(isExportShortcut(key({ ctrlKey: false }))).toBe(false);
    expect(isExportShortcut(key({ key: "k" }))).toBe(false);
  });
});
