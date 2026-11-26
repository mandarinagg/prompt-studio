import { useEffect, useRef, type RefObject } from "react";
import { idsToWant } from "../state/library";
import { libraryStore } from "../state/store";

interface Options {
  /** El contenedor que scrollea (null = la ventana). Se lee al montar y cuando cambian los ids. */
  root(container: HTMLElement): Element | null;
  /** Margen alrededor del contenedor para pedir un poco antes de que se vea. */
  rootMargin: string;
}

/**
 * Carga perezosa de miniaturas: pide solo las fotos visibles (y un margen) dentro de `container`,
 * en el orden de `ids`. Cada foto es un elemento con `data-asset-cell="<id>"`. Sirve a la
 * cuadrícula y a la tira del editor.
 */
export function useLazyThumbs(
  container: RefObject<HTMLElement | null>,
  ids: string[],
  missing: ReadonlySet<string>,
  options: Options,
) {
  // Las visibles sobreviven a las reconstrucciones del observer (si no, se pierden entre una y otra).
  const visibleRef = useRef<Set<string>>(new Set());
  const missingRef = useRef<ReadonlySet<string>>(missing);
  const idsRef = useRef<string[]>([]);
  const optionsRef = useRef(options);
  idsRef.current = ids;
  missingRef.current = missing;
  optionsRef.current = options;

  useEffect(() => {
    const el = container.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const visible = visibleRef.current;
    const known = new Set(ids);
    for (const id of visible) if (!known.has(id)) visible.delete(id);
    const observer = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const id = (e.target as HTMLElement).dataset.assetCell;
          if (!id) continue;
          if (e.isIntersecting) visible.add(id);
          else visible.delete(id);
        }
        const lib = libraryStore.getState();
        const want = idsToWant(ids, visible, missingRef.current, lib.thumbs, false);
        if (want.length > 0) lib.want(want);
      },
      { root: optionsRef.current.root(el), rootMargin: optionsRef.current.rootMargin },
    );
    el.querySelectorAll("[data-asset-cell]").forEach((cell) => observer.observe(cell));
    return () => observer.disconnect();
  }, [container, ids]);

  // Si las miniaturas se sueltan (el motor se reinició o se cayó) las visibles se vuelven a pedir.
  // Solo las que no tienen entrada: las idle o error esperan a verse de nuevo (sin reintentos en bucle).
  useEffect(() => {
    return libraryStore.subscribe((s, prev) => {
      if (s.thumbs === prev.thumbs) return;
      const want = idsToWant(idsRef.current, visibleRef.current, missingRef.current, s.thumbs, true);
      if (want.length > 0) s.want(want);
    });
  }, []);
}
