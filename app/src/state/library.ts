// Biblioteca del proyecto (#61): la selección de fotos y sus miniaturas. Recibe la API por
// parámetro para probarlo sin Tauri.
//
// Miniaturas: `thumbnail.get` devuelve la ruta si ya existe o `null` si se está generando (llega
// después por `thumbnail.ready`). El aviso se toma solo como señal: se confirma con otro
// `thumbnail.get`, que devuelve la ruta de la pila actual o `null` si la del aviso era de una
// pila anterior. Así un aviso viejo nunca pinta una miniatura vieja.
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, call as engineCall, ThumbnailReady } from "../engine/client";

export interface LibraryApi {
  call: typeof engineCall;
  /** Bytes de una miniatura de cache/ como blob URL. */
  cacheImage(path: string): Promise<string>;
  revoke(url: string): void;
}

/** Cuántos `thumbnail.get` + lectura de bytes a la vez (esperar un aviso no cuenta). */
export const MAX_IN_FLIGHT = 6;

// ---------------------------------------------------------------------------- selección

export interface Selection {
  /** Las fotos seleccionadas (sin repetir). */
  selected: string[];
  /** Desde dónde se mide un Shift+clic. */
  anchor: string | null;
  /** La foto con el foco del teclado. */
  focus: string | null;
}

export interface Modifiers {
  ctrl: boolean;
  shift: boolean;
}

/** Clic (o Espacio/flechas) sobre `id`: solo esa, Ctrl suma/quita, Shift rango desde el ancla. */
export function select(sel: Selection, id: string, { ctrl, shift }: Modifiers, order: string[]): Selection {
  const from = sel.anchor === null ? -1 : order.indexOf(sel.anchor);
  const to = order.indexOf(id);
  if (shift && from >= 0 && to >= 0) {
    const range = order.slice(Math.min(from, to), Math.max(from, to) + 1);
    const selected = ctrl ? [...sel.selected, ...range.filter((x) => !sel.selected.includes(x))] : range;
    return { selected, anchor: sel.anchor, focus: id };
  }
  if (ctrl) {
    const selected = sel.selected.includes(id) ? sel.selected.filter((x) => x !== id) : [...sel.selected, id];
    return { selected, anchor: id, focus: id };
  }
  return { selected: [id], anchor: id, focus: id };
}

/** Ctrl+A: todas, en el orden de la biblioteca; el ancla y el foco quedan si siguen ahí. */
export function selectAll(order: string[], sel?: Selection): Selection {
  const keep = (x: string | null | undefined) => (x != null && order.includes(x) ? x : null);
  const anchor = keep(sel?.anchor) ?? order[0] ?? null;
  return { selected: [...order], anchor, focus: keep(sel?.focus) ?? anchor };
}

/** Esc: ninguna. El foco del teclado se conserva. */
export function clear(sel?: Selection): Selection {
  return { selected: [], anchor: null, focus: sel?.focus ?? null };
}

/** Saca de la selección los ids que ya no están en `ids` (devuelve la misma si no cambia). */
export function prune(sel: Selection, ids: string[]): Selection {
  const known = new Set(ids);
  const selected = sel.selected.filter((x) => known.has(x));
  const anchor = sel.anchor !== null && known.has(sel.anchor) ? sel.anchor : null;
  const focus = sel.focus !== null && known.has(sel.focus) ? sel.focus : null;
  if (selected.length === sel.selected.length && anchor === sel.anchor && focus === sel.focus) return sel;
  return { selected, anchor, focus };
}

/**
 * Flechas, Inicio y Fin en la cuadrícula: el índice al que va el foco. `columns` son las columnas
 * reales (medidas del DOM). ↓ desde una fila más corta abajo va a la última foto.
 */
export function moveFocusIndex(index: number, key: string, columns: number, count: number): number {
  if (count <= 0) return index;
  const cols = Math.max(1, Math.floor(columns) || 1);
  const last = count - 1;
  switch (key) {
    case "ArrowLeft":
      return Math.max(0, index - 1);
    case "ArrowRight":
      return Math.min(last, index + 1);
    case "ArrowUp":
      return index - cols >= 0 ? index - cols : index;
    case "ArrowDown":
      if (index + cols <= last) return index + cols;
      return Math.floor(index / cols) < Math.floor(last / cols) ? last : index;
    case "Home":
      return 0;
    case "End":
      return last;
    default:
      return index;
  }
}

