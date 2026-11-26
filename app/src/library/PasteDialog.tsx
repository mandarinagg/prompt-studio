import { useEffect, useId, useState } from "react";
import { batchStore, useBatch } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

/** "Pegar ajustes de <foto> en N fotos", con la opción de incluir recorte, rotación y enderezado. */
export function PasteDialog({ open, onOpenChange, targets }: { open: boolean; onOpenChange(open: boolean): void; targets: string[] }) {
  const id = useId();
  const clipboard = useBatch((s) => s.clipboard);
  const [geometry, setGeometry] = useState(false);
  const n = targets.length;

  useEffect(() => {
    if (open) setGeometry(false); // cada vez, sin geometría por defecto
  }, [open]);

  const paste = async () => {
    onOpenChange(false);
    await batchStore.getState().paste(targets, geometry);
  };

  return (
    <Dialog
      open={open && clipboard !== null}
      onOpenChange={onOpenChange}
      title={`Pegar ajustes de ${clipboard?.file ?? "la foto"} en ${n === 1 ? "1 foto" : `${n} fotos`}`}
      description="Reemplaza los ajustes de esas fotos; se puede deshacer con Ctrl+Z."
      footer={
        <>
          <Button variant="quiet" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={() => void paste()}>
            Pegar
          </Button>
        </>
      }
    >
      <div className="plan-row">
        <input id={`${id}-geo`} type="checkbox" className="plan-check" checked={geometry} onChange={(e) => setGeometry(e.target.checked)} />
        <label htmlFor={`${id}-geo`} className="plan-name">
          Incluir recorte, rotación y enderezado
        </label>
      </div>
    </Dialog>
  );
}
