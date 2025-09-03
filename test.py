# recursive_crawler.py
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Dict, Any, Tuple, Set, Optional
# add near the top with other imports
from urllib.parse import quote, unquote

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

from colorama import init as colorama_init, Fore, Style

import json
import argparse
from pathlib import Path
from datetime import datetime


# ====== CONFIG ======
# ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_03d5e4592k982o5p105380x60465g2g4"
# ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_3ghe57k56j61205tr9uy4999zcf85197#!/home/%D0%A2%D1%80%D0%BE%D1%81%D1%8B"
ROOT_URL = "https://www.myqnapcloud.com/share/76f5f806np2m2676sux5w18d_3ghe57k56j61205tr9uy4999zcf85197#!/home/%D0%A2%D1%80%D0%BE%D1%81%D1%8B/%D0%A2%D1%80%D0%BE%D1%81%D0%B8%20%D1%83%D0%BF%D1%80%D0%B0%D0%B2%D0%BBi%D0%BD%D0%BD%D1%8F"
HEADLESS = True
LOAD_TIMEOUT = 20
URL_CHANGE_TIMEOUT = 10
CLICK_RETRY = 3
SLEEP_AFTER_CLICK = 0.2  # small grace sleep for UI animations
# =====================

colorama_init(autoreset=True)

def indent(depth: int) -> str:
    return "  " * depth

def info(msg: str, depth: int = 0):
    print(f"{indent(depth)}{Fore.CYAN}ℹ {Style.RESET_ALL}{msg}")

def ok(msg: str, depth: int = 0):
    print(f"{indent(depth)}{Fore.GREEN}✔ {Style.RESET_ALL}{msg}")

def warn(msg: str, depth: int = 0):
    print(f"{indent(depth)}{Fore.YELLOW}⚠ {Style.RESET_ALL}{msg}")

def err(msg: str, depth: int = 0):
    print(f"{indent(depth)}{Fore.RED}✖ {Style.RESET_ALL}{msg}")

def step(msg: str, depth: int = 0):
    print(f"{indent(depth)}{Fore.MAGENTA}▶ {Style.RESET_ALL}{msg}")

@dataclass
class Node:
    path: str
    files: List[str]
    folders: List["Node"]
    folder_display_name: Optional[str] = None   # e.g., "Ремкомплект ЄААТ 132-054.001"
    folder_encoded_name: Optional[str] = None   # e.g., "%D0%A0%D0%B5%D0%BC..."


def get_current_path(driver) -> str:
    url = driver.current_url
    hashbang_index = url.find("#!")
    if hashbang_index == -1:
        return "/"
    frag = url[hashbang_index + 2 :]
    if not frag.startswith("/"):
        frag = "/" + frag
    return frag

def wait_for_listing(driver, depth: int = 0) -> None:
    step("waiting for listing…", depth)
    WebDriverWait(driver, LOAD_TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[ng-if]"))
    )
    ok("listing loaded", depth)

def list_items(driver, depth: int = 0) -> Tuple[List[str], List[str]]:
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
    info(f"found {Fore.BLUE}{len(folders)} folders{Style.RESET_ALL} & {Fore.BLUE}{len(files)} files", depth)
    return folders, files

def click_folder_by_name(driver, name: str, depth: int = 0) -> None:
    xpath = (
        f"//a[@ng-if and contains(@ng-if, \"== 'directory'\") "
        f"and normalize-space(text()) = {escape_xpath_literal(name)}]"
    )
    step(f"click folder: {Fore.YELLOW}{name}{Style.RESET_ALL}", depth)
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

def wait_for_path_change(driver, old_path: str, depth: int = 0) -> None:
    step(f"wait for path change from {Fore.YELLOW}{old_path}{Style.RESET_ALL}", depth)
    WebDriverWait(driver, URL_CHANGE_TIMEOUT).until(
        lambda d: get_current_path(d) != old_path
    )
    ok(f"path -> {Fore.YELLOW}{get_current_path(driver)}{Style.RESET_ALL}", depth)

def navigate_back(driver, previous_path: str, depth: int = 0) -> None:
    step(f"back to {Fore.YELLOW}{previous_path}{Style.RESET_ALL}", depth)
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

