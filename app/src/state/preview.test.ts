import { describe, expect, it } from "vitest";
import { createPreviewLoop, type PreviewJob, type PreviewResult } from "./preview";

/** Render falso que se resuelve a mano, para controlar el orden. */
function fakeRender() {
  const calls: { job: PreviewJob; resolve(r: PreviewResult): void; reject(e: Error): void }[] = [];
  let n = 0;
  const render = (job: PreviewJob) =>
    new Promise<PreviewResult>((resolve, reject) => {
      calls.push({ job, resolve, reject });
    });
  const result = (): PreviewResult => ({ url: `blob:${++n}`, width: 100, height: 50, ms: 1 });
  return { render, calls, result };
}

const job = (ev: number, kind: PreviewJob["kind"] = "after", asset = "a"): PreviewJob => ({
  kind,
  asset,
  stack: { operations: [{ op: "exposure", ev }] },
  longSide: 1024,
});

const tick = () => new Promise((r) => setTimeout(r, 0));

describe("preview: gana el último", () => {
  it("con una en vuelo, las intermedias se descartan y solo queda la más reciente", async () => {
    const { render, calls, result } = fakeRender();
    const shown: string[] = [];
    const revoked: string[] = [];
    const loop = createPreviewLoop(render, {
      onResult: (_j, r) => shown.push(r.url),
      revoke: (u) => revoked.push(u),
    });
    loop.request(job(0.1));
    loop.request(job(0.2));
    loop.request(job(0.3));
    loop.request(job(0.4));
    expect(calls).toHaveLength(1);
    calls[0].resolve(result());
    await tick();
    expect(calls).toHaveLength(2);
    expect(calls[1].job.stack.operations![0]).toEqual({ op: "exposure", ev: 0.4 });
    calls[1].resolve(result());
    await tick();
    expect(shown).toEqual(["blob:1", "blob:2"]);
    expect(revoked).toEqual(["blob:1"]); // la anterior se libera al llegar la nueva
  });

  it("antes y después tienen cada uno su lugar pendiente; después va primero", async () => {
    const { render, calls, result } = fakeRender();
    const loop = createPreviewLoop(render, { onResult: () => {}, revoke: () => {} });
    loop.request(job(0.1));
    loop.request(job(0, "before"));
    loop.request(job(0.2));
    calls[0].resolve(result());
    await tick();
    expect(calls[1].job.kind).toBe("after");
    calls[1].resolve(result());
    await tick();
    expect(calls[2].job.kind).toBe("before");
  });

  it("al cambiar de foto, lo que estaba en vuelo se descarta y se libera", async () => {
    const { render, calls, result } = fakeRender();
    const shown: string[] = [];
    const revoked: string[] = [];
    const loop = createPreviewLoop(render, {
      onResult: (_j, r) => shown.push(r.url),
      revoke: (u) => revoked.push(u),
    });
    loop.request(job(0.1, "after", "a"));
    loop.request(job(0.2, "after", "a"));
    loop.reset();
    loop.request(job(0.5, "after", "b"));
    calls[0].resolve(result()); // llega tarde la de "a"
    await tick();
    expect(shown).toEqual([]);
    expect(revoked).toEqual(["blob:1"]);
    expect(calls).toHaveLength(2);
    expect(calls[1].job.asset).toBe("b");
    calls[1].resolve(result());
    await tick();
    expect(shown).toEqual(["blob:2"]);
  });

  it("un error se informa y el bucle sigue con la pendiente", async () => {
    const { render, calls, result } = fakeRender();
    const errors: string[] = [];
    const shown: string[] = [];
    const loop = createPreviewLoop(render, {
      onResult: (_j, r) => shown.push(r.url),
      onError: (_j, e) => errors.push(String(e)),
      revoke: () => {},
    });
    loop.request(job(0.1));
    loop.request(job(0.2));
    calls[0].reject(new Error("falló"));
    await tick();
    expect(errors).toEqual(["Error: falló"]);
    calls[1].resolve(result());
    await tick();
    expect(shown).toEqual(["blob:1"]);
  });

  it("dispose libera lo último que se mostró", async () => {
    const { render, calls, result } = fakeRender();
    const revoked: string[] = [];
    const loop = createPreviewLoop(render, { onResult: () => {}, revoke: (u) => revoked.push(u) });
    loop.request(job(0.1));
    loop.request(job(0, "before"));
    calls[0].resolve(result());
    await tick();
    calls[1].resolve(result());
    await tick();
    loop.dispose();
    expect(revoked.sort()).toEqual(["blob:1", "blob:2"]);
  });
});
