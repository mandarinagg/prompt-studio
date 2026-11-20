import { useEffect, useRef, useState } from "react";
import { hasGeometry } from "../lib/stack";
import { appStore, editorStore, useApp, useEditor } from "../state/store";
import { IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Tooltip } from "../ui/Tooltip";
import { AdjustPanel } from "./AdjustPanel";
import { Viewer } from "./Viewer";

const HOLD_MS = 250;

/** Volver a la lista de fotos: la marca "Editada" puede haber cambiado. */
export function closeEditor() {
  editorStore.getState().close();
  appStore.getState().refreshProject();
}

function isTyping(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

/** Editor de una foto: visor a la izquierda, ajustes a la derecha (diseño §7). */
export function EditorScreen() {
  const asset = useEditor((s) => s.asset)!;
  const saved = useEditor((s) => s.saved);
  const geometry = useEditor((s) => hasGeometry(s.stack));
  const assets = useApp((s) => s.project?.assets ?? []);
  const [holdBefore, setHoldBefore] = useState(false);
  const [split, setSplit] = useState(false);
  const holdTimer = useRef<number | null>(null);
  const held = useRef(false);

  const canSplit = !geometry;
  useEffect(() => {
    if (!canSplit) setSplit(false);
  }, [canSplit]);

  // ←/→: foto anterior o siguiente (salteando las que no se encuentran).
  const neighbour = (delta: 1 | -1) => {
    const usable = assets.filter((a) => !a.missing || a.id === asset.id);
    const i = usable.findIndex((a) => a.id === asset.id);
    const next = usable[i + delta];
    if (next) editorStore.getState().open(next);
  };

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const s = editorStore.getState();
      if (e.key === "Escape") {
        if (document.querySelector("[role=dialog]")) return;
        e.preventDefault();
        if (s.cropping) s.setCropping(false);
        else closeEditor();
        return;
      }
      if (isTyping(e.target)) return;
      const key = e.key.toLowerCase();
      if (e.ctrlKey && !e.altKey) {
        if (key === "z" && !e.shiftKey) s.undo();
        else if ((key === "z" && e.shiftKey) || key === "y") s.redo();
        else return;
        e.preventDefault();
        return;
      }
      if (e.altKey || e.metaKey) return;
      if (e.key === "\\") {
        e.preventDefault();
        setHoldBefore(true);
      } else if (key === "z") {
        s.setZoom(s.zoom === "fit" ? "actual" : "fit");
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        if ((e.target as HTMLElement)?.closest?.("[role=slider], .crop-frame")) return;
        e.preventDefault();
        neighbour(e.key === "ArrowLeft" ? -1 : 1);
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === "\\") setHoldBefore(false);
    };
    const blur = () => setHoldBefore(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  });

  // ◐: mantener muestra el original; un clic alterna la vista dividida.
  const comparePress = () => {
    held.current = false;
    holdTimer.current = window.setTimeout(() => {
      held.current = true;
      setHoldBefore(true);
    }, HOLD_MS);
  };
  const compareRelease = () => {
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    holdTimer.current = null;
    if (held.current) setHoldBefore(false);
    else if (canSplit) setSplit((v) => !v);
    held.current = false;
  };

  const compareLabel = canSplit
    ? `${split ? "Ocultar" : "Ver"} antes y después. Mantené apretado (o la tecla \\) para ver el original.`
    : "Mantené apretado (o la tecla \\) para ver el original. Con recorte o giro no hay vista dividida.";

  return (
    <div className="shell editor">
      <header className="topbar">
        <IconButton icon="back" label="Volver a las fotos (Esc)" onClick={closeEditor} />
        <h1 className="topbar-title">{asset.file}</h1>
        <span className="topbar-meta">{saved?.label && saved.cursor > 0 ? saved.label : ""}</span>
        <span className="topbar-spacer" />
        <IconButton
          icon="undo"
          label="Deshacer (Ctrl+Z)"
          disabled={!saved?.can_undo}
          onClick={() => editorStore.getState().undo()}
        />
        <IconButton
          icon="redo"
          label="Rehacer (Ctrl+Shift+Z)"
          disabled={!saved?.can_redo}
          onClick={() => editorStore.getState().redo()}
        />
        <Tooltip text={compareLabel}>
          <button
            type="button"
            className={`btn btn-secondary compare ${split ? "is-on" : ""}`}
            aria-pressed={canSplit ? split : undefined}
            aria-label={compareLabel}
            onPointerDown={comparePress}
            onPointerUp={compareRelease}
            onPointerLeave={() => {
              if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
              holdTimer.current = null;
              if (held.current) setHoldBefore(false);
              held.current = false;
            }}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && canSplit) {
                e.preventDefault();
                setSplit((v) => !v);
              }
            }}
          >
            <Icon name="compare" />
            <span>Antes/Después</span>
          </button>
        </Tooltip>
      </header>
      <div className="editor-body">
        <Viewer holdBefore={holdBefore} split={split} />
        <aside className="panel" aria-label="Ajustes de la foto">
          <AdjustPanel />
        </aside>
      </div>
    </div>
  );
}
