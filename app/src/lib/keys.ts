// Atajos de teclado compartidos por la biblioteca y el editor.

/** Si el foco está en un campo de texto (ahí las teclas son del campo, no atajos). */
export function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

/** Ctrl+E (exportar): no mientras se escribe ni con la tecla mantenida (no abre el diálogo dos veces). */
export function isExportShortcut(e: KeyboardEvent): boolean {
  return e.ctrlKey && !e.altKey && !e.metaKey && !e.repeat && e.key.toLowerCase() === "e" && !isTyping(e.target);
}
