import { useId, useState } from "react";
import { editorStore, useEditor } from "../state/store";
import { Button } from "../ui/Button";

/** El campo del pedido; Ctrl+K o `/` lo enfocan (EditorScreen). */
export const PROMPT_INPUT_ID = "prompt-input";

export const EXAMPLES = [
  "Más luz",
  "Colores más vivos",
  "Enderezar",
  "Recorte cuadrado para Instagram",
  "Más nítida",
  "Foto más cálida",
];

export function focusPrompt() {
  document.getElementById(PROMPT_INPUT_ID)?.focus();
}

/** "¿Qué querés hacer?": Enter envía, Shift+Enter salto de línea, Esc sale del campo. */
export function PromptBox() {
  const id = useId();
  const [text, setText] = useState("");
  const thinking = useEditor((s) => s.plan?.status === "thinking");

  const send = (value: string) => {
    if (!value.trim()) return;
    void editorStore.getState().ask(value);
  };

  return (
    <section className="prompt" aria-labelledby={`${id}-label`}>
      <label id={`${id}-label`} htmlFor={PROMPT_INPUT_ID} className="panel-title prompt-label">
        ¿Qué querés hacer?
      </label>
      <textarea
        id={PROMPT_INPUT_ID}
        className="input prompt-input"
        rows={2}
        maxLength={2000}
        value={text}
        placeholder="Por ejemplo: más luz y colores vivos"
        aria-describedby={`${id}-hint`}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            send(text);
          } else if (e.key === "Escape") {
            e.preventDefault();
            e.stopPropagation();
            e.currentTarget.blur();
          }
        }}
      />
      <p id={`${id}-hint`} className="field-hint">
        Enter para pedir · Shift+Enter, otra línea · Ctrl+K o / para volver acá
      </p>
      {!text.trim() && (
        <div className="prompt-examples" role="group" aria-label="Ejemplos de pedidos">
          {EXAMPLES.map((ex) => (
            <Button
              key={ex}
              variant="secondary"
              className="chip-btn"
              disabled={thinking}
              onClick={() => {
                setText(ex);
                send(ex);
              }}
            >
              {ex}
            </Button>
          ))}
        </div>
      )}
    </section>
  );
}
