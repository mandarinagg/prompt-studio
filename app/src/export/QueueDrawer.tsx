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
    if (cancelling) return;
    setCancelling(true);
    // Si el pedido falló (ya avisó), se puede reintentar. Si salió bien y la foto en curso todavía
    // se está terminando, queda en "Cancelando…" hasta que llegue el final.
    if (!(await jobsStore.getState().cancel(job.id))) setCancelling(false);
  };

  const remove = () => {
    jobsStore.getState().dismiss(job.id);
    onRemoved();
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
        </>
      ) : (
        <p className="queue-summary">
          <Icon name={s.kind === "error" ? "alert" : "check"} size={16} />
          <span className="selectable">{s.text}</span>
        </p>
      )}
      <div className="queue-actions">
        {finished && hasFile && (
          <Button icon="folder" aria-describedby={`${id}-title`} onClick={() => void jobsStore.getState().openFolder(job.id)}>
            Abrir carpeta
          </Button>
        )}
        {/* Cancelar y Quitar son el mismo botón (misma `key`, mismo lugar): si el job termina con
            el foco en Cancelar, el foco queda en Quitar en vez de perderse. Mientras cancela usa
            aria-disabled y no disabled, que también le sacaría el foco. */}
        <Button
          key="end"
          variant={finished ? "quiet" : "danger"}
          aria-describedby={`${id}-title`}
          aria-disabled={!finished && cancelling ? true : undefined}
          onClick={finished ? remove : cancel}
        >
          {finished ? "Quitar" : cancelling ? "Cancelando…" : "Cancelar"}
        </Button>
      </div>
    </li>
  );
}

/** Con la cola vacía, el foco vuelve a la foto con foco de la cuadrícula o al área principal. */
function focusMain() {
  const target =
    document.querySelector<HTMLElement>('.library-grid [data-asset][tabindex="0"]') ??
    document.querySelector<HTMLElement>("[data-main]");
  target?.focus({ preventScroll: true });
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
  const panelRef = useRef<HTMLElement>(null);
  const panelId = useId();

  const list = useMemo(() => order.flatMap((id) => (jobs[id] ? [jobs[id]] : [])), [order, jobs]);
  const running = list.some((j) => !isFinished(j));

  useEffect(() => {
    if (list.length === 0) setOpen(false);
  }, [list.length]);

  // Al abrir, el foco entra a la cola: el toggle va antes que el panel en el DOM (el panel se ve
  // arriba por CSS), así que sin esto el próximo Tab saldría de la cola.
  useEffect(() => {
    if (!open) return;
    const panel = panelRef.current;
    (panel?.querySelector<HTMLElement>("button:not([disabled])") ?? panel)?.focus({ preventScroll: true });
  }, [open]);

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
      {open && (
        <section
          ref={panelRef}
          id={panelId}
          className="queue-panel"
          role="region"
          tabIndex={-1}
          aria-label="Cola de exports"
        >
          <ul className="queue-list">
            {list.map((job) => (
              <QueueRow
                key={job.id}
                job={job}
                preset={presets[job.id]}
                // Si era el último, el botón de la cola desaparece: el foco va al área principal.
                onRemoved={() => (jobsStore.getState().order.length === 0 ? focusMain() : toggleRef.current?.focus())}
              />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
