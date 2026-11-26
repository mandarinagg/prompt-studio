import { Button } from "../ui/Button";

interface Props {
  count: number;
  /** Se puede abrir la primera seleccionada (no falta). */
  canEdit: boolean;
  onEdit(): void;
  /** Pedido para todas las elegidas (hace falta que alguna se encuentre). */
  onBatch(): void;
  canBatch: boolean;
  /** Exactamente una seleccionada y se encuentra. */
  canCopy: boolean;
  onCopy(): void;
  /** Hay ajustes copiados. */
  canPaste: boolean;
  onPaste(): void;
  onExport(): void;
  onClear(): void;
}

/** Barra de abajo cuando hay fotos seleccionadas. */
export function SelectionBar({ count, canEdit, onEdit, onBatch, canBatch, canCopy, onCopy, canPaste, onPaste, onExport, onClear }: Props) {
  return (
    <div className="selection-bar" role="region" aria-label="Selección">
      <span className="selection-count" role="status">
        {count === 1 ? "1 seleccionada" : `${count} seleccionadas`}
      </span>
      <Button variant="primary" disabled={!canEdit} onClick={onEdit}>
        Editar
      </Button>
      <Button
        variant="secondary"
        disabled={!canBatch}
        title={canBatch ? undefined : "Ninguna de las fotos elegidas se encuentra"}
        onClick={onBatch}
      >
        {count === 1 ? "✦ Pedido para la foto…" : `✦ Pedido para las ${count}…`}
      </Button>
      <Button variant="secondary" disabled={!canPaste} title={canPaste ? "Ctrl+Shift+V" : "Primero copiá los ajustes de una foto"} onClick={onPaste}>
        Pegar ajustes
      </Button>
      <Button
        variant="secondary"
        disabled={!canCopy}
        title={canCopy ? "Ctrl+Shift+C" : "Elegí una sola foto para copiar sus ajustes"}
        onClick={onCopy}
      >
        Copiar ajustes
      </Button>
      <Button variant="secondary" onClick={onExport}>
        Exportar…
      </Button>
      <Button variant="quiet" onClick={onClear}>
        Quitar selección
      </Button>
    </div>
  );
}
