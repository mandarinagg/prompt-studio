import { Button } from "../ui/Button";

interface Props {
  count: number;
  /** Se puede abrir la primera seleccionada (no falta). */
  canEdit: boolean;
  onEdit(): void;
  onClear(): void;
}

/** Barra de abajo cuando hay fotos seleccionadas. Las acciones sobre varias llegan con #62. */
export function SelectionBar({ count, canEdit, onEdit, onClear }: Props) {
  return (
    <div className="selection-bar" role="region" aria-label="Selección">
      <span className="selection-count" role="status">
        {count === 1 ? "1 seleccionada" : `${count} seleccionadas`}
      </span>
      <Button variant="primary" disabled={!canEdit} onClick={onEdit}>
        Editar
      </Button>
      <Button variant="quiet" onClick={onClear}>
        Quitar selección
      </Button>
    </div>
  );
}
