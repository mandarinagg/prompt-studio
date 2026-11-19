import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import {
  cacheUrl,
  call,
  onEngineEvent,
  onEngineFailed,
  onEngineRestarted,
  type AssetSummary,
  type EditPlan,
  type PlanCreated,
  type ProjectInfo,
  type StackState,
} from "./engine/client";
import "./App.css";

// Banco de pruebas del RPC v1 (#56): recorre proyecto → pedido → borrador → aplicar → undo con
// el cliente tipado. No es la UI de v0.1: la reemplazan #57–#59.

type BenchConfig = { photo: string; out: string; dir: string };

function loadImage(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => img.decode().then(resolve, resolve);
    img.onerror = () => reject(new Error(`no cargó ${src}`));
    img.src = src;
  });
}

/** ADR-0010: cuánto tarda la preview desde la respuesta del engine hasta estar decodificada. */
async function runBench(cfg: BenchConfig) {
  const name = `bench-${Date.now()}`;
  await call("project.create", { dir: cfg.dir, name });
  const [asset] = (await call("project.import", { paths: [cfg.photo] })).added;
  const samples: Record<string, unknown>[] = [];
  for (const long_side of [2048, 1024]) {
    for (let i = 0; i < 12; i++) {
      const stack: EditPlan = { operations: [{ op: "exposure", ev: 0.05 * (i + 1) }] };
      const t0 = performance.now();
      const r = await call("preview.render", { asset: asset.id, stack, long_side });
      const t1 = performance.now();
      await loadImage(cacheUrl(r.path));
      const t2 = performance.now();
      samples.push({ long_side, i, ...r, path: undefined, call_ms: t1 - t0, load_ms: t2 - t1 });
    }
  }
  await invoke("bench_report", { report: { photo_file: cfg.photo.split(/[\\/]/).pop(), samples } });
}

function App() {
  const [status, setStatus] = useState("…");
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  const [current, setCurrent] = useState<AssetSummary | null>(null);
  const [state, setState] = useState<StackState | null>(null);
  const [plan, setPlan] = useState<PlanCreated | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [form, setForm] = useState({ dir: "", name: "Prueba", open: "", importPath: "", prompt: "" });
  const projectPath = useRef<string | null>(null);

  useEffect(() => {
    invoke<BenchConfig | null>("bench_config").then((cfg) => {
      if (cfg) runBench(cfg).catch((e) => setStatus(`banco: ${e.message}`));
    });
    call("engine.version").then(
      (v) => setStatus(`pstudio ${v.pstudio} · Python ${v.python} · libvips ${v.libvips}`),
      (e) => setStatus(`error: ${e.message}`),
    );
    const subs = [
      onEngineEvent("thumbnail.ready", (t) => {
        if (t.path) setThumbs((m) => ({ ...m, [t.asset]: cacheUrl(t.path!) }));
      }),
      onEngineRestarted(async (n) => {
        setStatus(`El motor se reinició (intento ${n})`);
        if (projectPath.current) setProject(await call("project.open", { path: projectPath.current }));
      }),
      onEngineFailed((m) => setStatus(m)),
    ];
    return () => subs.forEach((s) => s.then((un) => un()));
  }, []);

  async function run<T>(fn: () => Promise<T>) {
    try {
      return await fn();
    } catch (e) {
      setStatus(`error: ${(e as Error).message}`);
    }
  }

  async function loaded(info: ProjectInfo) {
    projectPath.current = info.path;
    setProject(info);
    for (const a of info.assets) {
      const t = await call("thumbnail.get", { asset: a.id });
      if (t.path) setThumbs((m) => ({ ...m, [a.id]: cacheUrl(t.path!) }));
    }
  }

  async function select(a: AssetSummary) {
    setCurrent(a);
    setPlan(null);
    setState(await call("asset.state", { asset: a.id }));
    setPreview(cacheUrl((await call("preview.render", { asset: a.id, long_side: 1024 })).path));
  }

  async function show(asset: string, stack?: EditPlan) {
    setPreview(cacheUrl((await call("preview.render", { asset, stack, long_side: 1024 })).path));
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.currentTarget.value });

  return (
    <main className="container">
      <h1>PROMPT STUDIO · banco RPC v1</h1>
      <p>{status}</p>
      <div className="row">
        <input value={form.dir} onChange={set("dir")} placeholder="Carpeta" />
        <input value={form.name} onChange={set("name")} placeholder="Nombre" />
        <button onClick={() => run(async () => loaded(await call("project.create", { dir: form.dir, name: form.name })))}>
          Crear
        </button>
      </div>
      <div className="row">
        <input value={form.open} onChange={set("open")} placeholder="Ruta de un .pstudio" />
        <button onClick={() => run(async () => loaded(await call("project.open", { path: form.open })))}>Abrir</button>
      </div>
      {project && (
        <>
          <h2>{project.name}</h2>
          <div className="row">
            <input value={form.importPath} onChange={set("importPath")} placeholder="Foto o carpeta" />
            <button
              onClick={() =>
                run(async () => {
                  await call("project.import", { paths: [form.importPath] });
                  await loaded(await call("project.info"));
                })
              }
            >
              Importar
            </button>
          </div>
          <div className="row">
            {project.assets.map((a) => (
              <button key={a.id} onClick={() => run(() => select(a))} title={a.file}>
                {thumbs[a.id] ? <img src={thumbs[a.id]} alt={a.file} height={64} /> : a.file}
              </button>
            ))}
          </div>
        </>
      )}
      {current && state && (
        <>
          <div className="row">
            <input value={form.prompt} onChange={set("prompt")} placeholder="Pedido" />
            <button
              onClick={() =>
                run(async () => {
                  const p = await call("plan.create", { prompt: form.prompt, asset: current.id });
                  setPlan(p);
                  if (p.draft) await show(current.id, p.draft);
                })
              }
            >
              Pedir
            </button>
            {plan?.plan && (
              <button
                onClick={() =>
                  run(async () => {
                    setState(await call("asset.apply_plan", { asset: current.id, plan: plan.plan! }));
                    setPlan(null);
                    await show(current.id);
                  })
                }
              >
                Aplicar
              </button>
            )}
            <button disabled={!state.can_undo} onClick={() => run(async () => {
              setState(await call("asset.undo", { asset: current.id }));
              await show(current.id);
            })}>Deshacer</button>
            <button disabled={!state.can_redo} onClick={() => run(async () => {
              setState(await call("asset.redo", { asset: current.id }));
              await show(current.id);
            })}>Rehacer</button>
          </div>
          <p>
            {plan ? `Borrador (${plan.provider}, ${plan.ms.toFixed(0)} ms): ${plan.plan?.explanation ?? ""}` : state.label}
          </p>
          <pre>{JSON.stringify((plan?.draft ?? state.stack).operations, null, 1)}</pre>
          {preview && <img src={preview} alt="preview" style={{ maxWidth: "100%" }} />}
        </>
      )}
    </main>
  );
}

export default App;