def dfs_crawl(driver, visited: Set[str], max_depth: Optional[int] = None, depth: int = 0) -> Node:
    path = get_current_path(driver)
    info(f"path: {Fore.YELLOW}{path}{Style.RESET_ALL}", depth)

    if path in visited:
        warn("already visited — skip", depth)
        return Node(path=path, files=[], folders=[])
    visited.add(path)

    folders, files = list_items(driver, depth)
    for f in files:
        print(f"{indent(depth)}{Fore.WHITE}📄 {f}")

    display, encoded = last_segment_names(path)
    node = Node(
        path=path,
        files=files,
        folders=[],
        folder_display_name=display,
        folder_encoded_name=encoded,
    )

    if max_depth is not None and max_depth <= 0:
        warn("max depth reached", depth)
        return node

    for folder_name in folders:
        print(f"{indent(depth)}{Fore.CYAN}📂 {folder_name}")
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

        # Prefer the clicked label for child:
        child.folder_display_name = folder_name
        child.folder_encoded_name = quote(folder_name, safe="")

        node.folders.append(child)

        navigate_back(driver, before, depth)
        wait_for_listing(driver, depth)

    ok("done level", depth)
    return node

def flatten(node: Node) -> List[Dict[str, Any]]:
    """
    Produces rows for both files and folders, with folder display/encoded names.
    For files: keeps the file name and the folder (node) context.
    """
    rows: List[Dict[str, Any]] = []

    # current folder row (except for root if you prefer to skip it)
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
            "name": f,
            "parent_folder_display_name": node.folder_display_name,
            "parent_folder_encoded_name": node.folder_encoded_name,
        })

    # recurse into children
    for child in node.folders:
        rows.extend(flatten(child))

    return rows


def node_to_dict(node: Node) -> Dict[str, Any]:
    return {
        "path": node.path,
        "folder_display_name": node.folder_display_name,
        "folder_encoded_name": node.folder_encoded_name,
        "files": list(node.files),
        "folders": [node_to_dict(ch) for ch in node.folders],
    }

def save_json(tree: Node, rows: List[Dict[str, Any]], out_path: str, meta: Dict[str, Any] | None = None) -> None:
    """Зберігає структуру у JSON-файл (UTF-8, з відступами)."""
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

def last_segment_names(path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    From '/home/Aber/Ремкомплект ЄААТ 132-054.001' ->
      ('Ремкомплект ЄААТ 132-054.001', '%D0%A0%D0%B5%D0%BC...').
    Returns (display_name, encoded_name) or (None, None) for root.
    """
    seg = path.rsplit("/", 1)[-1] if "/" in path else path
    if not seg or seg == "" or seg == path:
        return (None, None)
    display = unquote(seg)
    encoded = quote(display, safe="")
    return (display, encoded)



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
        step(f"opening: {Fore.YELLOW}{root_url}{Style.RESET_ALL}")
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

# if __name__ == "__main__":
#     tree = run(ROOT_URL, max_depth=None)
#     print(f"\n{Fore.GREEN}Crawled root:{Style.RESET_ALL} {tree.path}")
#     print(f"{Fore.GREEN}Files in root:{Style.RESET_ALL} {tree.files}")
#     print(f"{Fore.GREEN}Folders:{Style.RESET_ALL} {[f.path for f in tree.folders]}")

#     rows = flatten(tree)
#     print("\n--- FLAT LIST ---")
#     for r in rows:
#         print(f"{r['type']:6} | {r['path']} | {r['name']}")

# ==== ЗАМІНИ свій блок if __name__ == "__main__": повністю ====
if __name__ == "__main__":
    # parser = argparse.ArgumentParser(description="Recursive QNAP crawler")
    # parser.add_argument("--url", default=ROOT_URL, help="Root URL to crawl")
    # parser.add_argument("--depth", type=int, default=None, help="Max depth (None = full)")
    # parser.add_argument("--out", default="structure.json", help="Output JSON path")
    # args = parser.parse_args()

    # tree = run(args.url, max_depth=args.depth)
    url = ROOT_URL
    filename = f"out/file-system{time.time()}.json"
    depth = 6
    tree = run(url, depth)
    rows = flatten(tree)

    # консольний підсумок
    print(f"\nCrawled root: {tree.path}")
    print("Files in root:", tree.files)
    print("Folders:", [f.path for f in tree.folders])
    print("\n--- FLAT LIST ---")
    for r in rows:
        print(f"{r['type']:6} | {r['path']} ")

    # запис у JSON
    save_json(
        tree,
        rows,
        out_path=filename,
        meta={
            "root_url": url,
            "max_depth": depth,
            "visited_roots": tree.path,
        },
    )
    ok(f"JSON saved -> {filename}")
