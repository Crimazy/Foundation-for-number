"""Footing schedule import from Excel / PDF / image."""
import io
import math

import pandas as pd
import pymupdf
from PIL import Image

from foundation import default_footing_table, footings_from_table
from foundation_schedule import complete_schedule, estimate_dims, merge_schedule, read_schedule_file


def _xlsx(rows):
    b = io.BytesIO()
    pd.DataFrame(rows).to_excel(b, header=False, index=False)
    return b.getvalue()


def test_excel_thai_headers_units():
    data = _xlsx([["ตารางฐานราก SS-02-01-01"], [],
                  ["เบอร์ฐาน", "จำนวนเข็ม", "ขนาดเข็ม (cm)", "กำลังรับน้ำหนัก (kN)", "ขนาดฐาน (m)", "ความหนา (cm)"],
                  ["F1A", 1, 26, 392.27, "0.60x0.60", 30],
                  ["F4B", "4-Ø300", None, 2353.6, "1.40x1.40", 75],
                  ["F6C", None, 35, 4118.8, None, None]])
    df, notes, imgs = read_schedule_file("s.xlsx", data)
    r = df.set_index("Footing")
    assert r.loc["F1A", "Pile D (mm)"] == 260 and r.loc["F1A", "Capacity (t)"] == 40.0
    assert (r.loc["F4B", "Piles"], r.loc["F4B", "Pile D (mm)"]) == (4, 300)
    assert (r.loc["F4B", "B (m)"], r.loc["F4B", "L (m)"], r.loc["F4B", "H (m)"]) == (1.4, 1.4, 0.75)
    assert r.loc["F6C", "Piles"] == 6 and r.loc["F6C", "B (m)"] > 0      # from mark + estimated size
    assert any("ประมาณขนาดฐาน" in n for n in notes) and imgs == []
    assert len(footings_from_table(df)) == 3


def test_excel_english_template_roundtrip():
    from foundation_schedule import template_xlsx
    base = default_footing_table()
    df, _, _ = read_schedule_file("t.xlsx", template_xlsx(base))
    assert df["Footing"].tolist() == base["Footing"].tolist()
    assert df["Color"].tolist() == base["Color"].tolist()
    assert df["B (m)"].tolist() == base["B (m)"].tolist()


def _pdf_with_table(data):
    doc = pymupdf.open()
    pg = doc.new_page()
    for i, r in enumerate(data):
        for j, c in enumerate(r):
            pg.draw_rect(pymupdf.Rect(40 + j * 75, 80 + i * 20, 40 + (j + 1) * 75, 80 + (i + 1) * 20))
            pg.insert_text((43 + j * 75, 94 + i * 20), c, fontsize=9)
    return doc.tobytes()


def test_pdf_table():
    data = [["Footing", "Piles", "Pile D (mm)", "Capacity (t)", "B (m)", "L (m)", "H (m)"],
            ["F3A", "3", "260", "120", "1.20", "1.10", "0.60"], ["F4C", "4", "350", "280", "1.60", "1.60", "0.85"]]
    df, notes, imgs = read_schedule_file("t.pdf", _pdf_with_table(data))
    r = df.set_index("Footing")
    assert r.loc["F3A", "B (m)"] == 1.2 and r.loc["F4C", "H (m)"] == 0.85 and len(imgs) == 1


def test_pdf_text_lines_and_scanned():
    doc = pymupdf.open()
    pg = doc.new_page()
    for k, t in enumerate(["FOOTING SCHEDULE", "F1A 1 260 40 0.60 0.60 0.30", "F6C 6-Ø350 420t 1.75 x 2.80 x 0.85"]):
        pg.insert_text((50, 72 + 18 * k), t)
    df, notes, _ = read_schedule_file("s.pdf", doc.tobytes())
    r = df.set_index("Footing")
    assert r.loc["F1A", "Capacity (t)"] == 40 and r.loc["F1A", "H (m)"] == 0.3
    assert (r.loc["F6C", "Piles"], r.loc["F6C", "Pile D (mm)"], r.loc["F6C", "L (m)"]) == (6, 350, 2.8)
    blank = pymupdf.open()
    blank.new_page()
    df2, notes2, imgs2 = read_schedule_file("scan.pdf", blank.tobytes())
    assert df2 is None and len(imgs2) == 1


def test_image_is_reference_only():
    b = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(b, "PNG")
    df, notes, imgs = read_schedule_file("ss.png", b.getvalue())
    assert df is None and len(imgs) == 1


def test_merge_keeps_colours_and_adds():
    base = default_footing_table()
    new, _ = complete_schedule(pd.DataFrame([{"Footing": "F4B", "Piles": 4, "Pile D (mm)": 300, "Capacity (t)": 250,
                                              "B (m)": 1.5, "L (m)": 1.5, "H (m)": 0.8},
                                             {"Footing": "F12X", "Piles": 12, "Pile D (mm)": 400,
                                              "Capacity (t)": 960}]))
    out = merge_schedule(base, new, replace=False).set_index("Footing")
    assert out.loc["F4B", "Capacity (t)"] == 250
    assert out.loc["F4B", "Color"] == base.set_index("Footing").loc["F4B", "Color"]
    assert "F12X" in out.index and len(out) == len(base) + 1
    assert merge_schedule(base, new, replace=True)["Footing"].tolist() == ["F4B", "F12X"]


def test_estimate_dims():
    assert estimate_dims(4, 300) == (1.5, 1.5, 0.7)
    b, l, h = estimate_dims(1, 260)
    assert b == l and not math.isnan(h)
