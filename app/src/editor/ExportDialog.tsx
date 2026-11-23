import { useEffect, useId, useState } from "react";
import type { JobInfo } from "../engine/client";
import { type ExportPreset, isFinished, summary } from "../state/jobs";
import { jobsStore, useEditor, useJobs } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { resizeText } from "./PlanPanel";

type Preset = ExportPreset;

/** Presets de docs/EXPORT_PRESETS.md con palabras de usuario (diseño §7). */
export const PRESETS: { id: Preset; title: string; detail: string }[] = [
  { id: "web", title: "Web — liviana para subir", detail: "WebP, lado largo 2048 px, sin ubicación" },
  { id: "catalog_square", title: "Cuadrada 1080 — catálogo", detail: "JPEG 1080×1080, recorte centrado" },
  { id: "social_vertical", title: "Vertical 4:5", detail: "JPEG 1080×1350, recorte centrado" },
  { id: "story_9x16", title: "Historia 9:16", detail: "JPEG 1080×1920, recorte centrado" },
  { id: "original", title: "Original", detail: "Mismo formato y tamaño que la foto" },
  { id: "high_quality", title: "Máxima calidad", detail: "Tamaño original, TIFF 16 bits o JPEG 95" },
];

function message(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

/** "Exportando foto.jpg — 40 %": el avance también en texto, no solo en la barra. */
export function progressText(job: JobInfo, file: string): string {
  if (job.status === "queued") return `Esperando para exportar ${file}…`;
  return `Exportando ${job.current ?? file} — ${Math.floor(job.fraction * 100)} %`;
}

interface ExportDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
}

/**
 * Exportar la foto actual con un preset: una copia en Exportadas/, el original no se toca. El
 * export es un job del engine (#60): el diálogo muestra su avance y deja cancelarlo; cerrarlo
 * no lo cancela (el toast avisa al terminar) y al reabrirlo se ve el avance del job en curso.
 */
export function ExportDialog({ open, onOpenChange }: ExportDialogProps) {
  const id = useId();
  const asset = useEditor((s) => s.asset);
  const hint = useEditor((s) => s.exportHint);
  const pendingPlan = useEditor((s) => s.plan !== null);
  const job = useJobs((s) => (asset ? s.jobs[s.byAsset[asset.id]] : undefined));
  const [preset, setPreset] = useState<Preset>("web");
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** El job que se vio correr con el diálogo abierto: al terminar, el diálogo reacciona. */
  const [watching, setWatching] = useState<string | null>(null);

  const running = job !== undefined && !isFinished(job);
  const busy = starting || running;

  useEffect(() => {
    if (!job) return;
    if (!isFinished(job)) {
      if (open) setWatching(job.id);
      return;
    }
    setCancelling(false);
    if (watching !== job.id) return;
    setWatching(null);
    if (!open) return; // el toast ya avisó
    const s = summary(job);
    if (job.status === "done" && s.kind === "info") onOpenChange(false);
    else if (s.kind === "error") setError(s.text);
  }, [job, open, watching, onOpenChange]);

  const run = async () => {
    if (!asset || busy) return;
    setStarting(true);
    setError(null);
    try {
      const job = await jobsStore.getState().submitExport([asset.id], preset);
      setWatching(job.id); // por si ya terminó antes de verlo correr
    } catch (err) {
      setError(`No se pudo exportar: ${message(err)}`);
    } finally {
      setStarting(false);
    }
  };

  const cancel = async () => {
    if (!job || !running || cancelling) return;
    setCancelling(true);
    await jobsStore.getState().cancel(job.id);
    // Si sigue corriendo, el botón queda deshabilitado hasta que el worker termine la foto.
  };

  const close = () => {
    setError(null);
    onOpenChange(false);
  };

  const last = job?.status === "done" ? job.results.find((r) => r.asset === asset?.id)?.path : null;
  const textId = `${id}-progress`;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setError(null);
        onOpenChange(o);
      }}
      title="Exportar"
      description="Se guarda una copia en la carpeta Exportadas, junto al proyecto. La foto original no se toca."
      footer={
        running ? (
          <>
            <Button variant="quiet" onClick={close}>
              Cerrar
            </Button>
            <Button variant="danger" onClick={cancel} disabled={cancelling}>
              {cancelling ? "Cancelando…" : "Cancelar export"}
            </Button>
          </>
        ) : (
          <>
            <Button variant="quiet" onClick={close}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={run} disabled={busy || !asset}>
              {starting ? "Exportando…" : "Exportar"}
            </Button>
          </>
        )
      }
    >
      <div className="form">
        <fieldset className="presets" disabled={busy}>
          <legend className="field-label">Cómo exportar {asset?.file}</legend>
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
        {running && job && (
          <div className="export-progress">
            <p id={textId} className="export-progress-text">
              {progressText(job, asset?.file ?? "la foto")}
            </p>
            <progress aria-labelledby={textId} max={1} value={job.status === "queued" ? undefined : job.fraction} />
            <p className="field-hint">Podés cerrar esta ventana: el export sigue y te avisamos cuando termine.</p>
          </div>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {last && !error && (
          <p className="field-hint">
            Última exportada: <span className="path selectable">{last}</span>
          </p>
        )}
      </div>
    </Dialog>
  );
}