// ---------------------------------------------------------------------------- store

export type ThumbStatus = "idle" | "loading" | "ready" | "error";

export interface Thumb {
  /** La versión pedida (cambia si la pila guardada pudo cambiar). */
  key: string;
  /** Blob URL de la última miniatura cargada; mientras se pide una versión nueva, la anterior. */
  url: string | null;
  status: ThumbStatus;
  error?: string;
}

export interface LibraryState extends Selection {
  /** Los ids de las fotos del proyecto, en el orden de la biblioteca. */
  order: string[];
  thumbs: Record<string, Thumb>;

  /** Las fotos del proyecto cambiaron (abrir, importar, volver del editor, Ubicar…). */
  sync(assets: AssetSummary[]): void;
  select(id: string, mods: Modifiers): void;
  selectAll(): void;
  clear(): void;
  /** Mueve el foco del teclado sin tocar la selección. */
  focusOn(id: string | null): void;

  /** Las fotos visibles (o cerca): pide las miniaturas que no tienen la versión actual. */
  want(ids: string[]): void;
  onThumbnailReady(ev: ThumbnailReady): void;
  /** La pila guardada de la foto cambió: si ya tenía miniatura, se vuelve a pedir. */
  invalidate(id: string): void;
  /**
   * Suelta todas las miniaturas (revoca sus blob URLs) y lo que estaba en vuelo. Al cerrar o
   * cambiar de proyecto también olvida las fotos y la selección; con `sameProject` (el motor se
   * reinició o se cayó con el mismo proyecto en pantalla) las conserva.
   */
  reset(opts?: { sameProject?: boolean }): void;
}

/** En qué anda el pedido de una foto (fuera del estado: no hace falta redibujar por esto). */
type Phase = "queued" | "running" | "waiting";

