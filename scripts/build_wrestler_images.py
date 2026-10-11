#!/usr/bin/env python3
"""
Build NMU wrestler website images from Wikimedia Commons / Wikipedia.

- SmackDown Hotel is NOT downloaded from or hotlinked.
- Wikimedia Commons candidates are preferred and license metadata is written to SOURCES.csv.
- The script prioritizes 1998-2001 imagery when available.
- Backgrounds are removed with rembg and all outputs are normalized to transparent PNG.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageOps, ImageDraw
from rembg import remove

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "wrestlers_manifest.json"
OUT = ROOT / "wrestlers"
OUT.mkdir(exist_ok=True)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ENWIKI_API = "https://en.wikipedia.org/w/api.php"
UA = "NoMercyUniverse/1.0 (fan archive image builder; Wikimedia source attribution preserved)"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

GOOD_YEARS = {1998: 26, 1999: 34, 2000: 40, 2001: 30, 1997: 12, 2002: 10}
BAD_WORDS = {
    "logo","poster","belt","championship belt","arena","match card","dvd","video game",
    "action figure","toy","autograph","signature","collage","group","team","crowd"
}

def clean_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").strip()

def commons_search(query: str, limit: int = 18):
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": 1600,
    }
    data = SESSION.get(COMMONS_API, params=params, timeout=40).json()
    return list((data.get("query") or {}).get("pages", {}).values())

def wikipedia_page_image(title: str):
    params = {
        "action": "query", "format": "json", "redirects": 1,
        "titles": title, "prop": "pageimages", "piprop": "thumbnail|original",
        "pithumbsize": 1600,
    }
    data = SESSION.get(ENWIKI_API, params=params, timeout=40).json()
    pages = list((data.get("query") or {}).get("pages", {}).values())
    if not pages:
        return None
    p = pages[0]
    return (p.get("original") or p.get("thumbnail") or {}).get("source")

def score_candidate(page: dict, person_name: str):
    title = (page.get("title") or "").lower()
    ii = (page.get("imageinfo") or [{}])[0]
    meta = ii.get("extmetadata") or {}
    desc = clean_html((meta.get("ImageDescription") or {}).get("value", "")).lower()
    text = title + " " + desc
    score = 0

    # Identity tokens
    tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", person_name) if len(t) > 2]
    score += sum(8 for t in tokens if t in text)

    # Wrestling relevance
    for w in ("wrestler","wrestling","wwf","wwe","ecw","wcw"):
        if w in text:
            score += 8

    # Era preference
    for year, pts in GOOD_YEARS.items():
        if str(year) in text:
            score += pts

    # Avoid obvious non-portrait assets
    for w in BAD_WORDS:
        if w in text:
            score -= 24

    width, height = ii.get("width") or 0, ii.get("height") or 0
    if width and height:
        ratio = height / max(width, 1)
        if 0.9 <= ratio <= 2.4:
            score += 10
        if min(width, height) >= 450:
            score += 5

    license_name = clean_html((meta.get("LicenseShortName") or {}).get("value", ""))
    if license_name:
        score += 5

    return score

def best_commons_candidate(name: str, aliases: list[str]):
    queries = []
    for alias in aliases:
        queries.extend([
            f'"{alias}" 2000 wrestling',
            f'"{alias}" 1999 wrestling',
            f'"{alias}" WWF',
            f'"{alias}" professional wrestler',
        ])

    seen = {}
    for q in queries:
        try:
            for page in commons_search(q):
                title = page.get("title")
                if title and title not in seen:
                    seen[title] = page
        except Exception:
            pass
        time.sleep(0.15)

    ranked = sorted(seen.values(), key=lambda p: score_candidate(p, name), reverse=True)
    return ranked[0] if ranked else None

def download(url: str):
    r = SESSION.get(url, timeout=60)
    r.raise_for_status()
    return r.content

def normalize_png(raw: bytes, out_path: Path):
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    # Keep inference reasonable for GitHub-hosted runner.
    if max(im.size) > 1800:
        im.thumbnail((1800, 1800), Image.Resampling.LANCZOS)

    alpha = im.getchannel("A")
    bbox = alpha.getbbox()
    already_transparent = bbox is not None and alpha.getextrema()[0] < 245

    if not already_transparent:
        result = remove(im)
        if isinstance(result, bytes):
            im = Image.open(io.BytesIO(result)).convert("RGBA")
        else:
            im = result.convert("RGBA")

    alpha = im.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        im = im.crop(bbox)

    # Consistent site asset: 800x1000 transparent canvas.
    target_w, target_h = 800, 1000
    scale = min((target_w * .90) / max(im.width,1), (target_h * .94) / max(im.height,1))
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (target_w, target_h), (0,0,0,0))
    x = (target_w - nw)//2
    y = target_h - nh
    canvas.alpha_composite(im, (x,y))
    canvas.save(out_path, "PNG", optimize=True)

def make_placeholder(name: str, path: Path):
    im = Image.new("RGBA", (800,1000), (0,0,0,0))
    d = ImageDraw.Draw(im)
    initials = "".join(w[0] for w in name.split()[:3]).upper()
    d.ellipse((190,180,610,600), fill=(40,40,45,255))
    d.rectangle((155,570,645,930), fill=(40,40,45,255))
    d.text((365,410), initials, anchor="mm", fill=(230,230,230,255))
    im.save(path, "PNG")

def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    source_rows = []
    failures = []

    for i, rec in enumerate(manifest, 1):
        wid, name, aliases = rec["id"], rec["name"], rec.get("aliases") or [rec["name"]]
        out_path = OUT / f"wrestler-{wid}.png"
        print(f"[{i}/{len(manifest)}] {name}")

        source_url = ""
        source_page = ""
        license_name = ""
        artist = ""
        credit = ""
        method = ""

        try:
            cand = best_commons_candidate(name, aliases)
            if cand:
                ii = (cand.get("imageinfo") or [{}])[0]
                meta = ii.get("extmetadata") or {}
                source_url = ii.get("thumburl") or ii.get("url") or ""
                source_page = "https://commons.wikimedia.org/wiki/" + quote(cand.get("title","").replace(" ","_"))
                license_name = clean_html((meta.get("LicenseShortName") or {}).get("value",""))
                artist = clean_html((meta.get("Artist") or {}).get("value",""))
                credit = clean_html((meta.get("Credit") or {}).get("value",""))
                method = "Wikimedia Commons"
                if source_url:
                    normalize_png(download(source_url), out_path)

            if not out_path.exists():
                # Fallback to the wrestler's English Wikipedia lead image.
                for alias in aliases + [name]:
                    url = wikipedia_page_image(alias)
                    if url:
                        source_url = url
                        source_page = "https://en.wikipedia.org/wiki/" + quote(alias.replace(" ","_"))
                        method = "Wikipedia lead-image fallback"
                        normalize_png(download(url), out_path)
                        break

            if not out_path.exists():
                raise RuntimeError("No usable image found")
        except Exception as e:
            failures.append((wid, name, str(e)))
            make_placeholder(name, out_path)
            method = "Placeholder - needs manual replacement"

        source_rows.append({
            "wrestler_id": wid,
            "name": name,
            "file": out_path.name,
            "source_method": method,
            "source_page": source_page,
            "source_image_url": source_url,
            "license": license_name,
            "artist": artist,
            "credit": credit,
        })

    with (OUT/"SOURCES.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=source_rows[0].keys())
        w.writeheader()
        w.writerows(source_rows)

    with (OUT/"MISSING.txt").open("w", encoding="utf-8") as f:
        if failures:
            for wid, name, err in failures:
                f.write(f"{wid}\t{name}\t{err}\n")
        else:
            f.write("No missing wrestler images.\n")

    print(f"Done. {len(manifest)-len(failures)} real images, {len(failures)} placeholders.")

if __name__ == "__main__":
    main()
