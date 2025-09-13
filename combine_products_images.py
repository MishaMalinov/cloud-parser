#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import unquote
from difflib import SequenceMatcher
from colorama import Fore, Style, init as colorama_init


# -------------------- CONFIG --------------------
CSV_COL_NAME = "name"
CSV_COL_SKU = "sku"
CSV_COL_ATTRS = "description"
CSV_COL_PRICE = "price"

# CSV_COL_URL = "url"

# DEFAULT_MIN_SCORE = 0.45    # якщо <0.5 — це вже дуже сумнівний матч
# PENALIZE_DEEP_PATH = 0.01   # штраф за кожен рівень після 4-го, максимум ~0.1
# BONUS_SKU_DIRECT = 0.60     # SKU — найсильніший сигнал \\ артикул
# BONUS_NAME_SUBSTR = 0.35    # назва важлива, але другорядна  \\ назва товару
DEFAULT_MIN_SCORE = 0.45
BONUS_SKU_DIRECT  = 0.55
BONUS_SKU_REVERSED= 0.45
BONUS_NAME_SUBSTR = 0.45
FORWARD_WEIGHT    = 0.60
REVERSE_WEIGHT    = 0.50
DIRECT_REV_BOOST  = 0.40
PENALIZE_DEEP_PATH= 0
FILE_TOKENS_TOP_K = 7
MIN_TOKEN_LEN     = 3

colorama_init(autoreset=True)

def log_info(msg: str):
    print(Fore.CYAN + "[INFO] " + Style.RESET_ALL + msg)

def log_success(msg: str):
    print(Fore.GREEN + "[OK] " + Style.RESET_ALL + msg)

def log_warn(msg: str):
    print(Fore.YELLOW + "[WARN] " + Style.RESET_ALL + msg)

def log_error(msg: str):
    print(Fore.RED + "[ERROR] " + Style.RESET_ALL + msg)

# ------------------------------------------------

@dataclass
class Product:
    name: str
    sku: str
    attrs: str
    # url: str
    price: Optional[float]

@dataclass
class FolderImages:
    brand: str
    path: str                  # e.g. "/home/CTM/...."
    folder_display: str        # human readable
    folder_encoded: str        # percent-encoded last segment
    images: List[str]          # list of preview_src
    files: List[str]           # file names in that folder

# -------------------- UTILS --------------------

def norm_text(s: str) -> str:
    if s is None:
        return ""
    s = unquote(str(s))
    s = s.lower()
    s = s.replace("’", "'").replace("`", "'").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s\-\.]", " ", s, flags=re.UNICODE)  # лишаємо букви/цифри/_/-/.
    s = re.sub(r"\s+", " ", s).strip()
    return s

def to_float_eu(s: str) -> Optional[float]:
    if s is None or s == "":
        return None
    s = str(s).strip().replace(" ", "").replace(",", ".")
    s = re.sub(r"[^0-9.\-]", "", s)
    try:
        return float(s)
    except Exception:
        return None

def ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()

def any_substring(needle: str, haystack: str) -> bool:
    return needle in haystack if (needle and haystack) else False

def tokenize_keep_order(s: str) -> List[str]:
    toks = re.findall(r"[A-Za-zА-Яа-яІіЇїЄєҐґ0-9\-\.]+", s)
    return [t for t in toks if len(t) >= MIN_TOKEN_LEN]

# -------------------- LOADERS --------------------

def load_products(csv_path: Path) -> List[Product]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        missing = [c for c in [CSV_COL_NAME, CSV_COL_SKU, CSV_COL_ATTRS, CSV_COL_PRICE] if c not in rd.fieldnames]
        if missing:
            raise SystemExit(f"CSV missing columns: {missing}\nFound: {rd.fieldnames}")
        out: List[Product] = []
        for row in rd:
            out.append(Product(
                name=(row.get(CSV_COL_NAME) or "").strip(),
                sku=(row.get(CSV_COL_SKU) or "").strip(),
                attrs=(row.get(CSV_COL_ATTRS) or "").strip(),
                # url=(row.get(CSV_COL_URL) or "").strip(),
                price=to_float_eu(row.get(CSV_COL_PRICE)),
            ))
        return out

