// La instancia real del store, conectada al engine por Tauri.
import { invoke } from "@tauri-apps/api/core";
import { documentDir } from "@tauri-apps/api/path";
import { useStore } from "zustand";
import { cacheImage, call, EngineError } from "../engine/client";
import { createAppStore, type AppState } from "./app";
import { createBatchStore, type BatchState } from "./batch";
import { createEditorStore, type EditorState } from "./editor";
import { createJobsStore, type JobsState } from "./jobs";
import { createLibraryStore, type LibraryState } from "./library";

export const appStore = createAppStore({
  call,
  documentDir,
  engineFailure: () => invoke<string | null>("engine_failure"),
});

export function useApp<T>(selector: (s: AppState) => T): T {
  return useStore(appStore, selector);
}

export const editorStore = createEditorStore({
  call,
  cacheImage,
  revoke: (url) => URL.revokeObjectURL(url),
  notify: (kind, text) => appStore.getState().notify(kind, text),
  pixelRatio: () => window.devicePixelRatio || 1,
  // Declarado más abajo: se llama mucho después de crearse los dos stores.
  onStackChanged: (id) => libraryStore.getState().invalidate(id),
});

export function useEditor<T>(selector: (s: EditorState) => T): T {
  return useStore(editorStore, selector);
}

export const jobsStore = createJobsStore({
  call,
  notify: (kind, text) => appStore.getState().notify(kind, text),
  openFolder: async (path) => {
    try {
      await invoke("open_folder", { path });
    } catch (err) {
      // Rust rechaza con `{message, code}`: que el aviso diga el motivo, no "[object Object]".
      const e = err as { message?: string; code?: number | null };
      throw new EngineError(e.message ?? String(err), e.code ?? null);
    }
  },
});

export function useJobs<T>(selector: (s: JobsState) => T): T {
  return useStore(jobsStore, selector);
}

export const libraryStore = createLibraryStore({
  call,
  cacheImage,
  revoke: (url) => URL.revokeObjectURL(url),
});

export function useLibrary<T>(selector: (s: LibraryState) => T): T {
  return useStore(libraryStore, selector);
}

export const batchStore = createBatchStore({
  call,
  notify: (kind, text) => appStore.getState().notify(kind, text),
  onStackChanged: (id) => libraryStore.getState().invalidate(id),
  refreshProject: () => appStore.getState().refreshProject(),
});

export function useBatch<T>(selector: (s: BatchState) => T): T {
  return useStore(batchStore, selector);
}

// La biblioteca sigue las fotos del proyecto abierto. Al cerrar o cambiar de proyecto suelta la
// selección y las miniaturas (los avisos del proyecto anterior que lleguen después se ignoran).
appStore.subscribe((s, prev) => {
  if (s.project === prev.project) return;
  if (s.project?.path !== prev.project?.path) libraryStore.getState().reset();
  libraryStore.getState().sync(s.project?.assets ?? []);
});

// El pedido para varias fotos (y su último lote) es del proyecto abierto.
appStore.subscribe((s, prev) => {
  if (s.project?.path !== prev.project?.path) batchStore.getState().reset();
});

// Si se cierra o se cambia de proyecto (p. ej. soltando otro .pstudio), el editor se cierra.
appStore.subscribe((s, prev) => {
  if (s.project?.path !== prev.project?.path && editorStore.getState().asset) editorStore.getState().close();
});
