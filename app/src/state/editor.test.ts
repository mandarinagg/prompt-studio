import { describe, expect, it } from "vitest";
import { EngineError, type EditPlan, type Method, type StackState } from "../engine/client";
import { createEditorStore, type EditorApi, refineSide } from "./editor";

type Handler = (params: any) => unknown;

const state = (stack: EditPlan = {}, over: Partial<StackState> = {}): StackState => ({
  asset: "a1",
  stack,
  cursor: 0,
  label: "Original",
  can_undo: false,
  can_redo: false,
  changed: false,
  export_hint: null,
  ...over,
});

function fakeApi(handlers: Partial<Record<Method, Handler>>) {
  const calls: { method: Method; params: any }[] = [];
  const notes: string[] = [];
  const revoked: string[] = [];
  let n = 0;
  const api: EditorApi = {
    call: (async (method: Method, params?: unknown) => {
      calls.push({ method, params });
      const h = handlers[method];
      if (!h) throw new EngineError(`sin manejador para ${method}`, null);
      return h(params);
    }) as EditorApi["call"],
    cacheImage: async (path) => `blob:${path}`,
    revoke: (url) => revoked.push(url),
    notify: (_kind, text) => notes.push(text),
    pixelRatio: () => 1,
  };
  const preview = () => ({ path: `p${++n}.jpg`, width: 1000, height: 600, proxy_ms: 0, render_ms: 1, encode_ms: 1 });
  return { api, calls, notes, revoked, preview };
}

const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => {
  for (let i = 0; i < 10; i++) await tick();
};
const asset = { id: "a1", file: "foto.jpg", edited: false, missing: false };

