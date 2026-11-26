import { describe, expect, it } from "vitest";
import { EngineError, type AssetSummary, type EditPlan, type Method, type StackState } from "../engine/client";
import { createBatchStore, referenceOf, type BatchApi } from "./batch";

type Handler = (params: any) => unknown;

const asset = (id: string, missing = false): AssetSummary => ({ id, file: `${id}.jpg`, edited: false, missing });
const state = (id: string, changed: boolean): StackState => ({
  asset: id,
  stack: {},
  cursor: 1,
  label: "Pedido",
  can_undo: true,
  can_redo: false,
  changed,
  export_hint: null,
});

const PLAN: EditPlan = {
  source_prompt: "más luz",
  operations: [
    { op: "exposure", ev: 0.3 },
    { op: "vibrance", amount: 20 },
  ],
};
const created = (plan: EditPlan | null) => ({ plan, provider: "rules", ms: 1, warnings: [], errors: [], draft: null, export_hint: null });

function fake(handlers: Partial<Record<Method, Handler>>) {
  const calls: { method: Method; params: any }[] = [];
  const notes: [string, string][] = [];
  const changed: string[] = [];
  let refreshed = 0;
  const api: BatchApi = {
    call: (async (method: Method, params?: unknown) => {
      calls.push({ method, params });
      const h = handlers[method];
      if (!h) throw new EngineError(`sin manejador para ${method}`, null);
      return h(params);
    }) as BatchApi["call"],
    notify: (kind, text) => notes.push([kind, text]),
    onStackChanged: (id) => changed.push(id),
    refreshProject: async () => {
      refreshed++;
    },
  };
  return { api, calls, notes, changed, refreshed: () => refreshed };
}

const ASSETS = [asset("a1"), asset("a2"), asset("a3")];
const planHandlers = (): Partial<Record<Method, Handler>> => ({ "plan.create": () => created(PLAN) });
const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
};

describe("referenceOf", () => {
  it("referenceOf skips missing and follows project order", () => {
    const assets = [asset("a1", true), asset("a2"), asset("a3")];
    expect(referenceOf(["a3", "a2"], assets)).toBe("a2");
    expect(referenceOf(["a1"], assets)).toBeNull();
    expect(referenceOf([], assets)).toBeNull();
  });
});

describe("store del pedido para varias fotos", () => {
  it("start fija las fotos y la de referencia", () => {
    const f = fake({});
    const store = createBatchStore(f.api);
    store.getState().start(["a2", "a3"], ASSETS);
    expect(store.getState().targets).toEqual(["a2", "a3"]);
    expect(store.getState().reference).toBe("a2");
    expect(store.getState().plan).toBeNull();
  });

  it("ask plans once on the reference photo", async () => {
    const f = fake(planHandlers());
    const store = createBatchStore(f.api);
    store.getState().start(["a1", "a2", "a3"], ASSETS);
    await store.getState().ask("  más luz ");
    const creates = f.calls.filter((c) => c.method === "plan.create");
    expect(creates).toHaveLength(1);
    expect(creates[0].params).toEqual({ prompt: "más luz", asset: "a1" });
    expect(store.getState().plan?.status).toBe("ready");
    expect(store.getState().plan?.rows).toHaveLength(2);
  });

  it("apply sends included rows to all targets and records lastGroup", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: "g1", states: [state("a1", true), state("a2", false), state("a3", true)] }),
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1", "a2", "a3"], ASSETS);
    await store.getState().ask("más luz");
    store.getState().toggleRow(1);
    store.getState().editRow(0, 0.5);
    expect(await store.getState().apply()).toBe(true);
    const call = f.calls.find((c) => c.method === "asset.apply_plan_many")!;
    expect(call.params).toEqual({
      assets: ["a1", "a2", "a3"],
      plan: { source_prompt: "más luz", operations: [{ op: "exposure", ev: 0.5 }] },
      label: "Pedido: más luz",
    });
    expect(f.changed).toEqual(["a1", "a3"]);
    expect(f.refreshed()).toBe(1);
    expect(store.getState().lastGroup).toEqual({ id: "g1", label: "Pedido: más luz", count: 2 });
    expect(f.notes).toContainEqual(["info", "Pedido aplicado a 3 fotos"]);
    expect(store.getState().plan).toBeNull();
  });

  it("apply with null group_id leaves lastGroup untouched and says nothing changed", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: null, states: [state("a1", false), state("a2", false)] }),
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1", "a2"], ASSETS);
    await store.getState().ask("más luz");
    expect(await store.getState().apply()).toBe(true);
    expect(store.getState().lastGroup).toBeNull();
    expect(f.changed).toEqual([]);
    expect(f.notes).toContainEqual(["info", "No hubo cambios en las fotos"]);
  });

  it("apply failure keeps the plan open and notifies", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => {
        throw new EngineError("disco lleno", null);
      },
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1", "a2"], ASSETS);
    await store.getState().ask("más luz");
    expect(await store.getState().apply()).toBe(false);
    expect(store.getState().plan?.status).toBe("ready");
    expect(f.notes).toContainEqual(["error", "No se pudo aplicar: disco lleno."]);
  });

  it("apply with no included rows does nothing", async () => {
    const f = fake(planHandlers());
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("más luz");
    store.getState().toggleRow(0);
    store.getState().toggleRow(1);
    expect(await store.getState().apply()).toBe(false);
    expect(f.calls.some((c) => c.method === "asset.apply_plan_many")).toBe(false);
  });

  it("a late plan.create answer after cancel is ignored", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const f = fake({
      "plan.create": async () => {
        await gate;
        return created(PLAN);
      },
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    const pending = store.getState().ask("más luz");
    expect(store.getState().plan?.status).toBe("thinking");
    store.getState().cancel();
    expect(store.getState().plan).toBeNull();
    release();
    await pending;
    await settle();
    expect(store.getState().plan).toBeNull();
  });

  it("clarification shows the question; answer re-plans with the prompt extended", async () => {
    let n = 0;
    const f = fake({
      "plan.create": () => {
        n++;
        return n === 1
          ? created({ source_prompt: "recortala", operations: [], clarification: "¿A qué proporción?" })
          : created(PLAN);
      },
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("recortala");
    expect(store.getState().plan?.result?.plan?.clarification).toBe("¿A qué proporción?");
    await store.getState().answer("cuadrada");
    const creates = f.calls.filter((c) => c.method === "plan.create");
    expect(creates[1].params.prompt).toBe("recortala cuadrada");
    expect(store.getState().plan?.rows).toHaveLength(2);
  });

  it("a failed plan.create leaves an error plan", async () => {
    const f = fake({
      "plan.create": () => {
        throw new EngineError("sin motor", null);
      },
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("más luz");
    expect(store.getState().plan?.status).toBe("error");
    expect(store.getState().plan?.error).toBe("No se pudo planificar: sin motor.");
  });

  it("reset clears everything including lastGroup", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: "g1", states: [state("a1", true)] }),
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("más luz");
    await store.getState().apply();
    expect(store.getState().lastGroup).not.toBeNull();
    store.getState().reset();
    expect(store.getState().lastGroup).toBeNull();
    expect(store.getState().targets).toEqual([]);
  });
});
