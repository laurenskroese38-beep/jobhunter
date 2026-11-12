"""Connecteurs vers les ATS (logiciels de recrutement) et page carrière générique.

Chaque connecteur renvoie une liste de dicts au format commun :
    title, company, location, url, description, posted, source
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .http import DomainSuspended, PoliteSession

log = logging.getLogger(__name__)


def _job(company, title, location, url, description="", posted="", source=""):
    return {
        "title": (title or "").strip(),
        "company": company,
        "location": (location or "").strip(),
        "url": url,
        "description": _strip_html(description)[:4000],
        "posted": posted or "",
        "source": source,
    }


def _strip_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", text).strip()


def _ms_to_date(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _json(resp):
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Connecteurs
# ---------------------------------------------------------------------------
def greenhouse(s: PoliteSession, company: str, slug: str, **_):
    data = _json(s.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
                       params={"content": "true"}))
    if not data:
        return []
    return [
        _job(company, j.get("title"), (j.get("location") or {}).get("name"),
             j.get("absolute_url"), j.get("content", ""),
             (j.get("updated_at") or "")[:10], "greenhouse")
        for j in data.get("jobs", [])
    ]


def lever(s: PoliteSession, company: str, slug: str, **_):
    data = None
    for host in ("api.lever.co", "api.eu.lever.co"):  # Lever a une instance UE
        data = _json(s.get(f"https://{host}/v0/postings/{slug}", params={"mode": "json"}))
        if data:
            break
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        out.append(_job(company, j.get("text"), " / ".join(filter(None, locs)),
                        j.get("hostedUrl"), j.get("descriptionPlain", ""),
                        _ms_to_date(j.get("createdAt")), "lever"))
    return out


def ashby(s: PoliteSession, company: str, slug: str, **_):
    data = _json(s.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}"))
    if not data:
        return []
    out = []
    for j in data.get("jobs", []):
        locs = [j.get("location", "")] + [
            x.get("location", "") for x in j.get("secondaryLocations") or []]
        out.append(_job(company, j.get("title"), " / ".join(filter(None, locs)),
                        j.get("jobUrl"), j.get("descriptionPlain", ""),
                        (j.get("publishedAt") or "")[:10], "ashby"))
    return out


def smartrecruiters(s: PoliteSession, company: str, slug: str, max_pages: int = 10, **_):
    out, offset = [], 0
    for _ in range(max_pages):
        data = _json(s.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings",
                           params={"limit": 100, "offset": offset}))
        if not data:
            break
        items = data.get("content", [])
        for j in items:
            loc = j.get("location") or {}
            where = ", ".join(filter(None, [loc.get("city"), loc.get("region"),
                                            (loc.get("country") or "").upper()]))
            out.append(_job(company, j.get("name"), where,
                            f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                            "", (j.get("releasedDate") or "")[:10], "smartrecruiters"))
        offset += len(items)
        if not items or offset >= data.get("totalFound", 0):
            break
    return out


_WD_RE = re.compile(
    r"https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)")


def workday(s: PoliteSession, company: str, url: str, search_terms=(), max_pages: int = 5, **_):
    """Workday n'a pas de liste complète bon marché : on interroge sa recherche
    avec quelques mots-clés au lieu de paginer des milliers d'offres."""
    m = _WD_RE.match(url)
    if not m:
        log.warning("URL Workday non reconnue pour %s : %s", company, url)
        return []
    tenant, wd, site = m.groups()
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    seen, out = set(), []
    for term in search_terms or [""]:
        total = 0
        for page in range(max_pages):
            body = {"appliedFacets": {}, "limit": 20, "offset": page * 20, "searchText": term}
            data = _json(s.post(api, json=body))
            if not data and page:          # page suivante refusée (limitation) : un nouvel essai
                data = _json(s.post(api, json=body))
            if not data:
                break
            # Workday n'indique le total qu'en première page (0 ensuite)
            total = data.get("total") or total
            posts = data.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath", "")
                if not path or path in seen:
                    continue
                seen.add(path)
                loc = j.get("locationsText") or ""
                if re.fullmatch(r"\d+ (Locations?|Standorte|Sites|Lieux)", loc.strip(), re.I):
                    loc = ""      # « 2 Locations » : lieu de la société utilisé à la place
                out.append(_job(company, j.get("title"), loc,
                                f"{base}/{site}{path}", "", j.get("postedOn", ""), "workday"))
            if len(posts) < 20 or (total and (page + 1) * 20 >= total):
                break
    return out


