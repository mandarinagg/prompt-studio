// "Pedido para N": se planifica un pedido una sola vez sobre una foto de referencia y se aplica
// a todas las seleccionadas como un lote. Reproduce ask/answer del editor (incluso ignorar la
// respuesta tardía de un pedido cancelado), pero sin previews: el plan se revisa como filas.
import { createStore, type StoreApi } from "zustand/vanilla";
import type { AssetSummary, EditPlan, call as engineCall } from "../engine/client";
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

export interface Clipboard {
  stack: EditPlan;
  /** De qué foto se copiaron los ajustes. */
  file: string;
}

export interface BatchState {
  /** Las fotos del lote, en el orden del proyecto. */
  targets: string[];
  /** La foto sobre la que se planifica. */
  reference: string | null;
  plan: PlanState | null;
  /** El último lote aplicado (para deshacerlo), null si no hay. */
  lastGroup: BatchGroup | null;
  /** Se está aplicando el lote: el diálogo no admite más cambios. */
  applying: boolean;
  /** Ajustes copiados de una foto (se pierden al cambiar de proyecto). */
  clipboard: Clipboard | null;

  /** `focused`: la foto con foco en la cuadrícula; si está entre las fotos del lote, es la referencia. */
  start(targets: string[], assets: AssetSummary[], focused?: string | null): void;
  ask(prompt: string): Promise<void>;
  /** Responde la pregunta del plan: se agrega al pedido y se vuelve a planificar. */
  answer(text: string): Promise<void>;
  toggleRow(index: number): void;
  editRow(index: number, value: number): void;
  /** Aplica las filas incluidas a todas las fotos; true si se aplicó. */
  apply(): Promise<boolean>;
  /** Cierra el pedido; si estaba pensando, la respuesta se ignora. */
  cancel(): void;
  /** Copia la pila guardada de la foto. */
  copy(asset: AssetSummary): Promise<void>;
  /** Copia una pila ya conocida (la guardada del editor, no la del arrastre). */
  copyStack(stack: EditPlan, file: string): void;
  /** Pega lo copiado en esas fotos como un lote; true si se pegó. */
  paste(targets: string[], geometry: boolean): Promise<boolean>;
  /** Deshace el último lote (solo las fotos que no cambiaron después). */
  undoLast(): Promise<void>;
  reset(): void;
}

/** La foto con foco si es del lote y no falta; si no, la primera de `targets` (orden del proyecto) que no falta. */
export function referenceOf(targets: string[], assets: AssetSummary[], focused?: string | null): string | null {
  const wanted = new Set(targets);
  if (focused != null && wanted.has(focused) && assets.some((a) => a.id === focused && !a.missing)) return focused;
  return assets.find((a) => wanted.has(a.id) && !a.missing)?.id ?? null;
}

const photos = (n: number) => (n === 1 ? "1 foto" : `${n} fotos`);

function tail(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

export function createBatchStore(api: BatchApi): StoreApi<BatchState> {
  return createStore<BatchState>()((set, get) => {
    // `gen` invalida respuestas de plan.create tras cancelar, empezar de nuevo o repreguntar.
    let gen = 0;
    let busy = false;

    return {
      targets: [],
      reference: null,
      plan: null,
      lastGroup: null,
      applying: false,
      clipboard: null,

      start(targets, assets, focused) {
        gen++;
        set({ targets, reference: referenceOf(targets, assets, focused), plan: null });
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
        if (!plan || !hasIncluded(plan) || targets.length === 0 || busy) return false;
        busy = true;
        set({ applying: true });
        const mine = gen;
        const label = `Pedido: ${plan.prompt}`.slice(0, 200);
        let r;
        try {
          r = await api.call("asset.apply_plan_many", {
            assets: targets as [string, ...string[]],
            plan: effectivePlan(plan),
            label,
          });
        } catch (err) {
          busy = false;
          set({ applying: false });
          api.notify("error", `No se pudo aplicar: ${tail(err)}`);
          return false;
        }
        // El motor ya guardó: un fallo de la interfaz de acá en adelante no es "no se pudo aplicar".
        // El plan se cierra antes de esperar al proyecto, y el bloqueo sigue hasta el final.
        if (mine === gen) {
          gen++;
          set({ plan: null });
        }
        try {
          const changed = r.states.filter((s) => s.changed);
          for (const s of changed) api.onStackChanged(s.asset);
          if (r.group_id) {
            set({ lastGroup: { id: r.group_id, label, count: changed.length } });
            api.notify("info", `Pedido aplicado a ${photos(targets.length)}`);
            await api.refreshProject().catch(() => {});
          } else {
            api.notify("info", "No hubo cambios en las fotos");
          }
        } finally {
          busy = false;
          set({ applying: false });
        }
        return true;
      },

      async copy(asset) {
        try {
          const s = await api.call("asset.state", { asset: asset.id });
          set({ clipboard: { stack: s.stack, file: asset.file } });
          api.notify("info", `Ajustes de ${asset.file} copiados`);
        } catch (err) {
          api.notify("error", `No se pudo copiar: ${tail(err)}`);
        }
      },

      copyStack(stack, file) {
        set({ clipboard: { stack, file } });
        api.notify("info", `Ajustes de ${file} copiados`);
      },

      async paste(targets, geometry) {
        const clipboard = get().clipboard;
        if (!clipboard || targets.length === 0 || busy) return false;
        busy = true;
        try {
          let r;
          try {
            r = await api.call("asset.paste", {
              assets: targets as [string, ...string[]],
              stack: clipboard.stack,
              geometry,
            });
          } catch (err) {
            api.notify("error", `No se pudo pegar: ${tail(err)}`);
            return false;
          }
          const changed = r.states.filter((s) => s.changed);
          for (const s of changed) api.onStackChanged(s.asset);
          if (r.group_id) {
            set({ lastGroup: { id: r.group_id, label: "Ajustes pegados", count: changed.length } });
            api.notify("info", `Ajustes pegados en ${photos(changed.length)}`);
            await api.refreshProject().catch(() => {});
          } else {
            api.notify("info", "No hubo cambios en las fotos");
          }
          return true;
        } finally {
          busy = false;
        }
      },

      async undoLast() {
        const group = get().lastGroup;
        if (!group || busy) return;
        busy = true;
        try {
          let r;
          try {
            r = await api.call("asset.undo_group", { group_id: group.id });
          } catch (err) {
            api.notify("error", `No se pudo deshacer: ${tail(err)}`);
            return;
          }
          set({ lastGroup: null });
          for (const id of r.undone) api.onStackChanged(id);
          const n = r.skipped.length;
          if (r.undone.length === 0) {
            api.notify(
              "info",
              n === 0
                ? "No hay nada para deshacer"
                : `No se deshizo «${group.label}»: ${n === 1 ? "1 cambió después" : `${n} cambiaron después`}`,
            );
          } else {
            const skipped = n === 0 ? "" : n === 1 ? ". 1 cambió después y quedó como estaba" : `. ${n} cambiaron después y quedaron como estaban`;
            api.notify("info", `Se deshizo «${group.label}» en ${photos(r.undone.length)}${skipped}`);
          }
          await api.refreshProject().catch(() => {});
        } finally {
          busy = false;
        }
      },

      cancel() {
        gen++;
        set({ plan: null });
      },

      reset() {
        gen++;
        set({ targets: [], reference: null, plan: null, lastGroup: null, clipboard: null });
      },
    };
  });
}
