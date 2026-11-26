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

  it("reset clears everything including lastGroup and clipboard (project change)", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: "g1", states: [state("a1", true)] }),
      "asset.state": () => ({ ...state("a1", false), stack: PLAN }),
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("más luz");
    await store.getState().apply();
    await store.getState().copy(asset("a1"));
    expect(store.getState().lastGroup).not.toBeNull();
    expect(store.getState().clipboard).not.toBeNull();
    store.getState().reset();
    expect(store.getState().lastGroup).toBeNull();
    expect(store.getState().clipboard).toBeNull();
    expect(store.getState().targets).toEqual([]);
  });

  it("apply is flagged as applying while the engine works, and ui errors after commit are not reported as engine failures", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": async () => {
        await gate;
        return { group_id: "g1", states: [state("a1", true)] };
      },
    });
    f.api.refreshProject = async () => {
      throw new Error("ui");
    };
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    await store.getState().ask("más luz");
    const pending = store.getState().apply();
    expect(store.getState().applying).toBe(true);
    release();
    expect(await pending).toBe(true);
    expect(store.getState().applying).toBe(false);
    expect(store.getState().lastGroup?.id).toBe("g1");
    expect(f.notes.some(([k, t]) => k === "error" && t.startsWith("No se pudo aplicar"))).toBe(false);
  });
});

const STACK_A: EditPlan = { source_prompt: "x", operations: [{ op: "exposure", ev: 0.4 }] };

