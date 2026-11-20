// La instancia real del store, conectada al engine por Tauri.
import { invoke } from "@tauri-apps/api/core";
import { documentDir } from "@tauri-apps/api/path";
import { useStore } from "zustand";
import { cacheImage, call } from "../engine/client";
import { createAppStore, type AppState } from "./app";
import { createEditorStore, type EditorState } from "./editor";

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
});

export function useEditor<T>(selector: (s: EditorState) => T): T {
  return useStore(editorStore, selector);
}

// Si se cierra o se cambia de proyecto (p. ej. soltando otro .pstudio), el editor se cierra.
appStore.subscribe((s, prev) => {
  if (s.project?.path !== prev.project?.path && editorStore.getState().asset) editorStore.getState().close();
});
