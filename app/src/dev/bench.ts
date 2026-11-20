// Banco de transporte de la preview (ADR-0010). Solo corre con PSTUDIO_BENCH_PHOTO y
// PSTUDIO_BENCH_OUT definidas (ver `bench_config` en src-tauri/src/lib.rs); la app normal no lo usa.
import { invoke } from "@tauri-apps/api/core";
import { cacheImage, call, onEngineRestarted, type EditPlan } from "../engine/client";

let benchStarted = false; // StrictMode monta dos veces en desarrollo: el banco corre una sola

type BenchConfig = { photo: string; out: string; dir: string; restart: boolean };

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
  const info = await call("project.create", { dir: cfg.dir, name });
  const [asset] = (await call("project.import", { paths: [cfg.photo] })).added;
  let restart: Record<string, unknown> | null = null;
  if (cfg.restart) {
    // Desde afuera se mata el proceso del engine; se espera el relanzamiento y se reabre.
    const t = performance.now();
    const attempt = await new Promise<number>((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("no hubo relanzamiento")), 90_000);
      onEngineRestarted((n) => {
        clearTimeout(timer);
        resolve(n);
      });
    });
    const waited = performance.now() - t;
    const t1 = performance.now();
    const reopened = await call("project.open", { path: info.path });
    restart = { attempt, waited_ms: waited, reopen_ms: performance.now() - t1, assets: reopened.assets.length };
  }
  const samples: Record<string, unknown>[] = [];
  for (const long_side of [2048, 1024]) {
    for (let i = 0; i < 12; i++) {
      const stack: EditPlan = { operations: [{ op: "exposure", ev: 0.05 * (i + 1) }] };
      const t0 = performance.now();
      const r = await call("preview.render", { asset: asset.id, stack, long_side });
      const t1 = performance.now();
      const url = await cacheImage(r.path);
      await loadImage(url);
      URL.revokeObjectURL(url);
      const t2 = performance.now();
      samples.push({ long_side, i, ...r, path: undefined, call_ms: t1 - t0, load_ms: t2 - t1 });
    }
  }
  await invoke("bench_report", { report: { photo_file: cfg.photo.split(/[\\/]/).pop(), restart, samples } });
}

/** Si la app se lanzó en modo banco, lo corre y devuelve true. */
export async function maybeRunBench(): Promise<boolean> {
  const cfg = await invoke<BenchConfig | null>("bench_config");
  if (!cfg || benchStarted) return cfg !== null;
  benchStarted = true;
  runBench(cfg).catch((e) => {
    invoke("bench_report", { report: { error: String(e?.message ?? e), code: e?.code ?? null } });
  });
  return true;
}
