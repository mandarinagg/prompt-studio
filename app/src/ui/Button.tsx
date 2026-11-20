import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { Tooltip } from "./Tooltip";

type Variant = "primary" | "secondary" | "quiet" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: IconName;
  /** Atajo que se muestra al lado del texto (p. ej. "Ctrl+N"). */
  shortcut?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", icon, shortcut, className, children, type = "button", ...rest },
  ref,
) {
  return (
    <button ref={ref} type={type} className={`btn btn-${variant} ${className ?? ""}`} {...rest}>
      {icon && <Icon name={icon} />}
      <span>{children}</span>
      {shortcut && <kbd className="btn-kbd">{shortcut}</kbd>}
    </button>
  );
});

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  /** Nombre accesible y texto del tooltip. */
  label: string;
}

export function IconButton({ icon, label, className, ...rest }: IconButtonProps): ReactNode {
  return (
    <Tooltip text={label}>
      <button type="button" aria-label={label} className={`icon-btn ${className ?? ""}`} {...rest}>
        <Icon name={icon} />
      </button>
    </Tooltip>
  );
}
