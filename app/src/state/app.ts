// Estado de la app (zustand): motor, proyecto abierto, recientes, diálogo de nuevo proyecto y
// avisos. Recibe el cliente del engine por parámetro para poder probarlo sin Tauri.
import { createStore, type StoreApi } from "zustand/vanilla";
import type { call as engineCall, ProjectInfo, RecentProject } from "../engine/client";

export interface Api {
  call: typeof engineCall;
  /** Carpeta por defecto para proyectos nuevos (Documentos). */
  documentDir: () => Promise<string>;
  /** Si el motor ya se dio por caído antes de que la UI escuchara los eventos, el motivo. */
  engineFailure: () => Promise<string | null>;
}

export type EngineStatus = "ready" | "failed";

export interface Toast {
  id: number;
  kind: "info" | "error";
  text: string;
  /** Queda hasta que se cierra (los errores siempre quedan). */
  sticky: boolean;
}

export interface NewProjectDraft {
  name: string;
  dir: string;
  photos: string[];
  error: string | null;
}

export interface CreateRequest {
  dir: string;
  name: string;
  photos: string[];
}

export interface AppState {
  engine: EngineStatus;
  engineMessage: string | null;
  project: ProjectInfo | null;
  recents: RecentProject[];
  defaultDir: string;
  busy: boolean;
  draft: NewProjectDraft | null;
  toasts: Toast[];

  boot(): Promise<void>;
  loadRecents(): Promise<void>;
  openProject(path: string): Promise<void>;
  startNewProject(init: { name?: string; photos?: string[] }): void;
  cancelNewProject(): void;
  createProject(req: CreateRequest): Promise<void>;
  importPhotos(paths: string[]): Promise<void>;
  closeProject(): Promise<void>;
  forgetRecent(path: string): Promise<void>;
  onRestarted(): Promise<void>;
  onFailed(message: string): void;
  notify(kind: Toast["kind"], text: string, sticky?: boolean): void;
  dismissToast(id: number): void;
}

/** Los mensajes del engine vienen en minúscula y sin punto: se muestran como oración. */
export function sentence(text: string): string {
  const t = text.trim();
  if (!t) return t;
  const s = t[0].toUpperCase() + t.slice(1);
  return /[.!?]$/.test(s) ? s : `${s}.`;
}

function messageOf(err: unknown): string {
  return sentence(err instanceof Error ? err.message : String(err));
}

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
}

function importSummary(added: number, duplicates: number, unsupported: number): string {
  if (added === 0) {
    const why = [
      duplicates > 0 && (duplicates === 1 ? "la foto ya estaba en el proyecto" : `las ${duplicates} fotos ya estaban en el proyecto`),
      unsupported > 0 &&
        (unsupported === 1 ? "1 archivo no es una foto compatible" : `${unsupported} archivos no son fotos compatibles`),
    ].filter(Boolean);
    return why.length ? `No se agregó nada: ${why.join("; ")}.` : "No se encontraron fotos para agregar.";
  }
  const parts = [
    added === 1 ? "Se agregó 1 foto." : `Se agregaron ${added} fotos.`,
    duplicates > 0 && `${plural(duplicates, "ya estaba", "ya estaban")} en el proyecto.`,
    unsupported > 0 &&
      `${plural(unsupported, "archivo no es una foto compatible", "archivos no son fotos compatibles")}.`,
  ];
  return parts.filter(Boolean).join(" ");
}

