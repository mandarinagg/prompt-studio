import { useState } from "react";
import type { EditPlan } from "../engine/client";
import {
  ADJUSTMENTS,
  AUTO,
  GROUPS,
  adjustmentLabel,
  formatValue,
  getValue,
  groupChanged,
  setValue,
  type Adjustment,
  type GroupId,
} from "../lib/adjustments";
import { matchRatio, RATIOS, ratioOf, reframe, rotateDegrees, rotateRect, type Ratio } from "../lib/crop";
import { findOp, opsOf, removeOp, setOp, toggleAuto } from "../lib/stack";
import { editorStore, useEditor } from "../state/store";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Slider } from "../ui/Slider";

const AUTO_LABEL: Record<"auto_exposure" | "auto_white_balance", [string, string]> = {
  auto_exposure: ["Luz automática", "Sin luz automática"],
  auto_white_balance: ["Color automático", "Sin color automático"],
};

const live = (stack: EditPlan) => editorStore.getState().live(stack);
const commit = (stack: EditPlan, label: string) => editorStore.getState().commit(stack, label);
const current = () => editorStore.getState().stack;

function AdjustSlider({ a }: { a: Adjustment }) {
  const stack = useEditor((s) => s.stack);
  return (
    <Slider
      label={a.label}
      value={getValue(stack, a)}
      min={a.min}
      max={a.max}
      step={a.step}
      resetValue={0}
      format={(v) => formatValue(a, v)}
      onChange={(v) => live(setValue(current(), a, v))}
      onCommit={(v) => commit(setValue(current(), a, v), adjustmentLabel(a, v))}
    />
  );
}

function AutoButton({ name }: { name: "auto_exposure" | "auto_white_balance" }) {
  const on = useEditor((s) => !!findOp(s.stack, name));
  return (
    <Button
      variant={on ? "primary" : "secondary"}
      aria-pressed={on}
      aria-label={AUTO_LABEL[name][0]}
      onClick={() => commit(toggleAuto(current(), name), AUTO_LABEL[name][on ? 1 : 0])}
    >
      Auto
    </Button>
  );
}

/** Recorte por proporción, rotar 90° y enderezar. */
function Geometry() {
  const stack = useEditor((s) => s.stack);
  const after = useEditor((s) => s.after);
  const cropping = useEditor((s) => s.cropping);
  const crop = findOp(stack, "crop");

  // Fuera del modo recorte la foto que se ve ya está recortada: su forma es la proporción.
  let active: Ratio | null = null;
  if (crop && after) {
    active = findOp(after.stack, "crop") ? matchRatio(after.width / after.height) : ratioOf(after.width, after.height, crop);
  }

  const chooseRatio = (ratio: Ratio) => {
    const s = editorStore.getState();
    const a = s.after;
    // En modo recorte se conoce la foto entera: el marco nuevo queda centrado donde estaba el otro.
    const uncropped = a && !findOp(a.stack, "crop");
    const op =
      uncropped && s.cropping
        ? { op: "crop" as const, rect: reframe(a.width, a.height, ratio, crop?.rect ?? null) }
        : { op: "crop" as const, aspect_ratio: ratio, anchor: "center" as const };
    s.setCropping(true);
    commit(setOp(s.stack, op), `Recorte ${ratio}`);
  };

  const rotate = (delta: 90 | -90) => {
    const s = current();
    const deg = findOp(s, "rotate")?.degrees ?? 0;
    let next = setOp(s, { op: "rotate", degrees: rotateDegrees(deg, delta) });
    const c = findOp(s, "crop");
    if (c?.rect && deg % 90 === 0) next = setOp(next, { ...c, rect: rotateRect(c.rect, delta) });
    commit(next, delta === 90 ? "Rotar a la derecha" : "Rotar a la izquierda");
  };

  return (
    <div className="geometry">
      <div className="geometry-row" role="group" aria-label="Proporción del recorte">
        {RATIOS.map((r) => (
          <Button
            key={r.id}
            variant={active === r.id ? "primary" : "secondary"}
            aria-pressed={active === r.id}
            onClick={() => chooseRatio(r.id)}
          >
            {r.label}
          </Button>
        ))}
        <Button
          variant="quiet"
          disabled={!crop}
          onClick={() => {
            editorStore.getState().setCropping(false);
            commit(removeOp(current(), "crop"), "Sin recorte");
          }}
        >
          Sin recorte
        </Button>
      </div>
      {crop && (
        <Button icon="crop" aria-pressed={cropping} onClick={() => editorStore.getState().setCropping(!cropping)}>
          {cropping ? "Listo" : "Encuadrar"}
        </Button>
      )}
      <div className="geometry-row">
        <Button icon="rotateLeft" onClick={() => rotate(-90)}>
          Rotar a la izquierda
        </Button>
        <Button icon="rotateRight" onClick={() => rotate(90)}>
          Rotar a la derecha
        </Button>
      </div>
      <AdjustSlider a={ADJUSTMENTS.find((a) => a.key === "straighten")!} />
    </div>
  );
}

function Group({ id, label, open, onToggle }: { id: GroupId; label: string; open: boolean; onToggle(): void }) {
  const changed = useEditor((s) => groupChanged(s.stack, id));
  const auto = AUTO[id];
  const sliders = ADJUSTMENTS.filter((a) => a.group === id && a.key !== "straighten");
  return (
    <section className={`group ${open ? "is-open" : ""}`}>
      <div className="group-head">
        <button type="button" className="group-toggle" aria-expanded={open} onClick={onToggle}>
          <Icon name="chevron" size={16} />
          <span>{label}</span>
          {changed && (
            <span className="group-dot" title="Modificado">
              <span className="sr-only">(modificado)</span>
            </span>
          )}
        </button>
        {auto && open && <AutoButton name={auto} />}
      </div>
      {open && (
        <div className="group-body">
          {id === "geometry" ? <Geometry /> : sliders.map((a) => <AdjustSlider key={a.key} a={a} />)}
        </div>
      )}
    </section>
  );
}

/** Ajustes agrupados (Luz, Color, Detalle, Efectos, Geometría). */
export function AdjustPanel() {
  const [open, setOpen] = useState<Set<GroupId>>(new Set(["light"]));
  const empty = useEditor((s) => opsOf(s.stack).length === 0);
  const toggle = (id: GroupId) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div className="adjust">
      <h2 className="panel-title">Ajustes</h2>
      {GROUPS.map((g) => (
        <Group key={g.id} id={g.id} label={g.label} open={open.has(g.id)} onToggle={() => toggle(g.id)} />
      ))}
      <div className="adjust-foot">
        <Button variant="quiet" disabled={empty} onClick={() => editorStore.getState().resetAll()}>
          Restablecer todo
        </Button>
      </div>
    </div>
  );
}
