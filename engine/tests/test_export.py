import json
import struct
from pathlib import Path

import numpy as np
import pytest
import pyvips
from imaging import ssim, synthetic_rgb, to_vips

from pstudio import main
from pstudio.export import (
    PRESETS,
    Box,
    apply_file,
    collect,
    preshrink_scale,
    resolve,
    run_batch,
)
from pstudio.ops import apply_plan
from pstudio.ops.geometry import output_size
from pstudio.render import OriginalProtectedError, decode, sha256_file
from pstudio.schema import EditPlan, Export

PLAN = EditPlan.model_validate(
    {"operations": [{"op": "exposure", "ev": 0.3}, {"op": "vibrance", "amount": 20}]}
)


def exif_with_gps() -> bytes:
    """EXIF mínimo: IFD0 con Make y un bloque GPS (latitud 40°26′ N)."""
    le = "<"
    ifd0_off, n0 = 8, 2
    make = b"TestCam\x00"
    make_off = ifd0_off + 2 + n0 * 12 + 4
    gps_off = make_off + len(make)
    lat_off = gps_off + 2 + 2 * 12 + 4
    ifd0 = struct.pack(le + "H", n0)
    ifd0 += struct.pack(le + "HHII", 0x010F, 2, len(make), make_off)
    ifd0 += struct.pack(le + "HHII", 0x8825, 4, 1, gps_off)
    ifd0 += struct.pack(le + "I", 0)
    gps = struct.pack(le + "H", 2)
    gps += struct.pack(le + "HHI", 0x0001, 2, 2) + b"N\x00\x00\x00"
    gps += struct.pack(le + "HHII", 0x0002, 5, 3, lat_off)
    gps += struct.pack(le + "I", 0)
    lat = struct.pack(le + "IIIIII", 40, 1, 26, 1, 0, 1)
    tiff = b"II*\x00" + struct.pack(le + "I", ifd0_off)
    return b"Exif\x00\x00" + tiff + ifd0 + make + gps + lat


def write_photo(path: Path, w: int = 96, h: int = 64, gps: bool = False, **save) -> Path:
    img = to_vips(synthetic_rgb(w, h, seed=5))
    if gps:
        img = img.copy()
        img.set_type(pyvips.GValue.blob_type, "exif-data", exif_with_gps())
    path.parent.mkdir(parents=True, exist_ok=True)
    img.write_to_file(str(path), **save)
    return path


def fields(path: Path) -> list[str]:
    return pyvips.Image.new_from_file(str(path), revalidate=True).get_fields()


# ------------------------------------------------------------------ resolución de ajustes
def info_of(tmp_path: Path, name: str = "f.jpg", **kw):
    return decode(write_photo(tmp_path / name, **kw))[1]


def test_precedence_cli_over_plan_over_preset(tmp_path):
    info = info_of(tmp_path)
    s = resolve(info, None, None)
    assert (s.preset, s.format, s.quality, s.metadata) == ("original", "jpeg", 100, "keep")
    plan = Export(preset="web", quality=70)
    s = resolve(info, plan, None)
    assert (s.preset, s.format, s.quality, s.metadata) == ("web", "webp", 70, "strip_gps")
    s = resolve(info, plan, Export(format="png", metadata="strip"))
    assert (s.format, s.quality, s.metadata) == ("png", 70, "strip")
    s = resolve(info, plan, Export(preset="catalog_square"))
    assert (s.preset, s.format, s.quality) == ("catalog_square", "jpeg", 70)  # quality del plan


def test_original_and_high_quality_follow_the_source(tmp_path):
    png16 = tmp_path / "g16.png"
    to_vips((synthetic_rgb(32, 24).astype(np.uint16) * 257), "rgb16").write_to_file(str(png16))
    info16 = decode(png16)[1]
    assert resolve(info16, Export(preset="original"), None).format == "png"
    assert resolve(info16, Export(preset="original"), None).depth == 16
    s = resolve(info16, Export(preset="high_quality"), None)
    assert (s.format, s.depth) == ("tiff", 16)
    s = resolve(info_of(tmp_path), Export(preset="high_quality"), None)
    assert (s.format, s.quality, s.depth) == ("jpeg", 95, 8)


