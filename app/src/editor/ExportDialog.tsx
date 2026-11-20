import { useId, useState } from "react";
import { call, type ExportParams } from "../engine/client";
import { appStore, useEditor } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";
import { resizeText } from "./PlanPanel";

type Preset = NonNullable<ExportParams["preset"]>;

/** Presets de docs/EXPORT_PRESETS.md con palabras de usuario (diseño §7). */
export const PRESETS: { id: Preset; title: string; detail: string }[] = [
  { id: "web", title: "Web — liviana para subir", detail: "WebP, lado largo 2048 px, sin ubicación" },
  { id: "catalog_square", title: "Cuadrada 1080 — catálogo", detail: "JPEG 1080×1080, recorte centrado" },
  { id: "social_vertical", title: "Vertical 4:5", detail: "JPEG 1080×1350, recorte centrado" },
  { id: "story_9x16", title: "Historia 9:16", detail: "JPEG 1080×1920, recorte centrado" },
  { id: "original", title: "Original", detail: "Mismo formato y tamaño que la foto" },
  { id: "high_quality", title: "Máxima calidad", detail: "Tamaño original, TIFF 16 bits o JPEG 95" },
];

function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

function message(err: unknown): string {
  const m = (err instanceof Error ? err.message : String(err)).trim();
  return /[.!?]$/.test(m) ? m : `${m}.`;
}

interface ExportDialogProps {
  open: boolean;
  onOpenChange(open: boolean): void;
}

/** Exportar la foto actual con un preset: una copia en Exportadas/, el original no se toca. */
export function ExportDialog({ open, onOpenChange }: ExportDialogProps) {
  const id = useId();
  const asset = useEditor((s) => s.asset);
  const hint = useEditor((s) => s.exportHint);
  const pendingPlan = useEditor((s) => s.plan !== null);
  const [preset, setPreset] = useState<Preset>("web");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);

  const run = async () => {
    if (!asset || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await call("asset.export", { asset: asset.id, preset });
      setLast(r.path);
      appStore.getState().notify("info", `Exportada: ${fileName(r.path)} (en ${r.out_dir})`);
      onOpenChange(false);
    } catch (err) {
      setError(`No se pudo exportar: ${message(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) setError(null);
        onOpenChange(o);
      }}
      title="Exportar"
      description="Se guarda una copia en la carpeta Exportadas, junto al proyecto. La foto original no se toca."
      footer={
        <>
          <Button variant="quiet" onClick={() => onOpenChange(false)}>
            Cancelar
          </Button>
          <Button variant="primary" onClick={run} disabled={busy || !asset}>
            {busy ? "Exportando…" : "Exportar"}
          </Button>
        </>
      }
    >
      <div className="form">
        <fieldset className="presets" disabled={busy}>
          <legend className="field-label">Cómo exportar {asset?.file}</legend>
          {PRESETS.map((p) => (
            <label key={p.id} className={`preset ${preset === p.id ? "is-on" : ""}`}>
              <input
                type="radio"
                name={`${id}-preset`}
                value={p.id}
                checked={preset === p.id}
                onChange={() => setPreset(p.id)}
              />
              <span className="preset-text">
                <span className="preset-title">{p.title}</span>
                <span className="preset-detail">{p.detail}</span>
              </span>
            </label>
          ))}
        </fieldset>
        {hint && (
          <p className="field-hint">
            El pedido sugiere achicar a {resizeText(hint)}. Elegí el preset que mejor se acerque.
          </p>
        )}
        {pendingPlan && (
          <p className="field-hint" role="note">
            El plan sin aplicar no se incluye.
          </p>
        )}
        {error && (
          <p className="field-error" role="alert">
            {error}
          </p>
        )}
        {last && !error && (
          <p className="field-hint">
            Última exportada: <span className="path selectable">{last}</span>
          </p>
        )}
      </div>
    </Dialog>
  );
}
