import { useEffect } from "react";
import type { Toast } from "../state/app";
import { useApp } from "../state/store";
import { Icon } from "./Icon";

const INFO_MS = 6000; // los avisos fijos (y los errores) quedan hasta que se cierran

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss(): void }) {
  useEffect(() => {
    if (toast.sticky) return;
    const timer = window.setTimeout(onDismiss, INFO_MS);
    return () => clearTimeout(timer);
  }, [toast.sticky]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={`toast toast-${toast.kind}`} role={toast.kind === "error" ? "alert" : "status"}>
      <Icon name={toast.kind === "error" ? "alert" : "check"} />
      <p>{toast.text}</p>
      <button type="button" className="icon-btn" aria-label="Cerrar aviso" onClick={onDismiss}>
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}

/** Avisos abajo a la derecha; el lector de pantalla los anuncia (`status` o `alert`). */
export function Toasts() {
  const toasts = useApp((s) => s.toasts);
  const dismiss = useApp((s) => s.dismissToast);
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}
