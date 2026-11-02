"""Import the footing schedule (pile-cap types) from Excel / CSV / PDF, or show an image for manual entry.

The result is always a table with the columns of ``foundation.FOOTING_COLUMNS``::

    Footing | Piles | Pile D (mm) | Capacity (t) | B (m) | L (m) | H (m) | Color

* Excel / CSV: the header row is found automatically (Thai or English headers, units in brackets
  such as ``(mm)``, ``(cm)``, ``(kN)`` are converted).
* PDF with real text: tables are read with PyMuPDF; if no table is found, every text line that
  starts with a footing mark (``F4B``, ``F-1``, ``PC6`` …) is read as a row.
* Scanned PDF / image: there is no text to read — the page is shown next to the table so the
  values can be typed in.

Missing values are filled where possible (number of piles from the mark ``F4B`` → 4, B × L × H
estimated from the pile layout) and reported, so the table can be checked before use.
"""
from __future__ import annotations

import io
import math
import re

import pandas as pd

from foundation import FOOTING_COLUMNS, KN_PER_TONF

PALETTE = ["#8ecae6", "#219ebc", "#126782", "#023047", "#a7c957", "#ffd166", "#f8961e", "#f3722c",
           "#d62828", "#b5179e", "#7209b7", "#560bad", "#3a0ca3", "#3f37c9", "#4361ee", "#4cc9f0",
           "#2a9d8f", "#e76f51", "#6d597a", "#b56576"]

# key -> header words (matched against the header text without units / punctuation)
ALIASES = {
    "name": ["footing", "footingtype", "type", "mark", "name", "เบอร์", "เบอร์ฐาน", "เบอร์ฐานราก", "ฐานราก",
             "ชนิดฐานราก", "ชื่อ", "ชื่อฐานราก", "รหัส", "pilecap", "cap type", "f"],
    "BL": ["ขนาดฐาน", "ขนาดฐานราก", "bxl", "b×l", "bxlxh", "b×l×h", "footingsize", "capsize", "dimension",
           "dimensions", "ขนาดฐานกว้างxยาว"],
    "piles": ["piles", "pile", "no.ofpiles", "noofpiles", "nopiles", "numberofpiles", "n", "npile", "จำนวนเข็ม",
              "เข็ม/ฐาน", "เข็มต่อฐาน", "เข็ม", "จำนวน"],
    "dia": ["piled", "piledia", "pilediameter", "pilesize", "dia", "diameter", "d", "size", "ขนาดเข็ม",
            "เส้นผ่านศูนย์กลาง", "เส้นผ่าศูนย์กลาง", "ø", "φ", "ขนาด"],
    "cap": ["capacity", "cap", "safeload", "sl", "pallow", "allowableload", "load", "กำลัง", "รับน้ำหนัก",
            "น้ำหนักบรรทุก", "น้ำหนักบรรทุกปลอดภัย", "กำลังรับน้ำหนัก", "กำลังรับ"],
    "B": ["b", "width", "กว้าง", "ความกว้าง"],
    "L": ["l", "length", "ยาว", "ความยาว"],
    "H": ["h", "t", "thk", "thick", "thickness", "depth", "หนา", "ความหนา", "ความลึก"],
    "color": ["color", "colour", "สี"],
}
TARGET = {"name": "Footing", "piles": "Piles", "dia": "Pile D (mm)", "cap": "Capacity (t)",
          "B": "B (m)", "L": "L (m)", "H": "H (m)", "color": "Color"}

MARK_RE = re.compile(r"^\s*([A-Za-z]{1,4}[-_ ]?\d{1,2}[A-Za-z]{0,2}\d?)\b")
NUM_RE = re.compile(r"(?<![A-WYZa-wyz])\d+(?:[.,]\d+)?")


def _norm(h) -> tuple[str, str]:
    """(header without unit, unit text) — both lower case, no spaces."""
    s = str(h or "").strip().lower()
    unit = " ".join(re.findall(r"[\(\[]([^\)\]]*)[\)\]]", s))
    base = re.sub(r"[\(\[][^\)\]]*[\)\]]", "", s)
    base = re.sub(r"[\s\.:,_\-]+", "", base)
    return base, unit.replace(" ", "")


