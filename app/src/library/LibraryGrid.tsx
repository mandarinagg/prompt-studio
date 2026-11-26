import { open } from "@tauri-apps/plugin-dialog";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { call } from "../engine/client";
import { moveFocusIndex } from "../state/library";
import { appStore, editorStore, libraryStore, useApp, useLibrary } from "../state/store";
import { AssetTile } from "./AssetTile";
import { SelectionBar } from "./SelectionBar";
import { useLazyThumbs } from "./useLazyThumbs";

export const IMAGE_FILTER = [{ name: "Imágenes", extensions: ["jpg", "jpeg", "png", "tif", "tiff", "webp"] }];

/** Cuántas columnas tiene la cuadrícula ahora, leídas del estilo calculado (no se adivinan). */
function columnsOf(grid: HTMLElement): number {
  const cols = getComputedStyle(grid).gridTemplateColumns;
  return cols && cols !== "none" ? cols.split(" ").length : 1;
}

/** Ubicar…: elegir el archivo de una foto que no se encuentra; el engine confirma que es la misma. */
async function relink(id: string) {
  const picked = await open({ multiple: false, title: "Ubicar la foto", filters: IMAGE_FILTER });
  if (typeof picked !== "string") return;
  try {
    await call("project.relink", { asset: id, path: picked });
  } catch (err) {
    appStore.getState().notify("error", err instanceof Error ? err.message : String(err));
    return; // nada cambia
  }
  await appStore.getState().refreshProject();
  libraryStore.getState().invalidate(id);
}

/**
 * La cuadrícula de fotos del proyecto. ARIA: `listbox` de selección múltiple con una `option` por
 * foto y foco móvil (roving tabindex): una sola foto entra con Tab y las flechas mueven el foco.
 */
export function LibraryGrid({ onExport }: { onExport(): void }) {
  const assets = useApp((s) => s.project?.assets);
  const list = useMemo(() => assets ?? [], [assets]);
  const thumbs = useLibrary((s) => s.thumbs);
  const selected = useLibrary((s) => s.selected);
  const focus = useLibrary((s) => s.focus);
  const gridRef = useRef<HTMLDivElement>(null);

  const ids = useMemo(() => list.map((a) => a.id), [list]);
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const tabbableId = focus !== null && ids.includes(focus) ? focus : (ids[0] ?? null);

  const missing = useMemo(() => new Set(list.filter((a) => a.missing).map((a) => a.id)), [list]);
  // Carga perezosa: solo las visibles (y una pantalla de margen), en el orden de la cuadrícula.
  useLazyThumbs(gridRef, ids, missing, {
    root: (grid) => grid.closest(".project-body"),
    rootMargin: `${window.innerHeight}px 0px`,
  });

  // Al volver del editor el foco está en <body>: se lo devolvemos a la foto con foco (solo al montar).
  useEffect(() => {
    const id = libraryStore.getState().focus;
    const active = document.activeElement;
    if (id === null || !ids.includes(id) || (active && active !== document.body)) return;
    gridRef.current
      ?.querySelector<HTMLElement>(`[data-asset="${CSS.escape(id)}"]`)
      ?.focus({ preventScroll: true });
    gridRef.current
      ?.querySelector<HTMLElement>(`[data-asset="${CSS.escape(id)}"]`)
      ?.scrollIntoView?.({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openAsset = useCallback(
    (id: string) => {
      const a = list.find((x) => x.id === id);
      if (a && !a.missing) void editorStore.getState().open(a);
    },
    [list],
  );

  const moveTo = (id: string) => {
    libraryStore.getState().focusOn(id);
    gridRef.current?.querySelector<HTMLElement>(`[data-asset="${CSS.escape(id)}"]`)?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget && !(e.target as HTMLElement).hasAttribute("data-asset")) return; // el botón "Ubicar…" usa sus propias teclas
    const lib = libraryStore.getState();
    const current = lib.focus !== null && ids.includes(lib.focus) ? lib.focus : (ids[0] ?? null);
    if (e.ctrlKey && e.key.toLowerCase() === "a") {
      e.preventDefault();
      lib.selectAll();
    } else if (e.key === "Escape") {
      if (lib.selected.length > 0) {
        e.preventDefault();
        lib.clear();
      }
    } else if (current === null) {
      return;
    } else if (e.key === " ") {
      e.preventDefault();
      lib.select(current, { ctrl: true, shift: false });
    } else if (e.key === "Enter") {
      e.preventDefault();
      openAsset(current);
    } else if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(e.key)) {
      e.preventDefault();
      const grid = gridRef.current;
      const next = moveFocusIndex(ids.indexOf(current), e.key, grid ? columnsOf(grid) : 1, ids.length);
      moveTo(ids[next]);
    }
  };

  // La primera seleccionada en el orden de la cuadrícula (Ctrl+clic no sigue ese orden).
  const first = list.find((a) => selectedSet.has(a.id));

  return (
    <>
      <div
        ref={gridRef}
        className="library-grid"
        role="listbox"
        aria-label="Fotos del proyecto"
        aria-multiselectable="true"
        onKeyDown={onKeyDown}
      >
        {list.map((a) => (
          <AssetTile
            key={a.id}
            asset={a}
            thumb={thumbs[a.id]}
            selected={selectedSet.has(a.id)}
            tabbable={a.id === tabbableId}
            onPick={(mods) => libraryStore.getState().select(a.id, mods)}
            onOpen={() => openAsset(a.id)}
            onFocusTile={() => libraryStore.getState().focusOn(a.id)}
            onRelink={() => void relink(a.id)}
          />
        ))}
      </div>
      {selected.length > 0 && (
        <SelectionBar
          count={selected.length}
          canEdit={!!first && !first.missing}
          onEdit={() => first && openAsset(first.id)}
          onExport={onExport}
          onClear={() => libraryStore.getState().clear()}
        />
      )}
    </>
  );
}
