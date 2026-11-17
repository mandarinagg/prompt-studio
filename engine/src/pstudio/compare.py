"""Informe HTML antes/después (`pstudio compare`): herramienta de desarrollo y prueba.

Aplica un plan a reducciones de las fotos y arma UNA página HTML autocontenida (imágenes en
data URI, sin ninguna referencia externa). Nunca escribe junto a las entradas: solo el `-o`.
"""

from __future__ import annotations

import base64
import html
import time
from dataclasses import dataclass
from pathlib import Path

import pyvips

from pstudio.ops import apply_plan
from pstudio.render.io import decode
from pstudio.schema import EditPlan

JPEG_QUALITY = 85
SAME_ASPECT_TOLERANCE = 0.01  # diferencia relativa de proporción para usar el divisor


@dataclass
class Entry:
    name: str
    seconds: float = 0.0
    original_size: tuple[int, int] | None = None
    before: bytes | None = None
    after: bytes | None = None
    before_size: tuple[int, int] | None = None
    after_size: tuple[int, int] | None = None
    error: str | None = None


def to_jpeg(img: pyvips.Image) -> bytes:
    """scRGB lineal (o cualquier espacio) → JPEG sRGB de 8 bits; el alfa se aplana sobre blanco."""
    if img.hasalpha():
        img = img.flatten(background=[1.0, 1.0, 1.0] if img.format == "float" else [255])
    return img.colourspace("srgb").cast("uchar").jpegsave_buffer(Q=JPEG_QUALITY)


def render_entry(plan: EditPlan, source: Path, size: int) -> Entry:
    start = time.perf_counter()
    entry = Entry(name=source.name)
    try:
        img, info = decode(source)
        entry.original_size = (info.width, info.height)
        k = min(1.0, size / max(img.width, img.height))
        if k < 1.0:
            img = img.resize(k, kernel="lanczos3")
        out = apply_plan(img, plan, scale=k)
        entry.before, entry.before_size = to_jpeg(img), (img.width, img.height)
        entry.after, entry.after_size = to_jpeg(out), (out.width, out.height)
    except (OSError, ValueError, pyvips.Error) as e:
        entry.error = str(e)
        entry.before = entry.after = None
    entry.seconds = time.perf_counter() - start
    return entry


# ------------------------------------------------------------------ HTML
def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _uri(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _same_aspect(entry: Entry) -> bool:
    (bw, bh), (aw, ah) = entry.before_size, entry.after_size
    return abs(bw / bh - aw / ah) <= SAME_ASPECT_TOLERANCE * (bw / bh)


def _plan_html(plan: EditPlan) -> str:
    parts = []
    if plan.explanation:
        parts.append(f'<p class="expl">{_esc(plan.explanation)}</p>')
    if not plan.operations:
        parts.append("<p>El plan no tiene operaciones.</p>")
    else:
        items = []
        for op in plan.operations:
            params = op.model_dump(mode="json", exclude_none=True)
            name = params.pop("op")
            detail = ", ".join(f"{_esc(k)}={_esc(v)}" for k, v in params.items())
            items.append(f"<li><b>{_esc(name)}</b>{(' · ' + detail) if detail else ''}</li>")
        parts.append("<ol>" + "".join(items) + "</ol>")
    return "".join(parts)


def _entry_html(entry: Entry) -> str:
    name = _esc(entry.name)
    if entry.error is not None:
        return (
            f'<section class="card err"><h2>{name}</h2>'
            f"<p>No se pudo procesar: {_esc(entry.error)}</p></section>"
        )
    ow, oh = entry.original_size
    meta = f"{ow}×{oh} px originales · {entry.seconds:.2f} s"
    before, after = _uri(entry.before), _uri(entry.after)
    bw, bh = entry.before_size
    aw, ah = entry.after_size
    toggle = '<button type="button" class="tog">Antes / Después</button>'
    if _same_aspect(entry):
        figure = (
            f'<div class="cmp split" style="aspect-ratio:{aw}/{ah}">'
            f'<img class="a" src="{after}" alt="Después: {name}">'
            f'<img class="b" src="{before}" alt="Antes: {name}">'
            '<span class="lbl lb">Antes</span><span class="lbl la">Después</span>'
            '<div class="bar"></div></div>'
        )
    else:
        figure = (
            '<div class="cmp side">'
            f'<figure><img src="{before}" alt="Antes: {name}" width="{bw}" height="{bh}">'
            "<figcaption>Antes</figcaption></figure>"
            f'<figure><img src="{after}" alt="Después: {name}" width="{aw}" height="{ah}">'
            f"<figcaption>Después ({aw}×{ah})</figcaption></figure></div>"
        )
    return (
        f'<section class="card"><h2>{name}</h2><p class="meta">{meta}</p>{figure}'
        f"<p>{toggle}</p></section>"
    )


def build_html(plan: EditPlan, entries: list[Entry], size: int) -> str:
    return (
        TEMPLATE.replace("@@CSS@@", CSS)
        .replace("@@JS@@", JS)
        .replace("@@COUNT@@", str(len(entries)))
        .replace("@@SIZE@@", str(size))
        .replace("@@PLAN@@", _plan_html(plan))
        .replace("@@CARDS@@", "\n".join(_entry_html(e) for e in entries))
    )


def write_report(path: Path, content: str, *, inputs: list[Path], overwrite: bool) -> None:
    """Escribe el informe; se niega a pisar una entrada o un archivo existente sin `overwrite`."""
    for src in inputs:
        if path.exists() and src.is_file() and path.samefile(src):
            raise FileExistsError(f"{path.name} es una de las imágenes de entrada")
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} ya existe (usá --overwrite para reemplazarlo)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


