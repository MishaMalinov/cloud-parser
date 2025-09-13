#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import xml.etree.ElementTree as ET
from xml.dom import minidom


# ---------- CONFIGURABLE MAPPINGS ----------
DEFAULT_AVAILABILITY = "in_stock"  # change to "1", "true", "available", etc.
DEFAULT_CURRENCY = "UAH"           # not serialized unless you add a node for it

# If your marketplace wants a different root or element names,
# change TAG_* below. The default is a simple, flat structure.
TAG_ROOT = "products"
TAG_ITEM = "product"
TAG_SKU = "sku"
TAG_NAME = "name"
TAG_PRICE = "price"
TAG_AVAIL = "availability"
TAG_BRAND = "brand"
TAG_CATEGORY = "category"
TAG_IMAGE = "picture"     # repeated for multiple images
TAG_URL = "url"
TAG_DESCRIPTION = "description"

# If you prefer CDATA for description, set to True (uses a safe fallback)
USE_CDATA_FOR_DESCRIPTION = True
# -------------------------------------------


def load_input(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    # accepted structures:
    # { "products": [...] }  <-- expected
    # [ ... ]                <-- raw array of products
    if isinstance(data, list):
        return {"products": data, "meta": {}}
    if isinstance(data, dict) and "products" in data and isinstance(data["products"], list):
        return data
    raise SystemExit("Unsupported JSON structure: expected object with 'products' array or a raw array.")


def as_text(x: Any) -> str:
    return "" if x is None else str(x)


def price_to_str(x: Optional[float]) -> str:
    if x is None:
        return ""
    return f"{float(x):.2f}"


def make_description(name: str, attributes: str) -> str:
    name = (name or "").strip()
    attrs = (attributes or "").strip()
    if name and attrs:
        return f"{name}\n{attrs}"
    return name or attrs


def append_text_node(parent: ET.Element, tag: str, value: str) -> None:
    el = ET.SubElement(parent, tag)
    el.text = value


def append_cdata_node(parent: ET.Element, tag: str, value: str) -> None:
    """
    xml.etree doesn't support CDATA directly. We'll inject it post-serialization
    via a placeholder token.
    """
    placeholder_start = "___CDATA_START___"
    placeholder_end = "___CDATA_END___"
    el = ET.SubElement(parent, tag)
    # wrap content with placeholders that we'll swap to <![CDATA[...]]>
    el.text = f"{placeholder_start}{value}{placeholder_end}"


def prettify_xml(elem: ET.Element, add_xml_decl: bool = True) -> str:
    rough = ET.tostring(elem, encoding="utf-8")
    reparsed = minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8") if add_xml_decl else \
           reparsed.toprettyxml(indent="  ", encoding=None)


def postprocess_cdata(xml_text: str) -> str:
    if not USE_CDATA_FOR_DESCRIPTION:
        return xml_text
    return xml_text.replace("___CDATA_START___", "<![CDATA[").replace("___CDATA_END___", "]]>")


def build_xml(products: List[Dict[str, Any]]) -> ET.Element:
    root = ET.Element(TAG_ROOT)

    for p in products:
        item = ET.SubElement(root, TAG_ITEM)

        sku = as_text(p.get("sku")).strip()
        name = as_text(p.get("name")).strip()
        price = p.get("price_eur")
        url = as_text(p.get("product_url")).strip()
        attrs = as_text(p.get("attributes")).strip()

        match = p.get("match") or {}
        brand = as_text(match.get("brand")).strip()
        category = as_text(match.get("folder_display_name")).strip()

        # images: list of urls (may be empty)
        images = p.get("images") or []

        # required/expected fields
        append_text_node(item, TAG_SKU, sku)
        append_text_node(item, TAG_NAME, name)
        append_text_node(item, TAG_PRICE, price_to_str(price))
        append_text_node(item, TAG_AVAIL, DEFAULT_AVAILABILITY)
        append_text_node(item, TAG_BRAND, brand)
        append_text_node(item, TAG_CATEGORY, category)
        append_text_node(item, TAG_URL, url)

        # description (optionally CDATA)
        description = make_description(name, attrs)
        if USE_CDATA_FOR_DESCRIPTION:
            append_cdata_node(item, TAG_DESCRIPTION, description)
        else:
            append_text_node(item, TAG_DESCRIPTION, description)

        # multi-image
        for img in images:
            if not img:
                continue
            append_text_node(item, TAG_IMAGE, as_text(img).strip())

    return root


def main():
    ap = argparse.ArgumentParser(description="Convert consolidated products_with_images.json to a simple XML feed.")
    ap.add_argument("--in", dest="inp", required=True, help="Path to products_with_images.json")
    ap.add_argument("--out", dest="out", default="products.xml", help="Output XML file path")
    ap.add_argument("--min-score", type=float, default=None,
                    help="If set, drop products whose match.score < min-score (keeps null matches if not set)")
    ap.add_argument("--only-matched", action="store_true",
                    help="If set, include only products that have a non-null match")
    args = ap.parse_args()

    inp = Path(args.inp)
    outp = Path(args.out)

    payload = load_input(inp)
    raw_products: List[Dict[str, Any]] = payload.get("products", [])

    # Filter by match options if requested
    products: List[Dict[str, Any]] = []
    for p in raw_products:
        m = p.get("match")
        if args.only_matched and not m:
            continue
        if args.min_score is not None and m and isinstance(m.get("score"), (int, float)):
            if float(m["score"]) < args.min_score:
                continue
        products.append(p)

    root = build_xml(products)
    xml_text = prettify_xml(root, add_xml_decl=True)
    xml_text = postprocess_cdata(xml_text)

    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(xml_text, encoding="utf-8")

    print(f"✓ Wrote XML: {outp} ({len(products)} items)")

if __name__ == "__main__":
    main()