def _match_headers(headers: list) -> dict[str, int]:
    found: dict[str, int] = {}
    normed = [_norm(h)[0] for h in headers]
    # exact matches first, then "starts with" for longer aliases
    for key, words in ALIASES.items():
        w = [re.sub(r"[\s\.:,_\-]+", "", x) for x in words]
        for i, n in enumerate(normed):
            if n and n in w and i not in found.values():
                found[key] = i
                break
    for key, words in ALIASES.items():
        if key in found:
            continue
        w = [re.sub(r"[\s\.:,_\-]+", "", x) for x in words if len(x) >= 3]
        for i, n in enumerate(normed):
            if n and i not in found.values() and any(n.startswith(x) for x in w):
                found[key] = i
                break
    return found


def _num(v) -> float:
    if v is None:
        return math.nan
    if isinstance(v, (int, float)):
        return float(v)
    m = NUM_RE.search(str(v))
    return float(m.group(0).replace(",", ".")) if m else math.nan


def _to_mm(v: float, unit: str) -> float:
    if math.isnan(v):
        return v
    if "mm" in unit:
        return v
    if "cm" in unit:
        return v * 10
    if unit in ("m",) or v <= 2.0:
        return v * 1000
    if v <= 100:          # bare number like 30 / 35 / 40 → cm
        return v * 10
    return v


def _to_m(v: float, unit: str) -> float:
    if math.isnan(v):
        return v
    if "mm" in unit:
        return v / 1000
    if "cm" in unit:
        return v / 100
    if v > 20:            # bare number in mm
        return v / 1000
    return v


def _to_t(v: float, unit: str) -> float:
    if math.isnan(v):
        return v
    if "kn" in unit:
        return round(v / KN_PER_TONF, 2)
    if "kg" in unit:
        return v / 1000
    return v


def _pile_spec(text: str) -> tuple[float, float]:
    """'4-Ø300', '4×0.30', '6 ต้น ø350 mm' → (piles, dia mm)."""
    s = str(text)
    m = re.search(r"(\d+)\s*(?:[x×*\-]|ต้น)\s*(?:[øØφD]|dia\.?)?\s*(\d+(?:\.\d+)?)", s)
    if m:
        return float(m.group(1)), _to_mm(float(m.group(2)), "")
    return _num(s), math.nan


def table_to_schedule(rows: list[list], header_row: int | None = None) -> tuple[pd.DataFrame | None, list[str]]:
    """Convert a raw 2-D table (first rows may be titles) to the schedule columns."""
    notes: list[str] = []
    if header_row is None:
        best, best_n = None, 0
        for i, r in enumerate(rows[:20]):
            n = len(_match_headers(r))
            if n > best_n and "name" in _match_headers(r):
                best, best_n = i, n
        if best is None or best_n < 2:
            return None, ["ไม่พบหัวตาราง (ต้องมีคอลัมน์เบอร์ฐานราก และอย่างน้อยอีก 1 คอลัมน์ เช่น จำนวนเข็ม / Capacity)"]
        header_row = best
    headers = rows[header_row]
    cols = _match_headers(headers)
    units = {k: _norm(headers[i])[1] for k, i in cols.items()}
    out = []
    for r in rows[header_row + 1:]:
        if not r or cols["name"] >= len(r):
            continue
        name = str(r[cols["name"]] or "").strip()
        if not name or name.lower() in ("nan", "none") or not re.search(r"\d", name):
            continue
        rec = {"Footing": name.replace(" ", "")}

        def get(k):
            i = cols.get(k)
            return r[i] if i is not None and i < len(r) else None

        piles, dia = math.nan, math.nan
        if "piles" in cols:
            piles, dia = _pile_spec(get("piles"))
        if "dia" in cols:
            d = _num(get("dia"))
            dia = _to_mm(d, units.get("dia", "")) if not math.isnan(d) else dia
        rec["Piles"] = piles
        rec["Pile D (mm)"] = dia
        rec["Capacity (t)"] = _to_t(_num(get("cap")), units.get("cap", "")) if "cap" in cols else math.nan
        for k in ("B", "L", "H"):
            rec[TARGET[k]] = _to_m(_num(get(k)), units.get(k, "")) if k in cols else math.nan
        if "BL" in cols:      # "1.40x1.40" or "1400×1400×750"
            vals = [float(x.replace(",", ".")) for x in NUM_RE.findall(str(get("BL") or ""))]
            for k, v in zip(("B (m)", "L (m)", "H (m)"), vals[:3]):
                if math.isnan(rec[k]):
                    rec[k] = _to_m(v, units.get("BL", ""))
        if "color" in cols and re.match(r"^#?[0-9a-fA-F]{6}$", str(get("color") or "").strip()):
            c = str(get("color")).strip()
            rec["Color"] = c if c.startswith("#") else "#" + c
        out.append(rec)
    if not out:
        return None, ["พบหัวตารางแต่ไม่มีแถวข้อมูลฐานราก"]
    used = ", ".join(TARGET.get(k, "B×L") for k in cols)
    notes.append(f"อ่านคอลัมน์: {used}")
    return pd.DataFrame(out), notes


