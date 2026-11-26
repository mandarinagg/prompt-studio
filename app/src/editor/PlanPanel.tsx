import { useEffect, useState } from "react";
import type { Resize } from "../engine/client";
import { hasIncluded } from "../state/draft";
import { editorStore, useEditor } from "../state/store";
import { Button } from "../ui/Button";
import { Clarification, PlanNotes, PlanRows, resizeText } from "./PlanRows";

export { resizeText };

/** Con reglas el plan llega en pocos ms: "Pensando…" solo si tarda más (no parpadea). */
export const THINKING_DELAY_MS = 150;

/** true recién pasado el retardo desde que se montó el componente que lo usa. */
export function useThinkingDelay(): boolean {
  const [late, setLate] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setLate(true), THINKING_DELAY_MS);
    return () => window.clearTimeout(t);
  }, []);
  return late;
}

function Thinking() {
  const late = useThinkingDelay();
  if (!late) return null;
  return (
    <div className="plan-thinking" role="status">
      <span>Pensando…</span>
      <Button variant="quiet" onClick={() => editorStore.getState().discardPlan()}>
        Cancelar
      </Button>
    </div>
  );
}

/** El plan propuesto: filas con casilla y valor, lo no disponible, la pregunta, Aplicar/Descartar. */
export function PlanPanel() {
  const plan = useEditor((s) => s.plan);
  if (!plan) return null;
  if (plan.status === "thinking") return <Thinking />;

  const discard = (
    <Button variant="quiet" onClick={() => editorStore.getState().discardPlan()}>
      Descartar
    </Button>
  );

  if (plan.status === "error") {
    return (
      <section className="plan" aria-label="Plan propuesto">
        <p className="field-error" role="alert">
          {plan.error}
        </p>
        <div className="plan-actions">{discard}</div>
      </section>
    );
  }

  const result = plan.result;
  const p = result?.plan;
  const unsupported = p?.unsupported ?? [];
  const question = p?.clarification;
  const resize = plan.rows.find((r) => r.included && r.op.op === "resize")?.op as Resize | undefined;

  return (
    <section className="plan" aria-label="Plan propuesto">
      <h2 className="panel-title">Plan propuesto</h2>
      {/* Con reglas puede venir lo concreto y una pregunta por lo otro: se ven las dos cosas. */}
      {question && <Clarification question={question} onAnswer={(t) => void editorStore.getState().answer(t)} />}
      {p?.explanation && <p className="plan-explanation">{p.explanation}</p>}
      <PlanRows
        rows={plan.rows}
        draft={plan.draft}
        showResult
        onToggle={(i) => editorStore.getState().toggleRow(i)}
        onEdit={(i, v) => editorStore.getState().editRow(i, v)}
      />
      {!question && plan.rows.length === 0 && unsupported.length === 0 && (
        <p className="field-hint">No encontré ajustes para ese pedido. Probá con otras palabras.</p>
      )}
      <PlanNotes result={result} />
      {resize && (
        <p className="field-hint">El tamaño ({resizeText(resize)}) se usa al exportar, no cambia la foto.</p>
      )}
      <div className="plan-actions">
        {(!question || plan.rows.length > 0) && (
          <Button variant="primary" disabled={!hasIncluded(plan)} onClick={() => void editorStore.getState().applyPlan()}>
            Aplicar
          </Button>
        )}
        {discard}
      </div>
    </section>
  );
}
