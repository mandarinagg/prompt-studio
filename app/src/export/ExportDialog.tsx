import { open as pickFolder } from "@tauri-apps/plugin-dialog";
import { useEffect, useId, useState } from "react";
import { resizeText } from "../editor/PlanPanel";
import type { AssetSummary, JobInfo, Resize } from "../engine/client";
import { type ExportPreset, exportable } from "../state/jobs";
import { appStore, jobsStore, useApp } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

/** Presets de docs/EXPORT_PRESETS.md con palabras de usuario (diseño §7); `short`, para la cola. */
export const PRESETS: { id: ExportPreset; title: string; short: string; detail: string }[] = [
  { id: "web", title: "Web — liviana para subir", short: "Web", detail: "WebP, lado largo 2048 px, sin ubicación" },
  {
    id: "catalog_square",
    title: "Cuadrada 1080 — catálogo",
    short: "Cuadrada 1080",
    detail: "JPEG 1080×1080, recorte centrado",
  },
  { id: "social_vertical", title: "Vertical 4:5", short: "Vertical 4:5", detail: "JPEG 1080×1350, recorte centrado" },
  { id: "story_9x16", title: "Historia 9:16", short: "Historia 9:16", detail: "JPEG 1080×1920, recorte centrado" },
  { id: "original", title: "Original", short: "Original", detail: "Mismo formato y tamaño que la foto" },
  {
    id: "high_quality",
    title: "Máxima calidad",
    short: "Máxima calidad",
    detail: "Tamaño original, TIFF 16 bits o JPEG 95",
  },
];

function message(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

/** "Exportando foto.jpg — 40 %": el avance también en texto, no solo en la barra. */
export function progressText(job: JobInfo, what: string): string {
  if (job.status === "queued") return `Esperando para exportar ${what}…`;
  return `Exportando ${job.current ?? what} — ${Math.floor(job.fraction * 100)} %`;
}

export const photos = (n: number) => (n === 1 ? "1 foto" : `${n} fotos`);

interface ExportDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  /** Las fotos a exportar; las que no se encuentran se avisan y se saltean. */
  assets: AssetSummary[];
  /** Desde el editor: el tamaño que sugirió el pedido. */
  hint?: Resize | null;
  /** Desde el editor: hay un plan sin aplicar (no entra en el export). */
  pendingPlan?: boolean;
}

/**
 * Exportar una o varias fotos con un preset: copias en la carpeta de exports del proyecto (o la
 * elegida, que el proyecto recuerda); los originales no se tocan. Confirmar crea un job del engine
 * y cierra el diálogo: el avance se ve en la cola de exports.
 */
export function ExportDialog({ open, onOpenChange, assets, hint, pendingPlan }: ExportDialogProps) {
  const id = useId();
  const exportDir = useApp((s) => s.project?.export_dir ?? "");
  const [preset, setPreset] = useState<ExportPreset>("web");
  const [outDir, setOutDir] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Cada vez que se abre arranca con la carpeta del proyecto (el preset elegido se mantiene).
  useEffect(() => {
    if (!open) return;
    setOutDir(null);
    setError(null);
  }, [open]);

  const { ids, missing } = exportable(assets);
  const folder = outDir ?? exportDir;
  const what = assets.length === 1 ? assets[0].file : photos(assets.length);

  const chooseFolder = async () => {
    const picked = await pickFolder({ directory: true, title: "Carpeta de exports", defaultPath: folder || undefined });
    if (typeof picked === "string") setOutDir(picked);
  };

  const run = async () => {
    if (starting || ids.length === 0) return;
    setStarting(true);
    setError(null);
    try {
      const chosen = outDir !== null && outDir !== exportDir ? outDir : undefined;
      await jobsStore.getState().submitExport(ids as [string, ...string[]], preset, chosen);
      onOpenChange(false);
      // El proyecto recuerda la carpeta nueva: la próxima vez se propone esa.
      if (chosen) void appStore.getState().refreshProject();
    } catch (err) {
      setError(`No se pudo exportar: ${message(err)}`);
    } finally {
      setStarting(false);
    }
  };

  const folderLabel = `${id}-folder`;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Exportar"
      description={
        assets.length === 1
          ? `${what}: se guarda una copia, la original no se toca.`
          : `${what}: se guarda una copia de cada una, los originales no se tocan.`
      }
      footer={
        <>
          <Button variant="quiet" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={run} disabled={starting || ids.length === 0}>
            {starting ? "Exportando…" : "Exportar"}
          </Button>
        </>
      }
    >
      <div className="form">
        <fieldset className="presets" disabled={starting}>
          <legend className="field-label">Cómo exportar</legend>
          {PRESETS.map((p) => (
            <label key={p.id} className={`preset ${preset === p.id ? "is-on" : ""}`}>
              <input
                type="radio"
                name={`${id}-preset`}
                value={p.id}
                checked={preset === p.id}
                onChange={() => setPreset(p.id)}
              />
              <span className="preset-text">
                <span className="preset-title">{p.title}</span>
                <span className="preset-detail">{p.detail}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <div className="field">
          <span id={folderLabel} className="field-label">
            Carpeta
          </span>
          <div className="field-row">
            <output className="input input-readonly" aria-labelledby={folderLabel} title={folder}>
              {folder}
            </output>
            <Button onClick={chooseFolder} disabled={starting}>
              Cambiar…
            </Button>
          </div>
        </div>
        {missing > 0 && (
          <p className="field-hint" role="note">
            {missing === 1 ? "1 no se encuentra y no se va a exportar." : `${missing} no se encuentran y no se van a exportar.`}
          </p>
        )}
        {hint && (
          <p className="field-hint">
            El pedido sugiere achicar a {resizeText(hint)}. Elegí el preset que mejor se acerque.
          </p>
        )}
        {pendingPlan && (
          <p className="field-hint" role="note">
            El plan sin aplicar no se incluye.
          </p>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </Dialog>
  );
}
