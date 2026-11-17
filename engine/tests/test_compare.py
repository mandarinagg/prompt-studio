from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest
import pyvips
from imaging import synthetic_rgb, to_vips

from pstudio import main
from pstudio.render import sha256_file

PLAN = {
    "operations": [{"op": "contrast", "amount": 15}],
    "explanation": "Más <contraste> & punch",
}
CROP_PLAN = {"operations": [{"op": "crop", "aspect_ratio": "1:1", "anchor": "center"}]}


def _photo(path: Path, w: int = 200, h: int = 150, seed: int = 0) -> Path:
    to_vips(synthetic_rgb(w, h, seed)).jpegsave(str(path))
    return path


def _plan(tmp_path: Path, data: dict = PLAN) -> Path:
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _run(*args: object) -> int:
    with pytest.raises(SystemExit) as e:
        main(["compare", *map(str, args)])
    return e.value.code


def test_report_one_comparison_per_input_and_error_card(tmp_path):
    a = _photo(tmp_path / "a.jpg")
    b = _photo(tmp_path / "b.jpg", seed=1)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"no soy una imagen")
    out = tmp_path / "out" / "informe.html"
    assert _run(_plan(tmp_path), a, b, bad, "-o", out) == 1
    page = out.read_text(encoding="utf-8")
    assert page.count('class="cmp split"') == 2
    assert page.count('class="card err"') == 1
    assert "bad.jpg" in page
    assert "Más &lt;contraste&gt; &amp; punch" in page
    assert "contrast" in page
    assert "http://" not in page and "https://" not in page
    assert page.count("data:image/jpeg;base64,") == 4


def test_different_aspect_is_side_by_side(tmp_path):
    a = _photo(tmp_path / "a.jpg")
    out = tmp_path / "i.html"
    assert _run(_plan(tmp_path, CROP_PLAN), a, "-o", out) == 0
    page = out.read_text(encoding="utf-8")
    assert 'class="cmp side"' in page and 'class="cmp split"' not in page


def test_filename_escaped_and_originals_untouched(tmp_path):
    weird = tmp_path / "<b>&.jpg"
    try:
        _photo(weird)
    except OSError, pyvips.Error:
        pytest.skip("el sistema de archivos no admite < > en nombres")
    folder = tmp_path / "fotos"
    folder.mkdir()
    ok = _photo(folder / "x.jpg")
    before = {p: sha256_file(p) for p in (weird, ok)}
    out = tmp_path / "i.html"
    assert _run(_plan(tmp_path), weird, folder, "-o", out) == 0
    page = out.read_text(encoding="utf-8")
    assert "&lt;b&gt;&amp;.jpg" in page and "<b>&.jpg" not in page
    assert {p: sha256_file(p) for p in before} == before
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        ["<b>&.jpg", "fotos", "i.html", "plan.json"]
    )


def test_refuses_overwrite_unless_flag(tmp_path):
    a = _photo(tmp_path / "a.jpg")
    out = tmp_path / "i.html"
    out.write_text("previo", encoding="utf-8")
    assert _run(_plan(tmp_path), a, "-o", out) == 2
    assert out.read_text(encoding="utf-8") == "previo"
    assert _run(_plan(tmp_path), a, "-o", out, "--overwrite") == 0
    assert "Comparación" in out.read_text(encoding="utf-8")


def test_refuses_output_equal_to_input(tmp_path):
    a = _photo(tmp_path / "a.jpg")
    h = sha256_file(a)
    assert _run(_plan(tmp_path), a, "-o", a, "--overwrite") == 2
    assert sha256_file(a) == h


def test_usage_errors(tmp_path):
    a = _photo(tmp_path / "a.jpg")
    out = tmp_path / "i.html"
    bad_plan = tmp_path / "bad.json"
    bad_plan.write_text('{"operations":[{"op":"nope"}]}', encoding="utf-8")
    assert _run(bad_plan, a, "-o", out) == 2
    assert _run(_plan(tmp_path), tmp_path / "falta.jpg", "-o", out) == 2
    empty = tmp_path / "vacia"
    empty.mkdir()
    assert _run(_plan(tmp_path), empty, "-o", out) == 2
    assert not out.exists()


def test_size_downscales_preview(tmp_path):
    a = _photo(tmp_path / "a.jpg", 400, 300)
    out = tmp_path / "i.html"
    assert _run(_plan(tmp_path), a, "--size", "100", "-o", out) == 0
    m = re.search(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", out.read_text(encoding="utf-8"))
    img = pyvips.Image.new_from_buffer(base64.b64decode(m.group(1)), "")
    assert max(img.width, img.height) == 100
