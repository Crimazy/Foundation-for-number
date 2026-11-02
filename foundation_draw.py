"""Drawing of the foundation plan: Plotly (app), Matplotlib (PDF) and DXF (CAD)."""
from __future__ import annotations

import io
import math
import os
import re
from datetime import date

import numpy as np
import pandas as pd

from foundation import CRITERIA, FMAT_COLOR, E2KModel, FmatZone, FootingType, zone_loads, zone_outline

HERE = os.path.dirname(os.path.abspath(__file__))
THAI_FONT_FILES = [
    os.path.join(HERE, "fonts", "Loma.otf"),
    "/usr/share/fonts/opentype/tlwg/Loma.otf",
    "/usr/share/fonts/truetype/tlwg/Loma.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansThai-Regular.ttf",
]


# --------------------------------------------------------------------------
# Shared geometry helpers
# --------------------------------------------------------------------------
def column_size(element: str) -> tuple[float, float] | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", str(element))
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    if a > 20 or b > 20:         # mm
        a, b = a / 1000, b / 1000
    return a, b


def is_sub_grid(label: str) -> bool:
    return "." in label


def grid_extent(model: E2KModel, df: pd.DataFrame) -> tuple[float, float, float, float]:
    sc = model.length_scale
    xs = [g.coord * sc for g in model.x_grids] + list(df["X"]) if len(df) else [g.coord * sc for g in model.x_grids]
    ys = [g.coord * sc for g in model.y_grids] + list(df["Y"]) if len(df) else [g.coord * sc for g in model.y_grids]
    if not xs:
        xs = [0, 10]
    if not ys:
        ys = [0, 10]
    return min(xs), max(xs), min(ys), max(ys)


def differs(assigned_all: dict[int, pd.DataFrame]) -> set[str]:
    """Joints whose footing differs between the criteria."""
    if len(assigned_all) < 2:
        return set()
    frames = [d.set_index("Joint")["Footing"] for d in assigned_all.values()]
    base = frames[0]
    out = set()
    for f in frames[1:]:
        f = f.reindex(base.index)
        out |= set(base.index[(base != f).values])
    return out


def legend_rows(df: pd.DataFrame, footings: list[FootingType]) -> list[tuple[str, str, int]]:
    rows = []
    for f in footings:
        n = int((df["Footing"] == f.name).sum())
        if n:
            rows.append((f.color, f"{f.name} ({f.piles}×{f.dia * 1000:.0f} mm, {f.cap:g} t) = {n} ฐาน", n))
    return rows


