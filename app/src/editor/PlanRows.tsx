// Piezas presentacionales del plan propuesto, compartidas por el editor (PlanPanel) y el pedido
// para varias fotos (BatchPromptDialog): no conocen ningún store, reciben todo por props.
import { useEffect, useId, useState } from "react";
import type { EditPlan, PlanCreated, Resize } from "../engine/client";
import { formatValue, getValue, type Adjustment } from "../lib/adjustments";
import type { Operation } from "../lib/stack";
import { planValue, rowAdjustment, type PlanRow } from "../state/draft";
import { Icon } from "../ui/Icon";

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

function ValueInput({ row, a, onEdit, disabled }: { row: PlanRow; a: Adjustment; onEdit(index: number, value: number): void; disabled?: boolean }) {
  const value = row.edited ?? planValue(row.op, a);
  const [text, setText] = useState(String(value));
  const [editing, setEditing] = useState(false);
  useEffect(() => {
    if (!editing) setText(String(value));
  }, [value, editing]);
  const commit = () => {
    setEditing(false);
    const v = text.trim() === "" ? Number.NaN : Number(text.replace(",", "."));
    onEdit(row.index, v);
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
      disabled={!row.included || disabled}
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

function Row({
  row,
  draft,
  showResult,
  disabled,
  onToggle,
  onEdit,
}: {
  row: PlanRow;
  draft: EditPlan | null;
  showResult: boolean;
  disabled?: boolean;
  onToggle(index: number): void;
  onEdit(index: number, value: number): void;
}) {
  const id = useId();
  const a = rowAdjustment(row.op);
  const result = showResult && a && draft && row.included ? formatValue(a, getValue(draft, a)) : null;
  return (
    <li className={`plan-row ${row.included ? "" : "is-off"}`}>
      <input
        id={id}
        type="checkbox"
        className="plan-check"
        checked={row.included}
        disabled={disabled}
        onChange={() => onToggle(row.index)}
      />
      <label htmlFor={id} className="plan-name">
        {a ? a.label : fixedText(row.op)}
      </label>
      {a && <ValueInput row={row} a={a} onEdit={onEdit} disabled={disabled} />}
      {result !== null && (
        <span className="plan-result" title="Cómo queda en la foto">
          → {result}
        </span>
      )}
    </li>
  );
}

interface PlanRowsProps {
  rows: PlanRow[];
  onToggle(index: number): void;
  onEdit(index: number, value: number): void;
  /** Muestra "→ resultado" junto a cada fila (necesita `draft`); en lote solo se ve el cambio. */
  showResult: boolean;
  draft?: EditPlan | null;
  disabled?: boolean;
}

/** Las filas del plan: casilla, nombre y valor editable. */
export function PlanRows({ rows, onToggle, onEdit, showResult, draft = null, disabled }: PlanRowsProps) {
  if (rows.length === 0) return null;
  return (
    <ul className="plan-rows">
      {rows.map((r) => (
        <Row key={r.index} row={r} draft={draft} showResult={showResult} disabled={disabled} onToggle={onToggle} onEdit={onEdit} />
      ))}
    </ul>
  );
}

/** Lo "no disponible" del plan (en ámbar, con el motivo) y los avisos del proveedor. */
export function PlanNotes({ result }: { result: PlanCreated | undefined }) {
  const unsupported = result?.plan?.unsupported ?? [];
  const messages = [...(result?.errors ?? []), ...(result?.warnings ?? [])];
  return (
    <>
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
    </>
  );
}

/** La pregunta del plan y el campo para responderla. */
export function Clarification({ question, onAnswer }: { question: string; onAnswer(text: string): void }) {
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
            onAnswer(text);
          } else if (e.key === "Escape") {
            e.stopPropagation();
            e.currentTarget.blur();
          }
        }}
      />
    </div>
  );
}
