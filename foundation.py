"""Foundation plan & footing selection (pile caps) from ETABS output.

Inputs
------
* ``.e2k``  (ETABS text model): grid lines, point coordinates, columns/walls,
  load patterns and load combinations.
* Excel "Joint Reactions" table exported from ETABS: FZ per joint and output case.

Logic
-----
For every support joint the service load ``P`` (max FZ over the chosen output
cases) is compared with the capacity of each footing type in the schedule
(sorted by capacity) and the first type that satisfies the chosen criterion is
picked:

    ทล.1 : P + W ≤ Cap          ทล.2 : P + W ≤ Cap × 1.05
    ทล.3 : P     ≤ Cap          ทล.4 : P     ≤ Cap × 1.05

where ``W = Area × H × γc`` (weight of the footing).  Joints that fall inside a
FMAT zone (defined by grid lines) are assigned to that mat instead, and any
joint can be overridden by hand.
"""
from __future__ import annotations

import io
import math
import re
import shlex
from dataclasses import dataclass, field

import pandas as pd

KN_PER_TONF = 9.80665
GAMMA_C = 2.4          # t/m³

# --------------------------------------------------------------------------
# Selection criteria
# --------------------------------------------------------------------------
CRITERIA = {
    1: dict(label="ทล.1 : (P + W) ≤ Cap", with_w=True, factor=1.00),
    2: dict(label="ทล.2 : (P + W) ≤ Cap × 1.05", with_w=True, factor=1.05),
    3: dict(label="ทล.3 : P ≤ Cap", with_w=False, factor=1.00),
    4: dict(label="ทล.4 : P ≤ Cap × 1.05", with_w=False, factor=1.05),
}

# --------------------------------------------------------------------------
# Footing schedule (defaults — edit to match the standard drawing SS-02-01-01)
# --------------------------------------------------------------------------
FOOTING_COLUMNS = ["Footing", "Piles", "Pile D (mm)", "Capacity (t)", "B (m)", "L (m)", "H (m)", "Color"]

DEFAULT_FOOTINGS = [
    # name, piles, D(mm), cap(t), B, L, H, color
    ("F1A", 1, 260, 40, 0.60, 0.60, 0.30, "#8ecae6"),
    ("F1B", 1, 300, 60, 0.75, 0.75, 0.40, "#219ebc"),
    ("F1C", 1, 350, 70, 0.80, 0.80, 0.45, "#126782"),
    ("F1D", 1, 400, 80, 0.90, 0.90, 0.50, "#023047"),
    ("F3A", 3, 260, 120, 1.20, 1.10, 0.60, "#a7c957"),
    ("F4A", 4, 260, 160, 1.20, 1.20, 0.70, "#ffd166"),
    ("F4B", 4, 300, 240, 1.40, 1.40, 0.75, "#f8961e"),
    ("F4C", 4, 350, 280, 1.60, 1.60, 0.85, "#f3722c"),
    ("F4D", 4, 400, 320, 1.80, 1.80, 0.95, "#d62828"),
    ("F6B", 6, 300, 360, 1.40, 2.30, 0.80, "#b5179e"),
    ("F6C", 6, 350, 420, 1.75, 2.80, 0.85, "#7209b7"),
    ("F6D", 6, 400, 480, 2.00, 3.20, 0.95, "#560bad"),
    ("F8C", 8, 350, 560, 2.80, 2.80, 0.95, "#3a0ca3"),
    ("F8D", 8, 400, 640, 3.20, 3.20, 1.05, "#3f37c9"),
    ("F9D", 9, 400, 720, 3.20, 3.20, 1.10, "#4361ee"),
]

FMAT_COLOR = "#2e7d32"
UNASSIGNED = "-"


def default_footing_table() -> pd.DataFrame:
    return pd.DataFrame(DEFAULT_FOOTINGS, columns=FOOTING_COLUMNS)


