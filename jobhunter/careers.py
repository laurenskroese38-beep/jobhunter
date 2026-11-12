"""Collecte sur les sites carrières, société par société.

Pour chaque société (firms.yaml) :
  1. ATS déjà connu (config ou mémorisé)       → API publique de l'ATS (rapide, fiable)
  2. sinon page carrière (config, ou trouvée depuis la page d'accueil)
     ouverte dans le navigateur :
       - ATS repéré dans les requêtes / iframes / liens → API
       - portail sans API (SuccessFactors, Umantis...) → ouvert à son tour
       - sinon offres lues dans la page ; si la page n'est qu'une vitrine,
         on suit le lien « Open positions / Offres d'emploi »
  3. la méthode qui a marché est mémorisée (detect_cache_days) et le résultat
     consigné dans l'onglet « Couverture » du rapport.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

from . import ats, browser as br, structured
from .http import DomainSuspended, PoliteSession

log = logging.getLogger(__name__)

# catégorie → (domaine attribué aux postes junior sans domaine dans l'intitulé,
#              « société d'investissement » pour les programmes génériques)
CATEGORIES = {
    "pe": ("Private Equity / VC / Private Markets", True),
    "vc": ("Private Equity / VC / Private Markets", True),
    "privmkt": ("Private Equity / VC / Private Markets", True),
    "ma": ("M&A / Investment Banking", True),
    "ib": (None, True),
    "am": ("Asset Management / Investments", True),
    "hf": ("Asset Management / Investments", True),
    "mfo": ("Asset Management / Investments", True),
    "bank": (None, True),
    "advisory": (None, False),
    "big4": (None, False),
    "insurer": (None, False),
    "corporate": (None, False),
}


def firm_profile(firm: dict) -> dict:
    dom, inv = CATEGORIES.get(firm.get("category", ""), (None, True))
    return {"investment_firm": firm.get("investment_firm", inv), "domain": firm.get("domain", dom)}


def _homepage(firm: dict) -> str | None:
    w = firm.get("website")
    if not w:
        return None
    return w if w.startswith("http") else "https://" + w.strip("/")


def _api(s, firm, resolved, acfg, b=None):
    company = {"name": firm["name"], "default_location": firm.get("default_location")}
    jobs = ats.fetch_company(s, company, resolved, acfg)
    if not jobs and resolved.get("ats") == "oracle" and b is not None and resolved.get("url"):
        # API Oracle non vérifiable partout : si elle ne renvoie rien, page lue au navigateur
        sc = b.scan(resolved["url"], expand=True)
        jobs, _ = br.extract_jobs(sc)
    return jobs


def _robots_ok(s, url: str) -> bool:
    if s is None or not getattr(s, "respect_robots", False):
        return True
    try:
        return s.allowed_by_robots(url)
    except Exception:  # noqa: BLE001
        return True


def _browser_jobs(b: br.Browser, url: str, depth: int = 0, s=None):
    """Ouvre url ; renvoie (offres, résolution, méthode, erreur)."""
    if not _robots_ok(s, url):
        return [], None, "", "robots.txt interdit cette page"
    sc = b.scan(url, expand=True)
    if not sc.ok and not sc.html:
        return [], None, "", sc.error or "page inaccessible"
    det = ats.detect_in(sc.haystack)
    if det:
        return None, det, "", ""
    portal = ats.find_portal(sc.haystack)
    if portal and depth < 2 and urlparse(portal).netloc != urlparse(sc.final_url).netloc:
        jobs, det, method, err = _browser_jobs(b, portal, depth + 1, s)
        if det or jobs:
            return jobs, det or {"ats": "browser", "url": portal}, method, err
    jobs, method = br.extract_jobs(sc)
    if not br.looks_like_listing(jobs) and depth < 2:
        nxt = br.pick_openings_link(sc)
        if nxt:
            jobs2, det2, method2, err2 = _browser_jobs(b, nxt, depth + 1, s)
            if det2 or jobs2:
                return jobs2, det2 or {"ats": "browser", "url": nxt}, method2, err2
    return jobs, {"ats": "browser", "url": sc.final_url or url}, method, sc.error


def host_variants(homepage: str) -> list[str]:
    """Autres façons d'écrire l'adresse : avec/sans www., puis http:// (vieux serveurs TLS)."""
    u = urlparse(homepage)
    host = u.netloc
    alt = host[4:] if host.startswith("www.") else "www." + host
    out = [homepage.replace("://" + host, "://" + alt, 1)]
    if u.scheme == "https":
        out.append(homepage.replace("https://", "http://", 1))
    return out


_NET_ERR = re.compile(r"ERR_|Timeout|timed out|SSL|CERT", re.I)