# --------------------------------------------------------------------------
# Plotly (interactive, in the app)
# --------------------------------------------------------------------------
def plotly_plan(df: pd.DataFrame, model: E2KModel, footings: list[FootingType], zones: list[FmatZone],
                highlight: set[str] | None = None, selected: set[str] | None = None,
                background=None, dxf_lines=None, show_piles: bool = True, height: int = 820):
    import plotly.graph_objects as go

    highlight = highlight or set()
    selected = selected or set()
    by_name = {f.name: f for f in footings}
    sc = model.length_scale
    x0, x1, y0, y1 = grid_extent(model, df)
    ext = 3.0
    fig = go.Figure()
    shapes, anns = [], []      # collected and set once: fig.add_shape() is very slow for many shapes

    def add_shape(**kw):
        shapes.append(kw)

    def add_ann(**kw):
        anns.append(kw)

    if background is not None:          # (PIL image, (xa, xb, ya, yb), opacity)
        img, (bxa, bxb, bya, byb), op = background
        fig.add_layout_image(dict(source=img, xref="x", yref="y", x=bxa, y=byb, sizex=bxb - bxa,
                                  sizey=byb - bya, sizing="stretch", opacity=op, layer="below"))
    if dxf_lines:
        xs, ys = [], []
        for seg in dxf_lines:
            xs += [p[0] for p in seg] + [None]
            ys += [p[1] for p in seg] + [None]
        fig.add_trace(go.Scattergl(x=xs, y=ys, mode="lines", line=dict(color="rgba(120,120,120,0.55)", width=1),
                                   hoverinfo="skip", name="แบบ CAD", showlegend=False))

    # grids
    for g in model.x_grids:
        x = g.coord * sc
        sub = is_sub_grid(g.label)
        add_shape(type="line", x0=x, x1=x, y0=y0 - ext, y1=y1 + ext, layer="below",
                      line=dict(color="#b0b0b0" if sub else "#808080", width=1, dash="dot" if sub else "dashdot"))
        if sub:
            add_ann(x=x, y=y1 + ext, text=g.label, showarrow=False, yshift=8, font=dict(size=9, color="#666"))
        else:
            add_ann(x=x, y=y0 - ext, text=f"<b>{g.label}</b>", showarrow=False, yshift=-14,
                               bordercolor="#333", borderwidth=1, borderpad=3, bgcolor="white", font=dict(size=11))
    for g in model.y_grids:
        y = g.coord * sc
        sub = is_sub_grid(g.label)
        add_shape(type="line", x0=x0 - ext, x1=x1 + ext, y0=y, y1=y, layer="below",
                      line=dict(color="#b0b0b0" if sub else "#808080", width=1, dash="dot" if sub else "dashdot"))
        if sub:
            add_ann(x=x1 + ext, y=y, text=g.label, showarrow=False, xshift=14, font=dict(size=9, color="#666"))
        else:
            add_ann(x=x0 - ext, y=y, text=f"<b>{g.label}</b>", showarrow=False, xshift=-16,
                               bordercolor="#333", borderwidth=1, borderpad=3, bgcolor="white", font=dict(size=11))

    # FMAT zones
    loads = zone_loads(df, [z.name for z in zones])
    for z in zones:
        o = zone_outline(z, model, df)
        if o is None:
            continue
        add_shape(type="rect", x0=o[0], x1=o[1], y0=o[2], y1=o[3], layer="below",
                      line=dict(color=FMAT_COLOR, width=2, dash="dash"), fillcolor="rgba(46,125,50,0.15)")
        add_ann(x=(o[0] + o[1]) / 2, y=o[3], text=f"<b>{z.name}  ΣP={loads.get(z.name, 0):.1f} t</b>",
                           showarrow=False, yshift=10, font=dict(size=11, color=FMAT_COLOR))

    # footings / piles / columns: one trace per colour (few traces render much faster than many shapes)
    def poly_trace(xs, ys, fill, line_color, width, name):
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", fill="toself" if fill else None, fillcolor=fill,
                                 line=dict(color=line_color, width=width), hoverinfo="skip", name=name,
                                 showlegend=False))

    groups: dict[str, tuple[list, list]] = {}
    sel_xy: tuple[list, list] = ([], [])
    pile_xy: tuple[list, list] = ([], [])
    col_xy: tuple[list, list] = ([], [])
    circ = [(math.cos(t), math.sin(t)) for t in np.linspace(0, 2 * math.pi, 13)]
    for _, r in df.iterrows():
        f = by_name.get(r["Footing"])
        if f is not None:
            gx, gy = groups.setdefault(f.name, ([], []))
            for px, py in f.outline():
                gx.append(r["X"] + px)
                gy.append(r["Y"] + py)
            gx.append(None)
            gy.append(None)
            if str(r["Joint"]) in selected:
                for px, py in f.outline():
                    sel_xy[0].append(r["X"] + px)
                    sel_xy[1].append(r["Y"] + py)
                sel_xy[0].append(None)
                sel_xy[1].append(None)
            if show_piles:
                rr = f.dia / 2
                for px, py in f.pile_xy():
                    for cx, cy in circ:
                        pile_xy[0].append(r["X"] + px + rr * cx)
                        pile_xy[1].append(r["Y"] + py + rr * cy)
                    pile_xy[0].append(None)
                    pile_xy[1].append(None)
        cs = column_size(r["Element"])
        if cs:
            b, h = cs
            for cx, cy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)):
                col_xy[0].append(r["X"] + cx * b / 2)
                col_xy[1].append(r["Y"] + cy * h / 2)
            col_xy[0].append(None)
            col_xy[1].append(None)
    for name, (gx, gy) in groups.items():
        poly_trace(gx, gy, by_name[name].color, "black", 1, name)
    if pile_xy[0]:
        poly_trace(*pile_xy, None, "#333", 0.8, "piles")
    if col_xy[0]:
        poly_trace(*col_xy, "black", "black", 0.5, "columns")
    if sel_xy[0]:
        poly_trace(*sel_xy, None, "#1565c0", 3.5, "selected")

    # labels + selectable markers
    zone_set = {z.name for z in zones}
    texts, colors = [], []
    for _, r in df.iterrows():
        hi = str(r["Joint"]) in highlight
        ng = not r.get("OK", True)
        if str(r["Footing"]) in zone_set:
            texts.append(f"P={r['P']:.1f}")
            colors.append("#1b5e20")
            continue
        ftxt = f"<b>{r['Footing']}</b>" if hi or ng else r["Footing"]
        texts.append(f"{'⚠ ' if ng else ''}{ftxt}<br>P={r['P']:.1f} t")
        colors.append("#ff6d00" if ng else ("#c62828" if hi else "#222"))
    util = df["Util"].apply(lambda u: "-" if pd.isna(u) else f"{u * 100:.1f}%")
    fig.add_trace(go.Scatter(
        x=df["X"], y=df["Y"], mode="markers+text", text=texts, textposition="top left",
        textfont=dict(size=10, color=colors),
        marker=dict(size=[16 if str(j) in selected else 9 for j in df["Joint"]],
                    color=["#1565c0" if str(j) in selected else "rgba(0,0,0,0.25)" for j in df["Joint"]],
                    symbol=["triangle-up" if not column_size(e) else "square" for e in df["Element"]],
                    line=dict(width=0)),
        customdata=np.stack([df["Joint"].astype(str), df["Grid"], df["Element"], df["Footing"], util], axis=-1),
        hovertemplate="Joint %{customdata[0]}  (%{customdata[1]})<br>%{customdata[2]}<br>"
                      "%{customdata[3]}  Util %{customdata[4]}<extra></extra>",
        name="joints", showlegend=False,
    ))
    fig.update_layout(
        shapes=shapes, annotations=anns,
        height=height, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", dragmode="select",
        xaxis=dict(visible=False, range=[x0 - ext - 3, x1 + ext + 3]),
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=1, range=[y0 - ext - 3, y1 + ext + 3]),
        clickmode="event+select",
    )
    return fig