@dataclass
class FootingType:
    name: str
    piles: int
    dia: float           # m
    cap: float           # t
    B: float             # m (along X)
    L: float             # m (along Y)
    H: float             # m
    color: str = "#888888"

    @property
    def area(self) -> float:
        if self.piles == 3:          # truncated triangle (corners chamfered)
            return 0.75 * self.B * self.L
        return self.B * self.L

    @property
    def weight(self) -> float:
        return self.area * self.H * GAMMA_C

    def pile_xy(self) -> list[tuple[float, float]]:
        """Pile centres relative to the footing centre (m)."""
        n, s = self.piles, 3.0 * self.dia
        if n == 1:
            return [(0.0, 0.0)]
        if n == 2:
            return [(-s / 2, 0.0), (s / 2, 0.0)]
        if n == 3:
            h = s * math.sqrt(3) / 2
            return [(-s / 2, -h / 3), (s / 2, -h / 3), (0.0, 2 * h / 3)]
        if n == 4:
            return [(-s / 2, -s / 2), (s / 2, -s / 2), (-s / 2, s / 2), (s / 2, s / 2)]
        if n == 5:
            return [(-s / 2, -s / 2), (s / 2, -s / 2), (-s / 2, s / 2), (s / 2, s / 2), (0.0, 0.0)]
        if n == 6:
            return [(x, y) for y in (-s, 0.0, s) for x in (-s / 2, s / 2)]
        if n == 8:
            return [(x, y) for y in (-s, 0.0, s) for x in (-s, 0.0, s) if (x, y) != (0.0, 0.0)]
        if n == 9:
            return [(x, y) for y in (-s, 0.0, s) for x in (-s, 0.0, s)]
        k = math.ceil(math.sqrt(n))
        pts = [((i % k - (k - 1) / 2) * s, (i // k - (k - 1) / 2) * s) for i in range(n)]
        return pts

    def outline(self) -> list[tuple[float, float]]:
        """Footing outline relative to its centre (closed polygon, m)."""
        b, l = self.B / 2, self.L / 2
        if self.piles == 3:
            c = 0.25 * self.B
            return [(-b, -l), (b, -l), (b, -l + 0.35 * self.L), (c, l), (-c, l),
                    (-b, -l + 0.35 * self.L), (-b, -l)]
        return [(-b, -l), (b, -l), (b, l), (-b, l), (-b, -l)]


def footings_from_table(df: pd.DataFrame) -> list[FootingType]:
    out = []
    for _, r in df.iterrows():
        try:
            name = str(r["Footing"]).strip()
            if not name or name.lower() == "nan":
                continue
            out.append(FootingType(
                name=name, piles=int(r["Piles"]), dia=float(r["Pile D (mm)"]) / 1000.0,
                cap=float(r["Capacity (t)"]), B=float(r["B (m)"]), L=float(r["L (m)"]),
                H=float(r["H (m)"]), color=str(r.get("Color") or "#888888"),
            ))
        except (TypeError, ValueError, KeyError):
            continue
    out.sort(key=lambda f: (f.cap, f.piles, f.area))
    return out


# --------------------------------------------------------------------------
# .e2k parser
# --------------------------------------------------------------------------
@dataclass
class Grid:
    label: str
    dir: str          # "X" -> line at x = coord (vertical), "Y" -> line at y = coord
    coord: float


@dataclass
class E2KModel:
    units: tuple[str, str] = ("TONF", "M")
    grids: list[Grid] = field(default_factory=list)
    points: dict[str, tuple[float, float]] = field(default_factory=dict)
    stories: list[tuple[str, float]] = field(default_factory=list)        # (name, elevation), top -> bottom
    columns: dict[str, str] = field(default_factory=dict)                  # point label -> column line label
    column_sections: dict[str, str] = field(default_factory=dict)          # column line label -> section (lowest story)
    wall_points: set[str] = field(default_factory=set)
    restraints: dict[str, str] = field(default_factory=dict)               # point label -> restraint string
    load_patterns: list[tuple[str, str]] = field(default_factory=list)     # (name, type)
    combos: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    combo_types: dict[str, str] = field(default_factory=dict)

    @property
    def x_grids(self) -> list[Grid]:
        return sorted([g for g in self.grids if g.dir == "X"], key=lambda g: g.coord)

    @property
    def y_grids(self) -> list[Grid]:
        return sorted([g for g in self.grids if g.dir == "Y"], key=lambda g: g.coord)

    @property
    def length_scale(self) -> float:
        """Factor converting model length units to metres."""
        u = self.units[1].upper()
        return {"M": 1.0, "MM": 0.001, "CM": 0.01, "FT": 0.3048, "IN": 0.0254}.get(u, 1.0)


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, posix=True)
    except ValueError:
        return line.replace('"', " ").split()


def _kv(tokens: list[str], key: str, default=None):
    up = [t.upper() for t in tokens]
    if key in up:
        i = up.index(key)
        if i + 1 < len(tokens):
            return tokens[i + 1]
    return default


def parse_e2k(text: str | bytes) -> E2KModel:
    if isinstance(text, bytes):
        for enc in ("utf-8", "cp874", "latin-1"):
            try:
                text = text.decode(enc)
                break
            except UnicodeDecodeError:
                continue
    m = E2KModel()
    section = ""
    lowest_story_seen: dict[str, int] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$"):
            section = line[1:].strip().upper()
            continue
        t = _tokens(line)
        if not t:
            continue
        head = t[0].upper()
        if section.startswith("CONTROLS") and head == "UNITS" and len(t) >= 3:
            m.units = (t[1].upper(), t[2].upper())
        elif section.startswith("STORIES") and head == "STORY":
            elev = _kv(t, "ELEV")
            m.stories.append((t[1], float(elev) if elev is not None else math.nan))
        elif section.startswith("GRIDS") and head == "GRID":
            label, d, c = _kv(t, "LABEL"), _kv(t, "DIR"), _kv(t, "COORD")
            if label is not None and d is not None and c is not None:
                m.grids.append(Grid(label=label, dir=d.upper(), coord=float(c)))
        elif section.startswith("POINT COORDINATES") and head == "POINT" and len(t) >= 4:
            try:
                m.points[t[1]] = (float(t[2]), float(t[3]))
            except ValueError:
                pass
        elif section.startswith("LINE CONNECTIVITIES") and head == "LINE" and len(t) >= 5:
            if t[2].upper() == "COLUMN":
                m.columns[t[3]] = t[1]
        elif section.startswith("AREA CONNECTIVITIES") and head == "AREA" and len(t) >= 4:
            if t[2].upper() == "PANEL":
                try:
                    n = int(t[3])
                    for p in t[4:4 + n]:
                        m.wall_points.add(p)
                except ValueError:
                    pass
        elif section.startswith("POINT ASSIGNS") and head == "POINTASSIGN" and len(t) >= 3:
            r = _kv(t, "RESTRAINT")
            if r:
                m.restraints[t[1]] = r
        elif section.startswith("LINE ASSIGNS") and head == "LINEASSIGN" and len(t) >= 3:
            sec = _kv(t, "SECTION")
            if sec:
                # keep the section of the lowest story (stories are listed top -> bottom)
                names = [s for s, _ in m.stories]
                idx = names.index(t[2]) if t[2] in names else -1
                if idx >= lowest_story_seen.get(t[1], -2):
                    lowest_story_seen[t[1]] = idx
                    m.column_sections[t[1]] = sec
        elif section.startswith("LOAD PATTERNS") and head == "LOADPATTERN" and len(t) >= 2:
            m.load_patterns.append((t[1], _kv(t, "TYPE", "")))
        elif section.startswith("LOAD COMBINATIONS") and head == "COMBO" and len(t) >= 2:
            name = t[1]
            m.combos.setdefault(name, [])
            typ = _kv(t, "TYPE")
            if typ:
                m.combo_types[name] = typ
            case = _kv(t, "LOADCASE") or _kv(t, "LOADCOMBO")
            sf = _kv(t, "SF")
            if case is not None:
                try:
                    m.combos[name].append((case, float(sf) if sf is not None else 1.0))
                except ValueError:
                    m.combos[name].append((case, 1.0))
    return m


# --------------------------------------------------------------------------
# Grid labelling
# --------------------------------------------------------------------------
def _nearest(grids: list[Grid], v: float) -> tuple[Grid | None, float]:
    if not grids:
        return None, 0.0
    g = min(grids, key=lambda g: abs(g.coord - v))
    return g, v - g.coord


def grid_label(model: E2KModel, x: float, y: float, tol: float = 0.05) -> str:
    """'2/A' style label; adds an offset like '3.3-0.27/B.1' when off-grid."""
    sc = model.length_scale

    def part(grids, v):
        g, d = _nearest(grids, v)
        if g is None:
            return f"{v * sc:.2f}"
        dm = d * sc
        return g.label if abs(dm) <= tol else f"{g.label}{dm:+.2f}"

    return f"{part(model.x_grids, x)}/{part(model.y_grids, y)}"


# --------------------------------------------------------------------------
# Joint reactions (Excel exported from ETABS)
# --------------------------------------------------------------------------
_COL_ALIASES = {
    "story": ["story"],
    "joint": ["joint label", "label", "joint", "point", "point label"],
    "unique": ["unique name", "uniquename"],
    "case": ["output case", "load case/combo", "load case", "outputcase", "case", "combo"],
    "step": ["step type", "steptype"],
    "fz": ["fz"],
    "fx": ["fx"], "fy": ["fy"], "mx": ["mx"], "my": ["my"],
    "x": ["x", "global x"], "y": ["y", "global y"],
}


def _match_cols(cols: list[str]) -> dict[str, str]:
    norm = {c: re.sub(r"\s+", " ", str(c)).strip().lower() for c in cols}
    found: dict[str, str] = {}
    for key, aliases in _COL_ALIASES.items():
        for a in aliases:
            for c, n in norm.items():
                if n == a and c not in found.values():
                    found[key] = c
                    break
            if key in found:
                break
    return found


def read_reactions(file, sheet: str | int | None = None) -> tuple[pd.DataFrame, str]:
    """Read an ETABS 'Joint Reactions' table (xlsx/xls/csv).

    Returns (df, force_unit) where df has columns
    Joint, Story, Case, Step, FX, FY, FZ, MX, MY (+ X, Y when present).
    """
    name = getattr(file, "name", str(file)).lower()
    data = file.read() if hasattr(file, "read") else open(file, "rb").read()
    if name.endswith(".csv") or name.endswith(".txt"):
        raw_sheets = {"csv": pd.read_csv(io.BytesIO(data), header=None, dtype=object)}
    else:
        raw_sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    order = list(raw_sheets)
    if sheet is not None:
        order = [sheet] + [s for s in order if s != sheet]
    # prefer sheets whose name mentions reactions
    order.sort(key=lambda s: 0 if "reaction" in str(s).lower() else 1)
    for sname in order:
        raw = raw_sheets[sname]
        hdr_row = None
        for i in range(min(len(raw), 15)):
            vals = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
            if "fz" in vals and any(v in vals for v in ("joint", "joint label", "label", "unique name", "point")):
                hdr_row = i
                break
        if hdr_row is None:
            continue
        headers = [str(v).strip() for v in raw.iloc[hdr_row].tolist()]
        body = raw.iloc[hdr_row + 1:].reset_index(drop=True)
        body.columns = headers
        unit = "tonf"
        # optional units row directly under the header
        if len(body):
            first = [str(v).strip().lower() for v in body.iloc[0].tolist()]
            fz_idx = [h.strip().lower() for h in headers].index("fz")
            if not _is_number(body.iloc[0, fz_idx]):
                u = first[fz_idx]
                if "kn" in u:
                    unit = "kN"
                elif "kgf" in u:
                    unit = "kgf"
                elif "tonf" in u or u in ("t", "ton", "tf"):
                    unit = "tonf"
                body = body.iloc[1:].reset_index(drop=True)
        cols = _match_cols(headers)
        if "fz" not in cols or ("joint" not in cols and "unique" not in cols):
            continue
        out = pd.DataFrame()
        out["Joint"] = body[cols.get("joint", cols.get("unique"))].astype(str).str.strip()
        out["Unique"] = body[cols["unique"]].astype(str).str.strip() if "unique" in cols else out["Joint"]
        out["Story"] = body[cols["story"]].astype(str).str.strip() if "story" in cols else ""
        out["Case"] = body[cols["case"]].astype(str).str.strip() if "case" in cols else "(case)"
        out["Step"] = body[cols["step"]].astype(str).str.strip() if "step" in cols else ""
        for k, c in (("FX", "fx"), ("FY", "fy"), ("FZ", "fz"), ("MX", "mx"), ("MY", "my"), ("X", "x"), ("Y", "y")):
            if c in cols:
                out[k] = pd.to_numeric(body[cols[c]], errors="coerce")
        out = out[out["FZ"].notna() & (out["Joint"] != "") & (out["Joint"].str.lower() != "nan")]
        out["Joint"] = out["Joint"].str.replace(r"\.0$", "", regex=True)
        return out.reset_index(drop=True), unit
    raise ValueError("ไม่พบตาราง Joint Reactions (ต้องมีหัวคอลัมน์ 'Joint Label'/'Unique Name' และ 'FZ')")


def _is_number(v) -> bool:
    try:
        float(v)
        return not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def to_tonf(values, unit: str):
    if unit == "kN":
        return values / KN_PER_TONF
    if unit == "kgf":
        return values / 1000.0
    return values


# --------------------------------------------------------------------------
# Joint table
# --------------------------------------------------------------------------
def build_joints(model: E2KModel, reactions: pd.DataFrame, cases: list[str], unit: str,
                 tol: float = 0.05) -> pd.DataFrame:
    """One row per support joint: coordinates (m), grid label, element, P (t)."""
    r = reactions[reactions["Case"].isin(cases)] if cases else reactions
    if r.empty:
        return pd.DataFrame(columns=["Joint", "X", "Y", "Grid", "Element", "P", "Case"])
    r = r.copy()
    r["P"] = to_tonf(r["FZ"], unit)
    # governing (max) FZ per joint over cases / steps
    idx = r.groupby("Joint")["P"].idxmax()
    g = r.loc[idx].set_index("Joint")
    sc = model.length_scale
    rows = []
    for j, rr in g.iterrows():
        if j in model.points:
            x, y = model.points[j]
        elif "X" in g.columns and pd.notna(rr.get("X")):
            x, y = float(rr["X"]), float(rr["Y"])
        else:
            continue
        if j in model.columns:
            sec = model.column_sections.get(model.columns[j], "")
            elem = sec or "Column"
        elif j in model.wall_points:
            elem = "Wall end"
        else:
            elem = "-"
        rows.append(dict(Joint=j, X=x * sc, Y=y * sc, Grid=grid_label(model, x, y, tol),
                         Element=elem, P=float(rr["P"]), Case=rr["Case"]))
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["Joint", "X", "Y", "Grid", "Element", "P", "Case"])
    return df.sort_values(["Y", "X"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Footing selection
# --------------------------------------------------------------------------
def select_footing(P: float, footings: list[FootingType], criterion: int) -> tuple[str, float]:
    """Return (footing name, utilisation) for the first type that works."""
    c = CRITERIA[criterion]
    for f in footings:
        load = P + (f.weight if c["with_w"] else 0.0)
        if load <= f.cap * c["factor"] + 1e-9:
            return f.name, load / f.cap
    if footings:
        f = footings[-1]
        load = P + (f.weight if c["with_w"] else 0.0)
        return f"{f.name}!", load / f.cap      # "!" = exceeds the largest type
    return UNASSIGNED, math.nan


@dataclass
class FmatZone:
    name: str
    x1: str
    x2: str
    y1: str
    y2: str
    margin: float = 0.5        # m, drawn outline beyond the outermost joints/grids

    def bounds(self, model: E2KModel) -> tuple[float, float, float, float] | None:
        sc = model.length_scale
        gx = {g.label: g.coord * sc for g in model.x_grids}
        gy = {g.label: g.coord * sc for g in model.y_grids}
        try:
            xa, xb = sorted((gx[self.x1], gx[self.x2]))
            ya, yb = sorted((gy[self.y1], gy[self.y2]))
        except KeyError:
            return None
        return xa, xb, ya, yb


def assign_footings(joints: pd.DataFrame, footings: list[FootingType], criterion: int,
                    zones: list[FmatZone], model: E2KModel, overrides: dict[str, str] | None = None,
                    tol: float = 0.05) -> pd.DataFrame:
    """Add columns Auto, Footing, Util, Source to the joint table."""
    df = joints.copy()
    overrides = overrides or {}
    autos, utils, fin, src = [], [], [], []
    by_name = {f.name: f for f in footings}
    c = CRITERIA[criterion]
    for _, r in df.iterrows():
        name, util = select_footing(r["P"], footings, criterion)
        zone = None
        for z in zones:
            b = z.bounds(model)
            if b and b[0] - tol <= r["X"] <= b[1] + tol and b[2] - tol <= r["Y"] <= b[3] + tol:
                zone = z.name
                break
        final, s = name, "auto"
        if zone:
            final, s = zone, "FMAT"
        ov = overrides.get(str(r["Joint"]))
        if ov and ov != "(auto)":
            final, s = ov, "แก้ไข"
        if final in by_name:
            f = by_name[final]
            util = (r["P"] + (f.weight if c["with_w"] else 0.0)) / f.cap
        elif final != name:
            util = math.nan
        autos.append(name)
        utils.append(util)
        fin.append(final)
        src.append(s)
    df["Auto"] = autos
    df["Footing"] = fin
    df["Util"] = utils
    df["Source"] = src
    # capacity check of the footing actually used (fails when an override is too small)
    df["OK"] = [not (pd.notna(u) and u > c["factor"] + 1e-9) and not str(f).endswith("!")
                for u, f in zip(df["Util"], df["Footing"])]
    return df


def summary_table(assigned: dict[int, pd.DataFrame], footings: list[FootingType],
                  zone_names: list[str]) -> pd.DataFrame:
    """Count of footings & piles for each criterion (like the sample summary page)."""
    rows = []
    for f in footings:
        row = {"Footing": f.name, "เข็ม/ฐาน": f.piles, "Capacity (t)": f.cap}
        for k, df in assigned.items():
            n = int((df["Footing"] == f.name).sum())
            row[f"ฐาน ทล.{k}"] = n
            row[f"เข็ม ทล.{k}"] = n * f.piles
        rows.append(row)
    tot = {"Footing": "รวม", "เข็ม/ฐาน": "", "Capacity (t)": ""}
    for k in assigned:
        tot[f"ฐาน ทล.{k}"] = sum(r[f"ฐาน ทล.{k}"] for r in rows)
        tot[f"เข็ม ทล.{k}"] = sum(r[f"เข็ม ทล.{k}"] for r in rows)
    rows.append(tot)
    for z in zone_names:
        row = {"Footing": z, "เข็ม/ฐาน": "รอออกแบบ", "Capacity (t)": ""}
        for k, df in assigned.items():
            row[f"ฐาน ทล.{k}"] = int((df["Footing"] == z).sum())
            row[f"เข็ม ทล.{k}"] = "-"
        rows.append(row)
    return pd.DataFrame(rows)


def zone_loads(df: pd.DataFrame, zone_names: list[str]) -> dict[str, float]:
    return {z: float(df.loc[df["Footing"] == z, "P"].sum()) for z in zone_names}


def zone_outline(zone: FmatZone, model: E2KModel, df: pd.DataFrame) -> tuple[float, float, float, float] | None:
    """Rectangle drawn for a FMAT: joints inside + margin (falls back to the grid box)."""
    b = zone.bounds(model)
    if b is None:
        return None
    pts = df[df["Footing"] == zone.name]
    if len(pts):
        xa, xb = min(b[0], pts["X"].min()), max(b[1], pts["X"].max())
        ya, yb = min(b[2], pts["Y"].min()), max(b[3], pts["Y"].max())
    else:
        xa, xb, ya, yb = b
    m = zone.margin
    return xa - m, xb + m, ya - m, yb + m
