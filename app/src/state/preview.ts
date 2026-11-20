// "Gana el último" (diseño §6): como mucho una preview en vuelo y una pendiente por tipo. Las
// intermedias se descartan, no se encolan.
//
// La unidad en vuelo incluye leer los bytes (`read_cache`): el engine borra la preview anterior
// de una foto cuando renderiza la siguiente, así que nunca se pide otra antes de tener la actual.
import type { EditPlan } from "../engine/client";

export interface PreviewJob {
  /** "after": la foto con la pila (o el borrador); "before": el original. */
  kind: "after" | "before";
  asset: string;
  stack: EditPlan;
  longSide: number;
}

export interface PreviewResult {
  url: string; // blob URL; el bucle la libera cuando la reemplaza
  width: number;
  height: number;
  ms: number;
}

export interface PreviewLoopEvents {
  onResult(job: PreviewJob, result: PreviewResult): void;
  onError?(job: PreviewJob, err: unknown): void;
  revoke(url: string): void;
}

export interface PreviewLoop {
  request(job: PreviewJob): void;
  /** Olvida lo pendiente y descarta lo que esté en vuelo (cambio de foto, cierre). */
  reset(): void;
  /** reset + libera lo último que se mostró. */
  dispose(): void;
}

const ORDER: PreviewJob["kind"][] = ["after", "before"];

export function createPreviewLoop(
  render: (job: PreviewJob) => Promise<PreviewResult>,
  events: PreviewLoopEvents,
): PreviewLoop {
  const pending = new Map<PreviewJob["kind"], PreviewJob>();
  const shown = new Map<PreviewJob["kind"], string>();
  let busy = false;
  let generation = 0;

  const next = () => {
    if (busy) return;
    const kind = ORDER.find((k) => pending.has(k));
    if (!kind) return;
    const job = pending.get(kind)!;
    pending.delete(kind);
    busy = true;
    const gen = generation;
    render(job).then(
      (result) => {
        busy = false;
        if (gen !== generation) {
          events.revoke(result.url);
        } else {
          const old = shown.get(job.kind);
          shown.set(job.kind, result.url);
          events.onResult(job, result);
          if (old) events.revoke(old);
        }
        next();
      },
      (err) => {
        busy = false;
        if (gen === generation) events.onError?.(job, err);
        next();
      },
    );
  };

  return {
    request(job) {
      pending.set(job.kind, job);
      next();
    },
    reset() {
      generation++;
      pending.clear();
    },
    dispose() {
      this.reset();
      for (const url of shown.values()) events.revoke(url);
      shown.clear();
    },
  };
}
