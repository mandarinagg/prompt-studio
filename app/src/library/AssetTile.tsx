import type { AssetSummary } from "../engine/client";
import type { Thumb } from "../state/library";
import { Button } from "../ui/Button";
import { Icon } from "../ui/Icon";

interface Props {
  asset: AssetSummary;
  thumb: Thumb | undefined;
  selected: boolean;
  /** Es la foto que entra con Tab (foco móvil: solo una a la vez). */
  tabbable: boolean;
  onPick(mods: { ctrl: boolean; shift: boolean }): void;
  onOpen(): void;
  onFocusTile(): void;
  onRelink(): void;
}

/** El nombre que oye quien usa lector de pantalla: archivo + estado. */
export function tileName(a: AssetSummary): string {
  return `${a.file}${a.edited ? ", editada" : ""}${a.missing ? ", no se encuentra" : ""}`;
}

/** Una foto de la biblioteca: miniatura, nombre y estado (siempre con ícono y texto). */
export function AssetTile({ asset, thumb, selected, tabbable, onPick, onOpen, onFocusTile, onRelink }: Props) {
  const url = thumb?.url ?? null;
  return (
    <div className="tile-cell" role="presentation" data-asset-cell={asset.id}>
      <div
        role="option"
        aria-selected={selected}
        aria-label={tileName(asset)}
        tabIndex={tabbable ? 0 : -1}
        data-asset={asset.id}
        className={`tile ${selected ? "is-selected" : ""} ${asset.missing ? "is-missing" : ""}`}
        onClick={(e) => onPick({ ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey })}
        onDoubleClick={() => {
          if (!asset.missing) onOpen();
        }}
        onFocus={onFocusTile}
      >
        <div className="tile-thumb">
          {url ? (
            <img src={url} alt="" draggable={false} />
          ) : asset.missing ? (
            <Icon name="alert" size={28} />
          ) : (
            <span className="tile-placeholder" aria-hidden="true" />
          )}
        </div>
        <span className="tile-file" aria-hidden="true">
          {asset.file}
        </span>
        <span className="tile-badges" aria-hidden="true">
          {asset.edited && (
            <span className="badge tile-badge">
              <Icon name="check" size={12} /> Editada
            </span>
          )}
          {asset.missing && (
            <span className="badge badge-warn tile-badge">
              <Icon name="alert" size={12} /> No se encuentra
            </span>
          )}
        </span>
        {selected && (
          <span className="tile-check" aria-hidden="true">
            <Icon name="check" size={14} />
          </span>
        )}
      </div>
      {asset.missing && (
        <Button variant="secondary" className="tile-relink" onClick={onRelink}>
          Ubicar…
        </Button>
      )}
    </div>
  );
}
