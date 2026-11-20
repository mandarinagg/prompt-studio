import type { RecentProject } from "../engine/client";
import { whenOpened } from "../lib/time";
import { useApp } from "../state/store";
import { Button, IconButton } from "../ui/Button";
import { Icon } from "../ui/Icon";

interface StartProps {
  /** Hay fotos o carpetas arrastradas sobre la ventana. */
  dragging: boolean;
  onOpen(): void;
}

/** Inicio: la mesa de luz donde se sueltan fotos, las dos acciones y los recientes. */
export function StartScreen({ dragging, onOpen }: StartProps) {
  const recents = useApp((s) => s.recents);
  const busy = useApp((s) => s.busy);
  const startNew = useApp((s) => s.startNewProject);

  return (
    <main className="start">
      <section className="start-main" aria-labelledby="start-title">
        <header className="start-brand">
          <h1 id="start-title" className="wordmark">
            PROMPT STUDIO
          </h1>
          <p className="start-tagline">Pedí en palabras lo que querés hacerle a tus fotos.</p>
        </header>

        <div className={`lighttable ${dragging ? "is-dragging" : ""}`}>
          <div className="lighttable-frames" aria-hidden="true">
            {Array.from({ length: 6 }, (_, i) => (
              <span key={i} className="lighttable-frame" />
            ))}
          </div>
          <div className="lighttable-copy">
            <p className="lighttable-title">
              {dragging ? "Soltalas para crear un proyecto" : "Soltá fotos o una carpeta acá"}
            </p>
            <p className="lighttable-hint">
              Se crea un proyecto con ellas. Las fotos originales no se mueven ni se modifican.
            </p>
          </div>
          <div className="lighttable-actions">
            <Button variant="primary" icon="plus" shortcut="Ctrl+N" disabled={busy} onClick={() => startNew({})}>
              Nuevo proyecto
            </Button>
            <Button icon="folder" shortcut="Ctrl+O" disabled={busy} onClick={onOpen}>
              Abrir proyecto…
            </Button>
          </div>
        </div>
      </section>

      <section className="recents" aria-labelledby="recents-title">
        <h2 id="recents-title" className="recents-title">
          Recientes
        </h2>
        {recents.length === 0 ? (
          <p className="recents-empty">Los proyectos que abras van a aparecer acá.</p>
        ) : (
          <ul className="recents-list">
            {recents.map((r) => (
              <RecentRow key={r.path} recent={r} />
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function RecentRow({ recent }: { recent: RecentProject }) {
  const open = useApp((s) => s.openProject);
  const forget = useApp((s) => s.forgetRecent);
  const busy = useApp((s) => s.busy);

  return (
    <li className={`recent ${recent.exists ? "" : "is-missing"}`}>
      <button
        type="button"
        className="recent-open"
        disabled={busy || !recent.exists}
        onClick={() => open(recent.path)}
        title={recent.path}
      >
        <span className="recent-name">{recent.name}</span>
        <span className="recent-path">{recent.path}</span>
        {recent.exists ? (
          <span className="recent-when">{whenOpened(recent.opened_at)}</span>
        ) : (
          <span className="recent-missing">
            <Icon name="alert" size={14} />
            No se encuentra: ¿se movió o se borró?
          </span>
        )}
      </button>
      <IconButton
        icon="close"
        label={`Quitar ${recent.name} de recientes`}
        className="recent-forget"
        onClick={() => forget(recent.path)}
      />
    </li>
  );
}
