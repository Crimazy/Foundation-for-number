"""Foundation plan / footing selection: parsers, selection logic and exports."""
import io

import pytest

from foundation import (
    FmatZone, assign_footings, build_joints, default_footing_table, footings_from_table, grid_label,
    parse_e2k, read_reactions, select_footing, summary_table, zone_loads,
)
from foundation_demo import demo_e2k, demo_reactions_xlsx


@pytest.fixture(scope="module")
def data():
    model = parse_e2k(demo_e2k())
    f = io.BytesIO(demo_reactions_xlsx())
    f.name = "rx.xlsx"
    rx, unit = read_reactions(f)
    joints = build_joints(model, rx, ["ASD_DL+SDL+LL"], unit)
    footings = footings_from_table(default_footing_table())
    zones = [FmatZone("FMAT1", "3", "3.4", "B", "C.1")]
    assigned = {k: assign_footings(joints, footings, k, zones, model) for k in (1, 2, 3, 4)}
    return model, rx, unit, joints, footings, zones, assigned


def test_parse_e2k(data):
    model = data[0]
    assert [g.label for g in model.x_grids][:3] == ["1", "2", "3"]
    assert [g.label for g in model.y_grids][-1] == "J.2"
    assert len(model.points) == 75
    assert model.combos["ASD_DL+SDL+LL"] == [("DL", 1.0), ("SDL", 1.0), ("LL", 1.0)]
    assert model.column_sections["C19"] == "C500x800"
    assert "10" in model.wall_points


def test_read_reactions(data):
    _, rx, unit, joints, *_ = data
    assert unit == "tonf"
    assert {"DL", "LL", "ASD_DL+SDL+LL"} <= set(rx["Case"])
    assert len(joints) == 75
    j = joints.set_index("Grid")
    assert j.loc["2/C", "P"] == pytest.approx(363.2)
    assert j.loc["2/C", "Element"] == "C500x800"
    assert j.loc["3/B", "Element"] == "Wall end"


def test_reactions_kn_and_envelope(data):
    model, rx, *_ = data
    r = rx.copy()
    r["FZ"] = r["FZ"] * 9.80665
    j = build_joints(model, r, ["DL", "ASD_DL+SDL+LL"], "kN").set_index("Grid")
    assert j.loc["2/A", "P"] == pytest.approx(204.9, abs=1e-6)     # envelope = max over cases


def test_grid_label_offset(data):
    model = data[0]
    assert grid_label(model, 16.23, 8.8) == "3.3-0.27/B.1"
    assert grid_label(model, 6.0, 0.0) == "2/A"


def test_select_footing_criteria(data):
    footings = data[4]
    # 6/B, P = 122.5 t: F3A fails with W under ทล.1 but passes Cap×1.05 under ทล.2
    assert select_footing(122.5, footings, 1)[0] == "F4A"
    assert select_footing(122.5, footings, 2)[0] == "F3A"
    assert select_footing(5000, footings, 1)[0].endswith("!")


def test_summary_matches_sample_sheet(data):
    *_, footings, zones, assigned = data
    s = summary_table(assigned, footings, [z.name for z in zones]).set_index("Footing")
    assert s.loc["รวม", "ฐาน ทล.1"] == 64 and s.loc["รวม", "เข็ม ทล.1"] == 229
    assert s.loc["รวม", "เข็ม ทล.2"] == 228
    assert s.loc["F4B", "ฐาน ทล.1"] == 34 and s.loc["F4D", "ฐาน ทล.1"] == 7
    assert s.loc["FMAT1", "ฐาน ทล.1"] == 11
    assert zone_loads(assigned[1], ["FMAT1"])["FMAT1"] == pytest.approx(1000.4, abs=0.2)


def test_override_and_ok_flag(data):
    model, _, _, joints, footings, zones, _ = data
    df = assign_footings(joints, footings, 1, zones, model, {"19": "F4A", "57": "FMAT1"})
    r = df.set_index("Joint")
    assert r.loc["19", "Footing"] == "F4A" and r.loc["19", "Source"] == "แก้ไข" and not r.loc["19", "OK"]
    assert r.loc["57", "Footing"] == "FMAT1"


def test_exports(data):
    from foundation_draw import build_dxf, build_pdf, dxf_segments, plotly_plan

    model, *_, footings, zones, assigned = data
    pdf = build_pdf(assigned, [1], model, footings, zones, "B6", "demo")
    assert pdf[:4] == b"%PDF"
    dxf = build_dxf(assigned, [1, 2], model, footings, zones, "B6")
    segs, layers = dxf_segments(dxf)
    assert "S-FOOTING" in layers and len(segs) > 100
    fig = plotly_plan(assigned[1], model, footings, zones)
    assert any(t.name == "joints" for t in fig.data)