_JOB_LINK_HINT = re.compile(
    r"job|career|carri|stelle|offre|poste|position|vacanc|opening|emploi|stage|intern", re.I)


def generic_html(s: PoliteSession, company: str, url: str, **_):
    """Dernier recours : liens de la page carrière dont le texte ressemble à une offre.
    Le filtrage par mots-clés en aval élimine le bruit."""
    resp = s.get(url, check_robots=True)
    if resp is None or resp.status_code != 200:
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ")).strip()
        href = urljoin(resp.url, a["href"])
        if not (8 <= len(text) <= 140) or href in seen:
            continue
        if not _JOB_LINK_HINT.search(href + " " + text):
            continue
        seen.add(href)
        out.append(_job(company, text, "", href, "", "", "site carrière"))
    return out


def personio(s: PoliteSession, company: str, slug: str, **_):
    """Flux XML public de Personio (très répandu chez les PME suisses)."""
    import xml.etree.ElementTree as ET
    for tld in ("de", "com"):
        resp = s.get(f"https://{slug}.jobs.personio.{tld}/xml", params={"language": "en"})
        if resp is not None and resp.status_code == 200 and "<position" in resp.text:
            break
    else:
        return []
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError:
        return []
    out = []
    for pos in root.iter("position"):
        get = lambda k: (pos.findtext(k) or "").strip()  # noqa: E731
        desc = " ".join((d.findtext("value") or "") for d in pos.iter("jobDescription"))
        out.append(_job(company, get("name"), get("office"),
                        f"https://{slug}.jobs.personio.{tld}/job/{get('id')}",
                        desc, get("createdAt")[:10], "personio"))
    return out


def recruitee(s: PoliteSession, company: str, slug: str, **_):
    data = _json(s.get(f"https://{slug}.recruitee.com/api/offers/"))
    if not data:
        return []
    out = []
    for j in data.get("offers", []):
        where = j.get("location") or ", ".join(filter(None, [j.get("city"), j.get("country")]))
        out.append(_job(company, j.get("title"), where, j.get("careers_url") or j.get("url"),
                        j.get("description", ""), (j.get("published_at") or "")[:10], "recruitee"))
    return out


def workable(s: PoliteSession, company: str, slug: str, **_):
    data = _json(s.get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}"))
    if not data:
        return []
    out = []
    for j in data.get("jobs", []):
        where = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
        out.append(_job(company, j.get("title"), where,
                        j.get("url") or j.get("shortlink") or f"https://apply.workable.com/{slug}/",
                        "", (j.get("published_on") or "")[:10], "workable"))
    return out


_ORACLE_RE = re.compile(r"https?://([\w.-]+\.oraclecloud\.(?:com|eu))/hcmUI/CandidateExperience/"
                        r"(?:\w{2}(?:-\w{2})?/)?sites/([\w-]+)", re.I)


def oracle(s: PoliteSession, company: str, url: str, max_pages: int = 8, **_):
    """Oracle Recruiting Cloud (UBP, EFG…) : API publique utilisée par la page elle-même.
    Résultats triés du plus récent au plus ancien, 25 par page."""
    m = _ORACLE_RE.search(url or "")
    if not m:
        return []
    host, site = m.groups()
    api = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    out, seen = [], set()
    for page in range(max_pages):
        finder = f"findReqs;siteNumber={site},limit=25,offset={page * 25},sortBy=POSTING_DATES_DESC"
        data = _json(s.get(api, params={"onlyData": "true", "finder": finder,
                                        "expand": "requisitionList.secondaryLocations"}))
        items = (data or {}).get("items") or []
        reqs = (items[0].get("requisitionList") if items else None) or []
        for r in reqs:
            rid = str(r.get("Id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            locs = [r.get("PrimaryLocation") or ""] + [
                x.get("Name", "") for x in (r.get("secondaryLocations") or []) if isinstance(x, dict)]
            out.append(_job(company, r.get("Title"), " / ".join(l for l in locs if l),
                            f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
                            r.get("ShortDescriptionStr") or "", str(r.get("PostedDate") or "")[:10],
                            "oracle"))
        total = items[0].get("TotalJobsCount", 0) if items else 0
        if len(reqs) < 25 or (total and (page + 1) * 25 >= total):
            break
    return out


CONNECTORS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "smartrecruiters": smartrecruiters,
    "workday": workday,
    "oracle": oracle,
    "personio": personio,
    "recruitee": recruitee,
    "workable": workable,
    "html": generic_html,
}


