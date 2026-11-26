// "Pedido para N": se planifica un pedido una sola vez sobre una foto de referencia y se aplica
// a todas las seleccionadas como un lote. Reproduce ask/answer del editor (incluso ignorar la
// respuesta tardía de un pedido cancelado), pero sin previews: el plan se revisa como filas.
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, call as engineCall } from "../engine/client";
import { editRowIn, effectivePlan, hasIncluded, rowsOf, toggleRowIn, type PlanState } from "./draft";

export interface BatchApi {
  call: typeof engineCall;
  notify(kind: "info" | "error", text: string): void;
  /** La pila de esa foto cambió: la biblioteca vuelve a pedir su miniatura. */
  onStackChanged(id: string): void;
  /** Vuelve a leer el proyecto (marca "editada" en las fotos). */
  refreshProject(): Promise<void>;
}

export interface BatchGroup {
  id: string;
  label: string;
  /** Cuántas fotos cambiaron de verdad. */
  count: number;
}

export interface BatchState {
  /** Las fotos del lote, en el orden del proyecto. */
  targets: string[];
  /** La foto sobre la que se planifica. */
  reference: string | null;
  plan: PlanState | null;
  /** El último lote aplicado (para deshacerlo), null si no hay. */
  lastGroup: BatchGroup | null;

  start(targets: string[], assets: AssetSummary[]): void;
  ask(prompt: string): Promise<void>;
  /** Responde la pregunta del plan: se agrega al pedido y se vuelve a planificar. */
  answer(text: string): Promise<void>;
  toggleRow(index: number): void;
  editRow(index: number, value: number): void;
  /** Aplica las filas incluidas a todas las fotos; true si se aplicó. */
  apply(): Promise<boolean>;
  /** Cierra el pedido; si estaba pensando, la respuesta se ignora. */
  cancel(): void;
  reset(): void;
}

/** La primera de `targets`, en el orden del proyecto, que no falta. */
export function referenceOf(targets: string[], assets: AssetSummary[]): string | null {
  const wanted = new Set(targets);
  return assets.find((a) => wanted.has(a.id) && !a.missing)?.id ?? null;
}

function tail(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

export function createBatchStore(api: BatchApi): StoreApi<BatchState> {
  return createStore<BatchState>()((set, get) => {
    // `gen` invalida respuestas de plan.create tras cancelar, empezar de nuevo o repreguntar.
    let gen = 0;
    let applying = false;

    return {
      targets: [],
      reference: null,
      plan: null,
      lastGroup: null,

      start(targets, assets) {
        gen++;
        set({ targets, reference: referenceOf(targets, assets), plan: null });
      },

      async ask(prompt) {
        const text = prompt.trim();
        const reference = get().reference;
        if (!text || !reference) return;
        const mine = ++gen;
        set({ plan: { prompt: text, status: "thinking", rows: [], draft: null } });
        try {
          const r = await api.call("plan.create", { prompt: text, asset: reference });
          if (mine !== gen) return;
          set({
            plan: { prompt: text, status: "ready", result: r, rows: rowsOf(r.plan), draft: null, exportHint: r.export_hint },
          });
        } catch (err) {
          if (mine !== gen) return;
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
        if (plan) set({ plan: toggleRowIn(plan, index) });
      },

      editRow(index, value) {
        const plan = get().plan;
        if (plan) set({ plan: editRowIn(plan, index, value) });
      },

      async apply() {
        const { plan, targets } = get();
        if (!plan || !hasIncluded(plan) || targets.length === 0 || applying) return false;
        applying = true;
        const mine = gen;
        try {
          const label = `Pedido: ${plan.prompt}`.slice(0, 200);
          const r = await api.call("asset.apply_plan_many", {
            assets: targets as [string, ...string[]],
            plan: effectivePlan(plan),
            label,
          });
          const changed = r.states.filter((s) => s.changed);
          for (const s of changed) api.onStackChanged(s.asset);
          if (r.group_id) {
            await api.refreshProject();
            set({ lastGroup: { id: r.group_id, label, count: changed.length } });
            api.notify("info", `Pedido aplicado a ${targets.length === 1 ? "1 foto" : `${targets.length} fotos`}`);
          } else {
            api.notify("info", "No hubo cambios en las fotos");
          }
          // Si mientras se aplicaba se canceló o se empezó otro, ese estado no se pisa.
          if (mine === gen) {
            gen++;
            set({ plan: null });
          }
          return true;
        } catch (err) {
          api.notify("error", `No se pudo aplicar: ${tail(err)}`);
          return false;
        } finally {
          applying = false;
        }
      },

      cancel() {
        gen++;
        set({ plan: null });
      },

      reset() {
        gen++;
        set({ targets: [], reference: null, plan: null, lastGroup: null });
      },
    };
  });
}
