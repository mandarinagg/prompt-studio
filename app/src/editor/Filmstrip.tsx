import { useEffect, useMemo, useRef } from "react";
import { editorStore, useApp, useEditor, useLibrary } from "../state/store";
import { useLazyThumbs } from "../library/useLazyThumbs";
import { Icon } from "../ui/Icon";

/**
 * La tira de fotos del proyecto, abajo en el editor. Son botones comunes (Tab llega, Enter abre):
 * no maneja flechas, así ←/→ siguen siendo "foto anterior/siguiente" del editor aunque el foco
 * esté en la tira.
 */
export function Filmstrip() {
  const current = useEditor((s) => s.asset?.id);
  const assets = useApp((s) => s.project?.assets);
  const list = useMemo(() => assets ?? [], [assets]);
  const thumbs = useLibrary((s) => s.thumbs);
  const stripRef = useRef<HTMLDivElement>(null);

  const ids = useMemo(() => list.map((a) => a.id), [list]);
  const missing = useMemo(() => new Set(list.filter((a) => a.missing).map((a) => a.id)), [list]);
  // El contenedor de la tira es el que scrollea; el margen es a los lados.
  useLazyThumbs(stripRef, ids, missing, { root: (strip) => strip, rootMargin: "0px 400px" });

  // Al cambiar de foto (clic, ←/→) la actual queda a la vista.
  useEffect(() => {
    if (!current) return;
    stripRef.current
      ?.querySelector<HTMLElement>(`[data-asset-cell="${CSS.escape(current)}"]`)
      ?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [current, ids]);

  return (
    <nav className="filmstrip" ref={stripRef} aria-label="Fotos del proyecto">
      {list.map((a) => {
        const url = thumbs[a.id]?.url ?? null;
        const isCurrent = a.id === current;
        return (
          <button
            key={a.id}
            type="button"
            className={`film-item ${isCurrent ? "is-current" : ""}`}
            data-asset-cell={a.id}
            aria-current={isCurrent ? "true" : undefined}
            aria-label={a.missing ? `${a.file}, no se encuentra` : a.file}
            disabled={a.missing}
            title={a.missing ? `${a.file}, no se encuentra` : a.file}
            onClick={() => {
              if (!isCurrent) void editorStore.getState().open(a);
            }}
          >
            {url ? (
              <img src={url} alt="" draggable={false} />
            ) : a.missing ? (
              <Icon name="alert" size={20} />
            ) : (
              <span className="tile-placeholder" aria-hidden="true" />
            )}
          </button>
        );
      })}
    </nav>
  );
}
