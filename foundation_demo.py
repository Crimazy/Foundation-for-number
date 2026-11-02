"""Demo data (building B6) in the same formats ETABS exports: .e2k text + Joint Reactions .xlsx.

Grid spacing is approximate (read off the sample drawing); loads follow the
sample footing-selection sheet (ASD_DL+SDL+LL) split into DL / SDL / LL.
"""
from __future__ import annotations

import io

import pandas as pd

X_GRIDS = [("1", 0.0), ("2", 6.0), ("3", 14.0), ("3.1", 14.5), ("3.3", 16.5), ("3.4", 20.0),
           ("4", 22.0), ("5", 30.0), ("6", 38.0), ("7", 46.0), ("8", 52.0)]
Y_GRIDS = [("A", 0.0), ("B", 6.0), ("B.1", 8.8), ("C", 9.5), ("C.1", 11.3), ("D", 17.5), ("E", 25.0),
           ("F", 32.5), ("G", 40.0), ("G.1", 46.0), ("H", 47.5), ("J", 49.0), ("J.1", 49.5), ("J.2", 52.0)]

# joint, grid x, grid y, x offset (m), section ("" = wall end), P service (t)
JOINTS = [
    (57, "2", "A", 0, "C500x500", 204.9), (59, "1", "A", 0, "C500x500", 103.2),
    (2379, "3", "A", 0, "C500x500", 157.1), (3, "8", "B", 0, "C500x500", 45.1),
    (4, "7", "B", 0, "C500x500", 110.7), (5, "6", "B", 0, "C500x500", 122.5),
    (6, "5", "B", 0, "C500x500", 134.3), (7, "4", "B", 0, "C500x500", 86.6),
    (8, "1", "B", 0, "C500x500", 116.1), (9, "2", "B", 0, "C500x500", 142.8),
    (10, "3", "B", 0, "", 107.2), (13, "8", "C", 0, "C500x800", 139.1),
    (14, "7", "C", 0, "C500x800", 252.9), (15, "6", "C", 0, "C500x800", 309.5),
    (16, "5", "C", 0, "C500x800", 276.2), (17, "4", "C", 0, "C500x800", 209.0),
    (18, "3", "C", 0, "C500x800", 152.6), (19, "2", "C", 0, "C500x800", 363.2),
    (20, "1", "C", 0, "C500x800", 178.4), (24, "8", "D", 0, "C500x800", 172.8),
    (25, "8", "E", 0, "C500x800", 188.1), (26, "8", "F", 0, "C500x800", 166.4),
    (27, "8", "G", 0, "C500x800", 195.2), (28, "7", "D", 0, "C500x500", 171.0),
    (29, "7", "E", 0, "C500x500", 169.3), (30, "7", "F", 0, "C500x500", 170.3),
    (31, "7", "G", 0, "C500x500", 165.5), (32, "6", "D", 0, "C500x500", 201.0),
    (33, "6", "E", 0, "C500x500", 194.0), (34, "6", "F", 0, "C500x500", 196.7),
    (35, "6", "G", 0, "C500x500", 188.6), (36, "5", "D", 0, "C500x500", 198.9),
    (37, "5", "E", 0, "C500x500", 190.1), (38, "5", "F", 0, "C500x500", 191.9),
    (39, "5", "G", 0, "C500x500", 186.6), (40, "4", "D", 0, "C500x500", 170.1),
    (41, "4", "E", 0, "C500x500", 192.7), (42, "4", "F", 0, "C500x500", 191.7),
    (43, "4", "G", 0, "C500x500", 186.7), (44, "3", "D", 0, "C500x500", 228.6),
    (45, "3", "E", 0, "C500x500", 197.9), (46, "3", "F", 0, "C500x500", 196.3),
    (47, "3", "G", 0, "C500x500", 189.1), (48, "2", "D", 0, "C500x500", 226.2),
    (49, "2", "E", 0, "C500x500", 170.3), (50, "2", "F", 0, "C500x500", 169.5),
    (51, "2", "G", 0, "C500x500", 165.4), (52, "1", "D", 0, "C500x800", 196.9),
    (53, "1", "E", 0, "C500x800", 177.9), (54, "1", "F", 0, "C500x800", 157.5),
    (55, "1", "G", 0, "C500x800", 172.0), (68, "6", "H", 0, "C500x800", 279.8),
    (69, "5", "H", 0, "C500x800", 280.3), (70, "4", "H", 0, "C500x800", 281.4),
    (71, "3", "H", 0, "C500x800", 275.8), (72, "2", "H", 0, "C500x800", 248.9),
    (73, "7", "H", 0, "C500x800", 285.5), (2, "3.3", "B", 0, "", 114.8),
    (77, "3", "B.1", 0, "", 93.6), (78, "3.3", "B.1", 0, "", 97.4),
    (80, "3.1", "B.1", 0, "", 24.2), (81, "3.3", "B.1", -0.27, "", 5.6),
    (82, "3.4", "C", 0, "", 28.7), (83, "3.4", "B", 0, "", 71.6),
    (1, "3.3", "C.1", 0, "", 178.4), (11, "3.4", "C.1", 0, "", 126.2),
    (12, "1", "J", 0, "C500x800", 101.4), (79, "8", "J", 0, "C500x800", 150.7),
    (98, "6", "J.2", 0, "C200x200", 30.5), (99, "5", "J.2", 0, "C200x200", 13.4),
    (100, "4", "J.2", 0, "C200x200", 13.7), (101, "3", "J.2", 0, "C200x200", 28.9),
    (102, "2", "J.2", 0, "C200x200", 24.5), (103, "7", "J.2", 0, "C200x200", 17.4),
    (104, "1", "J.2", 0, "C200x200", 5.4),
]

