// La instancia real del store, conectada al engine por Tauri.
import { invoke } from "@tauri-apps/api/core";
import { documentDir } from "@tauri-apps/api/path";
import { useStore } from "zustand";
import { call } from "../engine/client";
import { createAppStore, type AppState } from "./app";

export const appStore = createAppStore({
  call,
  documentDir,
  engineFailure: () => invoke<string | null>("engine_failure"),
});

export function useApp<T>(selector: (s: AppState) => T): T {
  return useStore(appStore, selector);
}
