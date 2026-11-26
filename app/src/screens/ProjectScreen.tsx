import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useMemo, useRef, useState } from "react";
import { ExportDialog } from "../export/ExportDialog";
import { adjustShortcut, isExportShortcut } from "../lib/keys";
import { BatchPromptDialog } from "../library/BatchPromptDialog";
import { PasteDialog } from "../library/PasteDialog";
import { IMAGE_FILTER, LibraryGrid } from "../library/LibraryGrid";
import { batchStore, useApp, useLibrary } from "../state/store";
import { Button, IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";

/** Proyecto abierto: barra superior con importar y exportar, y la biblioteca de fotos (cuadrícula con miniaturas). */
export function ProjectScreen({ dragging }: { dragging: boolean }) {
  const project = useApp((s) => s.project)!;
  const close = useApp((s) => s.closeProject);
  const busy = useApp((s) => s.busy);
  const importPhotos = useApp((s) => s.importPhotos);
  const count = project.assets.length;
  const missing = project.assets.filter((a) => a.missing).length;
  const selected = useLibrary((s) => s.selected);
  const [exporting, setExporting] = useState(false);
  const [batching, setBatching] = useState(false);
  const [pasting, setPasting] = useState(false);
  // Las seleccionadas en el orden de la cuadrícula (así se exportan).
  const toExport = useMemo(() => {
    const ids = new Set(selected);
    return project.assets.filter((a) => ids.has(a.id));
  }, [project.assets, selected]);

  const startBatch = () => {
    batchStore.getState().start(
      toExport.map((a) => a.id),
      project.assets,
    );
    setBatching(true);
  };

  const copySelected = () => {
    const only = toExport.length === 1 ? toExport[0] : null;
    if (only && !only.missing) void batchStore.getState().copy(only);
  };
  const openPaste = () => {
    if (batchStore.getState().clipboard && toExport.length > 0) setPasting(true);
  };

  // Ctrl+Shift+C / Ctrl+Shift+V / Ctrl+Z: copiar, pegar y deshacer el último lote de ajustes.
  const shortcuts = useRef({ copySelected, openPaste });
  shortcuts.current = { copySelected, openPaste };
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const action = adjustShortcut(e);
      if (!action || document.querySelector("[role=dialog]")) return;
      if ((e.target as HTMLElement | null)?.closest?.(".queue")) return;
      e.preventDefault();
      if (action === "copy") shortcuts.current.copySelected();
      else if (action === "paste") shortcuts.current.openPaste();
      else void batchStore.getState().undoLast();
    };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
  }, []);

  // Ctrl+E: exportar la selección (con un diálogo abierto, el diálogo manda).
  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (!isExportShortcut(e)) return;
      if (document.querySelector("[role=dialog]") || toExport.length === 0) return;
      e.preventDefault();
      setExporting(true);
    };
    window.addEventListener("keydown", down);
    return () => window.removeEventListener("keydown", down);
  }, [toExport.length]);

  const pickPhotos = async () => {
    const picked = await open({ multiple: true, title: "Importar fotos", filters: IMAGE_FILTER });
    if (Array.isArray(picked) && picked.length > 0) await importPhotos(picked);
  };
  const pickFolder = async () => {
    const picked = await open({ directory: true, title: "Importar carpeta" });
    if (typeof picked === "string") await importPhotos([picked]);
  };

  return (
    <div className="shell">
      <header className="topbar">
        <IconButton icon="back" label="Cerrar proyecto y volver al inicio" onClick={close} />
        <span className="topbar-brand">PROMPT STUDIO</span>
        <span className="topbar-sep" aria-hidden="true" />
        <h1 className="topbar-title">{project.name}</h1>
        <span className="topbar-meta">
          {count === 1 ? "1 foto" : `${count} fotos`}
          {missing > 0 && ` · ${missing === 1 ? "1 no se encuentra" : `${missing} no se encuentran`}`}
        </span>
        <span className="topbar-spacer" />
        <Button variant="secondary" icon="plus" disabled={busy} onClick={pickPhotos}>
          Importar fotos…
        </Button>
        <Button variant="secondary" icon="folder" disabled={busy} onClick={pickFolder}>
          Importar carpeta…
        </Button>
        <Button
          variant="secondary"
          shortcut="Ctrl+E"
          disabled={toExport.length === 0}
          title={toExport.length === 0 ? "Seleccioná las fotos que quieras exportar" : undefined}
          onClick={() => setExporting(true)}
        >
          {toExport.length === 0 ? "Exportar…" : `Exportar ${toExport.length}…`}
        </Button>
      </header>
      <ExportDialog open={exporting} onOpenChange={setExporting} assets={toExport} />
      <BatchPromptDialog open={batching} onOpenChange={setBatching} />
      <PasteDialog open={pasting} onOpenChange={setPasting} targets={toExport.map((a) => a.id)} />

      <main className={`project-body ${dragging ? "is-dragging" : ""}`} data-main tabIndex={-1}>
        {count === 0 ? (
          <div className="empty">
            <Icon name="photo" size={28} />
            <p className="empty-title">Este proyecto todavía no tiene fotos</p>
            <p className="empty-hint">Arrastrá fotos o una carpeta sobre la ventana para agregarlas.</p>
            <Button variant="primary" icon="plus" disabled={busy} onClick={pickPhotos}>
              Importar fotos…
            </Button>
          </div>
        ) : (
          <LibraryGrid onExport={() => setExporting(true)} onBatch={startBatch} onCopy={copySelected} onPaste={openPaste} />
        )}
        {dragging && <p className="drop-hint">Soltalas para agregarlas a {project.name}</p>}
      </main>
    </div>
  );
}
