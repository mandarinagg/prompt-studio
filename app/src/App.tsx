import { invoke } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { open } from "@tauri-apps/plugin-dialog";
import { useCallback, useEffect, useState } from "react";
import { maybeRunBench } from "./dev/bench";
import { onEngineEvent, onEngineFailed, onEngineRestarted } from "./engine/client";
import { classifyDrop, isProjectPath, projectFolder } from "./lib/paths";
import { EditorScreen } from "./editor/EditorScreen";
import { NewProjectDialog } from "./screens/NewProjectDialog";
import { ProjectScreen } from "./screens/ProjectScreen";
import { StartScreen } from "./screens/StartScreen";
import { appStore, editorStore, jobsStore, libraryStore, useApp, useEditor } from "./state/store";
import { Icon } from "./ui/Icon";
import { Toasts } from "./ui/Toasts";
import { TooltipProvider } from "./ui/Tooltip";

let booted = false; // StrictMode monta dos veces en desarrollo

/** Elegir una carpeta `.pstudio` y abrirla. */
async function chooseAndOpen() {
  const s = appStore.getState();
  const picked = await open({ directory: true, title: "Abrir proyecto", defaultPath: s.defaultDir || undefined });
  if (typeof picked !== "string") return;
  if (!isProjectPath(picked)) {
    s.notify("error", "Esa carpeta no es un proyecto. Elegí una carpeta que termine en .pstudio.");
    return;
  }
  await s.openProject(projectFolder(picked));
}

/** Lo que se suelta sobre la ventana: abre un proyecto, crea uno o agrega fotos al abierto. */
function handleDrop(paths: string[]) {
  const s = appStore.getState();
  if (s.busy || s.draft) return;
  const drop = classifyDrop(paths);
  if (drop.kind === "open") s.openProject(drop.path);
  else if (drop.kind === "create") {
    if (s.project) s.importPhotos(drop.photos);
    else s.startNewProject({ name: drop.name, photos: drop.photos });
  }
}

function EngineBanner() {
  const status = useApp((s) => s.engine);
  const message = useApp((s) => s.engineMessage);
  if (status !== "failed") return null;
  return (
    <div className="engine-banner" role="alert">
      <Icon name="alert" />
      <p>{message ?? "El motor de edición no responde."} Tus proyectos están guardados.</p>
    </div>
  );
}

export default function App() {
  const project = useApp((s) => s.project);
  const editing = useEditor((s) => s.asset !== null);
  const hasDraft = useApp((s) => s.draft !== null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (booted) return;
    booted = true;
    invoke("startup_metrics").catch(() => {});
    // Primero se escucha al motor y después se arranca: boot consulta si ya había fallado.
    Promise.all([
      onEngineRestarted(async () => {
        // Lo que esperaba o corría en el motor anterior no va a terminar (sus ids no vuelven).
        jobsStore.getState().onEngineLost("el motor se reinició");
        await appStore.getState().onRestarted();
        // Las miniaturas pedidas al motor anterior no van a llegar: se vuelven a pedir, pero
        // recién con el proyecto reabierto (si no, el motor nuevo contesta "no hay proyecto").
        libraryStore.getState().reset({ sameProject: true });
        // El proyecto se reabrió: el editor vuelve a pedir la pila y la preview.
        if (appStore.getState().project) await editorStore.getState().reload();
        else editorStore.getState().close();
      }),
      onEngineFailed((m) => {
        jobsStore.getState().onEngineLost("el motor dejó de responder");
        libraryStore.getState().reset({ sameProject: true });
        appStore.getState().onFailed(m);
      }),
      onEngineEvent("job.progress", (job) => jobsStore.getState().onEvent("job.progress", job)),
      onEngineEvent("job.done", (job) => jobsStore.getState().onEvent("job.done", job)),
      onEngineEvent("job.failed", (job) => jobsStore.getState().onEvent("job.failed", job)),
      onEngineEvent("thumbnail.ready", (ev) => libraryStore.getState().onThumbnailReady(ev)),
    ])
      .then(() => maybeRunBench())
      .then((bench) => {
        if (!bench) appStore.getState().boot();
      });
    getCurrentWebview().onDragDropEvent((e) => {
      const p = e.payload;
      if (p.type === "enter") setDragging(true);
      else if (p.type === "leave") setDragging(false);
      else if (p.type === "drop") {
        setDragging(false);
        handleDrop(p.paths);
      }
    });
  }, []);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.altKey || hasDraft || project || appStore.getState().busy) return;
      const key = e.key.toLowerCase();
      if (key === "n") {
        e.preventDefault();
        appStore.getState().startNewProject({});
      } else if (key === "o") {
        e.preventDefault();
        chooseAndOpen();
      }
    },
    [hasDraft, project],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  return (
    <TooltipProvider>
      <div className="app">
        <EngineBanner />
        {project && editing ? (
          <EditorScreen />
        ) : project ? (
          <ProjectScreen dragging={dragging} />
        ) : (
          <StartScreen dragging={dragging} onOpen={chooseAndOpen} />
        )}
      </div>
      <NewProjectDialog />
      <Toasts />
    </TooltipProvider>
  );
}
