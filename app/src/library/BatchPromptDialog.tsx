import { useId, useState } from "react";
import { Clarification, PlanNotes, PlanRows } from "../editor/PlanRows";
import { hasIncluded } from "../state/draft";
import { batchStore, useApp, useBatch } from "../state/store";
import { Button } from "../ui/Button";
import { Dialog } from "../ui/Dialog";

const photos = (n: number) => (n === 1 ? "1 foto" : `${n} fotos`);

/** El pedido y el plan; solo está montado mientras el diálogo está abierto. */
function Body() {
  const id = useId();
  const [text, setText] = useState("");
  const plan = useBatch((s) => s.plan);
  const thinking = plan?.status === "thinking";
  const ready = plan?.status === "ready" ? plan : null;
  const question = ready?.result?.plan?.clarification;
  const unsupported = ready?.result?.plan?.unsupported ?? [];
  const explanation = ready?.result?.plan?.explanation;

  return (
    <div className="batch-prompt">
      <label htmlFor={`${id}-text`} className="panel-title prompt-label">
        ¿Qué querés hacer?
      </label>
      <textarea
        id={`${id}-text`}
        className="input prompt-input"
        rows={2}
        maxLength={2000}
        autoFocus
        value={text}
        placeholder="Por ejemplo: más luz y colores vivos"
        aria-describedby={`${id}-hint`}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (text.trim() && !thinking) void batchStore.getState().ask(text);
          }
        }}
      />
      <p id={`${id}-hint`} className="field-hint">
        Enter para pedir · Shift+Enter, otra línea
      </p>
      {thinking && (
        <p className="plan-thinking-inline" role="status">
          Pensando…
        </p>
      )}
      {plan?.status === "error" && (
        <p className="field-error" role="alert">
          {plan.error}
        </p>
      )}
      {ready && (
        <section className="plan" aria-label="Plan propuesto">
          {question && <Clarification question={question} onAnswer={(t) => void batchStore.getState().answer(t)} />}
          {explanation && <p className="plan-explanation">{explanation}</p>}
          <PlanRows
            rows={ready.rows}
            showResult={false}
            onToggle={(i) => batchStore.getState().toggleRow(i)}
            onEdit={(i, v) => batchStore.getState().editRow(i, v)}
          />
          {!question && ready.rows.length === 0 && unsupported.length === 0 && (
            <p className="field-hint">No encontré ajustes para ese pedido. Probá con otras palabras.</p>
          )}
          <PlanNotes result={ready.result} />
        </section>
      )}
    </div>
  );
}

/** "Pedido para N fotos": se planifica una vez sobre la primera foto y se aplica a todas. */
export function BatchPromptDialog({ open, onOpenChange }: { open: boolean; onOpenChange(open: boolean): void }) {
  const count = useBatch((s) => s.targets.length);
  const reference = useBatch((s) => s.reference);
  const plan = useBatch((s) => s.plan);
  const referenceFile = useApp((s) => s.project?.assets.find((a) => a.id === reference)?.file);
  const canApply = hasIncluded(plan);

  const close = () => {
    batchStore.getState().cancel();
    onOpenChange(false);
  };
  const apply = async () => {
    if (await batchStore.getState().apply()) onOpenChange(false);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={count === 1 ? "Pedido para la foto" : `Pedido para ${photos(count)}`}
      description={`Se planifica con ${referenceFile ?? "la primera foto"} y se aplica a todas. Lo automático se ajusta en cada foto.`}
      footer={
        <>
          <Button variant="quiet" onClick={close}>
            Cancelar
          </Button>
          <Button variant="primary" disabled={!canApply} onClick={() => void apply()}>
            {count === 1 ? "Aplicar a la foto" : `Aplicar a las ${count}`}
          </Button>
        </>
      }
    >
      <Body />
    </Dialog>
  );
}