describe("store del editor", () => {
  it("abrir trae la pila y pide la foto editada y el original", async () => {
    const f = fakeApi({});
    const calls = f.calls;
    (f.api as any).call = (async (m: Method, p: any) => {
      calls.push({ method: m, params: p });
      if (m === "asset.state") return state({ operations: [{ op: "exposure", ev: 0.5 }] });
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    store.getState().setViewport(800, 500);
    await store.getState().open(asset);
    await settle();
    const s = store.getState();
    expect(s.stack.operations).toEqual([{ op: "exposure", ev: 0.5 }]);
    const renders = calls.filter((c) => c.method === "preview.render").map((c) => c.params);
    expect(renders[0]).toEqual({ asset: "a1", stack: { operations: [{ op: "exposure", ev: 0.5 }] }, long_side: 800 });
    expect(renders[1]).toEqual({ asset: "a1", stack: { operations: [] }, long_side: 800 });
    expect(s.after?.url).toBe("blob:p1.jpg");
    expect(s.before?.url).toBe("blob:p2.jpg");
  });

  it("mientras se arrastra la preview es de 1024; al soltar se guarda con etiqueta y se refina", async () => {
    const f = fakeApi({});
    let saved: any = null;
    (f.api as any).call = (async (m: Method, p: any) => {
      f.calls.push({ method: m, params: p });
      if (m === "asset.state") return state();
      if (m === "preview.render") return f.preview();
      if (m === "asset.set_stack") {
        saved = p;
        return state(p.stack, { cursor: 1, label: p.label, can_undo: true, changed: true });
      }
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    store.getState().setViewport(1600, 900);
    await store.getState().open(asset);
    await settle();
    f.calls.length = 0;

    const next = { operations: [{ op: "contrast" as const, amount: 20 }] };
    store.getState().live(next);
    await settle();
    expect(store.getState().stack).toEqual(next);
    expect(f.calls.filter((c) => c.method === "preview.render").map((c) => c.params.long_side)).toEqual([1024]);

    await store.getState().commit(next, "Contraste +20");
    await settle();
    expect(saved).toEqual({ asset: "a1", stack: next, label: "Contraste +20" });
    expect(store.getState().saved?.can_undo).toBe(true);
    expect(f.calls.filter((c) => c.method === "preview.render").map((c) => c.params.long_side)).toEqual([1024, 1600]);
  });

  it("si guardar falla, vuelve a la pila guardada y avisa", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method) => {
      if (m === "asset.state") return state();
      if (m === "preview.render") return f.preview();
      if (m === "asset.set_stack") throw new EngineError("no hay un proyecto abierto", -32001);
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    await store.getState().commit({ operations: [{ op: "vibrance", amount: 10 }] }, "Vibrancia +10");
    expect(store.getState().stack).toEqual({});
    expect(f.notes).toEqual(["No se pudo guardar el ajuste: no hay un proyecto abierto."]);
  });

  it("undo y redo aplican el estado que devuelve el engine", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method) => {
      if (m === "asset.state") return state({ operations: [{ op: "exposure", ev: 1 }] }, { cursor: 1, can_undo: true });
      if (m === "asset.undo") return state({}, { cursor: 0, can_redo: true, changed: true });
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    await store.getState().undo();
    expect(store.getState().stack).toEqual({});
    expect(store.getState().saved?.can_redo).toBe(true);
  });

  it("restablecer todo vuelve al original con una entrada de historial", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method) => {
      if (m === "asset.state") return state({ operations: [{ op: "exposure", ev: 1 }] }, { cursor: 1, can_undo: true });
      if (m === "asset.reset") return state({}, { cursor: 2, label: "Restablecer", can_undo: true, changed: true });
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    await store.getState().resetAll();
    expect(store.getState().stack).toEqual({});
    expect(store.getState().saved?.label).toBe("Restablecer");
  });

  it("al recortar se muestra la foto sin el recorte (el marco va encima)", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method, p: any) => {
      f.calls.push({ method: m, params: p });
      if (m === "asset.state") return state({ operations: [{ op: "crop", aspect_ratio: "1:1" }, { op: "exposure", ev: 1 }] });
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    await settle();
    f.calls.length = 0;
    store.getState().setCropping(true);
    await settle();
    expect(f.calls.find((c) => c.method === "preview.render")?.params.stack).toEqual({
      operations: [{ op: "exposure", ev: 1 }],
    });
  });

  it("cerrar libera las imágenes", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method) => {
      if (m === "asset.state") return state();
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    await settle();
    store.getState().close();
    expect(store.getState().asset).toBeNull();
    expect(f.revoked.sort()).toEqual(["blob:p1.jpg", "blob:p2.jpg"]);
  });

  it("resolución refinada: lado del visor por la densidad, entre 256 y 2048", () => {
    expect(refineSide(800, 500, 1)).toBe(800);
    expect(refineSide(800, 500, 1.5)).toBe(1200);
    expect(refineSide(1900, 1000, 2)).toBe(2048);
    expect(refineSide(0, 0, 1)).toBe(1024);
  });

  it("no pide la foto con una pila vacía antes de saber la pila guardada", async () => {
    const f = fakeApi({});
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    (f.api as any).call = (async (m: Method, p: any) => {
      f.calls.push({ method: m, params: p });
      if (m === "asset.state") {
        await gate;
        return state({ operations: [{ op: "exposure", ev: 1 }] });
      }
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    const opening = store.getState().open(asset);
    store.getState().setViewport(1600, 900); // el visor se monta y se mide antes de la respuesta
    await settle();
    expect(f.calls.filter((c) => c.method === "preview.render")).toEqual([]);
    release();
    await opening;
    await settle();
    expect(f.calls.find((c) => c.method === "preview.render")?.params.stack).toEqual({
      operations: [{ op: "exposure", ev: 1 }],
    });
  });

  it("si deshacer saca el recorte, se sale del modo recorte", async () => {
    const f = fakeApi({});
    (f.api as any).call = (async (m: Method) => {
      if (m === "asset.state") return state({ operations: [{ op: "crop", aspect_ratio: "1:1" }] }, { cursor: 1, can_undo: true });
      if (m === "asset.undo") return state({}, { changed: true, can_redo: true });
      if (m === "preview.render") return f.preview();
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    await store.getState().open(asset);
    store.getState().setCropping(true);
    await store.getState().undo();
    expect(store.getState().cropping).toBe(false);
  });

  it("un guardado que termina no pisa lo que se está arrastrando después", async () => {
    const f = fakeApi({});
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    (f.api as any).call = (async (m: Method, p: any) => {
      f.calls.push({ method: m, params: p });
      if (m === "asset.state") return state();
      if (m === "preview.render") return f.preview();
      if (m === "asset.set_stack") {
        await gate;
        return state(p.stack, { cursor: 1, can_undo: true, changed: true });
      }
      throw new Error(m);
    }) as EditorApi["call"];
    const store = createEditorStore(f.api);
    store.getState().setViewport(1600, 900);
    await store.getState().open(asset);
    await settle();
    const a = { operations: [{ op: "contrast" as const, amount: 20 }] };
    const b = { operations: [{ op: "contrast" as const, amount: 20 }, { op: "vibrance" as const, amount: 30 }] };
    const saving = store.getState().commit(a, "Contraste +20");
    store.getState().live(b);
    release();
    await saving;
    await settle();
    expect(store.getState().stack).toEqual(b);
    expect(store.getState().saved?.can_undo).toBe(true);
    const last = f.calls.filter((c) => c.method === "preview.render").at(-1)!;
    expect(last.params.stack).toEqual(b);
  });
});

// ------------------------------------------------------------------------------ pedido y plan
// Un engine falso con lo justo: una pila guardada y una fusión que suma exposición.
function planEngine(opts: { plan?: EditPlan; gate?: Promise<void> } = {}) {
  const f = fakeApi({});
  let saved: EditPlan = { operations: [{ op: "exposure", ev: 0.3 }] };
  const merge = (stack: EditPlan, plan: EditPlan): EditPlan => {
    const ev = (stack.operations ?? []).find((o) => o.op === "exposure") as any;
    const add = (plan.operations ?? []).find((o) => o.op === "exposure") as any;
    const rest = (plan.operations ?? []).filter((o) => o.op !== "exposure" && o.op !== "resize");
    const total = Math.round(((ev?.ev ?? 0) + (add?.ev ?? 0)) * 100) / 100;
    return { operations: [...(total ? [{ op: "exposure" as const, ev: total }] : []), ...rest] };
  };
  const plan: EditPlan = opts.plan ?? {
    source_prompt: "más luz",
    operations: [
      { op: "exposure", ev: 0.4 },
      { op: "vibrance", amount: 20 },
    ],
  };
  (f.api as any).call = (async (m: Method, p: any) => {
    f.calls.push({ method: m, params: p });
    if (m === "asset.state") return state(saved);
    if (m === "preview.render") return f.preview();
    if (m === "plan.create") {
      if (opts.gate) await opts.gate;
      const draft = merge(saved, plan);
      return { plan: { ...plan, source_prompt: p.prompt }, provider: "rules", ms: 1, warnings: [], errors: [], draft, export_hint: null };
    }
    if (m === "plan.draft") return { draft: merge(p.stack ?? saved, p.plan), export_hint: null };
    if (m === "asset.apply_plan") {
      saved = merge(saved, p.plan);
      return state(saved, { cursor: 1, label: p.label, can_undo: true, changed: true });
    }
    if (m === "asset.undo") {
      saved = {};
      return state(saved, { changed: true, can_redo: true });
    }
    throw new Error(m);
  }) as EditorApi["call"];
  return f;
}

async function openWith(e: ReturnType<typeof planEngine>) {
  const store = createEditorStore(e.api);
  store.getState().setViewport(800, 500);
  await store.getState().open(asset);
  await settle();
  e.calls.length = 0;
  return store;
}

/** Las previews "después" pedidas (las "antes" van con la pila vacía). */
const afterRenders = (e: ReturnType<typeof planEngine>) =>
  e.calls.filter((c) => c.method === "preview.render" && (c.params.stack.operations ?? []).length > 0).map((c) => c.params.stack);

describe("pedido y borrador del plan", () => {
  it("pedir muestra el borrador (pila ⊕ plan) sin guardarlo", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    const s = store.getState();
    expect(s.plan?.status).toBe("ready");
    expect(s.plan?.rows.map((r) => r.op.op)).toEqual(["exposure", "vibrance"]);
    expect(s.plan?.draft?.operations).toEqual([
      { op: "exposure", ev: 0.7 },
      { op: "vibrance", amount: 20 },
    ]);
    expect(afterRenders(e).at(-1)).toEqual(s.plan?.draft);
    expect(e.calls.some((c) => c.method === "asset.apply_plan" || c.method === "asset.set_stack")).toBe(false);
    expect(s.stack).toEqual({ operations: [{ op: "exposure", ev: 0.3 }] });
  });

  it("pedido vacío no hace nada", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("   ");
    expect(store.getState().plan).toBeNull();
    expect(e.calls).toEqual([]);
  });

  it("descartar mientras piensa: la respuesta se ignora", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const e = planEngine({ gate });
    const store = await openWith(e);
    const first = store.getState().ask("más luz");
    expect(store.getState().plan?.status).toBe("thinking");
    store.getState().discardPlan();
    release();
    await first;
    await settle();
    expect(store.getState().plan).toBeNull();
    for (const s of afterRenders(e)) expect(s).toEqual({ operations: [{ op: "exposure", ev: 0.3 }] });
  });

  it("el último pedido gana aunque el anterior responda después", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const e = planEngine({ gate });
    const store = await openWith(e);
    const a = store.getState().ask("más luz");
    const b = store.getState().ask("colores vivos");
    release();
    await Promise.all([a, b]);
    await settle();
    expect(store.getState().plan?.prompt).toBe("colores vivos");
    expect(store.getState().plan?.result?.plan?.source_prompt).toBe("colores vivos");
  });

  it("destildar o editar una fila recalcula el borrador con plan.draft", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    e.calls.length = 0;
    store.getState().toggleRow(1);
    await settle();
    const draftCall = e.calls.find((c) => c.method === "plan.draft")!;
    expect(draftCall.params.plan.operations).toEqual([{ op: "exposure", ev: 0.4 }]);
    expect(store.getState().plan?.draft?.operations).toEqual([{ op: "exposure", ev: 0.7 }]);
    store.getState().editRow(0, 9); // fuera de rango: se recorta a +5
    await settle();
    expect(store.getState().plan?.rows[0].edited).toBe(5);
    expect(store.getState().plan?.draft?.operations).toEqual([{ op: "exposure", ev: 5.3 }]);
    store.getState().editRow(0, Number.NaN); // vacío: vuelve al valor del plan
    await settle();
    expect(store.getState().plan?.rows[0].edited).toBeUndefined();
    expect(afterRenders(e).at(-1)).toEqual({ operations: [{ op: "exposure", ev: 0.7 }] });
  });

  it("sin filas incluidas no hay borrador: se ve la pila y Aplicar no hace nada", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    store.getState().toggleRow(0);
    store.getState().toggleRow(1);
    await settle();
    expect(store.getState().plan?.draft).toBeNull();
    expect(afterRenders(e).at(-1)).toEqual({ operations: [{ op: "exposure", ev: 0.3 }] });
    await store.getState().applyPlan();
    expect(e.calls.some((c) => c.method === "asset.apply_plan")).toBe(false);
  });

  it("un plan solo con 'no disponible' no deja borrador", async () => {
    const e = planEngine({ plan: { operations: [], unsupported: [{ request: "quitar el fondo", reason: "todavía no" }] } });
    const store = await openWith(e);
    await store.getState().ask("quitar el fondo");
    await settle();
    expect(store.getState().plan?.status).toBe("ready");
    expect(store.getState().plan?.draft).toBeNull();
    for (const s of afterRenders(e)) expect(s).toEqual({ operations: [{ op: "exposure", ev: 0.3 }] });
  });

  it("aplicar fusiona con etiqueta 'Pedido: …' y deja de mostrar el borrador", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    store.getState().toggleRow(1);
    await settle();
    const applying = store.getState().applyPlan();
    void store.getState().applyPlan(); // doble clic: una sola aplicación
    await applying;
    await settle();
    const applies = e.calls.filter((c) => c.method === "asset.apply_plan");
    expect(applies).toHaveLength(1);
    expect(applies[0].params).toEqual({
      asset: "a1",
      plan: { source_prompt: "más luz", operations: [{ op: "exposure", ev: 0.4 }] },
      label: "Pedido: más luz",
    });
    const s = store.getState();
    expect(s.plan).toBeNull();
    expect(s.stack).toEqual({ operations: [{ op: "exposure", ev: 0.7 }] });
    expect(s.saved?.label).toBe("Pedido: más luz");
    expect(afterRenders(e).at(-1)).toEqual(s.stack);
  });

  it("aplicar un plan con resize guarda la sugerencia de export", async () => {
    const e = planEngine({ plan: { operations: [{ op: "resize", width: 800 }] } });
    const call = e.api.call;
    (e.api as any).call = (async (m: Method, p: any) => {
      const r: any = await (call as any)(m, p);
      return m === "asset.apply_plan" ? { ...r, changed: false, export_hint: { op: "resize", width: 800, fit: "contain" } } : r;
    }) as EditorApi["call"];
    const store = await openWith(e);
    await store.getState().ask("para web");
    await settle();
    await store.getState().applyPlan();
    expect(store.getState().exportHint).toEqual({ op: "resize", width: 800, fit: "contain" });
    await store.getState().open({ ...asset, id: "a2" });
    expect(store.getState().exportHint).toBeNull();
  });

  it("responder a la pregunta vuelve a planificar con el pedido completo", async () => {
    const e = planEngine({ plan: { operations: [], clarification: "¿En toda la foto o solo en las sombras?" } });
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    await store.getState().answer("en las sombras");
    expect(e.calls.filter((c) => c.method === "plan.create").at(-1)?.params.prompt).toBe("más luz en las sombras");
  });

  it("deshacer con un plan abierto recalcula el borrador sobre la pila nueva", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    await store.getState().undo();
    await settle();
    expect(store.getState().plan?.draft?.operations).toEqual([
      { op: "exposure", ev: 0.4 },
      { op: "vibrance", amount: 20 },
    ]);
    expect(afterRenders(e).at(-1)).toEqual(store.getState().plan?.draft);
  });

  it("deshacer mientras piensa: el borrador se recalcula sobre la pila nueva", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const e = planEngine({ gate });
    const store = await openWith(e);
    const asking = store.getState().ask("más luz");
    await store.getState().undo();
    release();
    await asking;
    await settle();
    expect(store.getState().plan?.draft?.operations).toEqual([
      { op: "exposure", ev: 0.4 },
      { op: "vibrance", amount: 20 },
    ]);
  });

  it("mover un slider con un plan abierto muestra pila arrastrada ⊕ plan", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    e.calls.length = 0;
    store.getState().live({ operations: [{ op: "exposure", ev: 1 }] });
    await settle();
    expect(e.calls.find((c) => c.method === "plan.draft")?.params.stack).toEqual({ operations: [{ op: "exposure", ev: 1 }] });
    const last = e.calls.filter((c) => c.method === "preview.render").at(-1)!;
    expect(last.params).toMatchObject({
      long_side: 1024,
      stack: { operations: [{ op: "exposure", ev: 1.4 }, { op: "vibrance", amount: 20 }] },
    });
  });

  it("muchos cambios seguidos: como mucho un plan.draft en vuelo y gana el último", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    e.calls.length = 0;
    for (let i = 1; i <= 5; i++) store.getState().live({ operations: [{ op: "exposure", ev: i }] });
    await settle();
    const drafts = e.calls.filter((c) => c.method === "plan.draft").map((c) => c.params.stack.operations[0].ev);
    expect(drafts).toEqual([1, 5]);
    expect(store.getState().plan?.draft?.operations?.[0]).toEqual({ op: "exposure", ev: 5.4 });
  });

  it("cambiar de foto o cerrar descarta el plan", async () => {
    const e = planEngine();
    const store = await openWith(e);
    await store.getState().ask("más luz");
    await settle();
    await store.getState().open({ ...asset, id: "a2", file: "otra.jpg" });
    expect(store.getState().plan).toBeNull();
    await store.getState().ask("más luz");
    await settle();
    store.getState().close();
    expect(store.getState().plan).toBeNull();
  });

  it("si plan.create falla, queda el error y la foto sin borrador", async () => {
    const e = planEngine();
    const call = e.api.call;
    (e.api as any).call = (async (m: Method, p: any) => {
      if (m === "plan.create") throw new EngineError("no se pudo analizar foto.jpg", -32000);
      return (call as any)(m, p);
    }) as EditorApi["call"];
    const store = await openWith(e);
    await store.getState().ask("más luz");
    expect(store.getState().plan).toMatchObject({ status: "error", error: "No se pudo planificar: no se pudo analizar foto.jpg." });
  });
});
