"""Recherche via JobSpy (LinkedIn, Indeed, Google Jobs).

Ce qui limite le risque de blocage ici :
- aucune connexion à un compte LinkedIn (JobSpy utilise les pages publiques) :
  au pire c'est l'IP qui est freinée temporairement, jamais ton compte ;
- un site à la fois, avec une longue pause aléatoire entre deux recherches ;
- pas de récupération des descriptions LinkedIn (1 requête de plus par offre) ;
- dès qu'un site renvoie 429 / bloque, il est désactivé pour le reste du passage ;
- volume modéré (results_wanted) et fenêtre récente (hours_old).
"""
from __future__ import annotations

import logging
import random
import time

log = logging.getLogger(__name__)

_BLOCK_HINTS = ("429", "too many", "blocked", "rate limit", "forbidden", "403")


class _BlockWatcher(logging.Handler):
    """JobSpy journalise les erreurs au lieu de les lever : on écoute ses logs."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.hit = False

    def emit(self, record):
        msg = record.getMessage().lower()
        if any(h in msg for h in _BLOCK_HINTS):
            self.hit = True


def _val(row, key):
    v = row.get(key)
    if v is None:
        return ""
    try:  # NaN pandas
        if v != v:
            return ""
    except Exception:
        pass
    return str(v)


def search(cfg: dict, sleep=time.sleep, scrape_jobs=None, state: dict | None = None) -> list[dict]:
    """state (facultatif) : {"done": set de (site, terme, lieu) déjà faits,
    "blocked": set des sites coupés pour limitation} — permet de reprendre plus tard
    les recherches qu'un blocage LinkedIn a empêchées."""
    if scrape_jobs is None:
        from jobspy import scrape_jobs  # import tardif : dépendance lourde

    sites = list(cfg.get("sites", ["linkedin", "indeed"]))
    terms = cfg.get("search_terms", [])
    locations = cfg.get("locations", ["Switzerland"])
    lo, hi = cfg.get("delay_between_queries", [25, 60])
    max_empty = cfg.get("max_consecutive_empty", 3)
    state = state if state is not None else {}
    state.setdefault("done", set())
    state.setdefault("blocked", set())
    disabled: set[str] = set()
    limited = state["blocked"]
    empty_streak: dict[str, int] = {}
    watcher = _BlockWatcher()
    # JobSpy désactive la propagation de ses loggers : on s'y accroche directement.
    names = {f"JobSpy:{n}" for n in ("LinkedIn", "Indeed", "Google", "Glassdoor",
                                     "ZipRecruiter", "Bayt", "Naukri", "BDJobs")}
    names |= {n for n in logging.root.manager.loggerDict if n.startswith("JobSpy")}
    loggers = [logging.getLogger(n) for n in names]
    for lg in loggers:
        lg.addHandler(watcher)
    try:
        return _run(scrape_jobs, cfg, sites, terms, locations, lo, hi, sleep,
                    disabled, empty_streak, max_empty, watcher, state["done"], limited)
    finally:
        for lg in loggers:
            lg.removeHandler(watcher)


def _with_timeout(fn, kwargs, timeout):
    """Appelle fn(**kwargs) dans un thread ; TimeoutError si pas de réponse à temps."""
    import threading
    box = {}

    def target():
        try:
            box["ok"] = fn(**kwargs)
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc
    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError
    if "err" in box:
        raise box["err"]
    return box.get("ok")


def _run(scrape_jobs, cfg, sites, terms, locations, lo, hi, sleep,
         disabled, empty_streak, max_empty, watcher, done, limited=None):
    limited = limited if limited is not None else set()
    out: list[dict] = []
    first = True

    queries = [(site, term, loc) for term in terms for loc in locations for site in sites]
    for site, term, loc in queries:
        if site in disabled or (site, term, loc) in done:
            continue
        if not first:
            sleep(random.uniform(lo, hi))
        first = False

        kwargs = dict(
            site_name=[site],
            search_term=term,
            location=loc,
            results_wanted=cfg.get("results_wanted", 40),
            hours_old=cfg.get("hours_old", 72),
            country_indeed=cfg.get("country_indeed", "Switzerland"),
            linkedin_fetch_description=False,
            description_format="markdown",
            verbose=0,
        )
        if site == "google":
            kwargs["google_search_term"] = f"{term} jobs near {loc} since last week"
        if cfg.get("proxies"):
            kwargs["proxies"] = cfg["proxies"]

        watcher.hit = False
        try:
            df = _with_timeout(scrape_jobs, kwargs, cfg.get("query_timeout", 180))
        except TimeoutError:
            # requête figée (ex. connexion perdue pendant une mise en veille du PC) :
            # on n'attend pas indéfiniment, le site est abandonné pour ce passage
            log.warning("JobSpy %s / %r sans réponse depuis %ds : %s désactivé pour ce passage",
                        site, term, cfg.get("query_timeout", 180), site)
            disabled.add(site)
            limited.add(site)
            continue
        except Exception as exc:
            msg = str(exc).lower()
            if any(h in msg for h in _BLOCK_HINTS):
                log.warning("%s semble limiter les requêtes (%s) : désactivé pour ce passage",
                            site, exc)
                disabled.add(site)
                limited.add(site)
            else:
                log.warning("JobSpy %s / %r a échoué : %s", site, term, exc)
            continue

        n = 0 if df is None else len(df)
        if not watcher.hit:
            done.add((site, term, loc))
        log.info("JobSpy %-8s %-32r → %d offres", site, term, n)
        if watcher.hit:
            log.warning("%s signale une limitation : désactivé pour ce passage", site)
            disabled.add(site)
            limited.add(site)
        if not n:
            empty_streak[site] = empty_streak.get(site, 0) + 1
            if empty_streak[site] >= max_empty and site not in disabled:
                log.warning("%s : %d recherches vides d'affilée (blocage probable), "
                            "désactivé pour ce passage", site, max_empty)
                disabled.add(site)
            continue
        empty_streak[site] = 0
        for row in df.to_dict("records"):
            location = _val(row, "location")
            if not location:
                location = ", ".join(filter(None, [_val(row, "city"), _val(row, "state"),
                                                   _val(row, "country")]))
            out.append({
                "title": _val(row, "title"),
                "company": _val(row, "company"),
                "location": location,
                "url": _val(row, "job_url") or _val(row, "job_url_direct"),
                "description": _val(row, "description")[:4000],
                "posted": _val(row, "date_posted")[:10],
                "source": f"jobspy:{_val(row, 'site') or site}",
            })
    return out
