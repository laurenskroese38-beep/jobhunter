"""Client HTTP « poli » : c'est ici que se joue le risque de blocage.

Principes appliqués :
- une seule requête à la fois, et un délai aléatoire minimum entre deux
  requêtes vers le même domaine (pas de rafales régulières détectables) ;
- respect du code 429 / 503 et de l'en-tête Retry-After ;
- backoff exponentiel avec jitter sur les erreurs réseau et 5xx ;
- coupe-circuit : après N échecs sur un domaine, on arrête de le solliciter
  jusqu'au prochain passage (insister est ce qui fait bannir une IP) ;
- respect de robots.txt pour les pages HTML (les API JSON des ATS sont
  publiques et faites pour être lues) ;
- une session persistante (keep-alive, cookies) comme un navigateur.
"""
from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)


class DomainSuspended(Exception):
    """Le domaine a trop échoué pendant ce passage : on ne le sollicite plus."""


class PoliteSession:
    def __init__(
        self,
        min_delay: float = 3.0,
        max_delay: float = 7.0,
        max_retries: int = 4,
        max_failures_per_domain: int = 3,
        respect_robots_txt: bool = True,
        timeout: float = 25.0,
        user_agent: str | None = None,
        sleep=time.sleep,
    ):
        self.min_delay, self.max_delay = min_delay, max_delay
        self.max_retries = max_retries
        self.max_failures = max_failures_per_domain
        self.respect_robots = respect_robots_txt
        self.timeout = timeout
        self._sleep = sleep
        self._last_hit: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.stats = {"requests": 0, "retries": 0, "suspended": set()}

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent or DEFAULT_UA,
            "Accept-Language": "fr-CH,fr;q=0.9,en;q=0.8,de;q=0.7",
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        })

    # -- outils internes -------------------------------------------------
    def _wait_turn(self, domain: str) -> None:
        delay = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - self._last_hit.get(domain, -1e9)
        if elapsed < delay:
            self._sleep(delay - elapsed)
        self._last_hit[domain] = time.monotonic()

    def _backoff(self, attempt: int) -> float:
        return min(120.0, (2 ** attempt) * 5) * random.uniform(0.7, 1.3)

    @staticmethod
    def _retry_after(resp: requests.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except Exception:
                return None

    def _fail(self, domain: str) -> None:
        self._failures[domain] = self._failures.get(domain, 0) + 1
        if self._failures[domain] >= self.max_failures:
            log.warning("Coupe-circuit : %s suspendu pour ce passage", domain)
            self.stats["suspended"].add(domain)

    def is_suspended(self, url: str) -> bool:
        return urlparse(url).netloc in self.stats["suspended"]

    def allowed_by_robots(self, url: str) -> bool:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                self._wait_turn(parsed.netloc)
                r = self.session.get(base + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
                self._robots[base] = rp
            except requests.RequestException:
                self._robots[base] = None  # robots.txt injoignable : on autorise
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.session.headers["User-Agent"], url)

    # -- API publique ----------------------------------------------------
    def request(self, method: str, url: str, check_robots: bool = False, **kwargs):
        """Renvoie la réponse (2xx/404) ou None si abandon. Ne lève pas sur HTTP."""
        domain = urlparse(url).netloc
        if domain in self.stats["suspended"]:
            raise DomainSuspended(domain)
        if check_robots and self.respect_robots and not self.allowed_by_robots(url):
            log.info("robots.txt interdit %s : ignoré", url)
            return None
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(self.max_retries + 1):
            self._wait_turn(domain)
            self.stats["requests"] += 1
            try:
                resp = self.session.request(method, url, **kwargs)
            except requests.RequestException as exc:
                log.info("Erreur réseau %s (%s), essai %d", url, exc, attempt + 1)
                self.stats["retries"] += 1
                self._sleep(self._backoff(attempt))
                continue

            if resp.status_code in (429, 503):
                wait = self._retry_after(resp) or self._backoff(attempt + 1)
                if wait > 600:  # on ne bloque pas le run 10 min pour un domaine
                    self._fail(domain)
                    return None
                log.info("%s → %d, pause %.0fs", domain, resp.status_code, wait)
                self.stats["retries"] += 1
                self._sleep(wait)
                continue
            if resp.status_code >= 500:
                self.stats["retries"] += 1
                self._sleep(self._backoff(attempt))
                continue
            if resp.status_code in (401, 403):
                # Probablement un pare-feu anti-bot : insister aggraverait les choses.
                log.warning("%s → %d (accès refusé), on n'insiste pas", url, resp.status_code)
                self._fail(domain)
                self._fail(domain)
                return None

            self._failures[domain] = 0
            return resp

        self._fail(domain)
        return None

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)
