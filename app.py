
import io
import re
import pandas as pd
import streamlit as st
import PyPDF2

st.set_page_config(page_title="Docket QC Checker — PyPDF2 + Materials", layout="wide")
st.title("🧰 Docket QC Checker — PyPDF2")
st.caption("Adds material mismatch checks (Carcass, Shutter/Front, Finish, Edge band, Handle/Channel) + previous QC rules.")

def extract_pages_text(pdf_bytes):
    reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return pages

CHAIN_LINE = re.compile(r'\b(\d{2,4})(?:\s*\+\s*|\s+)(\d{2,4})(?:(?:\s*\+\s*|\s+)(\d{2,4})){1,40}\s*(?:=\s*)?(\d{2,5})?\b')
NUMBER_ONLY = re.compile(r'\b\d{2,5}\b')
MODULE_WITH_TRIPLE = re.compile(r'(?P<mod>[A-Za-z0-9\-_/]+)\s*[-: ]\s*(?P<w>\d{2,4})\s*[x×]\s*(?P<d>\d{2,4})\s*[x×]\s*(?P<h>\d{2,4})')
MODULE_SPACE_TRIPLE = re.compile(r'(?P<mod>[A-Za-z0-9\-_/]+)\s+(?P<w>\d{2,4})\s*[x×]\s*(?P<d>\d{2,4})\s*[x×]\s*(?P<h>\d{2,4})')

MAT_PATTERNS = {
    "Carcass": re.compile(r'(?:\bCARCASS\b|\bBOX\b|\bCABINET\b)\s*[:\-]?\s*(?P<val>[A-Za-z0-9\-/+(),.& ]{2,60})', re.I),
    "Shutter/Front": re.compile(r'(?:\bSHUTTER\S*\b|\bFRONT\S*\b|\bDOOR\S*\b)\s*[:\-]?\s*(?P<val>[A-Za-z0-9\-/+(),.& ]{2,60})', re.I),
    "Finish": re.compile(r'(?:\bFINISH\b|\bLAMINATE\b|\bVENEER\b|\bPU\b|\bPAINT\b)\s*[:\-]?\s*(?P<val>[A-Za-z0-9\-/+(),.& ]{2,60})', re.I),
    "Edge Band": re.compile(r'(?:\bEDGE\s*BAND\S*\b|\bEDGEBAND\S*\b)\s*[:\-]?\s*(?P<val>[A-Za-z0-9\-/+(),.& ]{2,60})', re.I),
    "Handle/Channel": re.compile(r'(?:\bHANDLE\S*\b|\bGOLA\b|\bCHANNEL\b|\bPROFILE\b)\s*[:\-]?\s*(?P<val>[A-Za-z0-9\-/+(),.& ]{2,60})', re.I),
}
MODULE_TOKEN = re.compile(r'\b([A-Za-z]{1,4}\d{1,3}[A-Za-z0-9\-]*)\b')

def section_label(line):
    t = line.upper()
    if "PLAN VIEW - BASE" in t: return "Plan Base"
    if "PLAN VIEW - WALL" in t: return "Plan Wall"
    if "PLAN VIEW - LOFT" in t: return "Plan Loft"
    if "ELEVATION A" in t and "INTERNAL" not in t: return "Elevation A"
    if "ELEVATION B" in t and "INTERNAL" not in t: return "Elevation B"
    if "ELEVATION C" in t and "INTERNAL" not in t: return "Elevation C"
    if "ELEVATION D" in t and "INTERNAL" not in t: return "Elevation D"
    if "CONSOLIDATED CABINETS LIST" in t or "CONSOLATED CABINETS LIST" in t: return "Consolidated"
    return None

def normalize_mat(s):
    if not s: return ""
    import re as _re
    t = _re.sub(r'[\s/\\\-_,.()+]+', ' ', s.lower()).strip()
    t = t.replace("plywood", "ply").replace("mr grade", "mr").replace("bwr grade", "bwr")
    return t

def parse_records(pages):
    rows = []
    current = "Unknown"
    for pageno, text in enumerate(pages, start=1):
        lines = (text or "").splitlines()
        for line in lines:
            lbl = section_label(line)
            if lbl:
                current = lbl
            for m in MODULE_WITH_TRIPLE.finditer(line):
                rows.append({"page": pageno, "context": current, "type": "module_dim",
                             "module": m.group("mod"),
                             "w": int(m.group("w")), "d": int(m.group("d")), "h": int(m.group("h")),
                             "line": line.strip()})
            for m in MODULE_SPACE_TRIPLE.finditer(line):
                rows.append({"page": pageno, "context": current, "type": "module_dim",
                             "module": m.group("mod"),
                             "w": int(m.group("w")), "d": int(m.group("d")), "h": int(m.group("h")),
                             "line": line.strip()})
            m = CHAIN_LINE.search(line)
            if m:
                nums = [int(x) for x in NUMBER_ONLY.findall(line)]
                if len(nums) >= 4:
                    rows.append({"page": pageno, "context": current, "type": "chain",
                                 "numbers": nums, "line": line.strip()})
            module_on_line = None
            mm = MODULE_TOKEN.search(line)
            if mm:
                module_on_line = mm.group(1)
            for cat, pat in MAT_PATTERNS.items():
                for matm in pat.finditer(line):
                    val = matm.group("val").strip()
                    rows.append({"page": pageno, "context": current, "type": "material",
                                 "module": module_on_line or f"UNKNOWN@{pageno}",
                                 "category": cat, "value": val, "value_norm": normalize_mat(val),
                                 "line": line.strip()})
    return pd.DataFrame(rows)