# --------------------------------------------------------------------------
# Matplotlib (PDF)
# --------------------------------------------------------------------------
def _setup_mpl():
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager as fm
    from matplotlib import pyplot as plt

    fam = None
    for p in THAI_FONT_FILES:
        if os.path.exists(p):
            try:
                fm.fontManager.addfont(p)
                fam = fm.FontProperties(fname=p).get_name()
                break
            except Exception:  # noqa: BLE001
                continue
    if fam:
        plt.rcParams["font.family"] = [fam, "DejaVu Sans"]
    plt.rcParams["pdf.fonttype"] = 42 if fam is None else 3
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _draw_plan_ax(ax, df, model, footings, zones, highlight, show_piles=True, fs=7.0):
    from matplotlib.patches import Circle, Polygon, Rectangle

    by_name = {f.name: f for f in footings}
    sc = model.length_scale
    x0, x1, y0, y1 = grid_extent(model, df)
    ext = 2.5
    for g in model.x_grids:
        x = g.coord * sc
        sub = is_sub_grid(g.label)
        ax.plot([x, x], [y0 - ext, y1 + ext], color="#999" if sub else "#666", lw=0.4,
                ls=(0, (6, 2, 1, 2)) if not sub else (0, (2, 2)), zorder=1)
        if sub:
            ax.text(x, y1 + ext + 0.3, g.label, ha="center", va="bottom", fontsize=fs * 0.75, color="#555")
        else:
            ax.add_patch(Circle((x, y0 - ext - 0.9), 0.85, fill=False, lw=0.6, zorder=3))
            ax.text(x, y0 - ext - 0.9, g.label, ha="center", va="center", fontsize=fs, zorder=4)
    for g in model.y_grids:
        y = g.coord * sc
        sub = is_sub_grid(g.label)
        ax.plot([x0 - ext, x1 + ext], [y, y], color="#999" if sub else "#666", lw=0.4,
                ls=(0, (6, 2, 1, 2)) if not sub else (0, (2, 2)), zorder=1)
        if sub:
            ax.text(x1 + ext + 0.3, y, g.label, ha="left", va="center", fontsize=fs * 0.75, color="#555")
        else:
            ax.add_patch(Circle((x0 - ext - 0.9, y), 0.85, fill=False, lw=0.6, zorder=3))
            ax.text(x0 - ext - 0.9, y, g.label, ha="center", va="center", fontsize=fs, zorder=4)

    loads = zone_loads(df, [z.name for z in zones])
    for z in zones:
        o = zone_outline(z, model, df)
        if o is None:
            continue
        ax.add_patch(Rectangle((o[0], o[2]), o[1] - o[0], o[3] - o[2], facecolor="#c8e6c9", edgecolor=FMAT_COLOR,
                               hatch="///", lw=0.9, ls="--", alpha=0.8, zorder=2))
        ax.text((o[0] + o[1]) / 2, o[3] + 0.3, f"{z.name}  ΣP={loads.get(z.name, 0):.1f} t", ha="center",
                va="bottom", fontsize=fs * 0.9, color=FMAT_COLOR, weight="bold", zorder=6)

    for _, r in df.iterrows():
        f = by_name.get(r["Footing"])
        if f is not None:
            pts = [(r["X"] + px, r["Y"] + py) for px, py in f.outline()]
            ax.add_patch(Polygon(pts, closed=True, facecolor=f.color, edgecolor="black", lw=0.5, zorder=3))
            if show_piles:
                for px, py in f.pile_xy():
                    ax.add_patch(Circle((r["X"] + px, r["Y"] + py), f.dia / 2, fill=False, lw=0.3,
                                        edgecolor="#222", zorder=4))
            top = max(p[1] for p in pts)
            left = min(p[0] for p in pts)
        else:
            top, left = r["Y"] + 0.4, r["X"] - 0.4
        cs = column_size(r["Element"])
        if cs:
            b, h = cs
            ax.add_patch(Rectangle((r["X"] - b / 2, r["Y"] - h / 2), b, h, facecolor="black", lw=0, zorder=5))
        else:
            ax.plot([r["X"]], [r["Y"]], marker="^", ms=2.2, color="black", zorder=5)
        hi = str(r["Joint"]) in highlight or not r.get("OK", True)
        col = "#c62828" if hi else ("#1b5e20" if str(r["Footing"]).startswith("FMAT") else "black")
        if str(r["Footing"]).startswith("FMAT"):
            ax.text(r["X"] + 0.25, r["Y"] + 0.25, f"P={r['P']:.1f}", fontsize=fs * 0.7, color=col, zorder=6)
        else:
            ax.text(left, top + 0.15, f"{r['Footing']}\nP={r['P']:.1f} t", fontsize=fs * 0.8, color=col,
                    weight="bold" if hi else "normal", ha="left", va="bottom", linespacing=1.0, zorder=6)

    ax.set_aspect("equal")
    ax.set_xlim(x0 - ext - 2.2, x1 + ext + 2.0)
    ax.set_ylim(y0 - ext - 2.2, y1 + ext + 1.6)
    ax.axis("off")


