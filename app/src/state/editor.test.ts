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
