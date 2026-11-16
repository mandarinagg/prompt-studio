import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

type Metrics = {
  engine_spawn_ms: number | null;
  engine_ready_ms: number | null;
  ui_ready_ms: number | null;
};

// Spike #3: verifica la comunicación UI → Rust → engine Python. No es la UI real (M3).
function App() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [version, setVersion] = useState<string>("…");
  const [path, setPath] = useState("");
  const [info, setInfo] = useState<string>("");

  useEffect(() => {
    invoke<Metrics>("startup_metrics").then(setMetrics);
    invoke<Record<string, string>>("engine_call", { method: "engine.version" })
      .then((v) => setVersion(`pstudio ${v.pstudio} · Python ${v.python} · libvips ${v.libvips}`))
      .catch((e) => setVersion(`error: ${e}`));
  }, []);

  async function readInfo(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await invoke("engine_call", { method: "image.info", params: { path } });
      setInfo(JSON.stringify(r));
    } catch (err) {
      setInfo(`error: ${err}`);
    }
  }

  return (
    <main className="container">
      <h1>PROMPT STUDIO · spike sidecar</h1>
      <p>{version}</p>
      {metrics && (
        <p>
          engine listo: {metrics.engine_ready_ms?.toFixed(0) ?? "…"} ms · UI lista:{" "}
          {metrics.ui_ready_ms?.toFixed(0)} ms
        </p>
      )}
      <form className="row" onSubmit={readInfo}>
        <input value={path} onChange={(e) => setPath(e.currentTarget.value)} placeholder="Ruta de una foto" />
        <button type="submit">image.info</button>
      </form>
      <p>{info}</p>
    </main>
  );
}

export default App;
