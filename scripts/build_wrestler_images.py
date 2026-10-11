#!/usr/bin/env python3
from __future__ import annotations
import csv, io, json, random, re, time
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image, ImageDraw
from rembg import remove

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "wrestlers"
OUT.mkdir(exist_ok=True)
MANIFEST = ROOT / "wrestlers_manifest.json"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKI_API = "https://en.wikipedia.org/w/api.php"
S = requests.Session()
S.headers.update({
    "User-Agent": "NoMercyUniverse/1.1 (fan archive image builder; Wikimedia source attribution preserved)",
    "Accept": "application/json,text/plain,*/*",
})

REQUEST_GAP = 2.0
DOWNLOAD_GAP = 1.0
MAX_RETRIES = 7
last_request = 0.0

GOOD_YEARS = {1998:25, 1999:35, 2000:42, 2001:30, 1997:10, 2002:8}
BAD_WORDS = {"logo","poster","belt","arena","match card","dvd","video game",
             "action figure","toy","autograph","signature","collage","crowd"}

def clean_html(s):
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").strip()

def wait_gap(gap):
    global last_request
    delay = last_request + gap - time.time()
    if delay > 0:
        time.sleep(delay)
    last_request = time.time()

def get_json(url, params):
    for attempt in range(MAX_RETRIES):
        wait_gap(REQUEST_GAP)
        r = S.get(url, params=params, timeout=60)
        if r.status_code == 429:
            try:
                delay = max(float(r.headers.get("Retry-After", "0")), 12.0)
            except Exception:
                delay = min(90.0, 12.0 * (attempt + 1))
            print(f"  API 429 -> waiting {delay:.0f}s")
            time.sleep(delay + random.uniform(.5, 2.0))
            continue
        if r.status_code >= 500:
            time.sleep(min(45, 5 * (attempt + 1)))
            continue
        r.raise_for_status()
        if "json" not in r.headers.get("content-type", "").lower():
            time.sleep(min(60, 8 * (attempt + 1)))
            continue
        return r.json()
    raise RuntimeError("Wikimedia API repeatedly rate-limited")

def download(url):
    for attempt in range(MAX_RETRIES):
        wait_gap(DOWNLOAD_GAP)
        r = S.get(url, timeout=90)
        if r.status_code == 429:
            try:
                delay = max(float(r.headers.get("Retry-After", "0")), 15.0)
            except Exception:
                delay = min(120.0, 15.0 * (attempt + 1))
            print(f"  image 429 -> waiting {delay:.0f}s")
            time.sleep(delay + random.uniform(.5, 2.0))
            continue
        if r.status_code >= 500:
            time.sleep(min(45, 5 * (attempt + 1)))
            continue
        r.raise_for_status()
        return r.content
    raise RuntimeError("Image download repeatedly rate-limited")

def commons_search(query, limit=10):
    data = get_json(COMMONS_API, {
        "action":"query","format":"json","formatversion":2,
        "generator":"search","gsrsearch":query,"gsrnamespace":6,"gsrlimit":limit,
        "prop":"imageinfo","iiprop":"url|size|extmetadata","iiurlwidth":800,
    })
    return (data.get("query") or {}).get("pages", [])

def wikipedia_thumb(title):
    data = get_json(WIKI_API, {
        "action":"query","format":"json","formatversion":2,"redirects":1,
        "titles":title,"prop":"pageimages","piprop":"thumbnail","pithumbsize":800,
    })
    pages = (data.get("query") or {}).get("pages", [])
    return ((pages[0].get("thumbnail") or {}).get("source") if pages else None)

def score(page, name):
    ii = (page.get("imageinfo") or [{}])[0]
    meta = ii.get("extmetadata") or {}
    text = ((page.get("title") or "") + " " +
            clean_html((meta.get("ImageDescription") or {}).get("value",""))).lower()
    s = 0
    for t in [x.lower() for x in re.findall(r"[A-Za-z0-9]+", name) if len(x) > 2]:
        if t in text: s += 9
    for w in ("wrestler","wrestling","wwf","wwe","ecw","wcw"):
        if w in text: s += 7
    for y,p in GOOD_YEARS.items():
        if str(y) in text: s += p
    for w in BAD_WORDS:
        if w in text: s -= 25
    width, height = ii.get("width") or 0, ii.get("height") or 0
    if width and height:
        ratio = height / max(width, 1)
        if .8 <= ratio <= 2.6: s += 10
        if min(width,height) >= 350: s += 5
    return s

def best_candidate(name, aliases):
    primary = (aliases or [name])[0]
    queries = [f'"{primary}" wrestling 1999 OR 2000']
    if primary.lower() != name.lower():
        queries.append(f'"{name}" professional wrestler')
    else:
        queries.append(f'"{name}" WWF OR WWE OR ECW OR WCW')
    seen = {}
    for q in queries:
        try:
            for p in commons_search(q):
                if p.get("title"): seen[p["title"]] = p
        except Exception as e:
            print("  search warning:", e)
    ranked = sorted(seen.values(), key=lambda p: score(p, name), reverse=True)
    return ranked[0] if ranked else None

