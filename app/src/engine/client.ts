// Cliente tipado del engine: UI → Rust (`engine_call`) → engine Python por JSON-RPC.
// Los tipos vienen de contract.gen.ts (generado desde los modelos Pydantic del engine).
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { Events, Methods } from "./contract.gen";

export type * from "./contract.gen";

export type Method = keyof Methods;
export type Params<M extends Method> = Methods[M]["params"];
export type Result<M extends Method> = Methods[M]["result"];

/** Un método sin params obligatorios se puede llamar sin el segundo argumento. */
type ParamsArg<M extends Method> = {} extends Params<M> ? [params?: Params<M>] : [params: Params<M>];

/** Error del engine con su código JSON-RPC (p. ej. -32001 = no hay un proyecto abierto). */
export class EngineError extends Error {
  constructor(
    message: string,
    readonly code: number | null,
  ) {
    super(message);
    this.name = "EngineError";
  }
}

export const ErrorCode = {
  invalidParams: -32602,
  engine: -32000,
  noProject: -32001,
  projectChanged: -32002,
} as const;

export async function call<M extends Method>(method: M, ...[params]: ParamsArg<M>): Promise<Result<M>> {
  try {
    return await invoke<Result<M>>("engine_call", { method, params: params ?? {} });
  } catch (err) {
    if (typeof err === "object" && err !== null && "message" in err) {
      const e = err as { message: string; code?: number | null };
      throw new EngineError(e.message, e.code ?? null);
    }
    throw new EngineError(String(err), null);
  }
}

type EngineEvent = { method: string; params: unknown };

/** Notificación del engine (sin `id`), reenviada por Rust como evento `engine-event`. */
export function onEngineEvent<E extends keyof Events>(
  name: E,
  handler: (payload: Events[E]) => void,
): Promise<UnlistenFn> {
  return listen<EngineEvent>("engine-event", (e) => {
    if (e.payload.method === name) handler(e.payload.params as Events[E]);
  });
}

/** El engine se cayó y Rust lo relanzó: hay que reabrir el proyecto (se guarda solo). */
export function onEngineRestarted(handler: (attempt: number) => void): Promise<UnlistenFn> {
  return listen<{ attempt: number }>("engine-restarted", (e) => handler(e.payload.attempt));
}

/** El engine se cayó demasiadas veces seguidas y no se relanza más. */
export function onEngineFailed(handler: (message: string) => void): Promise<UnlistenFn> {
  return listen<{ message: string }>("engine-failed", (e) => handler(e.payload.message));
}

/** URL para un archivo de `cache/` del proyecto (preview, miniatura) por el protocolo de assets. */
export function cacheUrl(path: string): string {
  return convertFileSrc(path);
}
