"""Données structurées : schema.org JobPosting (JSON-LD, celles que les sites
publient pour Google Jobs) et sitemaps XML.

Ce sont les sources les plus fiables : publiées volontairement par les sites,
stables, et identiques quel que soit l'habillage de la page.
"""
from __future__ import annotations

import gzip
import html as htmllib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

log = logging.getLogger(__name__)

_LD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                    re.I | re.S)


# ---------------------------------------------------------------------------
# JSON-LD JobPosting
# ---------------------------------------------------------------------------
def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _types(node) -> set[str]:
    t = node.get("@type")
    return {str(v).split("/")[-1] for v in _as_list(t)}


def _iter_nodes(data):
    """Parcourt tous les objets d'un bloc JSON-LD (listes, @graph, ItemList...)."""
    stack = [data]
    while stack:
        n = stack.pop()
        if isinstance(n, list):
            stack.extend(n)
        elif isinstance(n, dict):
            yield n
            for k in ("@graph", "itemListElement", "item", "mainEntity", "hasPart"):
                if k in n:
                    stack.append(n[k])


def _place_text(place) -> str:
    out = []
    for p in _as_list(place):
        if isinstance(p, str):
            out.append(p)
            continue
        if not isinstance(p, dict):
            continue
        addr = p.get("address", p)
        if isinstance(addr, str):
            out.append(addr)
            continue
        if isinstance(addr, dict):
            country = addr.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name") or country.get("identifier")
            parts = [addr.get("addressLocality"), addr.get("addressRegion"), country]
            out.append(", ".join(str(x) for x in parts if x))
        elif p.get("name"):
            out.append(str(p["name"]))
    return " / ".join(x for x in out if x)[:200]


def _clean(text) -> str:
    if not text:
        return ""
    text = htmllib.unescape(str(text))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def jobpostings_from_html(page_html: str, page_url: str = "") -> list[dict]:
    """Toutes les offres JobPosting déclarées dans la page (JSON-LD)."""
    jobs = []
    for raw in _LD_RE.findall(page_html or ""):
        raw = raw.strip().strip("<!--").strip("-->")
        try:
            data = json.loads(raw)
        except ValueError:
            try:   # JSON-LD mal formé courant : retours ligne / tabulations dans les chaînes
                data = json.loads(re.sub(r"[\r\n\t]+", " ", raw))
            except ValueError:
                continue
        for node in _iter_nodes(data):
            if "JobPosting" not in _types(node):
                continue
            title = _clean(node.get("title") or node.get("name"))
            if not title:
                continue
            org = node.get("hiringOrganization")
            if isinstance(org, dict):
                org = org.get("name")
            loc = _place_text(node.get("jobLocation"))
            if not loc and node.get("jobLocationType") == "TELECOMMUTE":
                loc = _place_text(node.get("applicantLocationRequirements")) or "Remote"
            emp = " ".join(str(e) for e in _as_list(node.get("employmentType")))
            jobs.append({
                "title": title,
                "location": loc,
                "url": node.get("url") or page_url,
                "description": _clean(node.get("description"))[:4000],
                "posted": str(node.get("datePosted") or "")[:10],
                "valid_through": str(node.get("validThrough") or "")[:10],
                "employment_type": emp,
                "company_hint": _clean(org) if org else "",
            })
    return jobs


# ---------------------------------------------------------------------------
# Sitemaps
# ---------------------------------------------------------------------------
JOB_URL = re.compile(
    r"/(job|jobs|stelle|stellen|stellenangebot|offre|offres|emploi|position|positions|vacanc\w*|"
    r"opening|career/job|careers/job|jobdetail|job-detail|posting|requisition|karriere/\w+/\d|"
    r"en/job|de/job|fr/job)[s]?[/\-_=?]", re.I)
CAREER_URL = re.compile(r"/(careers?|karriere|carrieres?|carri%c3%a8res?|jobs?|join[-_]?us|"
                        r"work[-_]with[-_]us|emplois?|stellen\w*|offene[-_]stellen|vacancies|"
                        r"open[-_]positions|jobs[-_]and[-_]careers|lavora[-_]con[-_]noi)(/|$|\.html?|\?)", re.I)
_LOC_TAG = re.compile(r"<(?:\w+:)?loc>\s*([^<\s]+)\s*</(?:\w+:)?loc>", re.I)


def parse_sitemap(content: bytes | str) -> tuple[list[str], list[str]]:
    """Renvoie (urls de pages, urls de sous-sitemaps)."""
    if isinstance(content, bytes):
        if content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except OSError:
                return [], []
        content = content.decode("utf-8", "replace")
    is_index = "<sitemapindex" in content[:2000].lower()
    locs = [htmllib.unescape(u) for u in _LOC_TAG.findall(content)]
    return ([], locs) if is_index else (locs, [])


def sitemaps_from_robots(robots_txt: str, base: str) -> list[str]:
    out = []
    for line in (robots_txt or "").splitlines():
        if line.lower().startswith("sitemap:"):
            out.append(urljoin(base, line.split(":", 1)[1].strip()))
    return out


def title_from_url(url: str) -> str:
    """« /jobs/12345-investment-analyst-intern-zurich » → « Investment Analyst Intern Zurich »."""
    path = urlparse(url).path.rstrip("/")
    seg = path.split("/")[-1] if path else ""
    if re.fullmatch(r"[\d\-_]+|[a-f0-9\-]{16,}", seg or "") and path.count("/") > 1:
        seg = path.split("/")[-2]
    seg = re.sub(r"\.(html?|aspx?|php)$", "", seg)
    seg = re.sub(r"(^|[-_])(\d{3,}|[a-f0-9]{8,}|jr\d+|req\d+|r\d{4,})(?=[-_]|$)", " ", seg, flags=re.I)
    words = [w for w in re.split(r"[-_+]+|%20", seg) if w]
    return " ".join(w if w.isupper() else w.capitalize() for w in words).strip()


def collect_sitemap_urls(fetch, base: str, max_sitemaps: int = 12, max_urls: int = 20000):
    """fetch(url) -> bytes|str|None. Parcourt robots.txt → sitemaps → sous-sitemaps.
    Renvoie (urls d'offres, urls de pages carrière)."""
    queue_, seen, pages = [], set(), []
    robots = fetch(urljoin(base, "/robots.txt"))
    if robots:
        queue_ += sitemaps_from_robots(robots if isinstance(robots, str) else
                                       robots.decode("utf-8", "replace"), base)
    if not queue_:
        queue_ = [urljoin(base, "/sitemap.xml"), urljoin(base, "/sitemap_index.xml")]
    # sous-sitemaps consacrés aux offres en priorité
    n = 0
    while queue_ and n < max_sitemaps and len(pages) < max_urls:
        queue_.sort(key=lambda u: 0 if re.search(r"job|career|karriere|stelle|vacanc|offre", u, re.I) else 1)
        sm = queue_.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        n += 1
        content = fetch(sm)
        if not content:
            continue
        urls, subs = parse_sitemap(content)
        pages += urls
        queue_ += [s for s in subs if s not in seen]
    jobs = [u for u in pages if JOB_URL.search(u)]
    careers = [u for u in pages if CAREER_URL.search(u) and u not in jobs]
    return jobs, careers
