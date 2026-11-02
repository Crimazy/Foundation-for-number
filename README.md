# 🧱 ผังฐานราก & เลือกเบอร์ฐานราก (จาก ETABS)

เว็บแอป Streamlit: แนบแบบ (PDF / CAD) + ไฟล์ ETABS `.e2k` + Excel Joint Reactions →
เลือกเบอร์ฐานรากเข็มอัตโนมัติ, กำหนด FMAT ด้วยช่วง Grid, แก้เบอร์รายจุดบนผัง แล้วดาวน์โหลดเป็น PDF / DXF / Excel

## วิธีใช้งาน

```bash
pip install -r requirements.txt
streamlit run app.py
```

กด **โหลดข้อมูลตัวอย่าง (อาคาร B6)** ที่แถบซ้ายเพื่อดูตัวอย่างได้ทันที

ทดสอบ: `python -m pytest -q`

## ขั้นตอน

1. **แนบไฟล์**
   - แบบแปลน **PDF / DXF / DWG** — ใช้ดูตำแหน่งและวางซ้อนบนผัง (PDF: เลือกหน้าและปรับขอบรูปให้ Grid ทับกัน,
     DXF: ใส่หน่วยและพิกัดจุด (0,0) ของโมเดล) • DWG แปลงได้เมื่อเครื่องมี LibreDWG `dwg2dxf` หรือ ODA File Converter —
     ถ้าไม่มีให้ Save As → DXF ใน AutoCAD
   - **.e2k** — อ่าน Grid, พิกัดจุด, เสา (หน้าตัด) / ผนัง, Load pattern และ Load combination
   - **Excel Joint Reactions** จาก ETABS (Joint Label / Unique Name, Output Case, FZ — อ่านหน่วยจากแถวหน่วยอัตโนมัติ: tonf / kN / kgf)
2. เลือก output case (เลือกหลายตัว = ใช้ FZ มากที่สุด) → แต่ละจุดได้ชื่อ Grid อัตโนมัติ เช่น `2/C`, `3.3-0.27/B.1`
3. **ตารางเบอร์ฐานราก** (เข็ม/ฐาน, Ø เข็ม, Capacity, B × L × H, สี) แก้ไข/เพิ่มได้ — ค่าเริ่มต้นเป็นค่าประมาณ ต้องตรวจกับแบบมาตรฐาน
4. เกณฑ์เลือกเบอร์ 4 ทางเลือก: ทล.1 (P+W) ≤ Cap • ทล.2 (P+W) ≤ 1.05Cap • ทล.3 P ≤ Cap • ทล.4 P ≤ 1.05Cap (W = Area × H × 2.4)
   — เลือกฐานที่ Capacity น้อยที่สุดที่ผ่าน
5. **FMAT**: กำหนดช่วง Grid X / Y (เช่น 3 → 3.4, B → C.1) หรือ ลากกรอบเลือกจุดบนผังแล้วกด “สร้าง FMAT” — แสดง ΣP
6. **แก้เบอร์รายจุด**: ลากกรอบ/คลิกบนผังแล้วกำหนดเบอร์ หรือแก้ในคอลัมน์ “แก้ไขเบอร์” ของตาราง (ตรวจ Util ให้ทันที)
7. **ดาวน์โหลด**: PDF A3 (สรุปจำนวนฐาน/เข็ม ทุกทางเลือก, ผังฐานรากตามสเกลพร้อมเบอร์และ P, ตารางเลือกเบอร์),
   **CAD (.dxf)** แยก Layer (S-GRID, S-FOOTING, S-PILE, S-TEXT-…, S-FMAT; หน่วย mm หรือ m) และตาราง Excel
- ปุ่ม “โหลดข้อมูลตัวอย่าง (อาคาร B6)” สร้างไฟล์ .e2k / Excel ตัวอย่างในรูปแบบที่ ETABS ส่งออก (`foundation_demo.py`)
- ฟอนต์ไทยสำหรับ PDF: `fonts/Loma.otf` (TLWG, GPL + font exception — ดู `fonts/Loma-COPYRIGHT.txt`)
- โมดูล: `app.py` (หน้าเว็บ Streamlit), `foundation.py` (อ่านไฟล์ + เลือกเบอร์), `foundation_draw.py` (Plotly / PDF / DXF), ทดสอบ `tests/test_foundation.py`
