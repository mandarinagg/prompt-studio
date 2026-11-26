import { describe, expect, it } from "vitest";
import { type AssetSummary, EngineError, type Method } from "../engine/client";
import {
  clear,
  createLibraryStore,
  type LibraryApi,
  idsToWant,
  MAX_IN_FLIGHT,
  moveFocusIndex,
  prune,
  select,
  selectAll,
} from "./library";

const ORDER = ["a", "b", "c", "d", "e"];
const none = { selected: [], anchor: null, focus: null };
const plain = { ctrl: false, shift: false };
const ctrl = { ctrl: true, shift: false };
const shift = { ctrl: false, shift: true };

describe("selección (funciones puras)", () => {
  it("un clic selecciona solo esa y la deja de ancla", () => {
    const s = select({ selected: ["a", "b"], anchor: "a", focus: "b" }, "c", plain, ORDER);
    expect(s).toEqual({ selected: ["c"], anchor: "c", focus: "c" });
  });

  it("Ctrl+clic suma y quita", () => {
    let s = select(none, "b", plain, ORDER);
    s = select(s, "d", ctrl, ORDER);
    expect(s.selected).toEqual(["b", "d"]);
    s = select(s, "b", ctrl, ORDER);
    expect(s).toEqual({ selected: ["d"], anchor: "b", focus: "b" });
  });

  it("Shift+clic selecciona el rango desde el ancla, en las dos direcciones", () => {
    let s = select(none, "b", plain, ORDER);
    s = select(s, "d", shift, ORDER);
    expect(s).toEqual({ selected: ["b", "c", "d"], anchor: "b", focus: "d" });
    s = select(s, "a", shift, ORDER);
    expect(s).toEqual({ selected: ["a", "b"], anchor: "b", focus: "a" });
  });

  it("Ctrl+Shift suma el rango a lo que había", () => {
    let s = select(none, "a", plain, ORDER);
    s = select(s, "d", ctrl, ORDER);
    s = select(s, "e", { ctrl: true, shift: true }, ORDER);
    expect(s.selected).toEqual(["a", "d", "e"]);
    expect(s.anchor).toBe("d");
  });

  it("Shift sin ancla (o con un ancla que ya no está) es un clic común", () => {
    expect(select(none, "c", shift, ORDER)).toEqual({ selected: ["c"], anchor: "c", focus: "c" });
    expect(select({ selected: ["z"], anchor: "z", focus: "z" }, "c", shift, ORDER).selected).toEqual(["c"]);
  });

  it("Ctrl+A selecciona todas en orden y Esc limpia sin perder el foco", () => {
    const s = selectAll(ORDER, { selected: ["c"], anchor: "c", focus: "c" });
    expect(s).toEqual({ selected: ORDER, anchor: "c", focus: "c" });
    expect(selectAll(ORDER)).toEqual({ selected: ORDER, anchor: "a", focus: "a" });
    expect(selectAll([])).toEqual(none);
    expect(clear(s)).toEqual({ selected: [], anchor: null, focus: "c" });
    expect(clear()).toEqual(none);
  });

  it("prune saca los ids que ya no existen (y no cambia nada si están todos)", () => {
    const s = { selected: ["a", "c", "e"], anchor: "c", focus: "e" };
    expect(prune(s, ["a", "b", "e"])).toEqual({ selected: ["a", "e"], anchor: null, focus: "e" });
    expect(prune(s, ORDER)).toBe(s);
  });
});

// ---------------------------------------------------------------------------- store

