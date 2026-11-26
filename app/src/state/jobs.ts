// Trabajos largos del engine (#60, #62): por ahora, exports. Se alimenta de los eventos `job.*` y
// de las respuestas de `job.export` / `job.cancel`, que pueden llegar en cualquier orden: el
// estado de un job nunca retrocede. Al terminar cada job avisa con un toast, esté o no abierta la
// cola. Recibe el cliente del engine por parámetro para poder probarlo sin Tauri.
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, call as engineCall, JobExportParams, JobInfo } from "../engine/client";

export interface JobsApi {
  call: typeof engineCall;
  notify(kind: "info" | "error", text: string): void;
  /** Abre la carpeta en el Explorador (Rust solo abre carpetas de exports). */
  openFolder(path: string): Promise<void>;
}

export type JobEvent = "job.progress" | "job.done" | "job.failed";
export type ExportPreset = NonNullable<JobExportParams["preset"]>;

export interface JobsState {
  jobs: Record<string, JobInfo>;
  /** Ids de los jobs de la cola, el más nuevo primero. */
  order: string[];
  /** El preset de cada job pedido desde acá (el engine no lo devuelve). */
  presets: Record<string, ExportPreset>;

  submitExport(assets: [string, ...string[]], preset?: ExportPreset, outDir?: string): Promise<JobInfo>;
  /** Pide cancelar; `false` si el pedido falló (ya avisó y se puede reintentar). */
  cancel(id: string): Promise<boolean>;
  /** Saca de la cola un job terminado (uno que sigue corriendo no se quita). */
  dismiss(id: string): void;
  /** Abre la carpeta donde exportó el job; si no se puede, avisa. */
  openFolder(id: string): Promise<void>;
  onEvent(method: JobEvent, params: JobInfo): void;
  /** El motor se reinició o se cayó: lo que esperaba o corría no va a terminar. */
  onEngineLost(reason: string): void;
}

const RANK: Record<JobInfo["status"], number> = { queued: 0, running: 1, done: 2, failed: 2, cancelled: 2 };

export function isFinished(job: JobInfo): boolean {
  return RANK[job.status] === 2;
}

/** Si `next` es un estado más nuevo que `prev` (nunca se vuelve atrás). */
function isNewer(prev: JobInfo | undefined, next: JobInfo): boolean {
  if (!prev) return true;
  if (isFinished(prev)) return false;
  const a = RANK[prev.status];
  const b = RANK[next.status];
  if (b !== a) return b > a;
  return next.fraction >= prev.fraction && next.done >= prev.done;
}

/** Las fotos que se pueden exportar (las que no se encuentran se saltean) y cuántas faltan. */
export function exportable(assets: AssetSummary[]): { ids: string[]; missing: number } {
  const ids = assets.filter((a) => !a.missing).map((a) => a.id);
  return { ids, missing: assets.length - ids.length };
}

/** El resumen del botón de la cola: "Exportando 2/8" o "Exportes terminados (3)". */
export function queueLabel(jobs: JobInfo[]): string {
  const pending = jobs.filter((j) => !isFinished(j));
  if (pending.length === 0) return `Exportes terminados (${jobs.length})`;
  const total = pending.reduce((n, j) => n + j.total, 0);
  const done = pending.reduce((n, j) => n + j.done, 0);
  return `Exportando ${Math.min(done + 1, total)}/${total}`;
}

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** Texto del engine (minúscula, sin punto) al final de una oración. */
function tail(text: string): string {
  const t = text.trim();
  return /[.!?]$/.test(t) ? t : `${t}.`;
}

function messageOf(err: unknown): string {
  return tail(err instanceof Error ? err.message : String(err));
}

function exported(job: JobInfo): string | null {
  const paths = job.results.flatMap((r) => (r.path ? [r.path] : []));
  if (paths.length === 0) return null;
  if (paths.length === 1) return `Exportada: ${fileName(paths[0])} (en ${job.out_dir})`;
  return `Exportadas ${paths.length} fotos (en ${job.out_dir})`;
}

/** El aviso de un job terminado. */
export function summary(job: JobInfo): { kind: "info" | "error"; text: string } {
  if (job.status === "failed") return { kind: "error", text: `No se pudo exportar: ${tail(job.error ?? "error desconocido")}` };
  const ok = exported(job);
  if (job.status === "cancelled") return { kind: "info", text: ok ? `Export cancelado. ${ok}` : "Export cancelado" };
  const failed = job.results.filter((r) => r.error);
  if (failed.length === 0) return { kind: "info", text: ok ?? "No había fotos para exportar" };
  const n = failed.length;
  const why = `${n} ${n === 1 ? "no se pudo exportar" : "no se pudieron exportar"}: ${tail(failed[0].error ?? "")}`;
  return { kind: "error", text: ok ? `${ok}. ${why}` : why };
}

export function createJobsStore(api: JobsApi): StoreApi<JobsState> {
  return createStore<JobsState>()((set, get) => {
    /** Los quitados de la cola: un aviso tardío no los vuelve a mostrar. */
    const dismissed = new Set<string>();

    /** Guarda `next` si es más nuevo; al pasar a terminado, avisa (una sola vez por job). */
    const merge = (next: JobInfo): JobInfo => {
      if (dismissed.has(next.id)) return next;
      const prev = get().jobs[next.id];
      if (!isNewer(prev, next)) return prev;
      set({ jobs: { ...get().jobs, [next.id]: next }, order: prev ? get().order : [next.id, ...get().order] });
      if (isFinished(next)) {
        const s = summary(next);
        api.notify(s.kind, s.text);
      }
      return next;
    };

    return {
      jobs: {},
      order: [],
      presets: {},

      async submitExport(assets, preset, outDir) {
        const params: JobExportParams = { assets, ...(preset && { preset }), ...(outDir && { out_dir: outDir }) };
        const queued = await api.call("job.export", params);
        set({ presets: { ...get().presets, [queued.id]: preset ?? "web" } }); // "web": el del engine
        return merge(queued);
      },

      async cancel(id) {
        try {
          merge(await api.call("job.cancel", { job: id }));
          return true;
        } catch (err) {
          api.notify("error", `No se pudo cancelar: ${messageOf(err)}`);
          return false;
        }
      },

      dismiss(id) {
        const job = get().jobs[id];
        if (!job || !isFinished(job)) return;
        dismissed.add(id);
        const { [id]: _job, ...jobs } = get().jobs;
        const { [id]: _preset, ...presets } = get().presets;
        set({ jobs, presets, order: get().order.filter((x) => x !== id) });
      },

      async openFolder(id) {
        const job = get().jobs[id];
        if (!job) return;
        try {
          await api.openFolder(job.out_dir);
        } catch (err) {
          api.notify("error", `No se pudo abrir la carpeta: ${messageOf(err)}`);
        }
      },

      onEvent(_method, params) {
        merge(params);
      },

      onEngineLost(reason) {
        const pending = Object.values(get().jobs).filter((j) => !isFinished(j));
        if (pending.length === 0) return;
        const jobs = { ...get().jobs };
        for (const j of pending) jobs[j.id] = { ...j, status: "failed", error: reason, current: null };
        set({ jobs });
        // Un solo aviso: varios toasts iguales no dicen nada más.
        const text =
          pending.length === 1
            ? `No se pudo exportar: ${tail(reason)}`
            : `No se pudieron terminar ${pending.length} exports: ${tail(reason)}`;
        api.notify("error", text);
      },
    };
  });
}
