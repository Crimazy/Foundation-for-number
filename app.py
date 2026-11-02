"""Streamlit page: foundation plan & footing selection from ETABS (.e2k + Joint Reactions Excel).

Run:  streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import date

import pandas as pd
import streamlit as st

from foundation import (
    CRITERIA, FmatZone, assign_footings, build_joints, default_footing_table, footings_from_table,
    parse_e2k, read_reactions, summary_table, zone_loads,
)
from foundation_demo import demo_e2k, demo_reactions_xlsx
from foundation_schedule import merge_schedule, read_schedule_file, template_xlsx
from foundation_draw import (
    build_dxf, build_pdf, differs, dwg_to_dxf, dxf_segments, grid_extent, pdf_page_images, plotly_plan,
)

st.set_page_config(page_title="ผังฐานราก / เลือกเบอร์ฐานราก", page_icon="🧱", layout="wide")
st.markdown("<style>.block-container{padding-top:1.4rem;} div[data-testid='stMetricValue']{font-size:1.4rem;}</style>",
            unsafe_allow_html=True)
ss = st.session_state

ss.setdefault("fd_ver", 0)
ss.setdefault("fd_overrides", {})
ss.setdefault("fd_sel", [])
ss.setdefault("fd_project", "อาคาร B6")
if "fd_footings" not in ss:
    ss.fd_footings = default_footing_table()
if "fd_zones" not in ss:
    ss.fd_zones = pd.DataFrame(columns=["FMAT", "Grid X จาก", "Grid X ถึง", "Grid Y จาก", "Grid Y ถึง", "ระยะเผื่อ (m)"])


def bump(keep: bool = True):
    """Re-mount the editors (new keys); keep the live edits of the footing / FMAT tables."""
    if keep:
        for live, base in (("fd_footings_live", "fd_footings"), ("fd_zones_live", "fd_zones")):
            if live in ss:
                ss[base] = ss[live]
    ss.fd_ver += 1


def load_demo():
    ss.fd_e2k = ("B6_demo.e2k", demo_e2k().encode())
    ss.fd_rx = ("B6_demo_Joint_Reactions.xlsx", demo_reactions_xlsx())
    ss.fd_zones = pd.DataFrame([["FMAT1", "3", "3.4", "B", "C.1", 0.5]], columns=ss.fd_zones.columns)
    ss.fd_overrides = {}
    ss.fd_sel = []
    ss.fd_project = "อาคาร B6"
    ss.pop("fd_cases", None)
    ss.pop("fd_zones_live", None)
    ss.fd_footings = ss.get("fd_footings_live", ss.fd_footings)
    bump(keep=False)


@st.cache_data(show_spinner=False)
def _parse_e2k(data: bytes):
    return parse_e2k(data)


@st.cache_data(show_spinner=False)
def _read_rx(name: str, data: bytes):
    f = io.BytesIO(data)
    f.name = name
    return read_reactions(f)


@st.cache_data(show_spinner=False)
def _read_sched(name: str, data: bytes):
    return read_schedule_file(name, data)


def apply_schedule(df: pd.DataFrame, replace: bool):
    """Button callback: put the imported footing schedule into the editor."""
    current = ss.get("fd_footings_live", ss.fd_footings)
    ss.fd_footings_live = merge_schedule(current, df, replace)
    ss.fd_sched_applied = ss.fd_sched[0]
    bump()


@st.cache_data(show_spinner=False)
def _pdf_pages(data: bytes):
    return pdf_page_images(data, zoom=1.6)


@st.cache_data(show_spinner=False)
def _dxf(data: bytes):
    return dxf_segments(data)


@st.cache_data(show_spinner=False)
def _dwg(data: bytes):
    return dwg_to_dxf(data)


# --------------------------------------------------------------------------
st.title("🧱 ผังฐานราก & เลือกเบอร์ฐานราก (จาก ETABS)")
st.caption("แนบแบบ (PDF / CAD) + ไฟล์ .e2k + Excel Joint Reactions → เลือกเบอร์ฐานรากอัตโนมัติ, "
           "กำหนดขอบเขต FMAT ด้วย Grid, แก้ไขเบอร์รายจุด แล้วดาวน์โหลดเป็น PDF / CAD (DXF)")

with st.sidebar:
    st.header("📁 โครงการ")
    st.text_input("ชื่อโครงการ / อาคาร", key="fd_project")
    st.button("โหลดข้อมูลตัวอย่าง (อาคาร B6)", on_click=load_demo, width="stretch")
    st.caption("ข้อมูลตัวอย่างสร้างตามรูปแบบไฟล์ที่ ETABS ส่งออก — ดาวน์โหลดไปดูรูปแบบได้ด้านล่าง")
    st.download_button("ตัวอย่าง .e2k", demo_e2k().encode(), "B6_demo.e2k", width="stretch")
    st.download_button("ตัวอย่าง Joint Reactions .xlsx", demo_reactions_xlsx(), "B6_demo_Joint_Reactions.xlsx",
                       width="stretch")
    st.download_button("แบบฟอร์มตารางฐานราก .xlsx", template_xlsx(ss.get("fd_footings_live", ss.fd_footings)),
                       "Footing_Schedule.xlsx", width="stretch",
                       help="ตารางเบอร์ฐานรากปัจจุบัน — แก้ใน Excel แล้วแนบกลับในช่องที่ 4")

# --------------------------------------------------------------------------
# 1) Uploads
# --------------------------------------------------------------------------
st.subheader("① แนบไฟล์")
c1, c2, c3, c4 = st.columns(4)
with c1:
    up = st.file_uploader("1. แบบแปลน (PDF / DXF / DWG) — ใช้ดูตำแหน่งฐานราก", type=["pdf", "dxf", "dwg"],
                          key=f"fd_up_plan_{ss.fd_ver}")
    if up is not None:
        ss.fd_plan = (up.name, up.getvalue())
    if ss.get("fd_plan"):
        st.success(f"แบบ: {ss.fd_plan[0]}")
with c2:
    up = st.file_uploader("2. ไฟล์ ETABS .e2k — Grid, พิกัดจุด, Load combination", type=["e2k", "txt", "$et"],
                          key=f"fd_up_e2k_{ss.fd_ver}")
    if up is not None:
        ss.fd_e2k = (up.name, up.getvalue())
    if ss.get("fd_e2k"):
        st.success(f".e2k: {ss.fd_e2k[0]}")
with c3:
    up = st.file_uploader("3. Excel แรงลงเสา (ETABS → Joint Reactions)", type=["xlsx", "xls", "csv"],
                          key=f"fd_up_rx_{ss.fd_ver}")
    if up is not None:
        ss.fd_rx = (up.name, up.getvalue())
    if ss.get("fd_rx"):
        st.success(f"Load: {ss.fd_rx[0]}")
with c4:
    up = st.file_uploader("4. ข้อมูลฐานราก (Excel / PDF / รูป) — เบอร์, จำนวนเข็ม, ขนาดเข็ม, Capacity, B×L×H",
                          type=["xlsx", "xls", "csv", "pdf", "png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"],
                          key=f"fd_up_sched_{ss.fd_ver}")
    if up is not None and (ss.get("fd_sched") or ("",))[0] != up.name + str(up.size):
        ss.fd_sched = (up.name + str(up.size), up.name, up.getvalue())
    if ss.get("fd_sched"):
        st.success(f"ฐานราก: {ss.fd_sched[1]}")

if not ss.get("fd_e2k") or not ss.get("fd_rx"):
    st.info("แนบไฟล์ .e2k และ Excel Joint Reactions (หรือกด **โหลดข้อมูลตัวอย่าง** ที่แถบซ้าย) เพื่อเริ่มต้น\n\n"
            "**Excel จาก ETABS:** Display → Show Tables → Analysis Results → Reactions → *Joint Reactions* → "
            "Export to Excel (ต้องมีคอลัมน์ Joint Label / Unique Name, Output Case, FZ)")
    if ss.get("fd_plan") and ss.fd_plan[0].lower().endswith(".pdf"):
        with st.expander("ดูแบบที่แนบ", expanded=True):
            for i, im in enumerate(_pdf_pages(ss.fd_plan[1])):
                st.image(im, caption=f"หน้า {i + 1}", width="stretch")
    st.stop()

try:
    model = _parse_e2k(ss.fd_e2k[1])
except Exception as e:  # noqa: BLE001
    st.error(f"อ่านไฟล์ .e2k ไม่ได้: {e}")
    st.stop()
try:
    rx, rx_unit = _read_rx(ss.fd_rx[0], ss.fd_rx[1])
except Exception as e:  # noqa: BLE001
    st.error(f"อ่าน Excel ไม่ได้: {e}")
    st.stop()
if not model.grids:
    st.warning("ไม่พบ Grid ในไฟล์ .e2k (ส่วน $ GRIDS)")

x_labels = [g.label for g in model.x_grids]
y_labels = [g.label for g in model.y_grids]

# --------------------------------------------------------------------------
# 2) Load case / combination
# --------------------------------------------------------------------------
st.subheader("② Load ที่ใช้เลือกฐานราก")
cases = list(dict.fromkeys(rx["Case"].tolist()))
if "fd_cases" not in ss or not set(ss.fd_cases) <= set(cases):
    pref = [c for c in cases if "ASD" in c.upper() or "SERV" in c.upper()]
    ss.fd_cases = pref[:1] or [c for c in cases if c in model.combos][:1] or cases[:1]
lc1, lc2, lc3 = st.columns([2.2, 1, 1])
with lc1:
    st.multiselect("Output case / combination (ถ้าเลือกหลายตัว ใช้ค่า FZ มากที่สุด — envelope)", cases, key="fd_cases")
with lc2:
    unit = st.selectbox("หน่วย FZ ใน Excel", ["tonf", "kN", "kgf"], index=["tonf", "kN", "kgf"].index(rx_unit),
                        help="อ่านจากแถวหน่วยใต้หัวตารางอัตโนมัติ")
with lc3:
    tol = st.number_input("ระยะคลาดเคลื่อนเข้า Grid (m)", 0.0, 1.0, 0.05, 0.01,
                          help="จุดที่ห่าง Grid เกินค่านี้จะแสดงระยะเยื้อง เช่น 3.3-0.27/B.1")
with st.expander(f"Load combination ใน .e2k ({len(model.combos)}) • Load pattern ({len(model.load_patterns)}) • "
                 f"Grid X {len(x_labels)} / Y {len(y_labels)} • จุด {len(model.points)}"):
    cc1, cc2 = st.columns(2)
    with cc1:
        st.dataframe(pd.DataFrame([{"Combination": n, "Type": model.combo_types.get(n, ""),
                                    "สูตร": " + ".join(f"{sf:g}{c}" for c, sf in parts)}
                                   for n, parts in model.combos.items()]), hide_index=True, width="stretch")
    with cc2:
        sc = model.length_scale
        st.dataframe(pd.DataFrame(
            [{"Grid": g.label, "แนว": "X (แกนตั้ง)" if g.dir == "X" else "Y (แกนนอน)", "พิกัด (m)": g.coord * sc}
             for g in model.x_grids + model.y_grids]), hide_index=True, width="stretch", height=260)

joints = build_joints(model, rx, ss.fd_cases, unit, tol)
if joints.empty:
    st.error("ไม่พบจุดที่ตรงกันระหว่าง Excel (Joint Label) และพิกัดจุดใน .e2k — ตรวจว่าเลือก output case ถูกต้อง")
    st.stop()
missing = sorted(set(rx["Joint"]) - set(joints["Joint"]) - {""})
if missing:
    st.warning(f"จุดใน Excel ที่ไม่พบพิกัดใน .e2k: {', '.join(missing[:20])}{' …' if len(missing) > 20 else ''}")

# --------------------------------------------------------------------------
# 3) Footing schedule + FMAT zones
# --------------------------------------------------------------------------
st.subheader("③ ตารางฐานราก และขอบเขต FMAT")
sched_imgs, imp = [], None
if ss.get("fd_sched"):
    key_, sname, sdata = ss.fd_sched
    with st.spinner(f"กำลังอ่าน {sname} ..."):
        try:
            imp, imp_notes, sched_imgs = _read_sched(sname, sdata)
        except Exception as e:  # noqa: BLE001
            imp, imp_notes, sched_imgs = None, [f"อ่านไฟล์ไม่ได้: {e}"], []
    applied = ss.get("fd_sched_applied") == key_
    with st.expander(f"📥 ข้อมูลฐานรากจากไฟล์: {sname}" + (" — ใช้แล้ว ✓" if applied else ""), expanded=not applied):
        for n in imp_notes:
            st.caption(f"• {n}")
        if imp is not None:
            st.dataframe(imp, hide_index=True, width="stretch",
                         column_config={"Capacity (t)": st.column_config.NumberColumn(format="%.1f")})
            ia, ib = st.columns([2, 1])
            mode = ia.radio("วิธีนำเข้า", ["แทนที่ตารางทั้งหมด", "อัปเดตเบอร์ที่ชื่อตรงกัน + เพิ่มเบอร์ใหม่"],
                            horizontal=True, key="fd_sched_mode")
            ib.button("ใช้ตารางนี้", type="primary", width="stretch", on_click=apply_schedule,
                      args=(imp, mode.startswith("แทนที่")))
        else:
            st.info("ไฟล์นี้ไม่มีตัวเลขที่อ่านได้ — ดูรูปข้างตารางด้านล่าง แล้วพิมพ์ค่าลงในตารางเบอร์ฐานราก "
                    "(หรือดาวน์โหลด “แบบฟอร์มตารางฐานราก” ที่แถบซ้าย กรอกใน Excel แล้วแนบกลับ)")
t1, t2 = st.columns([1.35, 1])
with t1:
    st.caption("ตารางเบอร์ฐานราก (แก้ได้ทุกช่อง / เพิ่มแถวได้) — ค่าเริ่มต้นเป็นค่าประมาณ ให้ตรวจกับแบบมาตรฐานฐานราก")
    ft = st.data_editor(ss.fd_footings, num_rows="dynamic", hide_index=True, key=f"fd_ed_ft_{ss.fd_ver}",
                        width="stretch", column_config={
                            "Color": st.column_config.TextColumn("สี (hex)", width="small"),
                            "Capacity (t)": st.column_config.NumberColumn(format="%.0f"),
                        })
    ss.fd_footings_live = ft
    footings = footings_from_table(ft)
    bad = [str(r["Footing"]) for _, r in ft.iterrows()
           if str(r["Footing"]).strip() and str(r["Footing"]) != "nan" and str(r["Footing"]) not in
           {f.name for f in footings}]
    if bad:
        st.warning(f"ยังไม่ใช้ในการเลือก (ข้อมูลไม่ครบ): {', '.join(bad)}")
    if sched_imgs:
        with st.expander(f"🖼️ รูปข้อมูลฐานรากที่แนบ ({len(sched_imgs)} หน้า) — ใช้ดูขณะกรอกตาราง",
                         expanded=imp is None):
            pg = st.number_input("หน้า", 1, len(sched_imgs), 1, key="fd_sched_pg") if len(sched_imgs) > 1 else 1
            st.image(sched_imgs[pg - 1], width="stretch")
with t2:
    st.caption("FMAT: เลือกช่วง Grid X และ Grid Y — จุดที่อยู่ในกรอบจะรวมเป็น FMAT นั้น")
    zdf = st.data_editor(
        ss.fd_zones, num_rows="dynamic", hide_index=True, key=f"fd_ed_zone_{ss.fd_ver}", width="stretch",
        column_config={
            "FMAT": st.column_config.TextColumn(default="FMAT1"),
            "Grid X จาก": st.column_config.SelectboxColumn(options=x_labels),
            "Grid X ถึง": st.column_config.SelectboxColumn(options=x_labels),
            "Grid Y จาก": st.column_config.SelectboxColumn(options=y_labels),
            "Grid Y ถึง": st.column_config.SelectboxColumn(options=y_labels),
            "ระยะเผื่อ (m)": st.column_config.NumberColumn(default=0.5, min_value=0.0, step=0.1),
        })
    ss.fd_zones_live = zdf
    zones = []
    for _, r in zdf.iterrows():
        vals = [r.get(c) for c in zdf.columns[:5]]
        if all(isinstance(v, str) and v for v in vals):
            m = r.get("ระยะเผื่อ (m)")
            zones.append(FmatZone(vals[0], vals[1], vals[2], vals[3], vals[4], float(m) if pd.notna(m) else 0.5))
zone_names = list(dict.fromkeys(z.name for z in zones))

crit_opts = list(CRITERIA)
k = st.radio("เกณฑ์เลือกเบอร์ (ทางเลือก)", crit_opts, format_func=lambda i: CRITERIA[i]["label"], horizontal=True,
             key="fd_crit")

overrides = {j: v for j, v in ss.fd_overrides.items() if v and v != "(auto)"}
assigned_all = {i: assign_footings(joints, footings, i, zones, model, overrides, tol) for i in crit_opts}
df = assigned_all[k]
highlight = differs(assigned_all)

by = {f.name: f for f in footings}
n_ft = int(df["Footing"].isin(by).sum())
n_pile = int(sum(by[v].piles for v in df["Footing"] if v in by))
over = df[df["Footing"].astype(str).str.endswith("!")]
mc = st.columns(5)
mc[0].metric("จำนวนจุด", len(df))
mc[1].metric("ฐานราก", n_ft)
mc[2].metric("เข็ม (ต้น)", n_pile)
mc[3].metric("FMAT (จุด)", int(df["Footing"].isin(zone_names).sum()))
mc[4].metric("ทางเลือกได้เบอร์ต่างกัน", len(highlight))
ng = df[~df["OK"] & ~df["Footing"].astype(str).str.endswith("!")]
if len(ng):
    st.warning(f"⚠ {len(ng)} จุดที่แก้เบอร์เองแล้วกำลังไม่พอ (Util เกิน): {', '.join(ng['Grid'] + ' → ' + ng['Footing'])}")
if len(over):
    st.error(f"{len(over)} จุดเกินกำลังฐานรากใหญ่ที่สุดในตาราง: {', '.join(over['Grid'])} — เพิ่มเบอร์ฐานรากหรือกำหนดเป็น FMAT")

# --------------------------------------------------------------------------
# 4) Plan
# --------------------------------------------------------------------------
st.subheader("④ ผังฐานราก — ลากกรอบ/คลิกเลือกจุดบนรูป เพื่อแก้เบอร์หรือสร้าง FMAT")
bg, dxf_lines = None, None
plan = ss.get("fd_plan")
x0, x1, y0, y1 = grid_extent(model, df)
with st.expander("แบบอ้างอิงที่แนบ (วางซ้อนบนผัง)", expanded=False):
    if not plan:
        st.caption("ยังไม่ได้แนบแบบ")
    elif plan[0].lower().endswith(".pdf"):
        pages = _pdf_pages(plan[1])
        pc = st.columns([1, 1, 1, 1, 1, 1])
        pno = pc[0].number_input("หน้า", 1, max(1, len(pages)), 1) - 1
        show_bg = pc[1].toggle("วางซ้อนบนผัง", value=False)
        op = pc[1].slider("ความทึบ", 0.1, 1.0, 0.4)
        bxa = pc[2].number_input("ขอบซ้ายของรูป X (m)", value=float(round(x0 - 6, 2)))
        bxb = pc[3].number_input("ขอบขวาของรูป X (m)", value=float(round(x1 + 6, 2)))
        bya = pc[4].number_input("ขอบล่างของรูป Y (m)", value=float(round(y0 - 6, 2)))
        byb = pc[5].number_input("ขอบบนของรูป Y (m)", value=float(round(y1 + 6, 2)))
        st.caption("ปรับขอบรูปให้ Grid ในแบบ PDF ทับกับ Grid ของโมเดล (ค่าเป็นพิกัดเมตรของโมเดล)")
        if pages:
            if show_bg:
                bg = (pages[pno], (bxa, bxb, bya, byb), op)
            st.image(pages[pno], width="stretch")
    else:
        data = plan[1]
        if plan[0].lower().endswith(".dwg"):
            data = _dwg(plan[1])
            if data is None:
                st.warning("เซิร์ฟเวอร์นี้ยังไม่มีตัวแปลง DWG (LibreDWG / ODA File Converter) — "
                           "ใน AutoCAD ใช้ **Save As → AutoCAD DXF** แล้วแนบไฟล์ .dxf แทน")
        if data:
            try:
                segs, layers = _dxf(data)
            except Exception as e:  # noqa: BLE001
                segs, layers = [], []
                st.error(f"อ่าน DXF ไม่ได้: {e}")
            if segs:
                dc = st.columns([1.2, 1, 1, 2])
                cad_unit = dc[0].selectbox("หน่วยในแบบ CAD", ["mm", "cm", "m"], index=0)
                ox = dc[1].number_input("พิกัด CAD X ของจุด (0,0) โมเดล", value=0.0)
                oy = dc[2].number_input("พิกัด CAD Y ของจุด (0,0) โมเดล", value=0.0)
                lay = dc[3].multiselect("Layer ที่แสดง (ว่าง = ทั้งหมด)", layers)
                if lay:
                    segs, _ = dxf_segments(data, lay)
                f = {"mm": 0.001, "cm": 0.01, "m": 1.0}[cad_unit]
                dxf_lines = [[((x - ox) * f, (y - oy) * f) for x, y in s] for s in segs]
                st.caption(f"{len(segs)} เส้นจากแบบ CAD — แสดงเป็นเส้นสีเทาบนผัง (ใส่ค่า offset ให้ Grid ทับกัน)")

show_piles = st.toggle("แสดงเข็ม", value=True)
sel = set(ss.fd_sel)
fig = plotly_plan(df, model, footings, zones, highlight, sel, bg, dxf_lines, show_piles)
ev = st.plotly_chart(fig, on_select="rerun", selection_mode=("points", "box", "lasso"), key=f"fd_plan_{ss.fd_ver}",
                     width="stretch", config={"displaylogo": False, "scrollZoom": True})
pts = ev.selection.points if hasattr(ev, "selection") else (ev or {}).get("selection", {}).get("points", [])
picked = [str(p["customdata"][0]) for p in pts if p.get("customdata")]
if picked and set(picked) != sel:
    ss.fd_sel = picked
    st.rerun()

sel_df = df[df["Joint"].astype(str).isin(ss.fd_sel)]
st.markdown(f"**จุดที่เลือก: {len(sel_df)}** " + (", ".join(sel_df["Grid"]) if len(sel_df) else
                                                   "— ใช้เครื่องมือ Box/Lasso Select หรือคลิกจุดบนผัง"))
if len(sel_df):
    a1, a2, a3, a4, a5 = st.columns([1.4, 1, 1.2, 1.2, 1])
    choice = a1.selectbox("กำหนดเบอร์ให้จุดที่เลือก", [f.name for f in footings] + zone_names + ["(auto)"],
                          key="fd_assign")
    if a2.button("กำหนด", type="primary", width="stretch"):
        for j in ss.fd_sel:
            ss.fd_overrides[j] = choice
        ss.fd_sel = []
        bump()
        st.rerun()
    new_name = a3.text_input("ชื่อ FMAT ใหม่", value=f"FMAT{len(zone_names) + 1}")
    if a4.button("สร้าง FMAT จากจุดที่เลือก", width="stretch"):
        sc = model.length_scale
        gx = sorted(model.x_grids, key=lambda g: g.coord)
        gy = sorted(model.y_grids, key=lambda g: g.coord)
        near = lambda gs, v: min(gs, key=lambda g: abs(g.coord * sc - v)).label  # noqa: E731
        row = [new_name, near(gx, sel_df["X"].min()), near(gx, sel_df["X"].max()),
               near(gy, sel_df["Y"].min()), near(gy, sel_df["Y"].max()), 0.5]
        ss.fd_zones_live = pd.concat([ss.fd_zones_live, pd.DataFrame([row], columns=ss.fd_zones.columns)],
                                     ignore_index=True)
        for j in ss.fd_sel:
            ss.fd_overrides.pop(j, None)
        ss.fd_sel = []
        bump()
        st.rerun()
    if a5.button("ล้างที่เลือก", width="stretch"):
        ss.fd_sel = []
        bump()
        st.rerun()

# --------------------------------------------------------------------------
# 5) Table (edit per joint)
# --------------------------------------------------------------------------
st.subheader("⑤ ตารางเลือกเบอร์ฐานราก (แก้เบอร์รายจุดได้ที่คอลัมน์ “แก้ไขเบอร์”)")
tbl = df[["Joint", "Grid", "Element", "P", "Auto", "Footing", "Util", "OK", "Source"]].copy()
for i in crit_opts:
    if i != k:
        tbl[f"ทล.{i}"] = assigned_all[i]["Footing"].values
tbl["แก้ไขเบอร์"] = [ss.fd_overrides.get(str(j), "(auto)") for j in tbl["Joint"]]
tbl["Util"] = tbl["Util"] * 100
tbl["ต่างกัน"] = ["●" if str(j) in highlight else "" for j in tbl["Joint"]]
ed = st.data_editor(
    tbl, hide_index=True, width="stretch", height=420, key=f"fd_ed_tbl_{ss.fd_ver}",
    disabled=[c for c in tbl.columns if c != "แก้ไขเบอร์"],
    column_config={
        "P": st.column_config.NumberColumn("P (t)", format="%.1f"),
        "Auto": st.column_config.TextColumn(f"อัตโนมัติ ทล.{k}"),
        "Footing": st.column_config.TextColumn("ใช้จริง"),
        "Util": st.column_config.NumberColumn("Util (%)", format="%.1f"),
        "Source": st.column_config.TextColumn("ที่มา"),
        "OK": st.column_config.CheckboxColumn("ผ่าน"),
        "แก้ไขเบอร์": st.column_config.SelectboxColumn(options=["(auto)"] + [f.name for f in footings] + zone_names),
    })
new_ov = {str(j): v for j, v in zip(ed["Joint"], ed["แก้ไขเบอร์"]) if v and v != "(auto)"}
if new_ov != overrides:
    ss.fd_overrides = new_ov
    bump()
    st.rerun()
bc1, bc2 = st.columns([1, 4])
if bc1.button("ล้างการแก้ไขทั้งหมด", disabled=not overrides):
    ss.fd_overrides = {}
    bump()
    st.rerun()
bc2.caption("การแก้ไขเบอร์ใช้กับทุกทางเลือก (ทล.1–4) • ‘ต่างกัน’ = ทางเลือก 1–4 ได้เบอร์ไม่เท่ากัน (ตัวแดงในแบบ)")

with st.expander("สรุปจำนวนฐานรากและเข็ม (ทุกทางเลือก)", expanded=True):
    st.dataframe(summary_table(assigned_all, footings, zone_names).astype(str), hide_index=True, width="stretch")
    for z, p in zone_loads(df, zone_names).items():
        st.markdown(f"• **{z}** : {int((df['Footing'] == z).sum())} จุด, ΣP = **{p:.1f} t** (รอออกแบบ)")

# --------------------------------------------------------------------------
# 6) Downloads
# --------------------------------------------------------------------------
st.subheader("⑥ ดาวน์โหลด")
d1, d2, d3 = st.columns([1.4, 1, 1])
with d1:
    plot_crit = st.multiselect("ทางเลือกที่จะวางในแบบ", crit_opts, default=[k],
                               format_func=lambda i: f"ทางเลือก {i}", key="fd_dl_crit")
with d2:
    cad_unit_out = st.selectbox("หน่วยแบบ CAD", ["mm", "m"], index=0)
with d3:
    piles_out = st.checkbox("วาดเข็มในแบบ", value=True)
src = (f"Load: {ss.fd_rx[0]} ({', '.join(ss.fd_cases)}) ; พิกัด: {ss.fd_e2k[0]}"
       + (f" ; แปลน: {plan[0]}" if plan else ""))
stem = f"{date.today():%y-%m-%d}_{ss.fd_project.replace(' ', '_')}_Foundation"
plot_crit = plot_crit or [k]
g1, g2, g3 = st.columns(3)
with g1:
    if st.button("สร้าง PDF", width="stretch", type="primary"):
        with st.spinner("กำลังสร้าง PDF ..."):
            ss.fd_pdf = build_pdf(assigned_all, plot_crit, model, footings, zones, ss.fd_project, src, piles_out)
    if ss.get("fd_pdf"):
        st.download_button("⬇️ ดาวน์โหลด PDF (A3)", ss.fd_pdf, f"{stem}.pdf", "application/pdf", width="stretch")
with g2:
    if st.button("สร้างไฟล์ CAD (DXF)", width="stretch", type="primary"):
        with st.spinner("กำลังสร้าง DXF ..."):
            ss.fd_dxf = build_dxf(assigned_all, plot_crit, model, footings, zones, ss.fd_project, cad_unit_out,
                                  piles_out)
    if ss.get("fd_dxf"):
        st.download_button("⬇️ ดาวน์โหลด CAD (.dxf)", ss.fd_dxf, f"{stem}.dxf", "application/dxf", width="stretch")
        st.caption("เปิดใน AutoCAD ได้โดยตรง (Save As .dwg ได้) • แยก Layer: S-GRID, S-FOOTING, S-PILE, S-TEXT-…, S-FMAT")
with g3:
    out = io.BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        summary_table(assigned_all, footings, zone_names).astype(str).to_excel(xw, sheet_name="Summary", index=False)
        full = df[["Joint", "Grid", "Element", "X", "Y", "P"]].copy()
        for i in crit_opts:
            full[f"ทล.{i}"] = assigned_all[i]["Footing"].values
            full[f"Util ทล.{i}"] = assigned_all[i]["Util"].values
        full["แก้ไขเบอร์"] = [ss.fd_overrides.get(str(j), "") for j in full["Joint"]]
        full.to_excel(xw, sheet_name="Footing Selection", index=False)
        ft.to_excel(xw, sheet_name="Footing Schedule", index=False)
    st.download_button("⬇️ ตาราง Excel", out.getvalue(), f"{stem}.xlsx", width="stretch")