# ------------------------------------------------------------------ presets
@pytest.mark.parametrize(
    ("preset", "size", "want"),
    [
        ("web", (3000, 2000), (2048, 1365)),
        ("web", (900, 600), (900, 600)),  # nunca agranda
        ("catalog_square", (300, 200), (1080, 1080)),
        ("social_vertical", (3000, 2000), (1080, 1350)),
        ("story_9x16", (3000, 2000), (1080, 1920)),
        ("original", (300, 200), (300, 200)),
    ],
)
def test_preset_sizes(tmp_path, preset, size, want):
    src = write_photo(tmp_path / "in.jpg", *size)
    r = apply_file(PLAN, src, tmp_path / "out" / "in", cli=Export(preset=preset))
    out = pyvips.Image.new_from_file(str(r.dest), revalidate=True)
    assert abs(out.width - want[0]) <= 1 and abs(out.height - want[1]) <= 1
    assert r.dest.suffix == {"webp": ".webp", "jpeg": ".jpg"}[r.settings.format]


def test_presets_table_matches_docs():
    doc = (Path(__file__).resolve().parents[2] / "docs" / "EXPORT_PRESETS.md").read_text("utf-8")
    for name in PRESETS:
        assert f"`{name}`" in doc


# ------------------------------------------------------------------ metadatos
@pytest.mark.parametrize(
    ("metadata", "gps", "make"),
    [("keep", True, True), ("strip_gps", False, True), ("strip", False, False)],
)
def test_metadata_modes(tmp_path, metadata, gps, make):
    src = write_photo(tmp_path / "gps.jpg", gps=True)
    assert "exif-ifd3-GPSLatitude" in fields(src)
    r = apply_file(
        PLAN, src, tmp_path / "out" / "gps", cli=Export(metadata=metadata, format="jpeg")
    )
    f = fields(r.dest)
    assert any(x.startswith("exif-ifd3-") for x in f) == gps
    assert ("exif-ifd0-Make" in f) == make
    if not gps:
        assert b"\x00N\x00\x00" not in r.dest.read_bytes()[:4096] or not make


def test_web_preset_strips_location_by_default(tmp_path):
    src = write_photo(tmp_path / "gps.jpg", gps=True)
    r = apply_file(PLAN, src, tmp_path / "out" / "gps", cli=Export(preset="web"))
    assert not any(x.startswith("exif-ifd3-") for x in fields(r.dest))


# ------------------------------------------------------------------ originales intocables
def test_never_writes_over_the_input(tmp_path):
    src = write_photo(tmp_path / "foto.jpg")
    before = sha256_file(src)
    with pytest.raises(OriginalProtectedError):
        apply_file(PLAN, src, tmp_path / "foto", overwrite=True)  # mismo nombre y formato
    assert sha256_file(src) == before


def test_existing_export_needs_overwrite(tmp_path):
    src = write_photo(tmp_path / "foto.jpg")
    apply_file(PLAN, src, tmp_path / "out" / "foto")
    with pytest.raises(FileExistsError):
        apply_file(PLAN, src, tmp_path / "out" / "foto")
    apply_file(PLAN, src, tmp_path / "out" / "foto", overwrite=True)


# ------------------------------------------------------------------ lote
def make_folder(root: Path) -> Path:
    src = root / "fotos"
    write_photo(src / "a.jpg")
    write_photo(src / "b.png")
    write_photo(src / "b.jpg")  # mismo nombre que b.png
    write_photo(src / "sub" / "c.webp")
    (src / "notas.txt").write_text("no es una imagen", "utf-8")
    (src / "rota.jpg").write_bytes(b"\xff\xd8 no es un JPEG de verdad")
    return src


def test_collect_folder(tmp_path):
    src = make_folder(tmp_path)
    batch = collect([src], tmp_path / "out")
    names = sorted(j.dest.name for j in batch.jobs)
    assert names == ["a", "b_jpg", "b_png", "rota"]
    assert [p.name for p in batch.skipped] == ["notas.txt"]
    deep = collect([src], tmp_path / "out", recursive=True)
    assert tmp_path / "out" / "sub" / "c" in [j.dest for j in deep.jobs]


def test_batch_keeps_going_after_an_error_and_leaves_originals_alone(tmp_path):
    src = make_folder(tmp_path)
    hashes = {p: sha256_file(p) for p in src.rglob("*") if p.is_file()}
    results = run_batch(PLAN, collect([src], tmp_path / "out"), cli=Export(preset="web"))
    ok = [r for r in results if not r.error]
    bad = [r for r in results if r.error]
    assert len(ok) == 3 and [r.source.name for r in bad] == ["rota.jpg"]
    assert all(r.dest.suffix == ".webp" and r.dest.exists() for r in ok)
    assert {p: sha256_file(p) for p in hashes} == hashes