# ---------------------------------------------------------------------------
# Détection automatique de l'ATS à partir d'une page carrière
# ---------------------------------------------------------------------------
_DETECT = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)")),
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([\w-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([\w-]+)")),
    ("smartrecruiters", re.compile(r"api\.smartrecruiters\.com/v1/companies/([\w-]+)")),
    ("personio", re.compile(r"([\w-]+)\.jobs\.personio\.(?:de|com)")),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com")),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?([\w-]+)")),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)")),
    ("lever", re.compile(r"api\.(?:eu\.)?lever\.co/v0/postings/([\w-]+)")),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([\w.-]+)")),
]

# Portails sans API publique simple : on les ouvre avec le navigateur.
PORTALS = re.compile(
    r"https?://(?:"
    r"career\d*\.successfactors\.(?:eu|com)/career\?[^\s\"'<>]*company=[\w]+[^\s\"'<>]*|"
    r"[\w.-]+\.successfactors\.(?:eu|com)/[^\s\"'<>]*|"
    r"recruitingapp-\d+\.umantis\.com/[^\s\"'<>]*|"
    r"[\w-]+\.abacuscity\.ch/[^\s\"'<>]*|"
    r"[\w-]+\.softgarden\.io/[^\s\"'<>]*|"
    r"[\w-]+\.teamtailor\.com/jobs[^\s\"'<>]*|"
    r"join\.com/companies/[\w-]+[^\s\"'<>]*|"
    r"[\w-]+\.onlyfy\.jobs[^\s\"'<>]*|[\w-]+\.prescreenapp\.io[^\s\"'<>]*|"
    r"[\w.-]+\.refline\.ch/[^\s\"'<>]*|"
    r"[\w.-]+\.oraclecloud\.com/hcmUI/CandidateExperience[^\s\"'<>]*|"
    r"[\w-]+\.taleo\.net/careersection[^\s\"'<>]*|"
    r"[\w-]+\.avature\.net/[^\s\"'<>]*|"
    r"[\w-]+\.jobs\.cz/[^\s\"'<>]*|"
    r"[\w.-]+\.icims\.com/jobs[^\s\"'<>]*|"
    r"[\w-]+\.bamboohr\.com/careers[^\s\"'<>]*|"
    r"[\w-]+\.breezy\.hr[^\s\"'<>]*|"
    r"[\w-]+\.jobs\.ch/[^\s\"'<>]*|www\.jobs\.ch/(?:en|de|fr)/companies/[^\s\"'<>]*|"
    r"(?:www\.)?jobup\.ch/(?:en|de|fr)/companies/[^\s\"'<>]*|"
    r"[\w-]+\.rexx-systems\.com/[^\s\"'<>]*|[\w-]+\.dvinci-hr\.com/[^\s\"'<>]*|"
    r"[\w-]+\.eightfold\.ai/careers[^\s\"'<>]*|[\w-]+\.csod\.com/ux/ats/careersite[^\s\"'<>]*|"
    r"[\w-]+\.pinpointhq\.com[^\s\"'<>]*|[\w-]+\.homerun\.co[^\s\"'<>]*|"
    r"jobs\.jobvite\.com/[\w-]+[^\s\"'<>]*|[\w-]+\.zohorecruit\.(?:com|eu)/[^\s\"'<>]*|"
    r"(?:www\.)?comeet\.com/jobs/[^\s\"'<>]*|[\w-]+\.careers\.hibob\.com[^\s\"'<>]*|"
    r"[\w-]+\.factorialhr\.\w+/[^\s\"'<>]*|[\w-]+\.talent-soft\.com/[^\s\"'<>]*|"
    r"[\w-]+\.jobs\.personio\.\w+/?[^\s\"'<>]*|(?:www\.)?ostendis\.com/[^\s\"'<>]*|"
    r"[\w-]+\.coveto\.de/[^\s\"'<>]*|[\w.-]+\.jobbase\.io/[^\s\"'<>]*"
    r")", re.I)