CSS = """
:root{--bg:#f6f6f4;--fg:#1c1c1c;--card:#fff;--line:#d8d8d4;--acc:#2b6cb0;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#e8e8e6;--card:#222;--line:#3a3a3a;
--acc:#7db3ec;--err:#ff8a80}}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.05rem;margin:0 0 .2em;overflow-wrap:anywhere}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;
margin:0 0 16px}
.err{border-color:var(--err)}.err p{color:var(--err);overflow-wrap:anywhere}
.meta{margin:0 0 8px;opacity:.7;font-size:.85rem}
.expl{font-style:italic}ol{margin:.3em 0;padding-left:1.4em}li{overflow-wrap:anywhere}
.cmp img{display:block;width:100%;height:auto}
.split{position:relative;overflow:hidden;touch-action:pan-y;cursor:ew-resize;
user-select:none;background:var(--line);max-width:100%}
.split img{position:absolute;inset:0;height:100%;object-fit:fill;pointer-events:none}
.split .b{clip-path:inset(0 calc(100% - var(--p,50%)) 0 0)}
.bar{position:absolute;top:0;bottom:0;left:var(--p,50%);width:3px;margin-left:-1.5px;
background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,.5)}
.lbl{position:absolute;top:8px;padding:2px 8px;border-radius:4px;background:rgba(0,0,0,.6);
color:#fff;font-size:.75rem;pointer-events:none}.lb{left:8px}.la{right:8px}
.side{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:8px}
.side figure{margin:0}.side figcaption{font-size:.8rem;opacity:.7;text-align:center}
.side.one figure.off{display:none}
button{font:inherit;padding:6px 14px;border:1px solid var(--acc);border-radius:6px;
background:transparent;color:var(--acc);cursor:pointer}
button:hover{background:var(--acc);color:var(--bg)}
.hint{opacity:.7;font-size:.85rem}
"""

JS = """
(function(){
var cur=null;
function setP(c,x){var r=c.getBoundingClientRect();
var p=Math.max(0,Math.min(100,(x-r.left)/r.width*100));c.style.setProperty('--p',p+'%');}
document.querySelectorAll('.split').forEach(function(c){
var drag=false;
c.addEventListener('pointerdown',function(e){drag=true;c.setPointerCapture(e.pointerId);
setP(c,e.clientX);});
c.addEventListener('pointermove',function(e){if(drag)setP(c,e.clientX);});
c.addEventListener('pointerup',function(){drag=false;});
c.addEventListener('pointercancel',function(){drag=false;});
});
document.querySelectorAll('.card').forEach(function(s){
s.addEventListener('pointerenter',function(){cur=s;});});
function toggle(s){
var c=s.querySelector('.split');
if(c){var p=parseFloat(c.style.getPropertyValue('--p'));if(isNaN(p))p=50;
c.style.setProperty('--p',p>=99?'0%':'100%');return;}
var d=s.querySelector('.side');if(!d)return;
var f=d.querySelectorAll('figure');
if(!d.classList.contains('one')){d.classList.add('one');f[1].classList.add('off');}
else if(f[1].classList.contains('off')){f[1].classList.remove('off');f[0].classList.add('off');}
else{d.classList.remove('one');f[0].classList.remove('off');}
}
document.querySelectorAll('.tog').forEach(function(b){
b.addEventListener('click',function(){toggle(b.closest('.card'));});});
document.addEventListener('keydown',function(e){
if(e.code!=='Space'||/BUTTON|INPUT|TEXTAREA/.test(e.target.tagName))return;
var s=cur||document.querySelector('.card:not(.err) .cmp');
if(s){s=s.closest('.card');e.preventDefault();toggle(s);}
});
})();
"""

TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PROMPT STUDIO · Comparación antes/después</title>
<style>@@CSS@@</style></head><body><main>
<h1>Comparación antes/después</h1>
<p class="hint">@@COUNT@@ foto(s), vista reducida a @@SIZE@@ px de lado largo. Arrastrá el
divisor o usá «Antes / Después» (barra espaciadora sobre la foto).</p>
<section class="card"><h2>Plan</h2>@@PLAN@@</section>
@@CARDS@@
</main><script>@@JS@@</script></body></html>
"""
