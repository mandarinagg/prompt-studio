import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { JobInfo } from "../engine/client";
import { type ExportPreset, isFinished, queueLabel, summary } from "../state/jobs";
import { jobsStore, useJobs } from "../state/store";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";
import { PRESETS, photos, progressText } from "./ExportDialog";

const presetName = (id: ExportPreset | undefined) => PRESETS.find((p) => p.id === id)?.short ?? "Export";

function QueueRow({ job, preset, onRemoved }: { job: JobInfo; preset?: ExportPreset; onRemoved(): void }) {
  const id = useId();
  const [cancelling, setCancelling] = useState(false);
  const title = `${presetName(preset)} · ${photos(job.total)}`;
  const finished = isFinished(job);
  const s = finished ? summary(job) : null;
  const hasFile = job.results.some((r) => r.path);

  const cancel = async () => {
    setCancelling(true);
    await jobsStore.getState().cancel(job.id);
    // Si sigue corriendo, el botón queda deshabilitado hasta que el engine termine la foto en curso.
  };

  return (
    <li className={`queue-row ${s?.kind === "error" ? "is-error" : ""}`}>
      <p id={`${id}-title`} className="queue-title">
        {title}
      </p>
      {s === null ? (
        <>
          <p id={`${id}-progress`} className="queue-progress-text">
            {progressText(job, photos(job.total))}
          </p>
          <progress
            aria-labelledby={`${id}-progress`}
            max={1}
            value={job.status === "queued" ? undefined : job.fraction}
          />
          <div className="queue-actions">
            <Button variant="danger" aria-describedby={`${id}-title`} disabled={cancelling} onClick={cancel}>
              {cancelling ? "Cancelando…" : "Cancelar"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="queue-summary">
            <Icon name={s.kind === "error" ? "alert" : "check"} size={16} />
            <span className="selectable">{s.text}</span>
          </p>
          <div className="queue-actions">
            {hasFile && (
              <Button
                icon="folder"
                aria-describedby={`${id}-title`}
                onClick={() => void jobsStore.getState().openFolder(job.id)}
              >
                Abrir carpeta
              </Button>
            )}
            <Button
              variant="quiet"
              aria-describedby={`${id}-title`}
              onClick={() => {
                jobsStore.getState().dismiss(job.id);
                onRemoved();
              }}
            >
              Quitar
            </Button>
          </div>
        </>
      )}
    </li>
  );
}

/**
 * La cola de exports, abajo a la derecha mientras haya un proyecto abierto (biblioteca y editor).
 * Cerrada es un botón con el resumen; abierta lista cada job con su avance o su resultado. Esc la
 * cierra y devuelve el foco al botón.
 */
export function QueueDrawer() {
  const jobs = useJobs((s) => s.jobs);
  const order = useJobs((s) => s.order);
  const presets = useJobs((s) => s.presets);
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const list = useMemo(() => order.flatMap((id) => (jobs[id] ? [jobs[id]] : [])), [order, jobs]);
  const running = list.some((j) => !isFinished(j));

  useEffect(() => {
    if (list.length === 0) setOpen(false);
  }, [list.length]);

  if (list.length === 0) return null;

  const close = () => {
    setOpen(false);
    toggleRef.current?.focus();
  };

  return (
    <div
      className="queue"
      onKeyDown={(e) => {
        if (e.key !== "Escape" || !open) return;
        e.preventDefault();
        e.stopPropagation(); // que Esc no cierre también el editor ni limpie la selección
        close();
      }}
    >
      {open && (
        <section id={panelId} className="queue-panel" role="region" aria-label="Cola de exports">
          <ul className="queue-list">
            {list.map((job) => (
              <QueueRow key={job.id} job={job} preset={presets[job.id]} onRemoved={() => toggleRef.current?.focus()} />
            ))}
          </ul>
        </section>
      )}
      <button
        ref={toggleRef}
        type="button"
        className={`queue-toggle ${running ? "is-running" : ""}`}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => setOpen((o) => !o)}
      >
        {!running && <Icon name="check" size={16} />}
        <span>{queueLabel(list)}</span>
        <Icon name="chevron" size={14} />
      </button>
    </div>
  );
}
