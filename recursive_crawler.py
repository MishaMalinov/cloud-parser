# recursive_crawler.py
from __future__ import annotations

import json
import argparse
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple, Set, Optional
import re

from urllib.parse import quote, unquote

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
)

# ====== CONFIG ======
# ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_03d5e4592k982o5p105380x60465g2g4"
# ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_3ghe57k56j61205tr9uy4999zcf85197#!/home/%D0%A2%D1%80%D0%BE%D1%81%D1%8B/%D0%A2%D1%80%D0%BE%D1%81%D0%B8%20%D1%83%D0%BF%D1%80%D0%B0%D0%B2%D0%BBi%D0%BD%D0%BD%D1%8F/%D0%84%D0%90%D0%90%D0%A2%20112-030-01500-010"
ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_3ghe57k56j61205tr9uy4999zcf85197#!/home/%D0%A2%D1%80%D0%BE%D1%81%D1%8B/%D0%A2%D1%80%D0%BE%D1%81%D0%B8%20%D1%83%D0%BF%D1%80%D0%B0%D0%B2%D0%BBi%D0%BD%D0%BD%D1%8F"
HEADLESS = True
LOAD_TIMEOUT = 20
URL_CHANGE_TIMEOUT = 10
CLICK_RETRY = 3
SLEEP_AFTER_CLICK = 0.2  # small grace sleep for UI animations
# Only these file types will be collected (case-insensitive)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")
# =====================

# ---------- tiny colored logs (no external deps) ----------
CSI = "\x1b["
def _c(code: str) -> str: return f"{CSI}{code}m"
COL = {
    "cyan": _c("36"), "green": _c("32"), "yellow": _c("33"),
    "red": _c("31"), "magenta": _c("35"), "blue": _c("34"),
    "reset": _c("0")
}
def indent(depth: int) -> str: return "  " * depth
def info(msg: str, depth: int = 0): print(f"{indent(depth)}{COL['cyan']}ℹ {COL['reset']}{msg}")
def ok(msg: str, depth: int = 0): print(f"{indent(depth)}{COL['green']}✔ {COL['reset']}{msg}")
def warn(msg: str, depth: int = 0): print(f"{indent(depth)}{COL['yellow']}⚠ {COL['reset']}{msg}")
def err(msg: str, depth: int = 0): print(f"{indent(depth)}{COL['red']}✖ {COL['reset']}{msg}")
def step(msg: str, depth: int = 0): print(f"{indent(depth)}{COL['magenta']}▶ {COL['reset']}{msg}")
# ----------------------------------------------------------

@dataclass
class FileItem:
    name: str
    preview_src: str  # absolute image URL from the preview <img src=...>

@dataclass
class Node:
    path: str
    files: List[FileItem]                 # ONLY image files with preview_src
    folders: List["Node"]
    folder_display_name: Optional[str] = None   # e.g., "Ремкомплект ЄААТ 132-054.001"
    folder_encoded_name: Optional[str] = None   # e.g., "%D0%A0%D0%...%D0%90%D0%A2%20132-054.001"

# -------------------- helpers --------------------

def get_current_path(driver) -> str:
    """
    Extracts SPA path from hashbang, e.g. ...#!/home/Aber/AL00038 -> /home/Aber/AL00038
    """
    url = driver.current_url
    hashbang_index = url.find("#!")
    if hashbang_index == -1:
        return "/"
    frag = url[hashbang_index + 2 :]
    if not frag.startswith("/"):
        frag = "/" + frag
    return frag

