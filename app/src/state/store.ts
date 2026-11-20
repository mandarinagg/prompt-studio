// La instancia real del store, conectada al engine por Tauri.
import { documentDir } from "@tauri-apps/api/path";
import { useStore } from "zustand";
import { call } from "../engine/client";
import { createAppStore, type AppState } from "./app";

export const appStore = createAppStore({ call, documentDir });

export function useApp<T>(selector: (s: AppState) => T): T {
  return useStore(appStore, selector);
}
