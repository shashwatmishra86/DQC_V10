
# Docket QC Checker — PyPDF2 + Materials

Adds **Material Mismatch** checks (Carcass, Shutter/Front, Finish, Edge band, Handle/Channel) to the working PyPDF2 app.

## Deploy Fresh
1. Create a new GitHub repo (e.g., `docket-qc-materials`).
2. Upload `app.py`, `requirements.txt`, `README.md` to the repo root.
3. Go to https://share.streamlit.io → New app → select repo → main file `app.py` → Deploy.

## Notes
- Parsing is heuristic. If your templates use different labels, tweak MAT_PATTERNS in `app.py`.
- Only mismatches are shown in the tables to keep reports clean.
