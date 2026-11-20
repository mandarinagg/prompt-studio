// Estado del editor de una foto: la pila guardada, lo que se ve mientras se arrastra, las
// previews (después y antes) y el modo recorte. Recibe la API por parámetro para probarlo sin
// Tauri; las previews pasan por el bucle "gana el último" (preview.ts).
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, call as engineCall, EditPlan, StackState } from "../engine/client";
import { normalize, withoutCrop } from "../lib/stack";
import { createPreviewLoop, type PreviewJob, type PreviewResult } from "./preview";

export interface EditorApi {
  call: typeof engineCall;
  /** Bytes de una preview de cache/ como blob URL. */
  cacheImage(path: string): Promise<string>;
  revoke(url: string): void;
  notify(kind: "info" | "error", text: string): void;
  pixelRatio(): number;
}

/** Mientras se arrastra (diseño §8: ≈1024 px de lado largo en < 100 ms). */
export const DRAG_SIDE = 1024;
const MAX_SIDE = 2048;
const MIN_SIDE = 256;

/** Resolución al soltar: el lado largo del visor por la densidad de pantalla. */
export function refineSide(width: number, height: number, ratio: number): number {
  const side = Math.ceil(Math.max(width, height) * ratio);
  if (side <= 0) return DRAG_SIDE;
  return Math.min(MAX_SIDE, Math.max(MIN_SIDE, side));
}

export interface Shown {
  url: string;
  width: number;
  height: number;
  /** La pila con la que se dibujó (sin recorte mientras se encuadra). */
  stack: EditPlan;
}

export type Zoom = "fit" | "actual";

export interface EditorState {
  asset: AssetSummary | null;
  /** Lo que tiene guardado el engine (pila, cursor, si hay undo/redo). */
  saved: StackState | null;
  /** Lo que se ve: la pila guardada o la que se está arrastrando. */
  stack: EditPlan;
  after: Shown | null;
  before: Shown | null;
  cropping: boolean;
  zoom: Zoom;
  viewport: { width: number; height: number };
  /** Último tiempo de preview (ida y vuelta, ms) y su resolución; para medir en desarrollo. */
  stats: { ms: number; side: number } | null;
  error: string | null;

  open(asset: AssetSummary): Promise<void>;
  close(): void;
  /** Tras un reinicio del motor: vuelve a pedir la pila y las previews. */
  reload(): Promise<void>;
  /** Mientras se arrastra: muestra `stack` a resolución reducida, sin guardar. */
  live(stack: EditPlan): void;
  /** Al soltar: guarda `stack` como una entrada de historial. */
  commit(stack: EditPlan, label: string): Promise<void>;
  undo(): Promise<void>;
  redo(): Promise<void>;
  /** Vuelve al original (una entrada "Restablecer"; se puede deshacer). */
  resetAll(): Promise<void>;
  setCropping(on: boolean): void;
  setZoom(zoom: Zoom): void;
  setViewport(width: number, height: number): void;
}

const VERBS = { "asset.undo": "deshacer", "asset.redo": "rehacer", "asset.reset": "restablecer" } as const;

function tail(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

export function createEditorStore(api: EditorApi): StoreApi<EditorState> {
  return createStore<EditorState>()((set, get) => {
    const render = async (job: PreviewJob): Promise<PreviewResult> => {
      const t0 = performance.now();
      const r = await api.call("preview.render", { asset: job.asset, stack: job.stack, long_side: job.longSide });
      const url = await api.cacheImage(r.path);
      return { url, width: r.width, height: r.height, ms: performance.now() - t0 };
    };

    const loop = createPreviewLoop(render, {
      onResult(job, r) {
        const shown = { url: r.url, width: r.width, height: r.height, stack: job.stack };
        if (job.kind === "after") set({ after: shown, stats: { ms: Math.round(r.ms), side: job.longSide }, error: null });
        else set({ before: shown });
      },
      onError(job, err) {
        if (job.kind === "after") set({ error: `No se pudo mostrar la foto: ${tail(err)}` });
      },
      revoke: api.revoke,
    });

    const side = () => {
      const { zoom, viewport } = get();
      return zoom === "actual" ? MAX_SIDE : refineSide(viewport.width, viewport.height, api.pixelRatio());
    };

    const shownStack = (stack: EditPlan) => normalize(get().cropping ? withoutCrop(stack) : stack);

    const requestAfter = (longSide = side()) => {
      const { asset, stack } = get();
      if (asset) loop.request({ kind: "after", asset: asset.id, stack: shownStack(stack), longSide });
    };

    const requestBefore = () => {
      const { asset } = get();
      if (asset) loop.request({ kind: "before", asset: asset.id, stack: { operations: [] }, longSide: side() });
    };

    const apply = (s: StackState) => set({ saved: s, stack: s.stack });

    const load = async () => {
      const asset = get().asset;
      if (!asset) return;
      try {
        const s = await api.call("asset.state", { asset: asset.id });
        if (get().asset?.id !== asset.id) return;
        apply(s);
        requestAfter();
        requestBefore();
      } catch (err) {
        if (get().asset?.id === asset.id) set({ error: `No se pudo abrir la foto: ${tail(err)}` });
      }
    };

    const step = async (method: "asset.undo" | "asset.redo" | "asset.reset") => {
      const asset = get().asset;
      if (!asset) return;
      try {
        const s = await api.call(method, { asset: asset.id });
        if (get().asset?.id !== asset.id) return;
        apply(s);
        if (s.changed) requestAfter();
      } catch (err) {
        api.notify("error", `No se pudo ${VERBS[method]}: ${tail(err)}`);
      }
    };

    return {
      asset: null,
      saved: null,
      stack: {},
      after: null,
      before: null,
      cropping: false,
      zoom: "fit",
      viewport: { width: 0, height: 0 },
      stats: null,
      error: null,

      async open(asset) {
        loop.dispose();
        set({ asset, saved: null, stack: {}, after: null, before: null, cropping: false, zoom: "fit", error: null });
        await load();
      },

      close() {
        loop.dispose();
        set({ asset: null, saved: null, stack: {}, after: null, before: null, cropping: false, error: null });
      },

      async reload() {
        loop.reset();
        await load();
      },

      live(stack) {
        set({ stack });
        requestAfter(DRAG_SIDE);
      },

      async commit(stack, label) {
        const asset = get().asset;
        if (!asset) return;
        set({ stack });
        try {
          const s = await api.call("asset.set_stack", { asset: asset.id, stack: normalize(stack), label });
          if (get().asset?.id !== asset.id) return;
          apply(s);
        } catch (err) {
          const saved = get().saved;
          if (saved) set({ stack: saved.stack });
          api.notify("error", `No se pudo guardar el ajuste: ${tail(err)}`);
        }
        requestAfter();
      },

      undo: () => step("asset.undo"),
      redo: () => step("asset.redo"),
      resetAll: () => step("asset.reset"),

      setCropping(on) {
        if (on === get().cropping) return;
        set({ cropping: on });
        requestAfter();
      },

      setZoom(zoom) {
        if (zoom === get().zoom) return;
        set({ zoom });
        requestAfter();
        requestBefore();
      },

      setViewport(width, height) {
        const before = side();
        set({ viewport: { width, height } });
        // Solo se vuelve a pedir si la resolución cambia de verdad (más de un 15%).
        if (get().asset && Math.abs(side() - before) / before > 0.15) {
          requestAfter();
          requestBefore();
        }
      },
    };
  });
}