def load_brand_jsons(json_dir: Path) -> List[FolderImages]:
    """
    Reads every *.json and builds per-folder containers with image preview_srcs.
    Accepts either:
      - {"meta": {...}, "flat": [...]}
      - [{"type":"file"|"folder", ...}, ...]     (plain flat list)
      - {} or []                                 (skipped)
    """
    out: List[FolderImages] = []
    skipped: List[str] = []

    for p in sorted(json_dir.glob("*.json")):
        try:
            text = p.read_text(encoding="utf-8")
            text = text.strip()
            if not text:
                skipped.append(f"{p.name}: empty file")
                continue

            payload = json.loads(text)

            # Normalize to (brand, flat)
            brand = p.stem
            flat = None

            if isinstance(payload, dict):
                meta = payload.get("meta") or {}
                brand = (meta.get("brand") or brand).strip() or brand
                flat = payload.get("flat")
            elif isinstance(payload, list):
                # assume this is the flat list directly
                flat = payload
            else:
                skipped.append(f"{p.name}: unsupported top-level type {type(payload).__name__}")
                continue

            if not flat or not isinstance(flat, list):
                skipped.append(f"{p.name}: no flat list")
                continue

            # group by folder path; keep only image files (with preview_src)
            folder_map: Dict[str, Dict[str, Any]] = {}

            for r in flat:
                if not isinstance(r, dict):
                    continue

                rtype = r.get("type")
                if rtype == "folder":
                    fpath = r.get("path") or ""
                    if not fpath:
                        continue
                    folder_map.setdefault(
                        fpath,
                        {
                            "folder_display": r.get("folder_display_name") or "",
                            "folder_encoded": r.get("folder_encoded_name") or "",
                            "images": [],
                            "files": [],
                        },
                    )
                elif rtype == "file":
                    fpath = r.get("path") or ""
                    if not fpath:
                        continue
                    entry = folder_map.setdefault(
                        fpath,
                        {
                            "folder_display": r.get("parent_folder_display_name") or "",
                            "folder_encoded": r.get("parent_folder_encoded_name") or "",
                            "images": [],
                            "files": [],
                        },
                    )
                    if r.get("preview_src"):
                        entry["images"].append(r["preview_src"])
                    if r.get("name"):
                        entry["files"].append(r["name"])

            # pack to FolderImages (only folders that have at least one image)
            for fpath, data in folder_map.items():
                images: List[str] = list(dict.fromkeys(data["images"]))  # dedupe, keep order
                files: List[str] = list(dict.fromkeys(data["files"]))
                if not images:
                    continue
                out.append(
                    FolderImages(
                        brand=brand,
                        path=fpath,
                        folder_display=data.get("folder_display", "")
                        or data.get("folder_encoded", "")
                        or fpath.rsplit("/", 1)[-1],
                        folder_encoded=data.get("folder_encoded", ""),
                        images=images,
                        files=files,
                    )
                )

        except json.JSONDecodeError as e:
            skipped.append(f"{p.name}: JSON decode error ({e})")
        except Exception as e:
            skipped.append(f"{p.name}: {e}")

    print(f"Loaded folders with images: {len(out)}")
    if skipped:
        log_warn("Skipped JSONs:")
        for s in skipped:
            log_warn("  - " + s)
    else:
        log_success("All JSONs parsed successfully")
    return out


# -------------------- MATCHING --------------------