def _legend_ax(ax, df, footings, zones, notes, fs=7.5):
    from matplotlib.patches import Rectangle

    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    rows = legend_rows(df, footings)
    loads = zone_loads(df, [z.name for z in zones])
    n_rows = len(rows) + len(zones)
    h = 0.032
    top = 0.98
    box_h = h * (n_rows + 1.6)
    ax.add_patch(Rectangle((0.005, top - box_h), 0.99, box_h, fill=False, lw=0.6, clip_on=False))
    ax.text(0.5, top - 0.02, "Footing", ha="center", va="top", fontsize=fs + 1, weight="bold")
    y = top - 0.06
    for color, txt, _ in rows:
        ax.add_patch(Rectangle((0.04, y - 0.011), 0.08, 0.022, facecolor=color, edgecolor="black", lw=0.4))
        ax.text(0.15, y, txt, va="center", fontsize=fs)
        y -= h
    for z in zones:
        n = int((df["Footing"] == z.name).sum())
        ax.add_patch(Rectangle((0.04, y - 0.011), 0.08, 0.022, facecolor="#c8e6c9", edgecolor=FMAT_COLOR,
                               hatch="///", lw=0.4))
        ax.text(0.15, y, f"{z.name} (ΣP={loads.get(z.name, 0):.1f} t, รอออกแบบ) = {n} จุด", va="center", fontsize=fs)
        y -= h
    y -= 0.04
    if notes:
        ax.text(0.0, y, "หมายเหตุ", fontsize=fs, weight="bold", va="top")
        y -= 0.03
        for line in notes:
            ax.text(0.0, y, f"• {line}", fontsize=fs * 0.9, va="top", wrap=True)
            y -= 0.026


def plan_notes(df: pd.DataFrame, footings: list[FootingType], zones: list[FmatZone], n_diff: int) -> list[str]:
    by = {f.name: f for f in footings}
    n_found = sum(1 for v in df["Footing"] if v in by)
    piles = sum(by[v].piles for v in df["Footing"] if v in by)
    notes = [
        "ขนาดฐานวาดตามสเกล วางศูนย์กลางตรงเสา",
        "P = service load ลงฐาน (ไม่รวมน้ำหนักฐาน)",
        "W_footing = Area × H × 2.4 t/m³",
        f"รวมเข็ม {piles} ต้น / {n_found} ฐาน" + (" (ไม่รวม FMAT)" if zones else ""),
    ]
    if n_diff:
        notes.insert(1, f"ตัวสีแดงหนา = ทางเลือก 1–4 ได้เบอร์ต่างกัน ({n_diff} จุด)")
    if zones:
        notes.append("กรอบ FMAT แสดงตำแหน่งเท่านั้น ยังไม่กำหนดขนาด")
    edited = int((df["Source"] == "แก้ไข").sum()) if "Source" in df else 0
    if edited:
        notes.append(f"แก้ไขเบอร์ฐานด้วยมือ {edited} จุด")
    return notes