SPLIT = {"DL": 0.60, "SDL": 0.10, "LL": 0.30}
COMBOS = {
    "ASD_DL+SDL+LL": {"DL": 1.0, "SDL": 1.0, "LL": 1.0},
    "U01_1.4DL+1.7LL": {"DL": 1.4, "SDL": 1.4, "LL": 1.7},
    "U02_1.2DL+1.6LL": {"DL": 1.2, "SDL": 1.2, "LL": 1.6},
}


def _xy(gx: str, gy: str, dx: float) -> tuple[float, float]:
    return dict(X_GRIDS)[gx] + dx, dict(Y_GRIDS)[gy]


def demo_e2k() -> str:
    L = ["$ File B6_demo.e2k  (demo — generated)", "", "$ PROGRAM INFORMATION", '  PROGRAM  "ETABS"  VERSION "21.0.0"', "",
         "$ CONTROLS", '  UNITS  "TONF"  "M"  "C"', "",
         "$ STORIES - IN SEQUENCE FROM TOP",
         '  STORY "Story2"  HEIGHT 4  MASTERSTORY "Yes"',
         '  STORY "Story1"  HEIGHT 3.65  SIMILARTO "Story2"',
         '  STORY "Base"  ELEV 0', "", "$ GRIDS",
         '  GRIDSYSTEM "G1"  TYPE "CARTESIAN"  BUBBLESIZE 1.25']
    for lab, c in X_GRIDS:
        L.append(f'  GRID "G1"  LABEL "{lab}"  DIR "X"  COORD {c}  VISIBLE "Yes"  BUBBLELOC "Default"')
    for lab, c in Y_GRIDS:
        L.append(f'  GRID "G1"  LABEL "{lab}"  DIR "Y"  COORD {c}  VISIBLE "Yes"  BUBBLELOC "Default"')
    L += ["", "$ LOAD PATTERNS"]
    L += ['  LOADPATTERN "DL"  TYPE  "Dead"  SELFWEIGHT  1', '  LOADPATTERN "SDL"  TYPE  "Super Dead"  SELFWEIGHT  0',
          '  LOADPATTERN "LL"  TYPE  "Live"  SELFWEIGHT  0']
    L += ["", "$ POINT COORDINATES"]
    for j, gx, gy, dx, _, _ in JOINTS:
        x, y = _xy(gx, gy, dx)
        L.append(f'  POINT "{j}"  {x:g} {y:g}')
    L += ["", "$ LINE CONNECTIVITIES"]
    for j, *_rest in JOINTS:
        if _rest[3]:
            L.append(f'  LINE  "C{j}"  COLUMN  "{j}"  "{j}"  1')
    walls = [(10, 77), (77, 80), (80, 81), (81, 78), (78, 2), (2, 83), (83, 82), (82, 11), (11, 1)]
    L += ["", "$ AREA CONNECTIVITIES"]
    for i, (a, b) in enumerate(walls, 1):
        L.append(f'  AREA "W{i}"  PANEL  4  "{a}"  "{b}"  "{b}"  "{a}"  1  1  0  0')
    L += ["", "$ POINT ASSIGNS"]
    for j, *_ in JOINTS:
        L.append(f'  POINTASSIGN  "{j}"  "Base"  RESTRAINT "UX UY UZ RX RY RZ"')
    L += ["", "$ LINE ASSIGNS"]
    for j, gx, gy, dx, sec, _ in JOINTS:
        if sec:
            L.append(f'  LINEASSIGN  "C{j}"  "Story1"  SECTION "{sec}"  MINNUMSTA 3')
    L += ["", "$ LOAD COMBINATIONS"]
    for name, parts in COMBOS.items():
        L.append(f'  COMBO "{name}"  TYPE "Linear Add"')
        for case, sf in parts.items():
            L.append(f'  COMBO "{name}"  LOADCASE "{case}"  SF {sf}')
    L += ["", "$ END OF MODEL FILE", ""]
    return "\n".join(L)


def demo_reactions_xlsx() -> bytes:
    rows = []
    for j, gx, gy, dx, sec, P in JOINTS:
        base = {c: P * f for c, f in SPLIT.items()}
        cases = [(c, "LinStatic", v) for c, v in base.items()]
        cases += [(n, "Combination", sum(base[c] * sf for c, sf in parts.items())) for n, parts in COMBOS.items()]
        for case, ctype, fz in cases:
            rows.append(["Base", j, j, case, ctype, "", round(0.004 * fz, 3), round(-0.003 * fz, 3), round(fz, 3),
                         round(0.01 * fz, 3), round(-0.008 * fz, 3), 0.0])
    cols = ["Story", "Joint Label", "Unique Name", "Output Case", "Case Type", "Step Type",
            "FX", "FY", "FZ", "MX", "MY", "MZ"]
    units = ["", "", "", "", "", "", "tonf", "tonf", "tonf", "tonf-m", "tonf-m", "tonf-m"]
    df = pd.DataFrame([units] + rows, columns=cols)
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as xw:
        pd.DataFrame([["TABLE:  Joint Reactions"]]).to_excel(xw, sheet_name="Joint Reactions", index=False, header=False)
        df.to_excel(xw, sheet_name="Joint Reactions", index=False, startrow=1)
    return bio.getvalue()