def score_match(prod: Product, folder: FolderImages) -> float:
    """
    Combines several signals into one score:
      - substring of SKU in folder path/name/files (big bonus)
      - substring of product name tokens in folder name/path
      - fuzzy ratio between normalized product name and folder_display/path
    Slightly penalize overly deep paths.
    """
    sku = norm_text(prod.sku) # product's sku
    pname = norm_text(prod.name) # product's name
    # folder data
    fdisp = norm_text(folder.folder_display)
    fpath = norm_text(folder.path)
    fnames = " ".join(norm_text(x) for x in folder.files)

    score = 0.0

    # direct SKU presence
    if sku:
        if any_substring(sku, fdisp) or any_substring(sku, fpath) or any_substring(sku, fnames):
            score += BONUS_SKU_DIRECT
        elif any_substring(fdisp, sku) or any_substring(fpath, sku):
            score += BONUS_SKU_REVERSED


    # product name substrings (use tokens)
    # ---------- improved NAME↔FOLDER logic ----------
    tokens = tokenize_keep_order(pname)  # product-name tokens (normed already)

    if tokens:
        # tokens from folder display/path
        folder_tokens = tokenize_keep_order(fdisp) + tokenize_keep_order(fpath)

        # tokens from file names inside the folder (use only the longest few)
        file_tokens_all = []
        for fn in folder.files:
            file_tokens_all.extend(tokenize_keep_order(norm_text(fn)))
        file_tokens_all = sorted(set(file_tokens_all), key=len, reverse=True)[:FILE_TOKENS_TOP_K]


        # uniq while preserving order
        def uniq_keep_order(xs: List[str]) -> List[str]:
            seen = set(); out=[]
            for x in xs:
                if x not in seen:
                    seen.add(x); out.append(x)
            return out

        folder_tokens = uniq_keep_order(folder_tokens)
        folder_tokens_all = uniq_keep_order(folder_tokens + file_tokens_all)

        # forward: do product tokens appear in folder display/path/files?
        forward_hits = [
            t for t in tokens
            if any_substring(t, fdisp) or any_substring(t, fpath) or any_substring(t, fnames)
        ]

        # reverse: do folder/file tokens appear in the product name?
        reverse_hits = [
            t for t in folder_tokens_all if any_substring(t, pname)
        ]

        # coverage + length-weighted coverage (forward)
        if tokens:
            cov_fwd = len(forward_hits) / len(tokens)
            len_fwd = sum(len(t) for t in forward_hits) / max(1, sum(len(t) for t in tokens))
        else:
            cov_fwd = len_fwd = 0.0

        # coverage + length-weighted coverage (reverse)
        if folder_tokens_all:
            cov_rev = len(reverse_hits) / len(folder_tokens_all)
            len_rev = sum(len(t) for t in reverse_hits) / max(1, sum(len(t) for t in folder_tokens_all))
        else:
            cov_rev = len_rev = 0.0

        # combine: forward is a bit more important than reverse
        forward_score = 0.5 * cov_fwd + 0.5 * len_fwd
        reverse_score = 0.5 * cov_rev + 0.5 * len_rev
        combined = FORWARD_WEIGHT * forward_score + REVERSE_WEIGHT * reverse_score
        score += BONUS_NAME_SUBSTR * min(1.0, combined)

        if any_substring(fdisp, pname) or any_substring(fpath, pname):
            score += BONUS_NAME_SUBSTR * DIRECT_REV_BOOST


        # score += BONUS_NAME_SUBSTR * min(1.0, combined) + BONUS_NAME_SUBSTR * direct_rev_boost
    # ---------- end improved block ----------



    # fuzzy ratios
    score += 0.5 * max(ratio(pname, fdisp), ratio(pname, fpath))  # up to 0.5

    # slight penalty for very deep folders (noise)
    depth = folder.path.count("/")
    score -= min(PENALIZE_DEEP_PATH * max(0, depth - 4), 0.10)

    # cap to [0, 1]
    return max(0.0, min(1.0, score))

def match_products_to_images(products: List[Product], folders: List[FolderImages], min_score: float) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    total = len(products)
    for idx, prod in enumerate(products, start=1):
        best: Optional[Tuple[FolderImages, float]] = None
        for fol in folders:
            s = score_match(prod, fol)
            if best is None or s > best[1]:
                best = (fol, s)
        if best and best[1] >= min_score:
            fol, s = best
            log_success(f"[{idx}/{total}] [MATCH] {prod.sku or prod.name} -> {fol.brand}/{fol.folder_display} (score={s:.2f})")

            results.append({
                "sku": prod.sku,
                "name": prod.name,
                "attributes": prod.attrs,
                "price": prod.price,
                # "product_url": prod.url,
                "match": {
                    "brand": fol.brand,
                    "folder_path": fol.path,
                    "folder_display_name": fol.folder_display,
                    "folder_encoded_name": fol.folder_encoded,
                    "score": round(s, 3),
                },
                "images": fol.images,
            })
        else:
            log_warn(f"[{idx}/{total}] [NO MATCH] {prod.sku or prod.name}")
            results.append({
                "sku": prod.sku,
                "name": prod.name,
                "attributes": prod.attrs,
                "price": prod.price,
                # "product_url": prod.url,
                "match": None,
                "images": [],
            })
    return results


# -------------------- SAVE --------------------

def save_output(rows: List[Dict[str, Any]], out_path: Path, meta: Dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "count": len(rows),
        "products": rows,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

# -------------------- CLI --------------------

def main():
    ap = argparse.ArgumentParser(description="Join products.csv with crawled images by fuzzy/substring matching.")
    ap.add_argument("--csv", required=True, help="Path to products.csv")
    ap.add_argument("--json-dir", required=True, help="Directory with per-brand *.json (crawler output)")
    ap.add_argument("--out", default="products_with_images.json", help="Output JSON path")
    ap.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE, help="Min score to accept a match (0..1)")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    json_dir = Path(args.json_dir)
    out_path = Path(args.out)

    products = load_products(csv_path)
    folders = load_brand_jsons(json_dir)

    log_info(f"Loaded products: {len(products)}")
    log_info(f"Loaded folders with images: {len(folders)}")

    joined = match_products_to_images(products, folders, args.min_score)
    matched = sum(1 for r in joined if r["match"])

    log_success(f"Matched: {matched}/{len(joined)} (min_score={args.min_score})")

    save_output(joined, out_path, {
        "csv": str(csv_path),
        "json_dir": str(json_dir),
        "min_score": args.min_score,
    })
    log_success(f"Saved -> {out_path}")


if __name__ == "__main__":
    main()