def build_pdf(assigned_all: dict[int, pd.DataFrame], criteria_to_plot: list[int], model: E2KModel,
              footings: list[FootingType], zones: list[FmatZone], project: str, source_note: str,
              show_piles: bool = True) -> bytes:
    """A3 landscape PDF: summary table, one plan per criterion, selection table."""
    plt = _setup_mpl()
    from matplotlib.backends.backend_pdf import PdfPages

    A3 = (16.54, 11.69)
    highlight = differs(assigned_all)
    zone_names = [z.name for z in zones]
    bio = io.BytesIO()
    from foundation import summary_table

    with PdfPages(bio) as pdf:
        # ---- page 1: summary
        fig = plt.figure(figsize=A3)
        fig.text(0.05, 0.94, f"สรุปจำนวนฐานรากและเข็ม – {project}", fontsize=16, weight="bold")
        fig.text(0.05, 0.915, "   |   ".join(CRITERIA[k]["label"] for k in sorted(assigned_all)), fontsize=9)
        st_df = summary_table(assigned_all, footings, zone_names)
        ax = fig.add_axes([0.05, 0.25, 0.9, 0.64])
        ax.axis("off")
        tbl = ax.table(cellText=st_df.astype(str).values.tolist(), colLabels=list(st_df.columns), loc="upper center",
                       cellLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.45)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_linewidth(0.4)
            if r == 0:
                cell.set_facecolor("#dbe5f1")
                cell.set_text_props(weight="bold")
            elif st_df.iloc[r - 1, 0] == "รวม":
                cell.set_text_props(weight="bold")
            elif st_df.iloc[r - 1, 0] in zone_names:
                cell.set_facecolor("#e8f5e9")
        y = 0.2
        any_df = next(iter(assigned_all.values()))
        for z, p in zone_loads(any_df, zone_names).items():
            n = int((any_df["Footing"] == z).sum())
            fig.text(0.05, y, f"• P รวมที่ลง {z} ({n} จุด) = {p:.1f} t – ยังไม่กำหนดขนาด/จำนวนเข็ม ไม่รวมในจำนวนเข็ม",
                     fontsize=9)
            y -= 0.022
        fig.text(0.05, y, f"• จุดที่มีเบอร์ต่างกันระหว่างทางเลือก = {len(highlight)} จุด", fontsize=9)
        y -= 0.022
        if source_note:
            fig.text(0.05, y, f"• {source_note}", fontsize=9)
        pdf.savefig(fig)
        plt.close(fig)

        # ---- plan pages
        for k in criteria_to_plot:
            df = assigned_all[k]
            fig = plt.figure(figsize=A3)
            fig.text(0.02, 0.965, f"FOUNDATION PLAN – {project}  |  ทางเลือก {k} : {CRITERIA[k]['label'].split(':', 1)[1].strip()}",
                     fontsize=14, weight="bold")
            if source_note:
                fig.text(0.02, 0.945, source_note, fontsize=7.5)
            fig.text(0.98, 0.012, f"{date.today():%d/%m/%Y}", fontsize=7, ha="right", color="#666")
            ax = fig.add_axes([0.02, 0.02, 0.72, 0.91])
            _draw_plan_ax(ax, df, model, footings, zones, highlight, show_piles)
            lax = fig.add_axes([0.76, 0.08, 0.22, 0.84])
            _legend_ax(lax, df, footings, zones, plan_notes(df, footings, zones, len(highlight)))
            pdf.savefig(fig)
            plt.close(fig)

        # ---- selection table pages
        keys = sorted(assigned_all)
        base = assigned_all[keys[0]]
        rows = []
        for _, r in base.iterrows():
            row = [str(r["Joint"]), r["Grid"], r["Element"], f"{r['P']:.1f}"]
            for k in keys:
                rr = assigned_all[k].set_index("Joint").loc[r["Joint"]]
                row += [rr["Footing"], "-" if pd.isna(rr["Util"]) else f"{rr['Util'] * 100:.1f}%"]
            note = ""
            if str(r["Footing"]).startswith("FMAT"):
                note = f"รวมเข้า {r['Footing']}"
            if r.get("Source") == "แก้ไข":
                note = "แก้ไขเบอร์"
            row.append(note)
            rows.append(row)
        cols = ["Joint", "Grid", "Element", "P (t)"]
        for k in keys:
            cols += [f"ทล.{k}", "Util"]
        cols.append("หมายเหตุ")
        per = 38
        pages = max(1, math.ceil(len(rows) / per))
        for p in range(pages):
            fig = plt.figure(figsize=A3)
            fig.text(0.05, 0.95, f"ตารางเลือกเบอร์ฐานราก – {project} (หน้า {p + 1}/{pages})", fontsize=14, weight="bold")
            fig.text(0.05, 0.93, "   |   ".join(CRITERIA[k]["label"] for k in keys) + "     (Util = Load/Cap ; W = Area×H×2.4)",
                     fontsize=8.5)
            ax = fig.add_axes([0.05, 0.03, 0.9, 0.88])
            ax.axis("off")
            chunk = rows[p * per:(p + 1) * per]
            tbl = ax.table(cellText=chunk, colLabels=cols, loc="upper center", cellLoc="center")
            tbl.auto_set_font_size(False)
            tbl.set_fontsize(8)
            tbl.scale(1, 1.32)
            for (r, c), cell in tbl.get_celld().items():
                cell.set_linewidth(0.3)
                if r == 0:
                    cell.set_facecolor("#dbe5f1")
                    cell.set_text_props(weight="bold")
                elif chunk[r - 1][0] in highlight and 4 <= c < 4 + 2 * len(keys):
                    cell.set_text_props(color="#c62828", weight="bold")
            pdf.savefig(fig)
            plt.close(fig)
    return bio.getvalue()


