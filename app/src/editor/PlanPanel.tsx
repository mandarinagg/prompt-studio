import { useEffect, useId, useState } from "react";
import type { EditPlan, Resize } from "../engine/client";
import { formatValue, getValue, type Adjustment } from "../lib/adjustments";
import type { Operation } from "../lib/stack";
import { hasIncluded, planValue, rowAdjustment, type PlanRow } from "../state/draft";
import { editorStore, useEditor } from "../state/store";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";

/** Con reglas el plan llega en pocos ms: "Pensando…" solo si tarda más (no parpadea). */
const THINKING_DELAY_MS = 150;

export function resizeText(r: Resize): string {
  if (r.width && r.height) return `${r.width}×${r.height} px`;
  if (r.width) return `${r.width} px de ancho`;
  if (r.height) return `${r.height} px de alto`;
  return "otro tamaño";
}

/** Texto fijo de las ops sin slider. */
function fixedText(op: Operation): string {
  switch (op.op) {
    case "crop":
      return op.aspect_ratio ? `Recorte ${op.aspect_ratio}` : "Recorte";
    case "rotate":
      return `Girar ${op.degrees ?? 90}°`;
    case "auto_exposure":
      return "Luz automática";
    case "auto_white_balance":
      return "Color automático";
    case "resize":
      return `Al exportar: ${resizeText(op)}`;
    default:
      return op.op;
  }
}

function ValueInput({ row, a }: { row: PlanRow; a: Adjustment }) {
  const value = row.edited ?? planValue(row.op, a);
  const [text, setText] = useState(String(value));
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) setText(String(value));
  }, [value, editing]);
  const commit = () => {
    setEditing(false);
    const v = text.trim() === "" ? Number.NaN : Number(text.replace(",", "."));
    editorStore.getState().editRow(row.index, v);
    // Si el valor quedó igual (p. ej. recortado al mismo máximo), el efecto no corre: se repone.
    setText(String(value));
  };
  return (
    <input
      type="number"
      className="input plan-num"
      aria-label={`Cambio de ${a.label}${a.unit ? ` (${a.unit})` : ""}`}
      step={a.step}
      min={a.min}
      max={a.max}
      value={text}
      disabled={!row.included}
      onFocus={() => setEditing(true)}
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          e.stopPropagation();
          setText(String(value));
          setEditing(false);
          e.currentTarget.blur();
        }
      }}
    />
  );
}

function Row({ row, draft }: { row: PlanRow; draft: EditPlan | null }) {
  const id = useId();
  const a = rowAdjustment(row.op);
  const result = a && draft && row.included ? formatValue(a, getValue(draft, a)) : null;
  return (
    <li className={`plan-row ${row.included ? "" : "is-off"}`}>
      <input
        id={id}
        type="checkbox"
        className="plan-check"
        checked={row.included}
        onChange={() => editorStore.getState().toggleRow(row.index)}
      />
      <label htmlFor={id} className="plan-name">
        {a ? a.label : fixedText(row.op)}
      </label>
      {a && <ValueInput row={row} a={a} />}
      {result !== null && (
        <span className="plan-result" title="Cómo queda en la foto">
          → {result}
        </span>
      )}
    </li>
  );
}

function Clarification({ question }: { question: string }) {
  const id = useId();
  const [text, setText] = useState("");
  return (
    <div className="plan-clarify">
      <label htmlFor={id} className="plan-question">
        {question}
      </label>
      <input
        id={id}
        className="input"
        value={text}
        placeholder="Tu respuesta"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && text.trim()) {
            e.preventDefault();
            void editorStore.getState().answer(text);
          } else if (e.key === "Escape") {
            e.stopPropagation();
            e.currentTarget.blur();
          }
        }}
      />
    </div>
  );
}

function Thinking() {
  const [late, setLate] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setLate(true), THINKING_DELAY_MS);
    return () => window.clearTimeout(t);
  }, []);
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
  const messages = [...(result?.errors ?? []), ...(result?.warnings ?? [])];
  const resize = plan.rows.find((r) => r.included && r.op.op === "resize")?.op as Resize | undefined;

  return (
    <section className="plan" aria-label="Plan propuesto">
      <h2 className="panel-title">Plan propuesto</h2>
      {question ? (
        <Clarification question={question} />
      ) : (
        <>
          {p?.explanation && <p className="plan-explanation">{p.explanation}</p>}
          {plan.rows.length > 0 && (
            <ul className="plan-rows">
              {plan.rows.map((r) => (
                <Row key={r.index} row={r} draft={plan.draft} />
              ))}
            </ul>
          )}
          {plan.rows.length === 0 && unsupported.length === 0 && (
            <p className="field-hint">No encontré ajustes para ese pedido. Probá con otras palabras.</p>
          )}
        </>
      )}
      {unsupported.length > 0 && (
        <ul className="plan-unsupported">
          {unsupported.map((u, i) => (
            <li key={i}>
              <Icon name="alert" size={16} />
              <span>
                <strong>No disponible:</strong> {u.request}. {u.reason}
                {u.reason && !/[.!?]$/.test(u.reason) ? "." : ""}
                {u.alternative ? ` ${u.alternative}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
      {messages.length > 0 && (
        <ul className="plan-messages">
          {messages.map((m, i) => (
            <li key={i}>{m}</li>
          ))}
        </ul>
      )}
      {resize && !question && (
        <p className="field-hint">El tamaño ({resizeText(resize)}) se usa al exportar, no cambia la foto.</p>
      )}
      <div className="plan-actions">
        {!question && (
          <Button variant="primary" disabled={!hasIncluded(plan)} onClick={() => void editorStore.getState().applyPlan()}>
            Aplicar
          </Button>
        )}
        {discard}
      </div>
    </section>
  );
}
