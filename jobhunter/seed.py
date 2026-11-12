"""Import de l'annuaire des membres SECA (Swiss Private Equity & Corporate
Finance Association) : nom, site web, type de société, ville, pays.

Une requête par fiche membre, avec les pauses du client poli : ~15-25 min
pour ~500 membres. À lancer une fois (ou de temps en temps)."""
from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
LIST_URL = "https://www.seca.ch/en/members"
MEMBER_RE = re.compile(r"/en/find-members/[\w%-]+/?$")
FIELDS = ["Company Name", "Homepage", "Type of Firm", "Status", "Town", "Country",
          "Investment Stages", "Geographical Focus"]


def parse_member(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        if dd:
            out[dt.get_text(" ", strip=True).rstrip(":")] = dd.get_text(" ", strip=True)
    # repli : lignes « Libellé » puis « valeur » dans le texte
    lines = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]
    for i, line in enumerate(lines[:-1]):
        label = line.rstrip(":")
        if label in FIELDS and label not in out:
            out[label] = lines[i + 1]
    if "Homepage" not in out:
        for a in soup.find_all("a", href=True):
            if a.get_text(strip=True).lower().startswith(("www.", "http")):
                out["Homepage"] = a.get_text(strip=True)
                break
    return out


def seca_members(s, out_path: Path) -> int:
    resp = s.get(LIST_URL)
    if resp is None or resp.status_code != 200:
        raise RuntimeError("annuaire SECA inaccessible")
    soup = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(resp.url, a["href"])
        if MEMBER_RE.search(href) and href not in links:
            links.append(href)
    log.info("SECA : %d fiches membres", len(links))
    rows = []
    for i, href in enumerate(links, 1):
        r = s.get(href)
        if r is None or r.status_code != 200:
            continue
        d = parse_member(r.text)
        d["SECA page"] = href
        rows.append(d)
        if i % 25 == 0:
            log.info("SECA : %d/%d", i, len(links))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS + ["SECA page"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)
