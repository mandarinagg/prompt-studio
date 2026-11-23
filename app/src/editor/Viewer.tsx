import { useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { findOp, setOp } from "../lib/stack";
import { frameFor, moveFrame } from "../lib/crop";
import { editorStore, useEditor } from "../state/store";
import type { Rect } from "../engine/client";

interface ViewerProps {
  /** Mantener `\` o el botón: se ve el original completo. */
  holdBefore: boolean;
  /** Vista dividida antes/después (solo sin geometría). */
  split: boolean;
}

/**
 * La foto. Ajustada a la ventana por defecto; 100% con doble clic o Z, y se desplaza
 * arrastrando. Mientras llega una preview nueva se sigue viendo la anterior (sin spinner).
 */
export function Viewer({ holdBefore, split }: ViewerProps) {
  const after = useEditor((s) => s.after);
  const before = useEditor((s) => s.before);
  const zoom = useEditor((s) => s.zoom);
  const cropping = useEditor((s) => s.cropping);
  const error = useEditor((s) => s.error);
  const stats = useEditor((s) => s.stats);
  // Hay borrador solo si el plan cambia algo visible (sin filas visibles se ve la pila).
  const drafting = useEditor((s) => !!s.plan?.draft);
  const file = useEditor((s) => s.asset?.file ?? "");
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ width: 0, height: 0 });
  const [splitAt, setSplitAt] = useState(50);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect;
      setBox({ width, height });
      editorStore.getState().setViewport(Math.round(width), Math.round(height));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const shown = holdBefore && before ? before : after;
  const dpr = window.devicePixelRatio || 1;
  let w = 0;
  let h = 0;
  if (shown) {
    if (zoom === "actual") {
      w = shown.width / dpr;
      h = shown.height / dpr;
    } else {
      const k = Math.min(box.width / shown.width, box.height / shown.height);
      w = shown.width * k;
      h = shown.height * k;
    }
  }

  // Desplazar arrastrando cuando la foto es más grande que el visor.
  const pan = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (zoom !== "actual" || e.button !== 0 || (e.target as HTMLElement).closest(".crop-frame, .split-handle")) return;
    const el = ref.current!;
    pan.current = { x: e.clientX, y: e.clientY, left: el.scrollLeft, top: el.scrollTop };
    el.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const p = pan.current;
    if (!p) return;
    ref.current!.scrollLeft = p.left - (e.clientX - p.x);
    ref.current!.scrollTop = p.top - (e.clientY - p.y);
  };
  const endPan = () => {
    pan.current = null;
  };

  const showSplit = split && !holdBefore && before && after && !cropping;
  const showCrop = cropping && after && !findOp(after.stack, "crop") && !holdBefore;

  return (
    <div
      ref={ref}
      className={`viewer ${zoom === "actual" ? "is-actual" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endPan}
      onPointerCancel={endPan}
      onDoubleClick={(e) => {
        if ((e.target as HTMLElement).closest(".crop-frame, .split-handle")) return;
        editorStore.getState().setZoom(zoom === "fit" ? "actual" : "fit");
      }}
    >
      {shown && (
        <div className="viewer-stage" style={{ width: w, height: h }}>
          <img
            className="viewer-img"
            src={shown.url}
            alt={holdBefore && before ? `${file}, original` : file}
            draggable={false}
          />
          {showSplit && (
            <>
              <img
                className="viewer-img viewer-before"
                src={before.url}
                alt=""
                draggable={false}
                style={{ clipPath: `inset(0 ${100 - splitAt}% 0 0)` }}
              />
              <SplitHandle at={splitAt} onChange={setSplitAt} />
              <span className="viewer-chip viewer-chip-left">Antes</span>
              <span className="viewer-chip viewer-chip-right">Después</span>
            </>
          )}
          {holdBefore && before && <span className="viewer-chip viewer-chip-left">Original</span>}
          {drafting && !(holdBefore && before) && (
            <span className="viewer-chip viewer-chip-plan" role="status">
              Vista previa del plan — sin aplicar
            </span>
          )}
          {showCrop && <CropFrame width={after.width} height={after.height} />}
        </div>
      )}
      {!shown && !error && <p className="viewer-note">Abriendo la foto…</p>}
      {error && (
        <p className="viewer-note viewer-error" role="alert">
          {error}
        </p>
      )}
      {import.meta.env.DEV && stats && (
        <span className="viewer-stats" aria-hidden="true">
          {stats.ms} ms · {stats.side} px
        </span>
      )}
    </div>
  );
}

function SplitHandle({ at, onChange }: { at: number; onChange(v: number): void }) {
  const ref = useRef<HTMLDivElement>(null);
  const drag = (e: ReactPointerEvent<HTMLDivElement>) => {
    const stage = ref.current?.parentElement;
    if (!stage || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
    const r = stage.getBoundingClientRect();
    onChange(Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100)));
  };
  return (
    <div
      ref={ref}
      className="split-handle"
      style={{ left: `${at}%` }}
      role="slider"
      tabIndex={0}
      aria-label="Divisor antes y después"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(at)}
      aria-valuetext={`${Math.round(at)}% antes`}
      onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
      onPointerMove={drag}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 10 : 2;
        if (e.key === "ArrowLeft") onChange(Math.max(0, at - step));
        else if (e.key === "ArrowRight") onChange(Math.min(100, at + step));
        else return;
        e.preventDefault();
      }}
    />
  );
}

/**
 * Marco de recorte con proporción fija: se arrastra para encuadrar (sin manijas). Mientras se
 * encuadra se ve la foto entera; al soltar se guarda como `rect`.
 */
function CropFrame({ width, height }: { width: number; height: number }) {
  const stack = useEditor((s) => s.stack);
  const crop = findOp(stack, "crop");
  const saved = crop ? frameFor(width, height, crop) : null;
  const [frame, setFrameState] = useState<Rect | null>(saved);
  const latest = useRef<Rect | null>(saved); // el último marco, sin esperar al render
  const setFrame = (f: Rect | null) => {
    latest.current = f;
    setFrameState(f);
  };
  const start = useRef<{ x: number; y: number; frame: Rect } | null>(null);
  const keyStart = useRef<Rect | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  // Si la pila cambia desde afuera (otra proporción, deshacer), el marco la sigue.
  const savedKey = JSON.stringify(saved);
  useEffect(() => {
    if (!start.current && !keyStart.current) setFrame(saved);
  }, [savedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!frame || !crop) return null;

  // Solo se guarda si el marco se movió (un clic sin arrastrar no crea historial).
  const commit = (from: Rect) => {
    const f = latest.current;
    if (!f || (f.x === from.x && f.y === from.y)) return;
    const s = editorStore.getState();
    s.commit(setOp(s.stack, { op: "crop", rect: f }), "Encuadre");
  };

  const stage = () => ref.current!.parentElement!.getBoundingClientRect();

  return (
    <div
      ref={ref}
      className="crop-frame"
      style={{
        left: `${frame.x * 100}%`,
        top: `${frame.y * 100}%`,
        width: `${frame.width * 100}%`,
        height: `${frame.height * 100}%`,
      }}
      role="group"
      tabIndex={0}
      aria-label="Marco de recorte. Arrastralo o usá las flechas para encuadrar."
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.currentTarget.setPointerCapture(e.pointerId);
        start.current = { x: e.clientX, y: e.clientY, frame };
      }}
      onPointerMove={(e) => {
        const s = start.current;
        if (!s) return;
        const r = stage();
        setFrame(moveFrame(s.frame, (e.clientX - s.x) / r.width, (e.clientY - s.y) / r.height));
      }}
      onPointerUp={() => {
        const s = start.current;
        if (!s) return;
        start.current = null;
        commit(s.frame);
      }}
      onPointerCancel={() => {
        const s = start.current;
        start.current = null;
        if (s) setFrame(s.frame);
      }}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 0.05 : 0.01;
        const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
        if (!d) return;
        e.preventDefault();
        // Con las flechas el marco se mueve al instante y se guarda una vez, al soltar la tecla.
        if (!keyStart.current) keyStart.current = latest.current;
        setFrame(moveFrame(latest.current ?? frame, d[0], d[1]));
      }}
      onKeyUp={(e) => {
        if (!e.key.startsWith("Arrow") || !keyStart.current) return;
        const from = keyStart.current;
        keyStart.current = null;
        commit(from);
      }}
    >
      <span className="crop-grid" aria-hidden="true" />
    </div>
  );
}
