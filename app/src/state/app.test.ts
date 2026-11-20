import { describe, expect, it } from "vitest";
import { EngineError, type Method, type Params, type ProjectInfo, type RecentProject } from "../engine/client";
import { createAppStore, type Api } from "./app";

type Handler = (params: any) => unknown;

function fakeApi(handlers: Partial<Record<Method, Handler>>) {
  const calls: { method: Method; params: unknown }[] = [];
  const api: Api = {
    call: (async (method: Method, params?: Params<Method>) => {
      calls.push({ method, params });
      const h = handlers[method];
      if (!h) throw new EngineError(`sin manejador para ${method}`, null);
      return h(params);
    }) as Api["call"],
    documentDir: async () => "C:\\Users\\u\\Documents",
  };
  return { api, calls };
}

const info = (over: Partial<ProjectInfo> = {}): ProjectInfo => ({
  path: "C:\\P\\Viaje.pstudio",
  name: "Viaje",
  cache_dir: "C:\\P\\Viaje.pstudio\\cache",
  assets: [],
  ...over,
});

const rec = (name: string, exists = true): RecentProject => ({
  path: `C:\\P\\${name}.pstudio`,
  name,
  opened_at: "2026-11-20T10:00:00+00:00",
  exists,
});

describe("store de la app", () => {
  it("boot carga recientes y la carpeta por defecto", async () => {
    const { api } = fakeApi({ "recent.list": () => ({ items: [rec("A")] }) });
    const store = createAppStore(api);
    await store.getState().boot();
    expect(store.getState().recents.map((r) => r.name)).toEqual(["A"]);
    expect(store.getState().defaultDir).toBe("C:\\Users\\u\\Documents");
  });

  it("abrir un proyecto lo deja abierto y refresca recientes", async () => {
    const { api } = fakeApi({
      "project.open": () => info(),
      "recent.list": () => ({ items: [rec("Viaje")] }),
    });
    const store = createAppStore(api);
    await store.getState().openProject("C:\\P\\Viaje.pstudio");
    expect(store.getState().project?.name).toBe("Viaje");
    expect(store.getState().recents[0].name).toBe("Viaje");
    expect(store.getState().busy).toBe(false);
  });

  it("si abrir falla, avisa con el mensaje del engine y no cambia de pantalla", async () => {
    const { api } = fakeApi({
      "project.open": () => {
        throw new EngineError("no existe el proyecto Viaje.pstudio", -32000);
      },
      "recent.list": () => ({ items: [rec("Viaje", false)] }),
    });
    const store = createAppStore(api);
    await store.getState().openProject("C:\\P\\Viaje.pstudio");
    const s = store.getState();
    expect(s.project).toBeNull();
    expect(s.toasts).toEqual([expect.objectContaining({ kind: "error", text: "No existe el proyecto Viaje.pstudio." })]);
    expect(s.recents[0].exists).toBe(false); // se refrescó: ahora se ve "no encontrado"
  });

  it("crear con fotos importa (con subcarpetas) y resume el resultado", async () => {
    const { api, calls } = fakeApi({
      "project.create": () => info(),
      "project.import": () => ({ added: [{}, {}], duplicates: 1, unsupported: ["x.txt"] }),
      "project.info": () => info({ assets: [{ id: "a", file: "a.jpg", edited: false, missing: false }] }),
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    store.getState().startNewProject({ photos: ["C:\\F\\a.jpg"], name: "Viaje" });
    expect(store.getState().draft).toEqual({ name: "Viaje", dir: "", photos: ["C:\\F\\a.jpg"], error: null });
    await store.getState().createProject({ dir: "C:\\P", name: "Viaje", photos: ["C:\\F\\a.jpg"] });
    expect(calls.map((c) => c.method)).toEqual(["project.create", "project.import", "project.info", "recent.list"]);
    expect(calls[1].params).toEqual({ paths: ["C:\\F\\a.jpg"], recursive: true });
    const s = store.getState();
    expect(s.draft).toBeNull();
    expect(s.project?.assets).toHaveLength(1);
    expect(s.toasts[0]).toMatchObject({
      kind: "info",
      text: "Se agregaron 2 fotos. 1 ya estaba en el proyecto. 1 archivo no es una foto compatible.",
    });
  });

  it("si crear falla, el error queda en el diálogo", async () => {
    const { api } = fakeApi({
      "project.create": () => {
        throw new EngineError("ya existe Viaje.pstudio", -32000);
      },
    });
    const store = createAppStore(api);
    store.getState().startNewProject({});
    await store.getState().createProject({ dir: "C:\\P", name: "Viaje", photos: [] });
    expect(store.getState().draft?.error).toBe("Ya existe Viaje.pstudio.");
    expect(store.getState().project).toBeNull();
    expect(store.getState().toasts).toEqual([]);
  });

  it("si la importación falla, el proyecto creado queda abierto y se avisa", async () => {
    const { api } = fakeApi({
      "project.create": () => info(),
      "project.import": () => {
        throw new EngineError("no se pudo leer a.jpg", -32000);
      },
      "project.info": () => info(),
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    await store.getState().createProject({ dir: "C:\\P", name: "Viaje", photos: ["C:\\F\\a.jpg"] });
    expect(store.getState().project?.name).toBe("Viaje");
    expect(store.getState().draft).toBeNull();
    expect(store.getState().toasts[0]).toMatchObject({ kind: "error", text: "No se pudo leer a.jpg." });
  });

  it("cerrar vuelve al inicio", async () => {
    const { api, calls } = fakeApi({
      "project.open": () => info(),
      "project.close": () => null,
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    await store.getState().openProject("C:\\P\\Viaje.pstudio");
    await store.getState().closeProject();
    expect(store.getState().project).toBeNull();
    expect(calls.some((c) => c.method === "project.close")).toBe(true);
  });

  it("al relanzarse el motor reabre el proyecto abierto", async () => {
    let opens = 0;
    const { api } = fakeApi({
      "project.open": () => (opens++, info()),
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    await store.getState().openProject("C:\\P\\Viaje.pstudio");
    await store.getState().onRestarted();
    expect(opens).toBe(2);
    expect(store.getState().engine).toBe("ready");
    expect(store.getState().toasts.at(-1)).toMatchObject({ kind: "info" });
  });

  it("si el motor se cae del todo queda el aviso", () => {
    const { api } = fakeApi({});
    const store = createAppStore(api);
    store.getState().onFailed("el motor se cerró varias veces seguidas: reiniciá la app");
    expect(store.getState().engine).toBe("failed");
    expect(store.getState().engineMessage).toBe("El motor se cerró varias veces seguidas: reiniciá la app.");
  });

  it("los avisos se descartan por id", () => {
    const { api } = fakeApi({});
    const store = createAppStore(api);
    store.getState().notify("info", "hola");
    const [t] = store.getState().toasts;
    store.getState().dismissToast(t.id);
    expect(store.getState().toasts).toEqual([]);
  });
  it("soltar fotos sobre el proyecto abierto las importa y actualiza la lista", async () => {
    const one = { id: "a", file: "a.jpg", edited: false, missing: false };
    const { api, calls } = fakeApi({
      "project.open": () => info(),
      "project.import": () => ({ added: [one], duplicates: 0, unsupported: [] }),
      "project.info": () => info({ assets: [one] }),
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    await store.getState().importPhotos(["C:\F\a.jpg"]); // sin proyecto: no hace nada
    expect(calls).toEqual([]);
    await store.getState().openProject("C:\P\Viaje.pstudio");
    await store.getState().importPhotos(["C:\F\a.jpg"]);
    expect(store.getState().project?.assets).toEqual([one]);
    expect(store.getState().toasts.at(-1)).toMatchObject({ kind: "info", text: "Se agregó 1 foto." });
  });
  it("si no se agregó nada nuevo, el aviso no dice \"0 fotos\"", async () => {
    const { api } = fakeApi({
      "project.open": () => info(),
      "project.import": () => ({ added: [], duplicates: 8, unsupported: [] }),
      "project.info": () => info(),
      "recent.list": () => ({ items: [] }),
    });
    const store = createAppStore(api);
    await store.getState().openProject("C:/P/Viaje.pstudio");
    await store.getState().importPhotos(["C:/F"]);
    expect(store.getState().toasts.at(-1)).toMatchObject({
      kind: "info",
      text: "No se agregó nada: las 8 fotos ya estaban en el proyecto.",
    });
  });
});
