import { describe, expect, it } from "vitest";
import { EngineError, type JobInfo, type Method } from "../engine/client";
import { createJobsStore, exportable, queueLabel, type JobsApi } from "./jobs";

const OUT = "C:/fotos/Viaje.pstudio/../Exportadas";

const info = (over: Partial<JobInfo> = {}): JobInfo => ({
  id: "j1",
  kind: "export",
  status: "queued",
  total: 1,
  done: 0,
  current: null,
  fraction: 0,
  out_dir: OUT,
  results: [],
  error: null,
  ms: null,
  ...over,
});

const ok = (asset: string, file: string) => ({ asset, path: `${OUT}/${file}`, error: null });

function fakeApi(handlers: Partial<Record<Method, (params: any) => unknown>> = {}, openFolder?: (path: string) => Promise<void>) {
  const calls: { method: Method; params: any }[] = [];
  const opened: string[] = [];
  const notes: { kind: string; text: string }[] = [];
  const api: JobsApi = {
    call: (async (method: Method, params?: unknown) => {
      calls.push({ method, params });
      const h = handlers[method];
      if (!h) throw new EngineError(`sin manejador para ${method}`, null);
      return h(params);
    }) as JobsApi["call"],
    notify: (kind, text) => notes.push({ kind, text }),
    openFolder: async (path) => {
      opened.push(path);
      if (openFolder) await openFolder(path);
    },
  };
  return { api, calls, notes, opened };
}