def _get_text(s: PoliteSession, url: str):
    try:
        r = s.get(url, check_robots=True)
    except DomainSuspended:
        return None
    except Exception:  # noqa: BLE001
        return None
    if r is None or r.status_code != 200:
        return None
    return r.content


def _pick_career_url(urls: list[str]) -> str | None:
    """La page carrière la plus « racine » parmi celles du sitemap, en anglais de préférence."""
    if not urls:
        return None
    def key(u):
        p = urlparse(u).path
        return (0 if re.search(r"/en(/|$)|^/(?!de/|fr/|it/)", p) else 1, p.count("/"), len(p))
    return sorted(urls, key=key)[0]


def sitemap_lookup(s: PoliteSession, base: str, budget: float = 45.0):
    """(page carrière, offres) d'après robots.txt / sitemap.xml du site."""
    if s is None:
        return None, []
    deadline = time.monotonic() + budget
    misses = [0]

    def fetch(u):
        # budget limité : un site lent ou cassé ne doit pas coûter plusieurs minutes
        if time.monotonic() > deadline or misses[0] >= 3:
            return None
        got = _get_text(s, u)
        if got is None:
            misses[0] += 1
        return got
    try:
        job_urls, career_urls = structured.collect_sitemap_urls(fetch, base, max_sitemaps=8)
    except Exception:  # noqa: BLE001
        log.debug("sitemap %s", base, exc_info=True)
        return None, []
    page = _pick_career_url(career_urls)
    if page:   # pages « sous » la page carrière = fiches d'offres (…/karriere/stagiaire-xyz/)
        root = page.rstrip("/") + "/"
        job_urls += [u for u in career_urls if u.startswith(root) and u.rstrip("/") + "/" != root
                     and u not in job_urls]
    jobs = [{"title": structured.title_from_url(u), "location": "", "url": u,
             "description": "", "posted": ""} for u in job_urls[:200]]
    jobs = [j for j in jobs if len(j["title"].split()) >= 2]
    return page, jobs


def _find_careers(b: br.Browser, s: PoliteSession, homepage: str) -> tuple[str | None, str, list]:
    """Renvoie (page carrière, erreur, offres trouvées directement dans le sitemap)."""
    url, sc = b.find_careers(homepage)
    if not url and not sc.ok and _NET_ERR.search(sc.error or ""):
        # certificat expiré, www. manquant, vieux TLS... : autres variantes de l'adresse
        for alt in host_variants(homepage):
            url2, sc2 = b.find_careers(alt)
            if url2 or sc2.ok:
                url, sc, homepage = url2, sc2, alt
                break
    if url:
        return url, "", []
    if sc.ok:
        base = f"{urlparse(sc.final_url or homepage).scheme}://{urlparse(sc.final_url or homepage).netloc}"
        # 1) sitemap : la page carrière (ou les offres elles-mêmes) déclarée par le site
        cur, sm_jobs = sitemap_lookup(s, base)
        if cur:
            return cur, "", sm_jobs
        # 2) chemins usuels, vérifiés par une simple requête
        for path in br.COMMON_PATHS:
            try:
                r = s.get(urljoin(base, path))
            except DomainSuspended:
                break
            except Exception:  # noqa: BLE001
                break
            if r is None:
                break                     # site injoignable : inutile d'essayer 20 adresses
            if r.status_code == 200 and len(r.text) > 2000 \
                    and urlparse(r.url).path.strip("/") \
                    and br.STRONG_CAREER.search(r.text[:200000]):
                return r.url, "", sm_jobs  # vraie page carrière (pas une redirection vers l'accueil)
        if sm_jobs:
            return None, "", sm_jobs
        return None, "aucune page carrière trouvée", []
    return None, sc.error or "site inaccessible", []


def enrich(s: PoliteSession, jobs: list[dict], page_url: str, limit: int = 6) -> int:
    """Ouvre la fiche des offres prometteuses (simple requête) pour lire leur JSON-LD
    JobPosting : vrai lieu, description (→ détection de l'allemand), date, type INTERN."""
    if s is None:
        return 0
    n = 0
    for j in jobs:
        if n >= limit:
            break
        u = j.get("url") or ""
        if not u or u.split("#")[0].rstrip("/") == page_url.split("#")[0].rstrip("/"):
            continue
        if j.get("location") and j.get("description"):
            continue
        if not br.JOB_WORD.search(j.get("title", "")):
            continue                      # seulement les intitulés qui pourraient être retenus
        n += 1
        content = _get_text(s, u)
        if not content:
            continue
        page = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
        ld = structured.jobpostings_from_html(page, u)
        if ld:
            d = ld[0]
            for k in ("location", "description", "posted", "valid_through", "employment_type"):
                if d.get(k) and not j.get(k):
                    j[k] = d[k]
        elif not j.get("description"):
            txt = re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", page, flags=re.S | re.I)
            j["description"] = re.sub(r"\s+", " ", txt)[:4000]
    return n