def _lines_to_schedule(lines: list[str]) -> pd.DataFrame | None:
    """Fallback for PDFs without a detectable table: rows that start with a footing mark."""
    out = []
    for line in lines:
        m = MARK_RE.match(line)
        if not m:
            continue
        name = re.sub(r"[\s_]", "", m.group(1))
        rest = line[m.end():]
        piles, dia = _pile_spec(rest) if re.search(r"\d+\s*[x×\-]\s*[øØφD]?\s*\d", rest) else (math.nan, math.nan)
        nums = [float(x.replace(",", ".")) for x in NUM_RE.findall(rest)]
        if len(nums) < 2:
            continue
        rec = {"Footing": name, "Piles": piles, "Pile D (mm)": dia, "Capacity (t)": math.nan,
               "B (m)": math.nan, "L (m)": math.nan, "H (m)": math.nan}
        if len(nums) >= 6 and math.isnan(piles):
            # template order: piles, D, capacity, B, L, H
            rec.update({"Piles": nums[0], "Pile D (mm)": _to_mm(nums[1], ""), "Capacity (t)": nums[2],
                        "B (m)": _to_m(nums[3], ""), "L (m)": _to_m(nums[4], ""), "H (m)": _to_m(nums[5], "")})
        else:
            if not math.isnan(piles):       # drop the numbers of the pile spec itself
                nums = nums[2:]
            small = [v for v in nums if v < 10 and v != int(v)] or [v for v in nums if v < 10]
            ints = [v for v in nums if v == int(v)]
            if math.isnan(rec["Piles"]):
                cand = [v for v in ints if 1 <= v <= 30]
                rec["Piles"] = cand[0] if cand else math.nan
            if math.isnan(rec["Pile D (mm)"]):
                cand = [v for v in ints if 150 <= v <= 1500]
                rec["Pile D (mm)"] = cand[0] if cand else math.nan
            big = [v for v in nums if v >= 10 and v not in (rec["Piles"], rec["Pile D (mm)"])]
            rec["Capacity (t)"] = big[0] if big else math.nan
            dims = [v for v in small if v not in (rec["Piles"],)]
            if len(dims) >= 3:
                rec["B (m)"], rec["L (m)"], rec["H (m)"] = dims[:3]
            elif len(dims) == 2:
                rec["B (m)"], rec["L (m)"], rec["H (m)"] = dims[0], dims[0], dims[1]
        out.append(rec)
    return pd.DataFrame(out) if out else None


# --------------------------------------------------------------------------
# Completing missing values
# --------------------------------------------------------------------------
def piles_from_mark(name: str) -> float:
    m = re.search(r"[A-Za-z]+[-_]?(\d{1,2})", str(name))
    return float(m.group(1)) if m else math.nan


