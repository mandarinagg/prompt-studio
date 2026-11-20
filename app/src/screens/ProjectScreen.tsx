import { useApp } from "../state/store";
import { IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";

/**
 * Proyecto abierto: barra superior y las fotos del proyecto. La biblioteca con miniaturas,
 * selección y editor se construye sobre esta pantalla.
 */
export function ProjectScreen({ dragging }: { dragging: boolean }) {
  const project = useApp((s) => s.project)!;
  const close = useApp((s) => s.closeProject);
  const count = project.assets.length;
  const missing = project.assets.filter((a) => a.missing).length;

  return (
    <div className="shell">
      <header className="topbar">
        <IconButton icon="back" label="Cerrar proyecto y volver al inicio" onClick={close} />
        <span className="topbar-brand">PROMPT STUDIO</span>
        <span className="topbar-sep" aria-hidden="true" />
        <h1 className="topbar-title">{project.name}</h1>
        <span className="topbar-meta">
          {count === 1 ? "1 foto" : `${count} fotos`}
          {missing > 0 && ` · ${missing === 1 ? "1 no se encuentra" : `${missing} no se encuentran`}`}
        </span>
      </header>

      <main className={`project-body ${dragging ? "is-dragging" : ""}`}>
        {count === 0 ? (
          <div className="empty">
            <Icon name="photo" size={28} />
            <p className="empty-title">Este proyecto todavía no tiene fotos</p>
            <p className="empty-hint">Arrastrá fotos o una carpeta sobre la ventana para agregarlas.</p>
          </div>
        ) : (
          <ul className="asset-list" aria-label="Fotos del proyecto">
            {project.assets.map((a) => (
              <li key={a.id} className={`asset ${a.missing ? "is-missing" : ""}`}>
                <Icon name={a.missing ? "alert" : "photo"} size={16} />
                <span className="asset-file">{a.file}</span>
                {a.edited && <span className="badge">Editada</span>}
                {a.missing && <span className="badge badge-warn">No se encuentra</span>}
              </li>
            ))}
          </ul>
        )}
        {dragging && <p className="drop-hint">Soltalas para agregarlas a {project.name}</p>}
      </main>
    </div>
  );
}