def _process(firm, state, s, b, acfg, cache_days, every_days):
    """Traite une société (dans un thread). Ne touche pas à la base.
    Renvoie dict(raw, method, err, resolved, save_resolution, skipped)."""
    res = {"raw": [], "method": "", "err": "", "resolved": None, "save": False, "skipped": False}
    resolved = None
    if firm.get("ats"):
        resolved = {k: firm[k] for k in ("ats", "slug", "url") if k in firm}
    elif state.get("resolved") and state.get("resolved_at") and \
            datetime.fromisoformat(state["resolved_at"]) > datetime.now() - timedelta(days=cache_days):
        resolved = state["resolved"]
        # page mémorisée mais rien lu la dernière fois : on refait la recherche de la page
        if resolved.get("ats") == "browser" and not state.get("found"):
            resolved = None
        elif resolved.get("ats") == "browser" and firm.get("careers_url") \
                and resolved.get("url") != firm["careers_url"] and not \
                (resolved.get("url") or "").startswith(firm["careers_url"].split("?")[0]):
            resolved = None               # page carrière imposée dans firms.yaml : prioritaire
        elif resolved.get("ats") == "browser" and _homepage(firm) and resolved.get("url"):
            # page mémorisée hors du site de la société, d'un ATS ou de son groupe
            # (ex. site de l'éditeur du logiciel RH) : on refait la recherche
            h, home = br._host(resolved["url"]), br._host(_homepage(firm))
            if not (br._same_site(resolved["url"], home) or br.ATS_HOST.search(h) or br._related(h, home)):
                resolved = None
    try:
        if resolved and resolved.get("ats") in ats.CONNECTORS and resolved["ats"] != "html":
            res["raw"], res["method"] = _api(s, firm, resolved, acfg, b), "api:" + resolved["ats"]
        elif b is None:
            res["method"], res["err"] = "ignoré", "navigateur indisponible"
        elif resolved and resolved.get("ats") == "browser":
            last = state.get("last_scan")
            if every_days > 1 and last and \
                    datetime.fromisoformat(last) > datetime.now() - timedelta(days=every_days):
                res["skipped"] = True
                return res
            raw, det, method, err = _browser_jobs(b, resolved["url"], s=s)
            if det and det.get("ats") != "browser":           # ATS découvert entre-temps
                resolved = det
                res.update(raw=_api(s, firm, det, acfg, b), method="api:" + det["ats"], save=True)
            else:
                res.update(raw=raw or [], method="navigateur:" + (method or "aucune"), err=err)
        else:
            careers = firm.get("careers_url")
            err, sm_jobs = "", []
            if not careers:
                home = _homepage(firm)
                careers, err, sm_jobs = _find_careers(b, s, home) if home else (None, "pas de site", [])
            res["err"] = err
            if not careers and sm_jobs:
                res.update(raw=sm_jobs, method="sitemap")
            if careers:
                raw, det, method, err = _browser_jobs(b, careers, s=s)
                if det and det.get("ats") != "browser":
                    resolved = det
                    res.update(raw=_api(s, firm, det, acfg, b), method="api:" + det["ats"])
                else:
                    resolved = det or {"ats": "browser", "url": careers}
                    raw = raw or []
                    known = {j["url"] for j in raw}
                    raw += [j for j in sm_jobs if j["url"] not in known]
                    res.update(raw=raw, method="navigateur:" + (method or "aucune"), err=err)
                res["save"] = True
        if res["raw"] and not res["method"].startswith("api:"):
            target = (resolved or {}).get("url") or ""
            enrich(s, res["raw"], target, limit=acfg.get("detail_pages", 6))
    except DomainSuspended as exc:
        res["err"] = f"domaine suspendu ({exc})"
    except Exception as exc:  # noqa: BLE001  (une société cassée ne bloque pas le reste)
        log.debug("Erreur pour %s", firm["name"], exc_info=True)
        res["err"] = f"{type(exc).__name__}: {exc}"[:200]
    res["resolved"] = resolved
    return res


