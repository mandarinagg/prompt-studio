// Estado del editor de una foto: la pila guardada, lo que se ve mientras se arrastra, las
// previews (después y antes) y el modo recorte. Recibe la API por parámetro para probarlo sin
// Tauri; las previews pasan por el bucle "gana el último" (preview.ts).
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, call as engineCall, EditPlan, Resize, StackState } from "../engine/client";
import { findOp, normalize, withoutCrop } from "../lib/stack";
import { clampEdit, effectivePlan, hasIncluded, rowAdjustment, rowsOf, visibleOps, type PlanState } from "./draft";
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
  /** El plan del último pedido, mientras se revisa (antes de Aplicar o Descartar). */
  plan: PlanState | null;
  /** Sugerencia de tamaño del último plan aplicado en esta foto (va al export, no a la pila). */
  exportHint: Resize | null;

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
  /** Pide un plan para el pedido y lo muestra como borrador, sin guardarlo. */
  ask(prompt: string): Promise<void>;
  /** Responde la pregunta del plan: se agrega al pedido y se vuelve a planificar. */
  answer(text: string): Promise<void>;
  toggleRow(index: number): void;
  /** Cambia el valor de una fila (unidades del slider); NaN vuelve al valor del plan. */
  editRow(index: number, value: number): void;
  /** Fusiona las filas incluidas en la pila (una entrada "Pedido: …"). */
  applyPlan(): Promise<void>;
  /** Vuelve a la pila sin el borrador; si estaba pensando, la respuesta se ignora. */
  discardPlan(): void;
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

    // Hasta saber la pila guardada no se pide nada: se vería la foto sin editar.
    // Con un plan abierto se ve el borrador (pila ⊕ plan), no la pila.
    const requestAfter = (longSide = side()) => {
      const { asset, stack, saved, plan } = get();
      const shown = plan?.draft ?? stack;
      if (asset && saved) loop.request({ kind: "after", asset: asset.id, stack: shownStack(shown), longSide });
    };

    // Pedidos y borrador, cada uno con "gana el último": `planGen` invalida respuestas de
    // plan.create (y borradores de un plan anterior); `draftGen`, borradores viejos del mismo
    // plan. Como mucho un plan.draft en vuelo y uno pendiente, como las previews.
    let planGen = 0;
    let draftGen = 0;
    let draftBusy = false;
    let draftQueued: { longSide?: number } | null = null;
    let applying = false;

    const dropPlan = () => {
      planGen++;
      draftGen++;
      draftQueued = null;
    };

    const setPlan = (patch: Partial<PlanState>) => {
      const plan = get().plan;
      if (plan) set({ plan: { ...plan, ...patch } });
    };

    const runDraft = async (longSide?: number) => {
      const { asset, plan, stack } = get();
      if (!asset || !plan || plan.status !== "ready") return;
      const gen = draftGen;
      const pgen = planGen;
      draftBusy = true;
      try {
        const r = await api.call("plan.draft", { asset: asset.id, plan: effectivePlan(plan), stack: normalize(stack) });
        if (gen === draftGen && pgen === planGen && get().asset?.id === asset.id) {
          setPlan({ draft: r.draft, exportHint: r.export_hint });
          requestAfter(longSide);
        }
      } catch (err) {
        if (gen === draftGen && pgen === planGen && get().asset?.id === asset.id) {
          // Un borrador viejo ya no coincide con las casillas: mejor ver la pila.
          setPlan({ draft: null });
          requestAfter(longSide);
          api.notify("error", `No se pudo mostrar el plan: ${tail(err)}`);
        }
      } finally {
        draftBusy = false;
        const queued = draftQueued;
        draftQueued = null;
        if (queued) void runDraft(queued.longSide);
      }
    };

    /** Vuelve a mostrar lo que corresponde: sin plan, la pila; con plan, pila ⊕ plan recalculado. */
    const refresh = (longSide?: number) => {
      const plan = get().plan;
      draftGen++;
      if (!plan || plan.status !== "ready") return requestAfter(longSide);
      if (!visibleOps(plan)) {
        // Nada visible (todo destildado, solo "no disponible" o solo resize): se ve la pila.
        draftQueued = null;
        if (plan.draft) setPlan({ draft: null });
        return requestAfter(longSide);
      }
      if (draftBusy) draftQueued = { longSide };
      else void runDraft(longSide);
    };

    const requestBefore = () => {
      const { asset, saved } = get();
      if (asset && saved) loop.request({ kind: "before", asset: asset.id, stack: { operations: [] }, longSide: side() });
    };

    // Si la pila nueva no tiene recorte (deshacer, restablecer), no queda un modo recorte invisible.
    const apply = (s: StackState) =>
      set({ saved: s, stack: s.stack, cropping: get().cropping && !!findOp(s.stack, "crop") });

    const load = async () => {
      const asset = get().asset;
      if (!asset) return;
      try {
        const s = await api.call("asset.state", { asset: asset.id });
        if (get().asset?.id !== asset.id) return;
        apply(s);
        refresh();
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
        if (s.changed) refresh();
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
      plan: null,
      exportHint: null,

      async open(asset) {
        loop.dispose();
        dropPlan();
        set({
          asset,
          saved: null,
          stack: {},
          after: null,
          before: null,
          cropping: false,
          zoom: "fit",
          error: null,
          plan: null,
          exportHint: null,
        });
        await load();
      },

      close() {
        loop.dispose();
        dropPlan();
        set({
          asset: null,
          saved: null,
          stack: {},
          after: null,
          before: null,
          cropping: false,
          error: null,
          plan: null,
          exportHint: null,
        });
      },

      async reload() {
        loop.reset();
        // El motor se reinició: el borrador puede no corresponder a la pila; se descarta.
        dropPlan();
        set({ plan: null });
        await load();
      },

      live(stack) {
        set({ stack });
        // Al 100% se arrastra a la resolución completa: con 1024 la foto se achicaría a la mitad.
        refresh(get().zoom === "actual" ? side() : DRAG_SIDE);
      },

      async commit(stack, label) {
        const asset = get().asset;
        if (!asset) return;
        set({ stack });
        try {
          const s = await api.call("asset.set_stack", { asset: asset.id, stack: normalize(stack), label });
          if (get().asset?.id !== asset.id) return;
          // Si mientras se guardaba ya se empezó a mover otro control, lo que se ve no se pisa.
          if (get().stack !== stack) {
            set({ saved: s });
            return;
          }
          apply(s);
        } catch (err) {
          const saved = get().saved;
          if (saved && get().stack === stack) set({ stack: saved.stack });
          api.notify("error", `No se pudo guardar el ajuste: ${tail(err)}`);
        }
        refresh();
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

      async ask(prompt) {
        const text = prompt.trim();
        const asset = get().asset;
        if (!text || !asset) return;
        const hadDraft = !!get().plan?.draft;
        dropPlan();
        const gen = planGen;
        const savedAt = get().saved;
        set({ plan: { prompt: text, status: "thinking", rows: [], draft: null } });
        if (hadDraft) requestAfter();
        try {
          const r = await api.call("plan.create", { prompt: text, asset: asset.id });
          if (gen !== planGen || get().asset?.id !== asset.id) return;
          const plan: PlanState = {
            prompt: text,
            status: "ready",
            result: r,
            rows: rowsOf(r.plan),
            draft: null,
            exportHint: r.export_hint,
          };
          // El borrador de plan.create vale si la pila no cambió mientras se pensaba.
          const current = get().saved === savedAt && get().stack === savedAt?.stack;
          if (visibleOps(plan) && current) plan.draft = r.draft;
          set({ plan });
          if (plan.draft) requestAfter();
          else refresh();
        } catch (err) {
          if (gen !== planGen || get().asset?.id !== asset.id) return;
          set({ plan: { prompt: text, status: "error", rows: [], draft: null, error: `No se pudo planificar: ${tail(err)}` } });
        }
      },

      async answer(text) {
        const plan = get().plan;
        if (!plan || !text.trim()) return;
        await get().ask(`${plan.prompt} ${text.trim()}`);
      },

      toggleRow(index) {
        const plan = get().plan;
        if (!plan || plan.status !== "ready") return;
        setPlan({ rows: plan.rows.map((r) => (r.index === index ? { ...r, included: !r.included } : r)) });
        refresh();
      },

      editRow(index, value) {
        const plan = get().plan;
        const row = plan?.rows.find((r) => r.index === index);
        const a = row && rowAdjustment(row.op);
        if (!plan || plan.status !== "ready" || !row || !a) return;
        const edited = clampEdit(a, value);
        setPlan({ rows: plan.rows.map((r) => (r.index === index ? { ...r, edited } : r)) });
        refresh();
      },

      async applyPlan() {
        const { asset, plan } = get();
        if (!asset || !plan || !hasIncluded(plan) || applying) return;
        applying = true;
        const gen = planGen;
        try {
          const label = `Pedido: ${plan.prompt}`.slice(0, 200);
          const s = await api.call("asset.apply_plan", { asset: asset.id, plan: effectivePlan(plan), label });
          if (get().asset?.id !== asset.id) return;
          apply(s);
          if (s.export_hint) set({ exportHint: s.export_hint });
          // Si mientras se aplicaba llegó otro pedido, ese sigue abierto sobre la pila nueva.
          if (gen === planGen) {
            dropPlan();
            set({ plan: null });
          }
          refresh();
        } catch (err) {
          api.notify("error", `No se pudo aplicar el plan: ${tail(err)}`);
        } finally {
          applying = false;
        }
      },

      discardPlan() {
        const hadDraft = !!get().plan?.draft;
        dropPlan();
        set({ plan: null });
        if (hadDraft) requestAfter();
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