def detect_in(haystack: str) -> dict | None:
    """Cherche un ATS avec API dans un texte (HTML, URLs de requêtes réseau...)."""
    m = _WD_RE.search(haystack)
    if m:
        return {"ats": "workday", "url": m.group(0)}
    m = _ORACLE_RE.search(haystack)
    if m:
        return {"ats": "oracle", "url": m.group(0)}
    for ats, rx in _DETECT:
        for m in rx.finditer(haystack):
            if m.group(1).lower() not in _IGNORED_SLUGS:
                return {"ats": ats, "slug": m.group(1)}
    return None


_ASSET = re.compile(r"\.(css|js|png|jpe?g|svg|gif|woff2?|ico|json)(\?|$)|rmkcdn\.|/static/|/assets?/", re.I)


def find_portal(haystack: str) -> str | None:
    """Premier lien vers un portail de recrutement (pas une ressource CSS/JS du portail)."""
    for m in PORTALS.finditer(haystack):
        url = html.unescape(m.group(0)).rstrip(".,;)")
        if not _ASSET.search(url):
            return url
    return None
_IGNORED_SLUGS = {"embed", "js", "api", "v1", "v2", "v3", "jobs", "job_board", "www", "j",
                  "widget", "accounts", "careers", "app", "static", "assets", "cdn"}


def detect_ats(s: PoliteSession, careers_url: str) -> dict:
    """Renvoie {'ats': ..., 'slug'|'url': ...}. Retombe sur 'html' si rien trouvé."""
    m = _WD_RE.search(careers_url)
    if m:
        return {"ats": "workday", "url": m.group(0)}
    for ats, rx in _DETECT:
        m = rx.search(careers_url)
        if m and m.group(1) not in _IGNORED_SLUGS:
            return {"ats": ats, "slug": m.group(1)}
    try:
        resp = s.get(careers_url, check_robots=True)
    except DomainSuspended:
        resp = None
    if resp is not None and resp.status_code == 200:
        haystack = resp.url + "\n" + resp.text
        m = _WD_RE.search(haystack)
        if m:
            return {"ats": "workday", "url": m.group(0)}
        for ats, rx in _DETECT:
            for m in rx.finditer(haystack):
                if m.group(1) not in _IGNORED_SLUGS:
                    return {"ats": ats, "slug": m.group(1)}
    return {"ats": "html", "url": careers_url}


def fetch_company(s: PoliteSession, company: dict, resolved: dict, ats_cfg: dict):
    """company = entrée du config ; resolved = résultat de detect_ats (ou config explicite)."""
    ats = resolved["ats"]
    fn = CONNECTORS.get(ats)
    if fn is None:
        log.warning("ATS inconnu %s pour %s", ats, company["name"])
        return []
    try:
        jobs = fn(s, company["name"],
                  slug=resolved.get("slug"), url=resolved.get("url"),
                  search_terms=ats_cfg.get("workday_search_terms", []),
                  max_pages=ats_cfg.get("workday_max_pages", 5))
    except DomainSuspended as exc:
        log.warning("%s : domaine %s suspendu, ignoré", company["name"], exc)
        return []
    except Exception:  # un connecteur cassé ne doit jamais faire tomber tout le run
        log.exception("Erreur inattendue pour %s", company["name"])
        return []
    default_loc = company.get("default_location")
    for j in jobs:
        if not j["location"] and default_loc:
            j["location"] = default_loc
    return jobs