def check_elevation_vs_consolidated(df):
    elev = df[(df["type"]=="module_dim") & (df["context"].str.startswith("Elevation"))].copy()
    cons = df[(df["type"]=="module_dim") & (df["context"]=="Consolidated")].copy()
    if elev.empty or cons.empty:
        return pd.DataFrame()
    elev_keyed = elev.groupby("module").agg({"w":"first","d":"first","h":"first","page":"first","line":"first","context":"first"})
    cons_keyed = cons.groupby("module").agg({"w":"first","d":"first","h":"first","page":"first","line":"first"})
    out = []
    for mod, er in elev_keyed.iterrows():
        if mod in cons_keyed.index:
            cr = cons_keyed.loc[mod]
            mism = []
            if er["w"] != cr["w"]:
                mism.append(f"Width {er['w']} vs {cr['w']}")
            if er["d"] != cr["d"]:
                mism.append(f"Depth {er['d']} vs {cr['d']}")
            if er["h"] != cr["h"]:
                mism.append(f"Height {er['h']} vs {cr['h']}")
            if mism:
                out.append({"Check": "Elevation vs Consolidated (Dims)",
                            "Module": mod,
                            "Elevation (W×D×H)": f"{er['w']}×{er['d']}×{er['h']}",
                            "Consolidated (W×D×H)": f"{cr['w']}×{cr['d']}×{cr['h']}",
                            "Mismatch": "; ".join(mism),
                            "Elevation Page": int(er["page"]),
                            "Consolidated Page": int(cr["page"]) })
    return pd.DataFrame(out)

def check_sum_chains(df):
    out = []
    for _, r in df[df["type"]=="chain"].iterrows():
        nums = r["numbers"]
        ctx = r["context"]
        parts = nums[:-1]
        stated = nums[-1]
        if sum(parts) == stated:
            result = "Match"
            used_total = stated
        else:
            cand = max(nums)
            result = "Match" if sum(parts) == cand else "Mismatch"
            used_total = cand
        if result == "Mismatch":
            out.append({"Drawing Type": ctx,
                        "Page": int(r["page"]),
                        "Parts": "+".join(map(str, parts)),
                        "Computed Sum": sum(parts),
                        "Stated/Heuristic Total": used_total,
                        "Result": result,
                        "Line": r["line"]})
    return pd.DataFrame(out)

def check_material_mismatches(df):
    mats = df[df["type"]=="material"].copy()
    if mats.empty:
        return pd.DataFrame()
    consolidated = mats[mats["context"]=="Consolidated"].copy()
    drawing = mats[mats["context"].isin(["Elevation A","Elevation B","Elevation C","Elevation D","Plan Base","Plan Wall","Plan Loft"])].copy()
    if consolidated.empty or drawing.empty:
        return pd.DataFrame()
    cons_first = consolidated.sort_values("page").groupby(["module","category"]).agg(
        list_page=("page","first"),
        list_line=("line","first"),
        list_value=("value","first"),
        list_value_norm=("value_norm","first")
    )
    draw_first = drawing.sort_values("page").groupby(["module","category"]).agg(
        draw_page=("page","first"),
        draw_context=("context","first"),
        draw_line=("line","first"),
        draw_value=("value","first"),
        draw_value_norm=("value_norm","first")
    )
    joined = draw_first.join(cons_first, how="inner")
    if joined.empty:
        return pd.DataFrame()
    rows = []
    for (mod, cat), r in joined.iterrows():
        dv = (r.get("draw_value_norm") or "").strip()
        cv = (r.get("list_value_norm") or "").strip()
        if dv and cv and dv != cv:
            rows.append({"Check": "Material Mismatch",
                         "Module": mod,
                         "Category": cat,
                         "Drawing Context": r.get("draw_context"),
                         "Drawing Value": r.get("draw_value"),
                         "Consolidated Value": r.get("list_value"),
                         "Drawing Page": int(r.get("draw_page") or 0),
                         "List Page": int(r.get("list_page") or 0)})
    return pd.DataFrame(rows)

pdf = st.file_uploader("Upload docket PDF", type=["pdf"])
if not pdf:
    st.info("Upload a text-based docket PDF (OCR if needed).")
    st.stop()

pdf_bytes = pdf.read()
pages = extract_pages_text(pdf_bytes)

st.subheader("Debug: Page 1 Text Preview")
st.code((pages[0] or "")[:1500] if pages else "[No pages]", language="text")

df = parse_records(pages)
with st.expander("Parsed Records (debug)"):
    st.dataframe(df, use_container_width=True)

issues = []

st.subheader("❌ Elevation ↔ Consolidated — Dimension mismatches")
dims_df = check_elevation_vs_consolidated(df)
if dims_df.empty:
    st.success("No Elevation vs Consolidated dimension mismatches found.")
else:
    st.dataframe(dims_df, use_container_width=True)
    dims_df.insert(0, "Check Type", "Dims: Elevation vs Consolidated")
    issues.append(dims_df)

st.subheader("🧮 Sum Check — Mismatches only")
sum_df = check_sum_chains(df)
if sum_df.empty:
    st.info("No dimension chains mismatched (or none detected).")
else:
    st.dataframe(sum_df, use_container_width=True)
    sum_df.insert(0, "Check Type", "Sum Check")
    issues.append(sum_df)

st.subheader("🎨 Material Mismatch — by Module & Category")
mat_df = check_material_mismatches(df)
if mat_df.empty:
    st.success("No material mismatches found (or no materials detected).")
else:
    st.dataframe(mat_df, use_container_width=True)
    mat_df.insert(0, "Check Type", "Material Mismatch")
    issues.append(mat_df)

if issues:
    final = pd.concat(issues, ignore_index=True)
    st.download_button("⬇️ Download Issues (Excel)", data=final.to_excel(index=False),
                       file_name="QC_Issues.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
else:
    st.success("No issues detected by the current heuristics.")
