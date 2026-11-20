import * as RD from "@radix-ui/react-dialog";
import type { ReactNode, RefObject } from "react";
import { Icon } from "./Icon";

interface DialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
  title: string;
  /** Una línea que explica qué pasa al confirmar (lectores de pantalla y vista). */
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** Qué enfocar al abrir (por defecto, el primer control: la X). */
  initialFocus?: RefObject<HTMLInputElement | null>;
}

/** Diálogo modal: Esc o la X lo cierran, el foco queda adentro mientras está abierto. */
export function Dialog({ open, onOpenChange, title, description, children, footer, initialFocus }: DialogProps) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="dialog-overlay" />
        <RD.Content
          className="dialog"
          onOpenAutoFocus={(e) => {
            if (!initialFocus?.current) return;
            e.preventDefault();
            initialFocus.current.select();
          }}
        >
          <header className="dialog-head">
            <RD.Title className="dialog-title">{title}</RD.Title>
            <RD.Close className="icon-btn" aria-label="Cerrar">
              <Icon name="close" />
            </RD.Close>
          </header>
          {description ? (
            <RD.Description className="dialog-desc">{description}</RD.Description>
          ) : (
            <RD.Description className="visually-hidden">{title}</RD.Description>
          )}
          <div className="dialog-body">{children}</div>
          {footer && <footer className="dialog-foot">{footer}</footer>}
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}