describe("store de trabajos", () => {
  it("exportar encola el job", async () => {
    const f = fakeApi({ "job.export": () => info({ total: 2 }) });
    const store = createJobsStore(f.api);
    const job = await store.getState().submitExport(["a1", "a2"], "web");
    expect(f.calls).toEqual([{ method: "job.export", params: { assets: ["a1", "a2"], preset: "web" } }]);
    expect(job.status).toBe("queued");
    expect(store.getState().jobs.j1.status).toBe("queued");
    expect(store.getState().presets.j1).toBe("web");
  });

  it("el progreso avanza y nunca retrocede", () => {
    const store = createJobsStore(fakeApi().api);
    const s = store.getState();
    s.onEvent("job.progress", info({ status: "running", done: 1, total: 3, fraction: 0.5, current: "b.jpg" }));
    s.onEvent("job.progress", info({ status: "running", done: 0, total: 3, fraction: 0.2, current: "a.jpg" }));
    expect(store.getState().jobs.j1.fraction).toBe(0.5);
    expect(store.getState().jobs.j1.current).toBe("b.jpg");
    s.onEvent("job.progress", info({ status: "running", done: 1, total: 3, fraction: 0.6, current: "b.jpg" }));
    expect(store.getState().jobs.j1.fraction).toBe(0.6);
  });

  it("un progreso que llega después del final se ignora", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    const s = store.getState();
    s.onEvent("job.done", info({ status: "done", done: 1, fraction: 1, results: [ok("a1", "foto.jpg")] }));
    s.onEvent("job.progress", info({ status: "running", fraction: 0.9, current: "foto.jpg" }));
    s.onEvent("job.failed", info({ status: "failed", error: "otro" }));
    expect(store.getState().jobs.j1.status).toBe("done");
    expect(f.notes).toHaveLength(1);
  });

  it("si el final llega antes que la respuesta de job.export, la respuesta no lo pisa", async () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    (f.api as any).call = async () => {
      store.getState().onEvent("job.done", info({ status: "done", done: 1, fraction: 1, results: [ok("a1", "foto.jpg")] }));
      return info();
    };
    const job = await store.getState().submitExport(["a1"], "web");
    expect(job.status).toBe("done");
    expect(store.getState().jobs.j1.status).toBe("done");
    expect(f.notes).toEqual([{ kind: "info", text: `Exportada: foto.jpg (en ${OUT})` }]);
  });

  it("toast de varias fotos", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store.getState().onEvent(
      "job.done",
      info({ status: "done", total: 3, done: 3, fraction: 1, results: [ok("a", "a.jpg"), ok("b", "b.jpg"), ok("c", "c.jpg")] }),
    );
    expect(f.notes).toEqual([{ kind: "info", text: `Exportadas 3 fotos (en ${OUT})` }]);
  });

  it("toast con errores: cuántas no se pudieron y el primer error", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store.getState().onEvent(
      "job.done",
      info({
        status: "done",
        total: 4,
        done: 4,
        fraction: 1,
        results: [
          ok("a", "a.jpg"),
          ok("b", "b.jpg"),
          { asset: "c", path: null, error: "falta el archivo original" },
          { asset: "d", path: null, error: "otro error" },
        ],
      }),
    );
    expect(f.notes).toEqual([
      { kind: "error", text: `Exportadas 2 fotos (en ${OUT}). 2 no se pudieron exportar: falta el archivo original.` },
    ]);
  });

  it("toast cuando ninguna se pudo exportar", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store
      .getState()
      .onEvent("job.done", info({ status: "done", done: 1, fraction: 1, results: [{ asset: "a", path: null, error: "disco lleno" }] }));
    expect(f.notes).toEqual([{ kind: "error", text: "1 no se pudo exportar: disco lleno." }]);
  });

  it("toast de cancelado (y lo que alcanzó a exportarse)", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store.getState().onEvent("job.done", info({ id: "j1", status: "cancelled", total: 2, results: [] }));
    store.getState().onEvent(
      "job.done",
      info({
        id: "j2",
        status: "cancelled",
        total: 3,
        done: 1,
        results: [ok("a", "a.jpg"), { asset: "b", path: null, error: null }, { asset: "c", path: null, error: null }],
      }),
    );
    expect(f.notes).toEqual([
      { kind: "info", text: "Export cancelado" },
      { kind: "info", text: `Export cancelado. Exportada: a.jpg (en ${OUT})` },
    ]);
  });

  it("toast de job fallido", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store.getState().onEvent("job.failed", info({ status: "failed", error: "no se pudo crear la carpeta" }));
    expect(f.notes).toEqual([{ kind: "error", text: "No se pudo exportar: no se pudo crear la carpeta." }]);
  });

  it("cancelar llama a job.cancel y aplica la respuesta sin avisar dos veces", async () => {
    const f = fakeApi({
      "job.export": () => info(),
      "job.cancel": () => info({ status: "cancelled" }),
    });
    const store = createJobsStore(f.api);
    await store.getState().submitExport(["a1"], "original");
    expect(await store.getState().cancel("j1")).toBe(true);
    expect(f.calls[1]).toEqual({ method: "job.cancel", params: { job: "j1" } });
    expect(store.getState().jobs.j1.status).toBe("cancelled");
    store.getState().onEvent("job.done", info({ status: "cancelled" })); // el evento del engine
    expect(f.notes).toEqual([{ kind: "info", text: "Export cancelado" }]);
  });

  it("si job.cancel falla, avisa", async () => {
    const f = fakeApi({ "job.export": () => info() });
    const store = createJobsStore(f.api);
    await store.getState().submitExport(["a1"], "web");
    expect(await store.getState().cancel("j1")).toBe(false); // la cola vuelve a dejar intentarlo
    expect(f.notes).toEqual([{ kind: "error", text: "No se pudo cancelar: sin manejador para job.cancel." }]);
    expect(store.getState().jobs.j1.status).toBe("queued");
  });

  it("si el motor se reinicia, los jobs pendientes quedan fallidos y sus eventos viejos se ignoran", () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    const s = store.getState();
    s.onEvent("job.progress", info({ id: "j1", status: "running", fraction: 0.4 }));
    s.onEvent("job.progress", info({ id: "j2", status: "queued" }));
    s.onEvent("job.done", info({ id: "j3", status: "done", done: 1, fraction: 1, results: [ok("a", "a.jpg")] }));
    f.notes.length = 0;
    s.onEngineLost("el motor se reinició");
    const jobs = store.getState().jobs;
    expect(jobs.j1).toMatchObject({ status: "failed", error: "el motor se reinició" });
    expect(jobs.j2).toMatchObject({ status: "failed", error: "el motor se reinició" });
    expect(jobs.j3.status).toBe("done");
    expect(f.notes).toEqual([{ kind: "error", text: "No se pudieron terminar 2 exports: el motor se reinició." }]);
    s.onEvent("job.progress", info({ id: "j1", status: "running", fraction: 0.8 }));
    expect(store.getState().jobs.j1.status).toBe("failed");
  });
  it("order lists newest first and dismiss removes only finished jobs", async () => {
    let n = 0;
    const f = fakeApi({ "job.export": () => info({ id: `j${++n}` }) });
    const store = createJobsStore(f.api);
    await store.getState().submitExport(["a1"], "web");
    await store.getState().submitExport(["a2"], "original");
    store.getState().onEvent("job.progress", info({ id: "j3", status: "running" })); // visto primero por un evento
    expect(store.getState().order).toEqual(["j3", "j2", "j1"]);
    store.getState().onEvent("job.done", info({ id: "j1", status: "done", done: 1, fraction: 1, results: [ok("a1", "a.jpg")] }));
    store.getState().dismiss("j2"); // todavía en cola: no se quita
    store.getState().dismiss("j1");
    expect(store.getState().order).toEqual(["j3", "j2"]);
    expect(store.getState().jobs.j1).toBeUndefined();
    expect(store.getState().presets.j1).toBeUndefined();
    // Un aviso repetido de un job ya quitado no lo vuelve a mostrar ni a avisar.
    f.notes.length = 0;
    store.getState().onEvent("job.done", info({ id: "j1", status: "done", done: 1, fraction: 1 }));
    expect(store.getState().order).toEqual(["j3", "j2"]);
    expect(f.notes).toEqual([]);
  });

  it("submitExport passes out_dir when given", async () => {
    const f = fakeApi({ "job.export": () => info() });
    const store = createJobsStore(f.api);
    await store.getState().submitExport(["a1", "a2"], "catalog_square", "D:/Entregas");
    expect(f.calls).toEqual([
      { method: "job.export", params: { assets: ["a1", "a2"], preset: "catalog_square", out_dir: "D:/Entregas" } },
    ]);
  });

  it("exportable excludes missing and counts them", () => {
    const a = (id: string, missing = false) => ({ id, file: `${id}.jpg`, edited: false, missing });
    expect(exportable([a("a"), a("b", true), a("c"), a("d", true)])).toEqual({ ids: ["a", "c"], missing: 2 });
    expect(exportable([])).toEqual({ ids: [], missing: 0 });
  });

  it("openFolder opens the job folder", async () => {
    const f = fakeApi();
    const store = createJobsStore(f.api);
    store.getState().onEvent("job.done", info({ status: "done", done: 1, fraction: 1, results: [ok("a1", "a.jpg")] }));
    await store.getState().openFolder("j1");
    expect(f.opened).toEqual([OUT]);
  });

  it("openFolder failure notifies a readable error", async () => {
    const f = fakeApi({}, async () => {
      throw new EngineError("la carpeta ya no existe", null);
    });
    const store = createJobsStore(f.api);
    store.getState().onEvent("job.done", info({ status: "done", done: 1, fraction: 1, results: [ok("a1", "a.jpg")] }));
    f.notes.length = 0;
    await store.getState().openFolder("j1");
    expect(f.notes).toEqual([{ kind: "error", text: "No se pudo abrir la carpeta: la carpeta ya no existe." }]);
  });

  it("queueLabel: avance de lo que corre o cuántos terminaron", () => {
    const run = info({ id: "j1", status: "running", total: 8, done: 1 });
    const queued = info({ id: "j2", status: "queued", total: 2 });
    const fin = info({ id: "j3", status: "done", total: 1, done: 1 });
    expect(queueLabel([run, fin])).toBe("Exportando 2/8");
    expect(queueLabel([run, queued, fin])).toBe("Exportando 2/10");
    expect(queueLabel([info({ status: "running", total: 3, done: 3 })])).toBe("Exportando 3/3");
    expect(queueLabel([fin, { ...fin, id: "j4" }])).toBe("Exportes terminados (2)");
  });
});
