#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Set

# Імпортуємо з твого краулера
# Файл recursive_crawler.py має лежати поруч або бути в PYTHONPATH
from recursive_crawler import run, flatten, save_json, IMAGE_EXTENSIONS  # type: ignore

# ───────── Утиліти ─────────

def read_processed(path: Path) -> Set[str]:
    """
    Зчитує список уже опрацьованих брендів (по одному в рядку, формат: 'YYYY-mm-ddTHH:MM:SSZ<TAB>Brand').
    Якщо файл відсутній — повертає порожню множину.
    """
    done: Set[str] = set()
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            brand = parts[1] if len(parts) == 2 else parts[0]
            done.add(brand)
    return done

def append_processed(path: Path, brand: str) -> None:
    ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\t{brand}\n")

def sanitize_filename(name: str) -> str:
    """
    Робить безпечну назву файлу: замінює недозволені символи, обрізає крайні крапки/пробіли.
    Не змінює регістр.
    """
    safe = "".join(ch if ch.isalnum() or ch in (" ", "-", "_", ".", "(", ")", "і", "І", "ї", "Ї", "є", "Є", "ґ", "Ґ") else "_" for ch in name)
    safe = "_".join(safe.split())  # пробіли -> _
    safe = safe.strip(" ._")
    return safe or "brand"

def read_csv_rows(csv_path: Path, col_brand: str, col_link: str):
    """
    Генерує кортежі (brand, link) з CSV. Підтримує UTF-8 та UTF-8-SIG.
    """
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in (col_brand, col_link) if c not in reader.fieldnames]
        if missing:
            raise SystemExit(f"CSV is missing columns: {missing}. Found: {reader.fieldnames}")
        for row in reader:
            brand = (row.get(col_brand) or "").strip()
            link = (row.get(col_link) or "").strip()
            if not brand or not link:
                continue
            yield brand, link

# ───────── Основна логіка ─────────

def main():
    parser = argparse.ArgumentParser(
        description="Batch crawl QNAP folders per brand CSV and save per-brand JSON."
    )
    parser.add_argument("--csv", required=True, help="Path to CSV with columns 'Бренд,Посилання'")
    parser.add_argument("--outdir", default="out", help="Directory to store JSON files")
    parser.add_argument("--processed", default="processed_brands.log", help="Path to file with already processed brands")
    parser.add_argument("--depth", type=int, default=None, help="Max crawl depth (None = full)")
    parser.add_argument("--sleep", type=float, default=0.5, help="Sleep seconds between brands")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite JSON even if brand is already processed")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    outdir = Path(args.outdir)
    processed_path = Path(args.processed)

    outdir.mkdir(parents=True, exist_ok=True)

    processed = read_processed(processed_path)
    print(f"Loaded processed brands: {len(processed)}")

    total = 0
    success = 0
    failed = 0

    for brand, link in read_csv_rows(csv_path, "Бренд", "Посилання"):
        total += 1

        # Пропустити, якщо вже опрацьовано і не просили перезапис
        if (brand in processed) and not args.overwrite:
            print(f"[SKIP] {brand} — already processed")
            continue

        safe_name = sanitize_filename(brand)
        out_json = outdir / f"{safe_name}.json"

        print(f"\n=== [{total}] {brand} ===")
        print(f"URL: {link}")
        try:
            tree = run(link, max_depth=args.depth)
            rows = flatten(tree)

            # Запис у JSON
            save_json(
                tree,
                rows,
                out_path=str(out_json),
                meta={
                    "brand": brand,
                    "root_url": link,
                    "max_depth": args.depth,
                    "image_extensions": IMAGE_EXTENSIONS,
                    "generated_at_local": datetime.now().isoformat(timespec="seconds"),
                },
            )
            print(f"[OK ] Saved -> {out_json}")

            # Позначаємо як опрацьований ОДРАЗУ після успіху
            append_processed(processed_path, brand)
            processed.add(brand)
            success += 1

        except KeyboardInterrupt:
            print("\nInterrupted by user. Progress saved.")
            break
        except Exception as e:
            failed += 1
            print(f"[ERR] {brand}: {e}", file=sys.stderr)

        # Пауза між брендами, щоб не навантажувати UI
        time.sleep(args.sleep)

    print("\n===== SUMMARY =====")
    print(f"Total in CSV : {total}")
    print(f"Processed    : {len(processed)} (new this run: {success})")
    print(f"Failed       : {failed}")
    print(f"Output dir   : {outdir}")
    print(f"Processed log: {processed_path}")

if __name__ == "__main__":
    main()
