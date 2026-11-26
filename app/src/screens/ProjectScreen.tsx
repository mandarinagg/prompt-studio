import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useMemo, useState } from "react";
import { ExportDialog } from "../export/ExportDialog";
import { isExportShortcut } from "../lib/keys";
import { IMAGE_FILTER, LibraryGrid } from "../library/LibraryGrid";
import { useApp, useLibrary } from "../state/store";
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
  // Las seleccionadas en el orden de la cuadrícula (así se exportan).
  const toExport = useMemo(() => {
    const ids = new Set(selected);
    return project.assets.filter((a) => ids.has(a.id));
  }, [project.assets, selected]);

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
          <LibraryGrid onExport={() => setExporting(true)} />
        )}
        {dragging && <p className="drop-hint">Soltalas para agregarlas a {project.name}</p>}
      </main>
    </div>
  );
}