def test_batch_into_the_same_folder_never_touches_originals(tmp_path):
    src = tmp_path / "fotos"
    a = write_photo(src / "a.jpg")
    before = sha256_file(a)
    results = run_batch(PLAN, collect([src], src), cli=Export(format="jpeg"))
    assert "original" in results[0].error
    assert sha256_file(a) == before
    results = run_batch(PLAN, collect([src], src), cli=Export(format="png"))
    assert results[0].error is None and (src / "a.png").exists()


# ------------------------------------------------------------------ achicar antes del plan
GEOM = EditPlan.model_validate(
    {
        "operations": [
            {"op": "straighten", "degrees": 4},
            {"op": "crop", "aspect_ratio": "4:5"},
            {"op": "rotate", "degrees": 90},
            {"op": "resize", "width": 500},
        ]
    }
)


def test_output_size_predicts_the_plan_geometry():
    img = to_vips(synthetic_rgb(600, 400)).colourspace("scrgb")
    for plan in [GEOM, EditPlan.model_validate({"operations": [{"op": "rotate", "degrees": 30}]})]:
        out = apply_plan(img, plan)
        w, h = output_size(600, 400, plan.operations)
        assert abs(out.width - w) <= 2 and abs(out.height - h) <= 2


def test_preshrink_scale():
    assert preshrink_scale(6000, 4000, PLAN, None) == 1.0
    assert preshrink_scale(2400, 1600, PLAN, Box(long_side=2048)) == 1.0  # casi no achica
    k = preshrink_scale(6000, 4000, PLAN, Box(long_side=2048))
    assert k == pytest.approx(2048 * 1.25 / 6000)
    k = preshrink_scale(6000, 4000, PLAN, Box(width=1080, height=1080))
    assert k == pytest.approx(1080 / 4000 * 1.25)


def test_preshrunk_export_matches_full_processing(tmp_path):
    src = write_photo(tmp_path / "big.png", 1600, 1200)
    plan = EditPlan.model_validate(
        {"operations": [{"op": "sharpen", "amount": 50}, {"op": "contrast", "amount": 20}]}
    )
    r = apply_file(plan, src, tmp_path / "out" / "big", cli=Export(preset="web", format="png"))
    assert r.settings.box == Box(long_side=2048)  # 1600 px: no hace falta achicar
    r = apply_file(plan, src, tmp_path / "out" / "sq", cli=Export(preset="catalog_square",
                                                                   format="png"))  # fmt: skip
    img, _ = decode(src)
    from pstudio.export import fit_box

    full = fit_box(apply_plan(img, plan), PRESETS["catalog_square"].box)
    got = pyvips.Image.new_from_file(str(r.dest), revalidate=True).numpy()
    want = full.colourspace("srgb").numpy()
    assert got.shape == want.shape
    assert ssim(got, want) > 0.97


# ------------------------------------------------------------------ CLI
def run_cli(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out, err = capsys.readouterr()
    return exc.value.code, out, err


def test_cli_apply(tmp_path, capsys):
    src = make_folder(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"operations": [{"op": "saturation", "amount": 20}]}), "utf-8")
    code, out, err = run_cli(["apply", str(plan), str(src), "-o", str(tmp_path / "o"),
                              "--preset", "web"], capsys)  # fmt: skip
    assert code == 1  # rota.jpg falla, el resto sale
    assert "3/4 exportadas" in out and "rota.jpg" in err and "notas.txt" in err

    one = src / "a.jpg"
    code, out, _ = run_cli(["apply", str(plan), str(one), "-o", str(tmp_path / "p"),
                            "--format", "png"], capsys)  # fmt: skip
    assert code == 0 and (tmp_path / "p" / "a.png").exists()

    bad = tmp_path / "mal.json"
    bad.write_text(json.dumps({"operations": [{"op": "eval"}]}), "utf-8")
    assert run_cli(["apply", str(bad), str(one), "-o", str(tmp_path / "q")], capsys)[0] == 2
    assert run_cli(["apply", str(plan), str(tmp_path / "nada.jpg"), "-o", "x"], capsys)[0] == 2
    code, _, err = run_cli(["apply", str(plan), str(one), "-o", "x", "--quality", "0"], capsys)
    assert code == 2 and "inválidas" in err