def plan_png(df, model, footings, zones, highlight, project, title, show_piles=True, dpi=110) -> bytes:
    plt = _setup_mpl()
    fig = plt.figure(figsize=(16.54, 11.69))
    fig.text(0.02, 0.965, f"FOUNDATION PLAN – {project}  |  {title}", fontsize=14, weight="bold")
    ax = fig.add_axes([0.02, 0.02, 0.72, 0.93])
    _draw_plan_ax(ax, df, model, footings, zones, highlight, show_piles)
    lax = fig.add_axes([0.76, 0.08, 0.22, 0.84])
    _legend_ax(lax, df, footings, zones, plan_notes(df, footings, zones, len(highlight)))
    bio = io.BytesIO()
    fig.savefig(bio, format="png", dpi=dpi)
    plt.close(fig)
    return bio.getvalue()


# --------------------------------------------------------------------------
# DXF (CAD)
# --------------------------------------------------------------------------
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) != 6:
        return (128, 128, 128)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def build_dxf(assigned_all: dict[int, pd.DataFrame], criteria_to_plot: list[int], model: E2KModel,
              footings: list[FootingType], zones: list[FmatZone], project: str, unit: str = "mm",
              show_piles: bool = True) -> bytes:
    """DXF (AutoCAD 2010) — one plan per criterion, placed side by side."""
    import ezdxf
    from ezdxf import colors as ezcolors
    from ezdxf.enums import TextEntityAlignment

    s = 1000.0 if unit == "mm" else 1.0
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM if unit == "mm" else ezdxf.units.M
    doc.styles.add("THAI", font="tahoma.ttf")
    layers = {
        "S-GRID": (8, "DASHDOT"), "S-GRID-SUB": (9, "DASHED"), "S-GRID-BUBBLE": (7, "CONTINUOUS"),
        "S-COLUMN": (7, "CONTINUOUS"), "S-FOOTING": (7, "CONTINUOUS"), "S-FOOTING-FILL": (8, "CONTINUOUS"),
        "S-PILE": (1, "CONTINUOUS"), "S-TEXT-FOOTING": (7, "CONTINUOUS"), "S-TEXT-LOAD": (5, "CONTINUOUS"),
        "S-TEXT-CHANGED": (1, "CONTINUOUS"), "S-FMAT": (3, "DASHED"), "S-TITLE": (7, "CONTINUOUS"),
        "S-LEGEND": (7, "CONTINUOUS"),
    }
    for name, (color, lt) in layers.items():
        if name not in doc.layers:
            doc.layers.add(name, color=color, linetype=lt)
    msp = doc.modelspace()
    by_name = {f.name: f for f in footings}
    highlight = differs(assigned_all)
    sc = model.length_scale
    x0, x1, y0, y1 = grid_extent(model, next(iter(assigned_all.values())))
    ext = 2.5
    width = (x1 - x0) + 2 * ext + 30.0      # leave room for the legend
    th = 0.25 * s                            # text height

    def T(txt, x, y, h=th, layer="S-TEXT-FOOTING", align=TextEntityAlignment.BOTTOM_LEFT, color=None):
        attrs = {"height": h, "layer": layer, "style": "THAI"}
        e = msp.add_text(txt, dxfattribs=attrs)
        e.set_placement((x, y), align=align)
        if color:
            e.rgb = _hex_to_rgb(color)
        return e

    for i, k in enumerate(criteria_to_plot):
        df = assigned_all[k]
        ox = i * width * s
        X = lambda v: ox + v * s          # noqa: E731
        Y = lambda v: v * s               # noqa: E731
        T(f"FOUNDATION PLAN – {project}  |  ทางเลือก {k} : {CRITERIA[k]['label'].split(':', 1)[1].strip()}",
          X(x0 - ext), Y(y1 + ext + 3.0), h=0.6 * s, layer="S-TITLE")
        for g in model.x_grids:
            x = g.coord * sc
            sub = is_sub_grid(g.label)
            msp.add_line((X(x), Y(y0 - ext)), (X(x), Y(y1 + ext)), dxfattribs={"layer": "S-GRID-SUB" if sub else "S-GRID"})
            if sub:
                T(g.label, X(x), Y(y1 + ext + 0.2), h=0.2 * s, layer="S-GRID-SUB", align=TextEntityAlignment.BOTTOM_CENTER)
            else:
                msp.add_circle((X(x), Y(y0 - ext - 0.8)), 0.8 * s, dxfattribs={"layer": "S-GRID-BUBBLE"})
                T(g.label, X(x), Y(y0 - ext - 0.8), h=0.5 * s, layer="S-GRID-BUBBLE", align=TextEntityAlignment.MIDDLE_CENTER)
        for g in model.y_grids:
            y = g.coord * sc
            sub = is_sub_grid(g.label)
            msp.add_line((X(x0 - ext), Y(y)), (X(x1 + ext), Y(y)), dxfattribs={"layer": "S-GRID-SUB" if sub else "S-GRID"})
            if sub:
                T(g.label, X(x1 + ext + 0.2), Y(y), h=0.2 * s, layer="S-GRID-SUB", align=TextEntityAlignment.MIDDLE_LEFT)
            else:
                msp.add_circle((X(x0 - ext - 0.8), Y(y)), 0.8 * s, dxfattribs={"layer": "S-GRID-BUBBLE"})
                T(g.label, X(x0 - ext - 0.8), Y(y), h=0.5 * s, layer="S-GRID-BUBBLE", align=TextEntityAlignment.MIDDLE_CENTER)

        loads = zone_loads(df, [z.name for z in zones])
        for z in zones:
            o = zone_outline(z, model, df)
            if o is None:
                continue
            pts = [(X(o[0]), Y(o[2])), (X(o[1]), Y(o[2])), (X(o[1]), Y(o[3])), (X(o[0]), Y(o[3]))]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-FMAT"})
            h = msp.add_hatch(color=3, dxfattribs={"layer": "S-FMAT"})
            h.set_pattern_fill("ANSI31", scale=0.1 * s)
            h.paths.add_polyline_path(pts, is_closed=True)
            T(f"{z.name}  ΣP={loads.get(z.name, 0):.1f} t", X((o[0] + o[1]) / 2), Y(o[3] + 0.2), h=0.35 * s,
              layer="S-FMAT", align=TextEntityAlignment.BOTTOM_CENTER)

        for _, r in df.iterrows():
            f = by_name.get(r["Footing"])
            top, left = r["Y"] + 0.4, r["X"] - 0.4
            if f is not None:
                pts = [(X(r["X"] + px), Y(r["Y"] + py)) for px, py in f.outline()[:-1]]
                msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-FOOTING"})
                h = msp.add_hatch(dxfattribs={"layer": "S-FOOTING-FILL"})
                h.rgb = _hex_to_rgb(f.color)
                h.transparency = 0.4
                h.paths.add_polyline_path(pts, is_closed=True)
                if show_piles:
                    for px, py in f.pile_xy():
                        msp.add_circle((X(r["X"] + px), Y(r["Y"] + py)), f.dia / 2 * s, dxfattribs={"layer": "S-PILE"})
                top = r["Y"] + max(p[1] for p in f.outline())
                left = r["X"] + min(p[0] for p in f.outline())
            cs = column_size(r["Element"])
            if cs:
                b, hh = cs
                pts = [(X(r["X"] - b / 2), Y(r["Y"] - hh / 2)), (X(r["X"] + b / 2), Y(r["Y"] - hh / 2)),
                       (X(r["X"] + b / 2), Y(r["Y"] + hh / 2)), (X(r["X"] - b / 2), Y(r["Y"] + hh / 2))]
                msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-COLUMN"})
                hc = msp.add_hatch(color=ezcolors.BLACK, dxfattribs={"layer": "S-COLUMN"})
                hc.paths.add_polyline_path(pts, is_closed=True)
            else:
                msp.add_circle((X(r["X"]), Y(r["Y"])), 0.1 * s, dxfattribs={"layer": "S-COLUMN"})
            hi = str(r["Joint"]) in highlight
            lay = "S-TEXT-CHANGED" if hi else "S-TEXT-FOOTING"
            if str(r["Footing"]).startswith("FMAT"):
                T(f"P={r['P']:.1f}", X(r["X"] + 0.2), Y(r["Y"] + 0.2), h=0.18 * s, layer="S-TEXT-LOAD")
            else:
                T(str(r["Footing"]), X(left), Y(top + 0.12 + 0.32), layer=lay)
                T(f"P={r['P']:.1f} t", X(left), Y(top + 0.12), h=0.22 * s, layer="S-TEXT-LOAD")

        # legend
        lx, ly = X(x1 + ext + 4.0), Y(y1 + ext)
        T("FOOTING", lx, ly, h=0.5 * s, layer="S-LEGEND")
        yy = ly - 1.2 * s
        for color, txt, _ in legend_rows(df, footings):
            pts = [(lx, yy), (lx + 1.0 * s, yy), (lx + 1.0 * s, yy + 0.6 * s), (lx, yy + 0.6 * s)]
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "S-LEGEND"})
            hh = msp.add_hatch(dxfattribs={"layer": "S-LEGEND"})
            hh.rgb = _hex_to_rgb(color)
            hh.paths.add_polyline_path(pts, is_closed=True)
            T(txt, lx + 1.4 * s, yy + 0.1 * s, h=0.35 * s, layer="S-LEGEND")
            yy -= 1.0 * s
        for z in zones:
            n = int((df["Footing"] == z.name).sum())
            T(f"{z.name} (ΣP={loads.get(z.name, 0):.1f} t, รอออกแบบ) = {n} จุด", lx + 1.4 * s, yy + 0.1 * s,
              h=0.35 * s, layer="S-LEGEND")
            yy -= 1.0 * s
        yy -= 0.6 * s
        T("หมายเหตุ", lx, yy, h=0.35 * s, layer="S-LEGEND")
        yy -= 0.7 * s
        for line in plan_notes(df, footings, zones, len(highlight)):
            T(f"• {line}", lx, yy, h=0.28 * s, layer="S-LEGEND")
            yy -= 0.55 * s

    sio = io.StringIO()
    doc.write(sio)
    return sio.getvalue().encode("utf-8")


