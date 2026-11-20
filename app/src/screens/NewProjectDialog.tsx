import { open } from "@tauri-apps/plugin-dialog";
import { useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

function joinPath(dir: string, name: string): string {
  if (!dir) return `${name}.pstudio`;
  const sep = dir.includes("\\") || !dir.includes("/") ? "\\" : "/";
  return `${dir.replace(/[\\/]+$/, "")}${sep}${name.trim()}.pstudio`;
}

/** Nombre y ubicación del proyecto nuevo. Si viene de arrastrar fotos, las agrega al crear. */
export function NewProjectDialog() {
  const draft = useApp((s) => s.draft);
  const busy = useApp((s) => s.busy);
  const cancel = useApp((s) => s.cancelNewProject);
  const create = useApp((s) => s.createProject);
  const [name, setName] = useState("");
  const [dir, setDir] = useState("");
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!draft) return;
    setName(draft.name);
    setDir(draft.dir);
    requestAnimationFrame(() => nameRef.current?.select());
  }, [draft?.name, draft?.dir, draft?.photos]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!draft) return null;
  const photos = draft.photos.length;
  const canCreate = name.trim() !== "" && dir !== "" && !busy;

  const chooseDir = async () => {
    const picked = await open({ directory: true, defaultPath: dir || undefined, title: "Dónde guardar el proyecto" });
    if (typeof picked === "string") setDir(picked);
  };

  const submit = () => {
    if (canCreate) create({ dir, name: name.trim(), photos: draft.photos });
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && !busy && cancel()}
      title="Nuevo proyecto"
      description={
        photos > 0
          ? `Se va a crear con ${photos === 1 ? "lo que soltaste" : `los ${photos} elementos que soltaste`}. Las fotos quedan donde están: el proyecto solo guarda dónde encontrarlas y tus ajustes.`
          : "Un proyecto guarda qué fotos estás editando y tus ajustes. Las fotos quedan donde están."
      }
      footer={
        <>
          <Button variant="quiet" onClick={cancel} disabled={busy}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={submit} disabled={!canCreate}>
            {busy ? "Creando…" : "Crear proyecto"}
          </Button>
        </>
      }
    >
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="field">
          <span className="field-label">Nombre</span>
          <input
            ref={nameRef}
            className="input"
            value={name}
            maxLength={100}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={draft.error ? true : undefined}
            aria-describedby={draft.error ? "new-project-error" : undefined}
          />
        </label>
        <div className="field">
          <span className="field-label" id="new-project-dir">
            Ubicación
          </span>
          <div className="field-row">
            <output className="input input-readonly" aria-labelledby="new-project-dir" title={dir}>
              {dir || "Elegí una carpeta"}
            </output>
            <Button onClick={chooseDir} disabled={busy}>
              Cambiar…
            </Button>
          </div>
        </div>
        <p className="field-hint">
          Se va a crear <span className="path">{joinPath(dir, name || "…")}</span>
        </p>
        {draft.error && (
          <p id="new-project-error" className="field-error" role="alert">
            {draft.error}
          </p>
        )}
        <button type="submit" hidden />
      </form>
    </Dialog>
  );
}