type Deferred<T> = { promise: Promise<T>; resolve(v: T): void; reject(e: unknown): void };
function deferred<T>(): Deferred<T> {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** Api falsa: `thumbnail.get` y `cacheImage` quedan pendientes hasta que el test los resuelve. */
function fakeApi() {
  const gets: { asset: string; d: Deferred<{ asset: string; path: string | null }> }[] = [];
  const loads: { path: string; d: Deferred<string> }[] = [];
  const revoked: string[] = [];
  const api: LibraryApi = {
    call: (async (method: Method, params?: any) => {
      if (method !== "thumbnail.get") throw new EngineError(`sin manejador para ${method}`, null);
      const d = deferred<{ asset: string; path: string | null }>();
      gets.push({ asset: params.asset, d });
      return d.promise;
    }) as LibraryApi["call"],
    cacheImage: (path) => {
      const d = deferred<string>();
      loads.push({ path, d });
      return d.promise;
    },
    revoke: (url) => revoked.push(url),
  };
  /** Responde el pedido pendiente de `asset` (el más viejo sin responder). */
  const answer = async (asset: string, path: string | null) => {
    const i = gets.findIndex((g) => g.asset === asset);
    if (i < 0) throw new Error(`no hay pedido para ${asset}`);
    const [g] = gets.splice(i, 1);
    g.d.resolve({ asset, path });
    await settle();
  };
  const load = async (path: string, url = `blob:${path}`) => {
    const i = loads.findIndex((l) => l.path === path);
    if (i < 0) throw new Error(`no se pidió ${path}`);
    const [l] = loads.splice(i, 1);
    l.d.resolve(url);
    await settle();
  };
  return { api, gets, loads, revoked, answer, load };
}

/** Deja correr las promesas encadenadas (todo es fake: no hace falta esperar timers). */
const settle = async () => {
  for (let i = 0; i < 20; i++) await Promise.resolve();
};

const asset = (id: string, over: Partial<AssetSummary> = {}): AssetSummary => ({
  id,
  file: `${id}.jpg`,
  edited: false,
  missing: false,
  ...over,
});

function setup(ids = ["a", "b", "c"]) {
  const f = fakeApi();
  const store = createLibraryStore(f.api);
  store.getState().sync(ids.map((id) => asset(id)));
  return { ...f, store, s: () => store.getState() };
}

describe("store de la biblioteca: selección", () => {
  it("las acciones usan el orden de las fotos del proyecto", () => {
    const t = setup(["a", "b", "c", "d"]);
    t.s().select("b", plain);
    t.s().select("d", shift);
    expect(t.s().selected).toEqual(["b", "c", "d"]);
    t.s().selectAll();
    expect(t.s().selected).toEqual(["a", "b", "c", "d"]);
    t.s().clear();
    expect(t.s().selected).toEqual([]);
    t.s().focusOn("c");
    expect(t.s().focus).toBe("c");
    expect(t.s().selected).toEqual([]);
  });

  it("la selección sobrevive a importar más fotos y se limpia de las que ya no están", () => {
    const t = setup(["a", "b", "c"]);
    t.s().select("a", plain);
    t.s().select("c", ctrl);
    t.s().sync(["a", "b", "c", "d"].map((id) => asset(id)));
    expect(t.s().selected).toEqual(["a", "c"]);
    t.s().sync(["a", "b"].map((id) => asset(id)));
    expect(t.s().selected).toEqual(["a"]);
    expect(t.s().order).toEqual(["a", "b"]);
  });
});

describe("store de la biblioteca: miniaturas", () => {
  it("want pide solo las que faltan y no repite pedidos", async () => {
    const t = setup();
    t.s().want(["a", "b"]);
    t.s().want(["a", "b", "zz"]); // zz no es del proyecto
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a", "b"]);
    expect(t.s().thumbs.a.status).toBe("loading");
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    expect(t.s().thumbs.a).toMatchObject({ status: "ready", url: "blob:C:/p/cache/thumbs/a.jpg" });
    t.s().want(["a", "b"]);
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["b"]);
    expect(t.loads).toEqual([]);
  });

  it("si se está generando, espera el aviso y confirma la ruta con otro thumbnail.get", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", null);
    expect(t.s().thumbs.a.status).toBe("loading");
    t.s().onThumbnailReady({ asset: "a", path: "C:/p/cache/thumbs/a-1.jpg", error: null });
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
    await t.answer("a", "C:/p/cache/thumbs/a-1.jpg");
    await t.load("C:/p/cache/thumbs/a-1.jpg");
    expect(t.s().thumbs.a).toMatchObject({ status: "ready", url: "blob:C:/p/cache/thumbs/a-1.jpg" });
  });

  it("un aviso que llega mientras se pregunta hace volver a preguntar si la respuesta es null", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    t.s().onThumbnailReady({ asset: "a", path: "C:/p/cache/thumbs/a.jpg", error: null });
    await t.answer("a", null);
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
  });

  it("un aviso con error deja la miniatura en error y want no insiste", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", null);
    t.s().onThumbnailReady({ asset: "a", path: null, error: "no se encuentra el archivo" });
    expect(t.s().thumbs.a).toMatchObject({ status: "error", url: null, error: "no se encuentra el archivo" });
    t.s().want(["a"]);
    await settle();
    expect(t.gets).toEqual([]);
  });

  it("un aviso sin ruta ni error deja la miniatura para volver a pedirla", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", null);
    t.s().onThumbnailReady({ asset: "a", path: null, error: null });
    expect(t.s().thumbs.a.status).toBe("idle");
    t.s().want(["a"]);
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
  });

  it("si thumbnail.get o la lectura fallan (motor caído o reiniciado), vuelve a idle sin insistir solo", async () => {
    const t = setup();
    t.s().want(["a", "b"]);
    await settle();
    t.gets.shift()!.d.reject(new EngineError("no hay un proyecto abierto", -32001));
    await t.answer("b", "C:/p/cache/thumbs/b.jpg");
    t.loads.shift()!.d.reject(new EngineError("no está en la caché", null));
    await settle();
    expect(t.s().thumbs.a).toMatchObject({ status: "idle" });
    expect(t.s().thumbs.b).toMatchObject({ status: "idle" });
    expect(t.gets).toEqual([]); // no hay reintento en caliente
    t.s().want(["a"]);
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
  });

  it("tras un reinicio del motor: el primer get falla, el siguiente want lo recupera", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    t.s().reset({ sameProject: true });
    t.s().want(["a"]); // el proyecto todavía no se reabrió en el motor nuevo
    await settle();
    t.gets.shift(); // el pedido del motor anterior nunca contesta
    t.gets.shift()!.d.reject(new EngineError("no hay un proyecto abierto", -32001));
    await settle();
    expect(t.s().thumbs.a.status).toBe("idle");
    t.s().want(["a"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    expect(t.s().thumbs.a).toMatchObject({ status: "ready", url: "blob:C:/p/cache/thumbs/a.jpg" });
  });

  it("un aviso de una foto que no se pidió (u otro proyecto) se ignora y no lee nada", async () => {
    const t = setup();
    t.s().onThumbnailReady({ asset: "a", path: "C:/otro/cache/thumbs/a.jpg", error: null });
    t.s().onThumbnailReady({ asset: "zz", path: "C:/otro/cache/thumbs/zz.jpg", error: null });
    await settle();
    expect(t.gets).toEqual([]);
    expect(t.loads).toEqual([]);
    expect(t.s().thumbs).toEqual({});
  });

  it("reset revoca todo y lo que llega después del proyecto anterior se ignora y se revoca", async () => {
    const t = setup();
    t.s().want(["a", "b", "c"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    await t.answer("b", "C:/p/cache/thumbs/b.jpg"); // b: leyendo los bytes
    await t.answer("c", null); // c: esperando el aviso
    t.s().select("a", plain);
    t.s().reset();
    expect(t.revoked).toEqual(["blob:C:/p/cache/thumbs/a.jpg"]);
    expect(t.s().thumbs).toEqual({});
    expect(t.s().order).toEqual([]);
    expect(t.s().selected).toEqual([]);
    await t.load("C:/p/cache/thumbs/b.jpg");
    expect(t.revoked).toContain("blob:C:/p/cache/thumbs/b.jpg");
    t.s().onThumbnailReady({ asset: "c", path: "C:/p/cache/thumbs/c.jpg", error: null });
    await settle();
    expect(t.gets).toEqual([]);
    expect(t.s().thumbs).toEqual({});
  });

  it("reset del mismo proyecto (motor reiniciado) conserva fotos y selección y vuelve a pedir", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    t.s().select("b", plain);
    t.s().reset({ sameProject: true });
    expect(t.revoked).toEqual(["blob:C:/p/cache/thumbs/a.jpg"]);
    expect(t.s().thumbs).toEqual({});
    expect(t.s().selected).toEqual(["b"]);
    expect(t.s().order).toEqual(["a", "b", "c"]);
    t.s().want(["a"]);
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
  });

  it("invalidate vuelve a pedirla; la anterior se ve hasta que llega la nueva y ahí se revoca", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a-v1.jpg");
    await t.load("C:/p/cache/thumbs/a-v1.jpg");
    const before = t.s().thumbs.a.key;
    t.s().invalidate("a");
    await settle();
    expect(t.s().thumbs.a).toMatchObject({ status: "loading", url: "blob:C:/p/cache/thumbs/a-v1.jpg" });
    expect(t.s().thumbs.a.key).not.toBe(before);
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
    await t.answer("a", "C:/p/cache/thumbs/a-v2.jpg");
    await t.load("C:/p/cache/thumbs/a-v2.jpg");
    expect(t.s().thumbs.a).toMatchObject({ status: "ready", url: "blob:C:/p/cache/thumbs/a-v2.jpg" });
    expect(t.revoked).toEqual(["blob:C:/p/cache/thumbs/a-v1.jpg"]);
  });

  it("una respuesta de una versión anterior se ignora (y su blob se revoca)", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a-v1.jpg"); // leyendo v1
    t.s().invalidate("a");
    await t.load("C:/p/cache/thumbs/a-v1.jpg");
    expect(t.revoked).toEqual(["blob:C:/p/cache/thumbs/a-v1.jpg"]);
    expect(t.s().thumbs.a).toMatchObject({ status: "loading", url: null });
    await t.answer("a", "C:/p/cache/thumbs/a-v2.jpg");
    await t.load("C:/p/cache/thumbs/a-v2.jpg");
    expect(t.s().thumbs.a).toMatchObject({ status: "ready", url: "blob:C:/p/cache/thumbs/a-v2.jpg" });
  });

  it("invalidate de una foto que nunca se pidió no pide nada (lo hará want)", async () => {
    const t = setup();
    t.s().invalidate("a");
    await settle();
    expect(t.gets).toEqual([]);
  });

  it("si cambia 'editada' o 'falta' al sincronizar, se vuelve a pedir", async () => {
    const t = setup();
    t.s().want(["a", "b"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    await t.answer("b", null);
    t.s().onThumbnailReady({ asset: "b", path: null, error: "no se encuentra el archivo" });
    t.s().sync([asset("a", { edited: true }), asset("b"), asset("c")]);
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a"]);
    t.s().sync([asset("a", { edited: true }), asset("b", { missing: true }), asset("c")]);
    t.s().sync([asset("a", { edited: true }), asset("b"), asset("c")]); // "Ubicar…"
    await settle();
    expect(t.gets.map((g) => g.asset)).toEqual(["a", "b"]);
  });

  it("una foto que sale del proyecto suelta su miniatura", async () => {
    const t = setup();
    t.s().want(["a"]);
    await settle();
    await t.answer("a", "C:/p/cache/thumbs/a.jpg");
    await t.load("C:/p/cache/thumbs/a.jpg");
    t.s().sync([asset("b"), asset("c")]);
    expect(t.revoked).toEqual(["blob:C:/p/cache/thumbs/a.jpg"]);
    expect(t.s().thumbs.a).toBeUndefined();
  });

  it(`como mucho ${MAX_IN_FLIGHT} pedidos en vuelo, y las visibles nuevas van primero`, async () => {
    const ids = Array.from({ length: 20 }, (_, i) => `f${i}`);
    const t = setup(ids);
    t.s().want(ids.slice(0, 10));
    await settle();
    expect(t.gets).toHaveLength(MAX_IN_FLIGHT);
    t.s().want(["f15", "f16"]);
    // Una respuesta con ruta sigue ocupando su lugar mientras se leen los bytes.
    await t.answer("f0", "C:/p/cache/thumbs/f0.jpg");
    expect(t.gets).toHaveLength(MAX_IN_FLIGHT - 1);
    expect(t.loads).toHaveLength(1);
    await t.load("C:/p/cache/thumbs/f0.jpg");
    expect(t.gets.map((g) => g.asset).at(-1)).toBe("f15");
    // Esperar un aviso no ocupa lugar.
    await t.answer("f1", null);
    expect(t.gets.map((g) => g.asset).at(-1)).toBe("f16");
    expect(t.gets).toHaveLength(MAX_IN_FLIGHT);
  });

  it("want mueve al frente las ya encoladas (en el orden pedido) sin duplicarlas", async () => {
    const ids = Array.from({ length: 10 }, (_, i) => `f${i}`);
    const t = setup(ids);
    t.s().want(ids);
    await settle();
    expect(t.gets).toHaveLength(MAX_IN_FLIGHT);
    t.s().want(["f7", "f8"]);
    await t.answer("f0", null);
    expect(t.gets.map((g) => g.asset).at(-1)).toBe("f7");
    await t.answer("f1", null);
    expect(t.gets.map((g) => g.asset).at(-1)).toBe("f8");
    expect(t.gets).toHaveLength(MAX_IN_FLIGHT);
    expect(t.gets.map((g) => g.asset).filter((x) => x === "f7")).toHaveLength(1);
  });
});