# --------------------------------------------------------------------------
# Reading the reference drawing
# --------------------------------------------------------------------------
def pdf_page_images(data: bytes, zoom: float = 2.0, max_pages: int = 10):
    """Render PDF pages to PIL images (requires PyMuPDF)."""
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(stream=data, filetype="pdf")
    out = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


def dwg_to_dxf(data: bytes) -> bytes | None:
    """Convert DWG -> DXF with LibreDWG (dwg2dxf) or ODA File Converter when installed."""
    import shutil
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, "in.dwg")
        with open(src, "wb") as fh:
            fh.write(data)
        exe = shutil.which("dwg2dxf")
        if exe:
            dst = os.path.join(td, "in.dxf")
            subprocess.run([exe, "-y", "-o", dst, src], capture_output=True, timeout=120)
            if os.path.exists(dst):
                return open(dst, "rb").read()
        oda = shutil.which("ODAFileConverter")
        if oda:
            outdir = os.path.join(td, "out")
            os.makedirs(outdir)
            subprocess.run([oda, td, outdir, "ACAD2018", "DXF", "0", "1", "*.dwg"], capture_output=True, timeout=180)
            for fn in os.listdir(outdir):
                if fn.lower().endswith(".dxf"):
                    return open(os.path.join(outdir, fn), "rb").read()
    return None


