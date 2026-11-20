import * as RS from "@radix-ui/react-slider";
import { useEffect, useId, useState } from "react";
import { parseNumber, snap } from "../lib/numbers";

interface SliderProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  /** Valor al que vuelve con doble clic. */
  resetValue: number;
  /** Texto del valor ("+0.40 EV"); también lo leen los lectores de pantalla. */
  format?(value: number): string;
  /** Mientras se arrastra o se usan las flechas. */
  onChange(value: number): void;
  /** Al soltar, al confirmar el número o al restablecer. */
  onCommit?(value: number): void;
}

/**
 * Slider con etiqueta, valor editable, doble clic para restablecer y flechas para ajuste fino
 * (Shift o RePág/AvPág: pasos de a 10).
 */
export function Slider({ label, value, min, max, step, resetValue, format, onChange, onCommit }: SliderProps) {
  const id = useId();
  const show = format ?? ((v: number) => String(v));
  const [text, setText] = useState(show(value));
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) setText(show(value));
  }, [value, editing]); // eslint-disable-line react-hooks/exhaustive-deps

  const commitText = () => {
    setEditing(false);
    const parsed = parseNumber(text.replace(/[^\d.,+-]/g, ""), min, max);
    if (parsed === null) {
      setText(show(value));
      return;
    }
    const v = snap(parsed, step);
    onChange(v);
    onCommit?.(v);
  };

  const reset = () => {
    onChange(resetValue);
    onCommit?.(resetValue);
  };

  return (
    <div className={`slider ${value !== resetValue ? "is-changed" : ""}`}>
      <div className="slider-head">
        <label htmlFor={`${id}-num`} className="slider-label">
          {label}
        </label>
        <input
          id={`${id}-num`}
          className="slider-num"
          inputMode="decimal"
          value={text}
          onFocus={() => setEditing(true)}
          onChange={(e) => setText(e.target.value)}
          onBlur={commitText}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              setText(show(value));
              setEditing(false);
              e.currentTarget.blur();
            }
          }}
        />
      </div>
      <RS.Root
        className="slider-root"
        min={min}
        max={max}
        step={step}
        value={[value]}
        onValueChange={([v]) => onChange(snap(v, step))}
        onValueCommit={([v]) => onCommit?.(snap(v, step))}
        onDoubleClick={reset}
      >
        <RS.Track className="slider-track">
          <RS.Range className="slider-range" />
        </RS.Track>
        <RS.Thumb className="slider-thumb" aria-label={label} aria-valuetext={show(value)} />
      </RS.Root>
    </div>
  );
}
