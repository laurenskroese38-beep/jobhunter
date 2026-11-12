#!/usr/bin/env python3
"""Capture de pages réelles pour diagnostiquer / améliorer l'extraction.

Pour chaque société (par défaut : celles sans résultat au dernier passage) :
  data/dump/<slug>/home.html, home.json (liens, requêtes réseau, JSON reçus)
  data/dump/<slug>/cand<N>.html/.json  (pages carrière candidates)
  data/dump/<slug>/robots.txt, sitemap.xml (si présents)
Usage : python tools/dump_sites.py [--all] [--limit N] [noms...]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import threading
import queue
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests  # noqa: E402
import yaml  # noqa: E402

from jobhunter import browser as br  # noqa: E402

OUT = ROOT / "data" / "dump"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"}


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50]


def save_scan(d: Path, tag: str, sc: br.Scan):
    (d / f"{tag}.html").write_text(sc.html or "", encoding="utf-8")
    payloads = []
    for u, data in sc.payloads[:30]:
        s = json.dumps(data, ensure_ascii=False)
        payloads.append({"url": u, "size": len(s), "sample": s[:3000]})
    meta = {"url": sc.url, "final_url": sc.final_url, "ok": sc.ok, "error": sc.error,
            "links": sc.links[:600], "requests": sorted(set(sc.seen_urls))[:800],
            "payloads": payloads, "text": sc.text[:20000]}
    (d / f"{tag}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


def candidates(sc: br.Scan, home: str, n=3):
    hostbase = ".".join(urlparse(sc.final_url or home).netloc.split(".")[-2:])
    out = []
    for text, href in sc.links:
        hay = f"{text} {urlparse(href).path}"
        if br.STRONG_CAREER.search(hay) or br.WEAK_CAREER.search(text.split("\n")[0]):
            h = urlparse(href).netloc
            if (h.endswith(hostbase) or br.ATS_HOST.search(h)) and href not in out:
                out.append(href)
    return out[:n]


def fetch_static(d: Path, home: str):
    base = f"{urlparse(home).scheme}://{urlparse(home).netloc}"
    for name, path in (("robots.txt", "/robots.txt"), ("sitemap.xml", "/sitemap.xml")):
        try:
            r = requests.get(base + path, headers=UA, timeout=15)
            if r.status_code == 200 and len(r.text) < 3_000_000:
                (d / name).write_text(r.text, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            (d / (name + ".err")).write_text(str(e), encoding="utf-8")


def work(q, done, lock):
    with br.Browser(min_delay=1, max_delay=2, timeout=30, settle=6) as b:
        while True:
            try:
                f = q.get_nowait()
            except queue.Empty:
                return
            d = OUT / slug(f["name"])
            d.mkdir(parents=True, exist_ok=True)
            home = f.get("website") or ""
            if home and not home.startswith("http"):
                home = "https://" + home
            try:
                fetch_static(d, home)
                sc = b.scan(home)
                save_scan(d, "home", sc)
                urls = ([f["careers_url"]] if f.get("careers_url") else []) + candidates(sc, home)
                for i, u in enumerate(urls[:3]):
                    save_scan(d, f"cand{i}", b.scan(u))
                (d / "info.json").write_text(json.dumps({"firm": f, "candidates": urls},
                                                        ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                (d / "error.txt").write_text(repr(e), encoding="utf-8")
            with lock:
                done.append(f["name"])
                print(f"[{len(done)}] {f['name']}", flush=True)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    firms = yaml.safe_load(open(ROOT / "firms.yaml", encoding="utf-8"))["firms"]
    firms = [f for f in firms if f.get("site", True) and f.get("website")]
    if args:
        firms = [f for f in firms if any(a.lower() in f["name"].lower() for a in args)]
    elif "--all" not in sys.argv:
        db = sqlite3.connect(ROOT / "data" / "jobs.sqlite")
        good = {r[0] for r in db.execute(
            "select company from firm_state where found > 0 or method like 'api:%'")}
        firms = [f for f in firms if f["name"] not in good]
    if "--limit" in sys.argv:
        firms = firms[:int(sys.argv[sys.argv.index("--limit") + 1])]
    print(f"{len(firms)} sociétés à capturer", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    q, done, lock = queue.Queue(), [], threading.Lock()
    for f in firms:
        q.put(f)
    ths = [threading.Thread(target=work, args=(q, done, lock)) for _ in range(3)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    print("Terminé :", OUT)


if __name__ == "__main__":
    main()