def collect(cfg: dict, s: PoliteSession, store, evaluate, use_browser: bool = True,
            on_kept=None) -> list[dict]:
    """Parcourt toutes les sociétés (plusieurs navigateurs en parallèle) ;
    renvoie les offres retenues (déjà évaluées)."""
    import random
    import threading

    firms = [f for f in cfg.get("firms", []) if f.get("site", True)]
    random.shuffle(firms)
    acfg, ccfg = cfg.get("ats", {}), cfg.get("careers", {})
    cache_days = acfg.get("detect_cache_days", 30)
    every_days = ccfg.get("browser_every_days", 1)
    workers = max(1, int(ccfg.get("parallel", 3))) if use_browser else 1
    states = {f["name"]: (store.firm_state(f["name"]) or {}) for f in firms}
    # Reprise : un passage interrompu (veille, fenêtre fermée) puis relancé ne refait pas
    # les sociétés déjà lues il y a moins de resume_hours (leurs offres sont déjà en base).
    resume_h = ccfg.get("resume_hours", 10)
    if resume_h:
        cutoff = datetime.now() - timedelta(hours=resume_h)
        def done_ok(st):         # lue avec succès (pas d'erreur) depuis moins de resume_h
            return bool(st.get("last_scan")) and not st.get("error") \
                and datetime.fromisoformat(st["last_scan"]) > cutoff
        recent = [f for f in firms if done_ok(states[f["name"]])]
        if recent:
            log.info("Reprise : %d société(s) déjà lue(s) depuis moins de %dh, ignorée(s)",
                     len(recent), resume_h)
            firms = [f for f in firms if f not in recent]

    import queue
    tasks: queue.Queue = queue.Queue()
    results: queue.Queue = queue.Queue()
    for f in firms:
        tasks.put(f)
    failed = threading.Event()

    def worker():
        """Chaque thread ouvre SON navigateur, traite des sociétés, puis le ferme lui-même
        (Playwright exige que le navigateur soit fermé par le thread qui l'a ouvert)."""
        b = None
        if use_browser and not failed.is_set():
            try:
                b = br.Browser(min_delay=ccfg.get("min_delay", 3), max_delay=ccfg.get("max_delay", 6),
                               timeout=ccfg.get("timeout", 30), settle=ccfg.get("settle", 6)).__enter__()
            except Exception as exc:  # noqa: BLE001
                if not failed.is_set():
                    log.error("Navigateur indisponible (%s) : seules les API d'ATS seront utilisées. "
                              "Lance LANCER.bat pour l'installer.", exc)
                failed.set()
        try:
            while True:
                try:
                    firm = tasks.get_nowait()
                except queue.Empty:
                    return
                t0 = time.monotonic()
                try:
                    r = _process(firm, states[firm["name"]], s, b, acfg, cache_days, every_days)
                except Exception as exc:  # noqa: BLE001
                    r = {"raw": [], "method": "", "err": f"{type(exc).__name__}: {exc}"[:200],
                         "resolved": None, "save": False, "skipped": False}
                r["secs"] = time.monotonic() - t0
                results.put((firm, r))
        finally:
            if b is not None:
                b.__exit__(None, None, None)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for th in threads:
        th.start()

    kept: list[dict] = []
    done = 0
    stall_limit = ccfg.get("stall_minutes", 5) * 60
    last_result = time.monotonic()
    while done < len(firms):
        try:
            firm, r = results.get(timeout=5)
            last_result = time.monotonic()
        except queue.Empty:
            if not any(th.is_alive() for th in threads) and results.empty():
                break
            # plus aucune société en file et plus rien ne revient : un navigateur est bloqué
            # (ex. planté au réveil du PC) → on abandonne les sociétés restantes, on continue.
            if tasks.empty() and time.monotonic() - last_result > stall_limit:
                log.warning("Navigateur bloqué depuis %d min : %d société(s) abandonnée(s) pour ce "
                            "passage", stall_limit // 60, len(firms) - done)
                break
            continue
        done += 1
        name = firm["name"]
        if r["skipped"]:
            continue
        if r["save"]:
            store.save_firm_resolution(name, r["resolved"])
        loc = None if firm.get("global") else firm.get("location", "Switzerland")
        prof = firm_profile(firm)
        ok = []
        for j in r["raw"]:
            j = {"description": "", "posted": "", "location": "", "source": "", **j, "company": name}
            if not j["location"] and loc:
                j["location"] = loc
            j["source"] = j["source"] or ("site:" + r["method"].split(":")[-1])
            ev = evaluate(j, prof)
            if ev:
                ok.append(ev)
        target = (r["resolved"] or {}).get("url") or (r["resolved"] or {}).get("slug") or ""
        store.save_firm_scan(name, r["method"], len(r["raw"]), len(ok), r["err"], target)
        log.info("[%d/%d] %-34s %-24s %4d éléments → %3d retenus %s(%.0fs)",
                 done, len(firms), name[:34], (r["method"] or "-")[:24], len(r["raw"]), len(ok),
                 f"[{r['err'][:60]}] " if r["err"] else "", r["secs"])
        kept += ok
        if on_kept and ok:
            on_kept(ok)                   # enregistré tout de suite : rien de perdu si interruption
    for th in threads:
        th.join(timeout=60)
    return kept