export function createLibraryStore(api: LibraryApi): StoreApi<LibraryState> {
  return createStore<LibraryState>()((set, get) => {
    let assets = new Map<string, AssetSummary>();
    /** Sube con `invalidate`: es parte de la clave de la miniatura. */
    const versions = new Map<string, number>();
    const phase = new Map<string, Phase>();
    /** Llegó un `thumbnail.ready` mientras corría su `thumbnail.get`. */
    const heard = new Set<string>();
    let queue: string[] = [];
    let active = 0;
    /** Sube con `reset`: lo que estaba en vuelo de antes se descarta al volver. */
    let generation = 0;

    const keyOf = (id: string): string => {
      const a = assets.get(id);
      return `${versions.get(id) ?? 0}:${a?.edited ? "e" : "o"}:${a?.missing ? "m" : "f"}`;
    };

    const patch = (id: string, thumb: Thumb | null) => {
      const thumbs = { ...get().thumbs };
      if (thumb) thumbs[id] = thumb;
      else delete thumbs[id];
      set({ thumbs });
    };

    const selection = (): Selection => {
      const { selected, anchor, focus } = get();
      return { selected, anchor, focus };
    };

    /** Pone el pedido de `id` primero en la fila (o lo marca para repetir si ya corre). */
    const enqueue = (id: string) => {
      const p = phase.get(id);
      if (p === "running") return; // al terminar ve que la clave cambió y lo vuelve a pedir
      queue = [id, ...queue.filter((x) => x !== id)];
      phase.set(id, "queued");
    };

    /** Marca la versión actual como pedida (conservando la imagen anterior) y la encola. */
    const request = (id: string) => {
      const prev = get().thumbs[id];
      patch(id, { key: keyOf(id), url: prev?.url ?? null, status: "loading" });
      enqueue(id);
    };

    const pump = () => {
      while (active < MAX_IN_FLIGHT && queue.length > 0) {
        const id = queue.shift()!;
        if (phase.get(id) !== "queued") continue;
        phase.set(id, "running");
        active++;
        void run(id, generation);
      }
    };

    const run = async (id: string, gen: number) => {
      const key = get().thumbs[id]?.key;
      heard.delete(id);
      let path: string | null = null;
      let url: string | null = null;
      let failed = false;
      try {
        path = (await api.call("thumbnail.get", { asset: id })).path;
        if (path !== null && gen === generation && get().thumbs[id]?.key === key) url = await api.cacheImage(path);
      } catch {
        // Transporte/RPC o lectura de la caché (motor caído o reiniciado): se reintenta en el
        // próximo `want`, no solo.
        failed = true;
      }
      if (gen !== generation) {
        if (url) api.revoke(url); // de un proyecto (o motor) anterior
        return;
      }
      active--;
      const current = get().thumbs[id];
      if (!current) {
        // La foto salió del proyecto mientras tanto.
        phase.delete(id);
        if (url) api.revoke(url);
      } else if (current.key !== key) {
        // La pila cambió mientras tanto: esta respuesta no sirve, se pide la versión nueva.
        if (url) api.revoke(url);
        phase.delete(id);
        enqueue(id);
      } else if (failed) {
        phase.delete(id);
        patch(id, { key: current.key, url: current.url, status: "idle" });
      } else if (url !== null) {
        phase.delete(id);
        if (current.url) api.revoke(current.url);
        patch(id, { key: current.key, url, status: "ready" });
      } else if (heard.has(id)) {
        // El aviso llegó antes que la respuesta: puede que ya esté lista, se vuelve a preguntar.
        phase.delete(id);
        enqueue(id);
      } else {
        phase.set(id, "waiting");
      }
      heard.delete(id);
      pump();
    };

    return {
      order: [],
      thumbs: {},
      selected: [],
      anchor: null,
      focus: null,

      sync(list) {
        const next = new Map(list.map((a) => [a.id, a]));
        const prev = assets;
        assets = next;
        const thumbs = get().thumbs;
        const dropped = Object.keys(thumbs).filter((id) => !next.has(id));
        if (dropped.length > 0) {
          const kept = { ...thumbs };
          for (const id of dropped) {
            const url = kept[id].url;
            if (url) api.revoke(url);
            delete kept[id];
            phase.delete(id);
            versions.delete(id);
          }
          queue = queue.filter((id) => next.has(id));
          set({ thumbs: kept });
        }
        const order = list.map((a) => a.id);
        set({ order, ...prune(selection(), order) });
        for (const a of list) {
          const old = prev.get(a.id);
          if (old && (old.edited !== a.edited || old.missing !== a.missing) && get().thumbs[a.id]) request(a.id);
        }
        pump();
      },

      select(id, mods) {
        set(select(selection(), id, mods, get().order));
      },

      selectAll() {
        set(selectAll(get().order, selection()));
      },

      clear() {
        set(clear(selection()));
      },

      focusOn(id) {
        set({ focus: id });
      },

      want(ids) {
        // Al revés: cada una se pone primero, así quedan en el orden en que se pidieron.
        for (const id of [...ids].reverse()) {
          if (!assets.has(id)) continue;
          const t = get().thumbs[id];
          if (t && t.key === keyOf(id) && t.status !== "idle") {
            // Ya pedida: si sigue en la fila (no en vuelo), pasa al frente.
            if (phase.get(id) === "queued") queue = [id, ...queue.filter((x) => x !== id)];
            continue;
          }
          request(id);
        }
        pump();
      },

      onThumbnailReady({ asset, path, error }) {
        const t = get().thumbs[asset];
        const p = phase.get(asset);
        if (!t || t.status !== "loading" || !p) return; // no se pidió, o es de otro proyecto
        if (p === "running") {
          heard.add(asset);
          return;
        }
        if (p !== "waiting") return; // ya está en la fila: la respuesta dirá
        if (error !== null) {
          phase.delete(asset);
          patch(asset, { key: t.key, url: t.url, status: "error", error });
        } else if (path === null) {
          // No quedó lista (raro): se vuelve a pedir la próxima vez que se vea.
          phase.delete(asset);
          patch(asset, { key: t.key, url: t.url, status: "idle" });
        } else {
          enqueue(asset);
          pump();
        }
      },

      invalidate(id) {
        versions.set(id, (versions.get(id) ?? 0) + 1);
        if (get().thumbs[id] && assets.has(id)) {
          request(id);
          pump();
        }
      },

      reset(opts) {
        for (const t of Object.values(get().thumbs)) if (t.url) api.revoke(t.url);
        generation++;
        active = 0;
        queue = [];
        phase.clear();
        heard.clear();
        if (opts?.sameProject) {
          set({ thumbs: {} });
          return;
        }
        versions.clear();
        assets = new Map();
        set({ order: [], thumbs: {}, ...clear() });
      },
    };
  });
}
