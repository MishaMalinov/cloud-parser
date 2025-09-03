import re
import sys
import requests
import pandas as pd
from config import EXCEL_TABLE

def to_csv_from_url(url: str, out_path: str = "sheet.csv"):
    """
    Завантажує Google Sheet за будь-яким посиланням (htmlview, edit, view)
    і зберігає її у CSV (поточний gid).
    """
    # Спроба побудувати пряме CSV-посилання
    m = re.search(r"/spreadsheets/(?:u/\d+/)?d/([^/]+)/", url)
    gid = None

    # gid може бути в #gid= або параметрах запиту
    gid_match = re.search(r"[#?&]gid=(\d+)", url)
    if gid_match:
        gid = gid_match.group(1)

    if m and gid:
        sheet_id = m.group(1)
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        r = requests.get(csv_url, timeout=30)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        print(f"Saved: {out_path}")
        return

    # Фолбек: парсити HTML-представлення першої таблиці
    print("Direct CSV URL not found; falling back to parsing HTML…")
    tables = pd.read_html(url)
    if not tables:
        raise RuntimeError("No tables found on the page.")
    tables[0].to_csv(out_path, index=False)
    print(f"Saved (parsed HTML): {out_path}")

if __name__ == "__main__":
    # Використання:
    # python grab_sheet.py "https://docs.google.com/…/htmlview#gid=0" output.csv
    
    url = EXCEL_TABLE
    out = "excel_table.csv"
    to_csv_from_url(url, out)
