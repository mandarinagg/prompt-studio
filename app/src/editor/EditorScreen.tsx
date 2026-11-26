import { useEffect, useRef, useState } from "react";
import { ExportDialog } from "../export/ExportDialog";
import { isTyping } from "../lib/keys";
import { hasGeometry } from "../lib/stack";
import { appStore, editorStore, useApp, useEditor } from "../state/store";
import { Button, IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { Tooltip } from "../ui/Tooltip";
import { AdjustPanel } from "./AdjustPanel";
import { Filmstrip } from "./Filmstrip";
import { PlanPanel } from "./PlanPanel";
import { focusPrompt, PromptBox } from "./PromptBox";
import { Viewer } from "./Viewer";

const HOLD_MS = 250;

/** Volver a la lista de fotos: la marca "Editada" puede haber cambiado. */
export function closeEditor() {
  editorStore.getState().close();
  appStore.getState().refreshProject();
}

/** Editor de una foto: visor a la izquierda, ajustes a la derecha (diseño §7). */
export function EditorScreen() {
  const asset = useEditor((s) => s.asset)!;
  const saved = useEditor((s) => s.saved);
  const geometry = useEditor((s) => hasGeometry(s.stack));
  const exportHint = useEditor((s) => s.exportHint);
  const pendingPlan = useEditor((s) => s.plan !== null);
  const assets = useApp((s) => s.project?.assets ?? []);
  const [holdBefore, setHoldBefore] = useState(false);
  const [split, setSplit] = useState(false);
  const [exporting, setExporting] = useState(false);
  const holdTimer = useRef<number | null>(null);
  const held = useRef(false);

  const canSplit = !geometry;
  useEffect(() => {
    if (!canSplit) setSplit(false);
  }, [canSplit]);

  // ←/→: foto anterior o siguiente (salteando las que no se encuentran).
  const neighbour = useRef<(delta: 1 | -1) => void>(() => {});
  neighbour.current = (delta) => {
    const usable = assets.filter((a) => !a.missing || a.id === asset.id);
    const i = usable.findIndex((a) => a.id === asset.id);
    const next = usable[i + delta];
    if (next) editorStore.getState().open(next);
  };

  useEffect(() => {
    const isBackslash = (e: KeyboardEvent) => e.key === "\\" || e.code === "Backslash";
    const down = (e: KeyboardEvent) => {
      const s = editorStore.getState();
      if (isTyping(e.target)) return; // Esc en un campo lo maneja el campo (cancela lo escrito)
      // Con un diálogo abierto (export) los atajos del editor no corren: el diálogo maneja Esc.
      if (document.querySelector("[role=dialog]")) return;
      // En la cola de exports, las flechas y Esc son de la cola.
      if ((e.target as HTMLElement | null)?.closest?.(".queue")) return;
      // `\` va antes que los modificadores: en teclados en español se escribe con AltGr (Ctrl+Alt).
      if (isBackslash(e)) {
        e.preventDefault();
        setHoldBefore(true);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        if (s.cropping) s.setCropping(false);
        else closeEditor();
        return;
      }
      const key = e.key.toLowerCase();
      if (e.ctrlKey && !e.altKey) {
        if (key === "k") focusPrompt();
        else if (key === "e") {
          if (!s.asset?.missing && !e.repeat) setExporting(true);
        }
        else if (key === "z" && !e.shiftKey) s.undo();
        else if ((key === "z" && e.shiftKey) || key === "y") s.redo();
        else return;
        e.preventDefault();
        return;
      }
      if (e.ctrlKey || e.altKey || e.metaKey) return;
      if (e.key === "/") {
        e.preventDefault(); // que la barra no quede escrita en el pedido
        focusPrompt();
      } else if (key === "z") {
        s.setZoom(s.zoom === "fit" ? "actual" : "fit");
      } else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        if ((e.target as HTMLElement)?.closest?.("[role=slider], .crop-frame")) return;
        e.preventDefault();
        if (!e.repeat) neighbour.current(e.key === "ArrowLeft" ? -1 : 1);
      }
    };
    const up = (e: KeyboardEvent) => {
      // Con AltGr la tecla puede soltarse como otra; soltar AltGr también termina el "mantener".
      if (isBackslash(e) || e.key === "AltGraph" || e.key === "Alt" || e.key === "Control") setHoldBefore(false);
    };
    const blur = () => setHoldBefore(false);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    };
  }, []);

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
            onPointerCancel={() => {
              if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
              holdTimer.current = null;
              held.current = false;
              setHoldBefore(false);
            }}
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
        <Button variant="secondary" shortcut="Ctrl+E" disabled={asset.missing} onClick={() => setExporting(true)}>
          Exportar…
        </Button>
      </header>
      <ExportDialog
        open={exporting}
        onOpenChange={setExporting}
        assets={[asset]}
        hint={exportHint}
        pendingPlan={pendingPlan}
      />
      <div className="editor-body" data-main tabIndex={-1}>
        <Viewer holdBefore={holdBefore} split={split} />
        <aside className="panel" aria-label="Pedido y ajustes de la foto">
          <PromptBox key={asset.id} />
          <PlanPanel />
          <AdjustPanel />
        </aside>
      </div>
      <Filmstrip />
    </div>
  );
}