describe("copiar, pegar y deshacer el lote", () => {
  const pasteHandlers = (): Partial<Record<Method, Handler>> => ({
    "asset.state": () => ({ ...state("a1", false), stack: STACK_A }),
    "asset.paste": () => ({ group_id: "gp", states: [state("a2", true), state("a3", true)] }),
  });

  it("copy reads the saved stack via asset.state", async () => {
    const f = fake(pasteHandlers());
    const store = createBatchStore(f.api);
    await store.getState().copy(asset("a1"));
    expect(f.calls[0]).toEqual({ method: "asset.state", params: { asset: "a1" } });
    expect(store.getState().clipboard).toEqual({ stack: STACK_A, file: "a1.jpg" });
    expect(f.notes).toContainEqual(["info", "Ajustes de a1.jpg copiados"]);
  });

  it("copyStack stores the given stack", () => {
    const f = fake({});
    const store = createBatchStore(f.api);
    store.getState().copyStack(STACK_A, "x.jpg");
    expect(store.getState().clipboard).toEqual({ stack: STACK_A, file: "x.jpg" });
    expect(f.notes).toContainEqual(["info", "Ajustes de x.jpg copiados"]);
  });

  it("paste sends geometry flag and records lastGroup \"Ajustes pegados\"", async () => {
    const f = fake(pasteHandlers());
    const store = createBatchStore(f.api);
    store.getState().copyStack(STACK_A, "a1.jpg");
    expect(await store.getState().paste(["a2", "a3"], true)).toBe(true);
    const call = f.calls.find((c) => c.method === "asset.paste")!;
    expect(call.params).toEqual({ assets: ["a2", "a3"], stack: STACK_A, geometry: true });
    expect(f.changed).toEqual(["a2", "a3"]);
    expect(f.refreshed()).toBe(1);
    expect(store.getState().lastGroup).toEqual({ id: "gp", label: "Ajustes pegados", count: 2 });
    expect(f.notes).toContainEqual(["info", "Ajustes pegados en 2 fotos"]);
  });

  it("paste without clipboard does nothing", async () => {
    const f = fake(pasteHandlers());
    const store = createBatchStore(f.api);
    expect(await store.getState().paste(["a2"], false)).toBe(false);
    expect(f.calls).toEqual([]);
  });

  it("undoLast reports skipped", async () => {
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: "g1", states: [state("a1", true), state("a2", true), state("a3", true)] }),
      "asset.undo_group": () => ({ undone: ["a1", "a2"], skipped: ["a3"] }),
    });
    const store = createBatchStore(f.api);
    store.getState().start(["a1", "a2", "a3"], ASSETS);
    await store.getState().ask("más luz");
    await store.getState().apply();
    f.changed.length = 0;
    await store.getState().undoLast();
    expect(f.calls.find((c) => c.method === "asset.undo_group")!.params).toEqual({ group_id: "g1" });
    expect(f.changed).toEqual(["a1", "a2"]);
    expect(f.notes).toContainEqual(["info", "Se deshizo «Pedido: más luz» en 2 fotos. 1 cambió después y quedó como estaba"]);
    expect(store.getState().lastGroup).toBeNull();
  });

  it("undoLast uses singular and plural correctly", async () => {
    const f = fake({
      "asset.state": () => ({ ...state("a1", false), stack: STACK_A }),
      "asset.paste": () => ({ group_id: "gp", states: [state("a2", true)] }),
      "asset.undo_group": () => ({ undone: ["a2"], skipped: ["a3", "a4"] }),
    });
    const store = createBatchStore(f.api);
    store.getState().copyStack(STACK_A, "a1.jpg");
    await store.getState().paste(["a2"], false);
    expect(f.notes).toContainEqual(["info", "Ajustes pegados en 1 foto"]);
    await store.getState().undoLast();
    expect(f.notes).toContainEqual(["info", "Se deshizo «Ajustes pegados» en 1 foto. 2 cambiaron después y quedaron como estaban"]);
  });

  it("undoLast with no lastGroup makes no call", async () => {
    const f = fake({});
    const store = createBatchStore(f.api);
    await store.getState().undoLast();
    expect(f.calls).toEqual([]);
    expect(f.notes).toEqual([]);
  });

  it("undoLast with nothing undone reports why, without saying 0 fotos", async () => {
    const f = fake({
      "asset.state": () => ({ ...state("a1", false), stack: STACK_A }),
      "asset.paste": () => ({ group_id: "gp", states: [state("a2", true)] }),
      "asset.undo_group": () => ({ undone: [], skipped: ["a2", "a3"] }),
    });
    const store = createBatchStore(f.api);
    store.getState().copyStack(STACK_A, "a1.jpg");
    await store.getState().paste(["a2"], false);
    await store.getState().undoLast();
    expect(f.notes).toContainEqual(["info", "No se deshizo «Ajustes pegados»: 2 cambiaron después"]);
  });

  it("undoLast with nothing undone nor skipped says there is nothing to undo", async () => {
    const f = fake({
      "asset.state": () => ({ ...state("a1", false), stack: STACK_A }),
      "asset.paste": () => ({ group_id: "gp", states: [state("a2", true)] }),
      "asset.undo_group": () => ({ undone: [], skipped: [] }),
    });
    const store = createBatchStore(f.api);
    store.getState().copyStack(STACK_A, "a1.jpg");
    await store.getState().paste(["a2"], false);
    await store.getState().undoLast();
    expect(f.notes).toContainEqual(["info", "No hay nada para deshacer"]);
  });

  it("a second apply/paste/undo makes no engine call while refreshProject is pending", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const f = fake({
      ...planHandlers(),
      "asset.apply_plan_many": () => ({ group_id: "g1", states: [state("a1", true)] }),
      "asset.paste": () => ({ group_id: "gp", states: [state("a2", true)] }),
      "asset.undo_group": () => ({ undone: ["a1"], skipped: [] }),
    });
    f.api.refreshProject = () => gate;
    const store = createBatchStore(f.api);
    store.getState().start(["a1"], ASSETS);
    store.getState().copyStack(STACK_A, "a1.jpg");
    await store.getState().ask("más luz");
    const first = store.getState().apply();
    await settle();
    expect(store.getState().applying).toBe(true);
    expect(store.getState().plan).toBeNull();
    expect(await store.getState().apply()).toBe(false);
    expect(await store.getState().paste(["a2"], false)).toBe(false);
    await store.getState().undoLast();
    release();
    expect(await first).toBe(true);
    expect(store.getState().applying).toBe(false);
    expect(f.calls.filter((c) => c.method === "asset.apply_plan_many")).toHaveLength(1);
    expect(f.calls.some((c) => c.method === "asset.paste" || c.method === "asset.undo_group")).toBe(false);
  });
});