def last_segment_names(path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    From '/home/Aber/Ремкомплект ЄААТ 132-054.001' ->
      ('Ремкомплект ЄААТ 132-054.001', '%D0%A0%D0%B5%D0%BC...')
    """
    seg = path.rsplit("/", 1)[-1] if "/" in path else path
    if not seg or seg == "" or seg == path:
        return (None, None)
    display = unquote(seg)
    encoded = quote(display, safe="")
    return (display, encoded)

def escape_xpath_literal(s: str) -> str:
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = []
    for part in s.split("'"):
        parts.append(f"'{part}'")
        parts.append('"\'"')
    parts = parts[:-1]
    return "concat(" + ", ".join(parts) + ")"

def is_image_name(name: str) -> bool:
    low = name.lower()
    return any(low.endswith(ext) for ext in IMAGE_EXTENSIONS)

# -------------------- waits & listing --------------------

def wait_for_listing(driver, depth: int = 0) -> None:
    step("waiting for listing…", depth)
    WebDriverWait(driver, LOAD_TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[ng-if]"))
    )
    ok("listing loaded", depth)

def list_raw_items(driver, depth: int = 0) -> Tuple[List[str], List[str]]:
    """
    Returns (folder_names, file_names) by reading ng-if attribute.
    NOTE: These are just visible names; files will later be filtered to images and previewed.
    """
    wait_for_listing(driver, depth)
    anchors = driver.find_elements(By.CSS_SELECTOR, "a[ng-if]")
    folders, files = [], []
    for a in anchors:
        try:
            text = a.text.strip()
            if not text:
                continue
            ng_if = a.get_attribute("ng-if") or ""
            if "== 'directory'" in ng_if:
                folders.append(text)
            elif "!= 'directory'" in ng_if:
                files.append(text)
        except StaleElementReferenceException:
            continue
    # de-dup, preserve order
    folders = list(dict.fromkeys(folders))
    files = list(dict.fromkeys(files))
    info(f"found {COL['blue']}{len(folders)} folders{COL['reset']} & {COL['blue']}{len(files)} files", depth)
    return folders, files

# -------------------- navigation actions --------------------

def click_folder_by_name(driver, name: str, depth: int = 0) -> None:
    xpath = (
        f"//a[@ng-if and contains(@ng-if, \"== 'directory'\") "
        f"and normalize-space(text()) = {escape_xpath_literal(name)}]"
    )
    step(f"open folder: {COL['yellow']}{name}{COL['reset']}", depth)
    el = WebDriverWait(driver, LOAD_TIMEOUT).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    for i in range(CLICK_RETRY):
        try:
            el.click()
            time.sleep(SLEEP_AFTER_CLICK)
            ok(f"clicked (try {i+1})", depth)
            return
        except (ElementClickInterceptedException, StaleElementReferenceException):
            warn(f"retry click… ({i+1})", depth)
            time.sleep(0.25)
    driver.execute_script("arguments[0].click();", el)
    ok("clicked via JS", depth)

def click_file_by_name(driver, name: str, depth: int = 0) -> None:
    """
    Click a file item (non-directory) by visible text.
    """
    xpath = (
        f"//a[@ng-if and contains(@ng-if, \"!= 'directory'\") "
        f"and normalize-space(text()) = {escape_xpath_literal(name)}]"
    )
    step(f"preview file: {COL['yellow']}{name}{COL['reset']}", depth)
    el = WebDriverWait(driver, LOAD_TIMEOUT).until(
        EC.element_to_be_clickable((By.XPATH, xpath))
    )
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    for i in range(CLICK_RETRY):
        try:
            el.click()
            time.sleep(SLEEP_AFTER_CLICK)
            ok(f"clicked (try {i+1})", depth)
            return
        except (ElementClickInterceptedException, StaleElementReferenceException):
            warn(f"retry click… ({i+1})", depth)
            time.sleep(0.25)
    driver.execute_script("arguments[0].click();", el)
    ok("clicked via JS", depth)

def wait_for_preview_image_and_get_src(driver, depth: int = 0) -> Optional[str]:
    """
    Waits for the image preview container and returns the <img src="...">.
    Structure example:
    <div class="preview-content" ng-show="preview_type == 'image'" image-preview="preview_url">
        <img src="https://.../get_thumb...&name=...JPG...">
    </div>
    """
    step("waiting for preview image…", depth)
    try:
        container = WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div.preview-content[ng-show*="image"]')
            )
        )
        img = WebDriverWait(driver, LOAD_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'div.preview-content[ng-show*="image"] img[src]')
            )
        )
        src = img.get_attribute("src")
        ok("preview image captured", depth)
        return src
    except TimeoutException:
        warn("no preview image appeared", depth)
        return None

def close_preview(driver, depth: int = 0) -> None:
    """
    Attempts to close the preview overlay: ESC -> fallback click on close buttons.
    """
    step("closing preview… (ESC)", depth)
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        WebDriverWait(driver, 5).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, 'div.preview-content[ng-show*="image"]')
            )
        )
        ok("preview closed (ESC)", depth)
        return
    except Exception:
        pass

    # fallback: commonly used close elements
    for sel in [
        '[ng-click*="close"]',
        ".icon-close",
        ".close",
        'button[title*="Close"]',
    ]:
        try:
            btn = driver.find_element(By.CSS_SELECTOR, sel)
            btn.click()
            WebDriverWait(driver, 5).until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, 'div.preview-content[ng-show*="image"]')
                )
            )
            ok(f"preview closed ({sel})", depth)
            return
        except Exception:
            continue

    warn("could not confirm preview closed; continuing", depth)

def wait_for_path_change(driver, old_path: str, depth: int = 0) -> None:
    step(f"wait for path change from {COL['yellow']}{old_path}{COL['reset']}", depth)
    WebDriverWait(driver, URL_CHANGE_TIMEOUT).until(
        lambda d: get_current_path(d) != old_path
    )
    ok(f"path -> {COL['yellow']}{get_current_path(driver)}{COL['reset']}", depth)

def navigate_back(driver, previous_path: str, depth: int = 0) -> None:
    step(f"back to {COL['yellow']}{previous_path}{COL['reset']}", depth)
    driver.back()
    try:
        WebDriverWait(driver, URL_CHANGE_TIMEOUT).until(
            lambda d: get_current_path(d) == previous_path
        )
        ok("restored parent path", depth)
    except TimeoutException:
        warn("history back timeout, forcing hash…", depth)
        driver.execute_script(f"window.location.hash = '#!{previous_path}';")
        wait_for_listing(driver, depth)

# -------------------- core DFS crawl --------------------

def dfs_crawl(driver, visited: Set[str], max_depth: Optional[int] = None, depth: int = 0) -> Node:
    path = get_current_path(driver)
    info(f"path: {COL['yellow']}{path}{COL['reset']}", depth)

    if path in visited:
        warn("already visited — skip", depth)
        return Node(path=path, files=[], folders=[], *last_segment_names(path))

    visited.add(path)

    folder_display, folder_encoded = last_segment_names(path)
    raw_folders, raw_files = list_raw_items(driver, depth)

    # Process ONLY image files: click, grab preview src, close preview
    image_files: List[FileItem] = []
    for fname in raw_files:
        if not is_image_name(fname):
            continue
        try:
            click_file_by_name(driver, fname, depth)
            src = wait_for_preview_image_and_get_src(driver, depth)
            if src:
                image_files.append(FileItem(name=fname, preview_src=src))
            close_preview(driver, depth)
            # ensure listing is back
            wait_for_listing(driver, depth)
        except Exception as e:
            warn(f"skip file due to error: {fname} ({e})", depth)

    node = Node(
        path=path,
        files=image_files,
        folders=[],
        folder_display_name=folder_display,
        folder_encoded_name=folder_encoded,
    )

    if max_depth is not None and max_depth <= 0:
        warn("max depth reached", depth)
        return node

    # Recurse into folders
    for folder_name in raw_folders:
        print(f"{indent(depth)}{COL['cyan']}📂 {folder_name}{COL['reset']}")
        before = get_current_path(driver)
        click_folder_by_name(driver, folder_name, depth)
        try:
            wait_for_path_change(driver, before, depth)
        except TimeoutException:
            warn("hash not changed; waiting listing anyway…", depth)
            wait_for_listing(driver, depth)

        child = dfs_crawl(
            driver,
            visited=visited,
            max_depth=(None if max_depth is None else max_depth - 1),
            depth=depth + 1,
        )
        # Trust clicked label more than hash segment
        child.folder_display_name = folder_name
        child.folder_encoded_name = quote(folder_name, safe="")
        node.folders.append(child)

        # Return to parent
        navigate_back(driver, before, depth)
        wait_for_listing(driver, depth)

    ok("done level", depth)
    return node

# -------------------- flatten & JSON --------------------

def flatten(node: Node) -> List[Dict[str, Any]]:
    """
    Flat rows that include folders and ONLY image files with preview_src.
    """
    rows: List[Dict[str, Any]] = []

    # current folder row (keep root as well)
    rows.append({
        "type": "folder",
        "path": node.path,
        "folder_display_name": node.folder_display_name,
        "folder_encoded_name": node.folder_encoded_name,
    })

    # files inside this folder
    for f in node.files:
        rows.append({
            "type": "file",
            "path": node.path,
            "name": f.name,
            "preview_src": f.preview_src,
            "parent_folder_display_name": node.folder_display_name,
            "parent_folder_encoded_name": node.folder_encoded_name,
        })

    # recurse
    for child in node.folders:
        rows.extend(flatten(child))

    return rows

def node_to_dict(node: Node) -> Dict[str, Any]:
    return {
        "path": node.path,
        "folder_display_name": node.folder_display_name,
        "folder_encoded_name": node.folder_encoded_name,
        "files": [{"name": f.name, "preview_src": f.preview_src} for f in node.files],
        "folders": [node_to_dict(ch) for ch in node.folders],
    }

def save_json(tree: Node, rows: List[Dict[str, Any]], out_path: str, meta: Dict[str, Any] | None = None) -> None:
    payload = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            **(meta or {})
        },
        "tree": node_to_dict(tree),
        "flat": rows,
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

# -------------------- run --------------------

def run(root_url: str, max_depth: Optional[int] = None) -> Node:
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless=new")
    else:
        opts.add_argument("--headless=false")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")

    info("init chrome driver")
    driver = webdriver.Chrome(service=Service(), options=opts)
    ok("driver ready")

    try:
        step(f"opening: {COL['yellow']}{root_url}{COL['reset']}")
        driver.get(root_url)
        wait_for_listing(driver, 0)

        t0 = time.time()
        visited: Set[str] = set()
        tree = dfs_crawl(driver, visited=visited, max_depth=max_depth, depth=0)
        dt = time.time() - t0
        ok(f"crawl finished in {dt:.2f}s, visited {len(visited)} paths")
        return tree
    finally:
        driver.quit()

# -------------------- CLI --------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recursive QNAP image crawler (folders + image preview srcs)")
    parser.add_argument("--url", default=ROOT_URL, help="Root URL to crawl")
    parser.add_argument("--depth", type=int, default=None, help="Max depth (None = full)")
    parser.add_argument("--out", default=f"structure-{time.time()}.json", help="Output JSON path")
    args = parser.parse_args()

    tree = run(args.url, max_depth=args.depth)
    rows = flatten(tree)

    # console summary
    print(f"\n{COL['green']}Crawled root:{COL['reset']} {tree.path}")
    print(f"{COL['green']}Folders:{COL['reset']} {[f.path for f in tree.folders]}")
    print(f"{COL['green']}Image files in root:{COL['reset']} {[f.name for f in tree.files]}")

    # write JSON
    save_json(
        tree,
        rows,
        out_path=args.out,
        meta={
            "root_url": args.url,
            "max_depth": args.depth,
            "image_extensions": IMAGE_EXTENSIONS,
        },
    )
    ok(f"JSON saved -> {args.out}")