def dxf_segments(data: bytes, layers: list[str] | None = None, max_segments: int = 40000):
    """Line work of a DXF as a list of polylines [(x, y), ...] in drawing units, plus the layer list."""
    import ezdxf
    from ezdxf import recover

    try:
        doc, _ = recover.read(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        doc = ezdxf.read(io.StringIO(data.decode("utf-8", errors="ignore")))
    msp = doc.modelspace()
    all_layers = sorted({e.dxf.layer for e in msp if e.dxf.hasattr("layer")})
    segs = []

    def add(pts):
        if len(segs) < max_segments and len(pts) >= 2:
            segs.append([(float(p[0]), float(p[1])) for p in pts])

    def walk(entities, depth=0):
        for e in entities:
            if layers and e.dxf.get("layer", "0") not in layers:
                continue
            t = e.dxftype()
            try:
                if t == "LINE":
                    add([e.dxf.start, e.dxf.end])
                elif t == "LWPOLYLINE":
                    pts = [(p[0], p[1]) for p in e.get_points("xy")]
                    if e.closed:
                        pts.append(pts[0])
                    add(pts)
                elif t == "POLYLINE":
                    pts = [(v.dxf.location[0], v.dxf.location[1]) for v in e.vertices]
                    if e.is_closed:
                        pts.append(pts[0])
                    add(pts)
                elif t in ("CIRCLE", "ARC"):
                    c, r = e.dxf.center, e.dxf.radius
                    a0, a1 = (0, 360) if t == "CIRCLE" else (e.dxf.start_angle, e.dxf.end_angle)
                    if a1 < a0:
                        a1 += 360
                    ang = np.radians(np.linspace(a0, a1, 24))
                    add(list(zip(c[0] + r * np.cos(ang), c[1] + r * np.sin(ang))))
                elif t == "INSERT" and depth < 3:
                    walk(e.virtual_entities(), depth + 1)
            except Exception:  # noqa: BLE001
                continue

    walk(msp)
    return segs, all_layers