export function createAppStore(api: Api): StoreApi<AppState> {
  let nextToast = 1;

  return createStore<AppState>()((set, get) => ({
    engine: "ready",
    engineMessage: null,
    project: null,
    recents: [],
    defaultDir: "",
    busy: false,
    draft: null,
    toasts: [],

    async boot() {
      const failure = await api.engineFailure().catch(() => null);
      if (failure) get().onFailed(failure);
      const [dir] = await Promise.all([api.documentDir().catch(() => ""), get().loadRecents()]);
      set({ defaultDir: dir });
    },

    async loadRecents() {
      try {
        set({ recents: (await api.call("recent.list")).items });
      } catch {
        // Sin recientes no pasa nada: la pantalla de inicio sigue sirviendo.
      }
    },

    async openProject(path) {
      if (get().busy) return;
      set({ busy: true });
      try {
        set({ project: await api.call("project.open", { path }) });
      } catch (err) {
        get().notify("error", messageOf(err));
      } finally {
        set({ busy: false });
      }
      await get().loadRecents();
    },

    startNewProject({ name = "Nuevo proyecto", photos = [] }) {
      if (get().busy) return;
      const dir = get().defaultDir;
      set({ draft: { name, dir, photos, error: null } });
      if (!dir) {
        // Ctrl+N antes de que boot terminara: se completa la ubicación apenas se sabe.
        api.documentDir().then(
          (d) => {
            const draft = get().draft;
            if (draft && !draft.dir) set({ defaultDir: d, draft: { ...draft, dir: d } });
          },
          () => {},
        );
      }
    },

    cancelNewProject() {
      set({ draft: null });
    },

    async createProject({ dir, name, photos }) {
      set({ busy: true });
      try {
        try {
          set({ project: await api.call("project.create", { dir, name }) });
        } catch (err) {
          const draft = get().draft ?? { name, dir, photos, error: null };
          set({ draft: { ...draft, name, dir, error: messageOf(err) } });
          return;
        }
        set({ draft: null });
        await get().importPhotos(photos);
      } finally {
        set({ busy: false });
      }
      await get().loadRecents();
    },

    async importPhotos(paths) {
      const [first, ...rest] = paths;
      if (!first || !get().project) return;
      const owner = !get().busy; // dentro de createProject ya está ocupado
      if (owner) set({ busy: true });
      try {
        // Carpetas con subcarpetas incluidas: es lo que se espera al soltar una carpeta.
        const r = await api.call("project.import", { paths: [first, ...rest], recursive: true });
        get().notify("info", importSummary(r.added.length, r.duplicates, r.unsupported.length));
      } catch (err) {
        get().notify("error", messageOf(err));
      }
      try {
        set({ project: await api.call("project.info") });
      } catch {
        // Queda la lista anterior; la próxima acción la actualiza.
      } finally {
        if (owner) set({ busy: false });
      }
    },

    async closeProject() {
      try {
        await api.call("project.close");
      } catch {
        // Si el motor no responde, igual se vuelve al inicio: el proyecto ya está guardado.
      }
      set({ project: null });
      await get().loadRecents();
    },

    async forgetRecent(path) {
      try {
        set({ recents: (await api.call("recent.forget", { path })).items });
      } catch (err) {
        get().notify("error", messageOf(err));
      }
    },

    async onRestarted() {
      set({ engine: "ready", engineMessage: null });
      const project = get().project;
      if (!project) return;
      set({ busy: true });
      try {
        const reopened = await api.call("project.open", { path: project.path });
        if (get().project?.path !== project.path) {
          // Se cerró mientras se reabría: el engine no debe quedar con él abierto.
          await api.call("project.close").catch(() => null);
          return;
        }
        set({ project: reopened });
        get().notify("info", "El motor se reinició y tu proyecto se volvió a abrir. No se perdió nada.", true);
      } catch (err) {
        if (get().project?.path !== project.path) return;
        set({ project: null });
        get().notify("error", `El motor se reinició pero no se pudo reabrir el proyecto: ${messageOf(err)}`);
      } finally {
        set({ busy: false });
      }
    },

    onFailed(message) {
      set({ engine: "failed", engineMessage: sentence(message) });
    },

    notify(kind, text, sticky = kind === "error") {
      const id = nextToast++;
      set({ toasts: [...get().toasts, { id, kind, text, sticky }] });
    },

    dismissToast(id) {
      set({ toasts: get().toasts.filter((t) => t.id !== id) });
    },
  }));
}