describe("moveFocusIndex", () => {
  // 7 fotos en 3 columnas:  0 1 2 / 3 4 5 / 6
  it("izquierda y derecha avanzan de a una y se detienen en los bordes", () => {
    expect(moveFocusIndex(1, "ArrowRight", 3, 7)).toBe(2);
    expect(moveFocusIndex(1, "ArrowLeft", 3, 7)).toBe(0);
    expect(moveFocusIndex(0, "ArrowLeft", 3, 7)).toBe(0);
    expect(moveFocusIndex(6, "ArrowRight", 3, 7)).toBe(6);
  });

  it("arriba y abajo saltan una fila según las columnas", () => {
    expect(moveFocusIndex(1, "ArrowDown", 3, 7)).toBe(4);
    expect(moveFocusIndex(4, "ArrowUp", 3, 7)).toBe(1);
    expect(moveFocusIndex(1, "ArrowUp", 3, 7)).toBe(1);
  });

  it("abajo en la última fila corta va a la última foto; en una fila completa no se mueve", () => {
    expect(moveFocusIndex(4, "ArrowDown", 3, 7)).toBe(6);
    expect(moveFocusIndex(6, "ArrowDown", 3, 7)).toBe(6);
    expect(moveFocusIndex(5, "ArrowDown", 3, 6)).toBe(5);
  });

  it("Inicio y Fin van a la primera y la última", () => {
    expect(moveFocusIndex(4, "Home", 3, 7)).toBe(0);
    expect(moveFocusIndex(2, "End", 3, 7)).toBe(6);
  });

  it("columnas inválidas cuentan como una y otras teclas no mueven", () => {
    expect(moveFocusIndex(1, "ArrowDown", 0, 4)).toBe(2);
    expect(moveFocusIndex(1, "a", 3, 7)).toBe(1);
    expect(moveFocusIndex(0, "ArrowRight", 3, 0)).toBe(0);
  });
});

describe("idsToWant", () => {
  const order = ["a", "b", "c", "d"];
  const thumbs = {
    b: { key: "0:o:f", url: null, status: "idle" as const },
    c: { key: "0:o:f", url: "u", status: "ready" as const },
  };
  it("devuelve las visibles en orden de la biblioteca, sin las que faltan", () => {
    const visible = new Set(["d", "c", "a", "b"]);
    expect(idsToWant(order, visible, new Set(["a"]), thumbs, false)).toEqual(["b", "c", "d"]);
  });
  it("con onlyUnknown deja afuera las que ya tienen entrada (idle, ready, error)", () => {
    const visible = new Set(["a", "b", "c", "d"]);
    expect(idsToWant(order, visible, new Set(), thumbs, true)).toEqual(["a", "d"]);
  });
  it("ignora las no visibles", () => {
    expect(idsToWant(order, new Set(["d"]), new Set(), {}, true)).toEqual(["d"]);
  });
});