def estimate_dims(piles: int, dia_mm: float) -> tuple[float, float, float]:
    """Rough pile-cap size: spacing 3D, edge 1D from pile centre (rounded up to 5 cm)."""
    d = dia_mm / 1000
    s, e = 3 * d, d
    up = lambda v: math.ceil(v / 0.05 - 1e-9) * 0.05  # noqa: E731
    if piles <= 1:
        b = l = up(d + 2 * max(0.15, d / 2))
    elif piles == 2:
        b, l = up(s + 2 * e), up(2 * e)
    elif piles == 3:
        b, l = up(s + 2 * e), up(s * math.sqrt(3) / 2 + 2 * e)
    elif piles in (4, 5):
        b = l = up(s + 2 * e)
    elif piles == 6:
        b, l = up(s + 2 * e), up(2 * s + 2 * e)
    else:
        k = math.ceil(math.sqrt(piles))
        b = l = up((k - 1) * s + 2 * e)
    h = up(max(0.3, 0.5 * s + 0.25)) if piles > 1 else up(max(0.3, 1.2 * d))
    return round(b, 2), round(l, 2), round(h, 2)


def complete_schedule(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Fill what can be inferred; returns notes about every filled / still-missing value."""
    notes = []
    out = df.copy()
    for c in FOOTING_COLUMNS:
        if c not in out:
            out[c] = math.nan if c != "Color" else None
    out = out[FOOTING_COLUMNS]
    for i, r in out.iterrows():
        name = r["Footing"]
        if pd.isna(r["Piles"]):
            p = piles_from_mark(name)
            if not math.isnan(p):
                out.at[i, "Piles"] = p
                notes.append(f"{name}: จำนวนเข็ม = {p:g} (จากชื่อเบอร์)")
        if any(pd.isna(r[c]) for c in ("B (m)", "L (m)", "H (m)")) and pd.notna(out.at[i, "Piles"]) \
                and pd.notna(r["Pile D (mm)"]):
            b, l, h = estimate_dims(int(out.at[i, "Piles"]), float(r["Pile D (mm)"]))
            for c, v in (("B (m)", b), ("L (m)", l), ("H (m)", h)):
                if pd.isna(r[c]):
                    out.at[i, c] = v
            notes.append(f"{name}: ประมาณขนาดฐาน {b:.2f}×{l:.2f}×{h:.2f} m (ไม่มีในไฟล์ — ควรตรวจ)")
        if not isinstance(r["Color"], str) or not r["Color"].startswith("#"):
            out.at[i, "Color"] = PALETTE[i % len(PALETTE)]
        missing = [c for c in ("Piles", "Pile D (mm)", "Capacity (t)") if pd.isna(out.at[i, c])]
        if missing:
            notes.append(f"{name}: ยังไม่มี {', '.join(missing)} — กรอกเพิ่มในตาราง")
    out = out.drop_duplicates(subset="Footing", keep="first").reset_index(drop=True)
    return out, notes


# --------------------------------------------------------------------------
# File readers
# --------------------------------------------------------------------------
def _read_pdf(data: bytes) -> tuple[pd.DataFrame | None, list[str], list]:
    import pymupdf
    from PIL import Image

    doc = pymupdf.open(stream=data, filetype="pdf")
    frames, notes, images, lines = [], [], [], []
    for pno, page in enumerate(doc):
        if pno < 10:
            pix = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6))
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
        try:
            for t in page.find_tables().tables:
                if t.col_count > 30:          # grid lines of a plan, not a schedule
                    continue
                fast = [[c or "" for c in r] for r in t.extract()]
                if not any("name" in _match_headers(r) and len(_match_headers(r)) >= 2 for r in fast[:20]):
                    continue
                # text inside each cell box (more reliable than Table.extract() for decimals)
                rows = [[page.get_textbox(pymupdf.Rect(c)).strip().replace("\n", " ") if c else "" for c in row.cells]
                        for row in t.rows]
                df, _ = table_to_schedule(rows)
                if df is not None:
                    frames.append(df)
        except Exception:  # noqa: BLE001  (old PyMuPDF without find_tables)
            pass
        lines += page.get_text("text").splitlines()
    if not "".join(lines).strip() and not frames:
        return None, ["PDF ไม่มีข้อความ (เป็นภาพสแกน) — ดูรูปด้านข้างแล้วกรอกตารางเอง"], images
    by_lines = _lines_to_schedule(lines)
    if frames:
        df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="Footing", keep="first")
        notes.append(f"อ่านจากตารางใน PDF ({len(frames)} ตาราง)")
        if by_lines is not None:      # fill gaps from text such as a legend "F4B (4×300 mm, 240 t)"
            extra = by_lines.drop_duplicates(subset="Footing").set_index("Footing")
            df = df.set_index("Footing")
            before = int(df.isna().sum().sum())
            for c in ("Piles", "Pile D (mm)", "Capacity (t)", "B (m)", "L (m)", "H (m)"):
                if c in extra:
                    df[c] = df[c].fillna(extra[c].reindex(df.index))
            df = df.reset_index()
            if int(df.isna().sum().sum()) < before:
                notes.append("เติมค่าที่ขาดจากข้อความในหน้าอื่นของ PDF (เช่น คำอธิบายสัญลักษณ์) — ควรตรวจ")
        return df, notes, images
    if by_lines is not None:
        notes.append("ไม่พบเส้นตารางใน PDF — อ่านจากบรรทัดที่ขึ้นต้นด้วยเบอร์ฐาน (ควรตรวจทุกช่อง)")
        return by_lines, notes, images
    return None, ["ไม่พบข้อมูลเบอร์ฐานรากในข้อความของ PDF — ดูรูปด้านข้างแล้วกรอกตารางเอง"], images


def read_schedule_file(name: str, data: bytes) -> tuple[pd.DataFrame | None, list[str], list]:
    """Returns (schedule or None, notes, reference images)."""
    low = name.lower()
    if low.endswith(".pdf"):
        df, notes, images = _read_pdf(data)
    elif low.endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff")):
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
        return None, ["รูปภาพ: แสดงไว้ข้างตารางเพื่อกรอกค่าตามรูป (ยังอ่านตัวเลขจากรูปอัตโนมัติไม่ได้)"], [img.convert("RGB")]
    else:
        if low.endswith((".csv", ".txt")):
            sheets = {"csv": pd.read_csv(io.BytesIO(data), header=None, dtype=object)}
        else:
            sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
        df, notes = None, []
        for sname, raw in sheets.items():
            rows = raw.where(pd.notna(raw), None).values.tolist()
            d, n = table_to_schedule(rows)
            if d is not None:
                df, notes = d, [f"แผ่นงาน '{sname}'"] + n
                break
            notes = n
        images = []
    if df is None:
        return None, notes, images
    df, more = complete_schedule(df)
    return df, notes + more, images


def merge_schedule(current: pd.DataFrame, new: pd.DataFrame, replace: bool) -> pd.DataFrame:
    if replace:
        return new.reset_index(drop=True)
    cur = current.set_index("Footing")
    nw = new.set_index("Footing")
    used = set(cur["Color"].astype(str))
    free = [c for c in PALETTE if c not in used]
    for name, r in nw.iterrows():
        r = r.copy()
        if name in cur.index and isinstance(cur.at[name, "Color"], str) and cur.at[name, "Color"].startswith("#"):
            r["Color"] = cur.at[name, "Color"]          # keep the colour already used on the plan
        elif r.get("Color") in used and free:
            r["Color"] = free.pop(0)
        cur.loc[name] = r
        used.add(str(r["Color"]))
    out = cur.reset_index()[FOOTING_COLUMNS]
    return out.sort_values(["Capacity (t)", "Piles"], na_position="last").reset_index(drop=True)


def template_xlsx(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="Footing Schedule", index=False)
        ws = xw.sheets["Footing Schedule"]
        for col, w in zip("ABCDEFGH", (10, 8, 12, 13, 8, 8, 8, 10)):
            ws.column_dimensions[col].width = w
    return bio.getvalue()