def normalize(raw, path):
    im = Image.open(io.BytesIO(raw)).convert("RGBA")
    if max(im.size) > 1400:
        im.thumbnail((1400,1400), Image.Resampling.LANCZOS)
    if im.getchannel("A").getextrema()[0] >= 245:
        result = remove(im)
        im = Image.open(io.BytesIO(result)).convert("RGBA") if isinstance(result, bytes) else result.convert("RGBA")
    bbox = im.getchannel("A").getbbox()
    if bbox:
        im = im.crop(bbox)
    tw, th = 800, 1000
    scale = min((tw*.90)/max(im.width,1), (th*.94)/max(im.height,1))
    im = im.resize((max(1,int(im.width*scale)), max(1,int(im.height*scale))), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA",(tw,th),(0,0,0,0))
    canvas.alpha_composite(im, ((tw-im.width)//2, th-im.height))
    canvas.save(path, "PNG", optimize=True)

def placeholder(name, path):
    im = Image.new("RGBA",(800,1000),(0,0,0,0))
    d = ImageDraw.Draw(im)
    initials = "".join(w[0] for w in name.split()[:3]).upper()
    d.ellipse((190,180,610,600), fill=(40,40,45,255))
    d.rectangle((155,570,645,930), fill=(40,40,45,255))
    d.text((400,410), initials, anchor="mm", fill=(230,230,230,255))
    im.save(path,"PNG")

def missing_ids():
    p = OUT/"MISSING.txt"
    if not p.exists():
        return None
    ids=set()
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        m=re.match(r"^\s*(\d+)\t", line)
        if m:
            ids.add(int(m.group(1)))
    return ids or None

def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    retry = missing_ids()
    work = [r for r in manifest if int(r["id"]) in retry] if retry else manifest
    print(f"Processing {len(work)} wrestlers ({'retry only' if retry else 'full run'}).")

    sources = {}
    sp = OUT/"SOURCES.csv"
    if sp.exists():
        try:
            with sp.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    sources[int(row["wrestler_id"])] = row
        except Exception:
            pass

    failures=[]
    for i, rec in enumerate(work, 1):
        wid=int(rec["id"]); name=rec["name"]; aliases=rec.get("aliases") or [name]
        path=OUT/f"wrestler-{wid}.png"
        print(f"[{i}/{len(work)}] {wid} {name}")
        row={"wrestler_id":wid,"name":name,"file":path.name,"source_method":"",
             "source_page":"","source_image_url":"","license":"","artist":"","credit":""}
        try:
            cand=best_candidate(name, aliases)
            if cand:
                ii=(cand.get("imageinfo") or [{}])[0]
                meta=ii.get("extmetadata") or {}
                url=ii.get("thumburl") or ii.get("url")
                if url:
                    normalize(download(url), path)
                    row.update({
                        "source_method":"Wikimedia Commons",
                        "source_page":"https://commons.wikimedia.org/wiki/"+quote((cand.get("title") or "").replace(" ","_")),
                        "source_image_url":url,
                        "license":clean_html((meta.get("LicenseShortName") or {}).get("value","")),
                        "artist":clean_html((meta.get("Artist") or {}).get("value","")),
                        "credit":clean_html((meta.get("Credit") or {}).get("value","")),
                    })
            if not path.exists():
                for alias in (aliases[:2] + [name]):
                    url=wikipedia_thumb(alias)
                    if url:
                        normalize(download(url), path)
                        row.update({
                            "source_method":"Wikipedia thumbnail fallback",
                            "source_page":"https://en.wikipedia.org/wiki/"+quote(alias.replace(" ","_")),
                            "source_image_url":url,
                        })
                        break
            if not path.exists():
                raise RuntimeError("No usable image found")
            sources[wid]=row
        except Exception as e:
            print("  FAILED:", e)
            failures.append((wid,name,str(e)))
            if not path.exists():
                placeholder(name,path)

    with (OUT/"MISSING.txt").open("w",encoding="utf-8") as f:
        if failures:
            for wid,name,err in failures:
                f.write(f"{wid}\t{name}\t{err}\n")
        else:
            f.write("No missing wrestler images.\n")

    fields=["wrestler_id","name","file","source_method","source_page","source_image_url","license","artist","credit"]
    with (OUT/"SOURCES.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for wid in sorted(sources):
            w.writerow({k:sources[wid].get(k,"") for k in fields})
    print(f"Recovered {len(work)-len(failures)}; still missing {len(failures)}.")

if __name__=="__main__":
    main()
