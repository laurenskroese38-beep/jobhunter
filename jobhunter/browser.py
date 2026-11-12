"""Accès aux sites carrières qui chargent leurs offres en JavaScript.

On ouvre la page dans un vrai Chromium sans interface (Playwright), comme un
visiteur : la page s'exécute, appelle ses propres API, affiche ses offres. On
récupère alors :
  - les URLs de toutes les requêtes et iframes  → détection de l'ATS / du portail ;
  - les réponses JSON reçues                    → offres structurées si l'API est maison ;
  - les liens et le texte affichés              → offres listées dans la page.

Pour rester discret : une page à la fois, pauses aléatoires, images / polices /
vidéos non chargées (moins de requêtes), un passage par jour au maximum.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
import html as htmllib
from urllib.parse import urljoin, urlparse

from .structured import jobpostings_from_html

log = logging.getLogger(__name__)

CAREER_LINK = re.compile(
    r"career|karriere|carriere|carri%c3%a8re|jobs?\b|emploi|stellen|vacanc|join[- ]?us|"
    r"work[- ]with[- ]us|working[- ]at|opportunit|recruit|recrut|offene|open[- ]positions|"
    r"talent|lavora|lavoro|join[- ]the[- ]team|our[- ]people|people", re.I)
OPENINGS_LINK = re.compile(
    r"open (positions|roles|vacancies)|current (openings|vacancies|opportunities|positions)|"
    r"(all|see|view|browse|search|find) (all )?(our )?(open )?(jobs|positions|openings|vacancies|opportunities|roles)|"
    r"job (offers|openings|opportunities|search|board|listings)|vacancies|postes? (ouverts|vacants)|"
    r"offres d.emploi|nos offres|emplois? disponibles|stellenangebote|offene stellen|"
    r"apply now|postuler", re.I)
OPENINGS_WEAK = re.compile(r"internships?|stages|students?|graduates?|early careers?|"
                           r"jobs? (&|and) (internships|careers)|opportunities", re.I)
JOB_WORD = re.compile(
    r"\bintern(ship)?s?\b|\bstagiaire|\bstage\b|\bpraktik|\bgraduate|\btrainee|\banalyst|"
    r"\banalyste|\bassociate|\bassocie|\bjunior|\bsummer\b|\boff.?cycle|\bmaster.?s thesis|"
    r"\bworking student|\bwerkstudent|\bconsultant|\bvie\b", re.I)
SKIP_LINK = re.compile(r"^(mailto|tel|javascript):|\.(pdf|jpg|png|zip|docx?)(\?|$)|"
                       r"linkedin\.com|facebook\.com|twitter\.com|x\.com|instagram\.com|"
                       r"youtube\.com|xing\.com|glassdoor|kununu", re.I)
COMMON_PATHS = ["/careers", "/en/careers", "/career", "/en/career", "/jobs", "/en/jobs",
                "/karriere", "/de/karriere", "/fr/carrieres", "/fr/carriere", "/join-us",
                "/en/join-us", "/en/about-us/careers", "/about-us/careers", "/about/careers",
                "/company/careers", "/en/company/careers", "/work-with-us", "/stellen",
                "/offene-stellen", "/emplois", "/fr/emplois", "/en/jobs-and-careers"]
TITLE_KEYS = ("title", "jobTitle", "job_title", "positionTitle", "postingTitle", "Title",
              "name", "text", "jobName", "requisitionTitle", "displayJobTitle", "jobPostingTitle",
              "PostingTitle", "positionName", "vacancyTitle", "headline")
LOC_KEYS = ("location", "locations", "city", "locationName", "jobLocation", "locationsText",
            "primaryLocation", "PrimaryLocation", "office", "workLocation", "Location",
            "address", "jobLocations", "cityName", "locationsText", "workplace", "place")
URL_KEYS = ("url", "absolute_url", "applyUrl", "jobUrl", "link", "href", "hostedUrl",
            "externalPath", "canonicalPositionUrl", "detailUrl", "jobDetailUrl", "permalink",
            "slug", "path", "jobPostingUrl", "applyLink", "ExternalURL", "externalUrl")
JOBISH_KEYS = {"location", "locations", "department", "jobid", "job_id", "requisitionid",
               "postingdate", "posteddate", "postedon", "employmenttype", "jobtype", "city",
               "country", "applyurl", "joburl", "hostedurl", "externalpath", "team", "office",
               "contracttype", "workplacetype", "categories", "primarylocation", "requisitionid",
               "postedate", "dateposted", "workplace", "seniority", "function", "jobfamily",
               "employment_type", "worktype", "reqid", "jobreqid", "positionid"}


# Bandeaux cookies : on REFUSE (seulement les cookies nécessaires). Jamais « accepter ».
_CONSENT_JS = r"""() => {
  const deep = (root, sel, out=[]) => {
    root.querySelectorAll(sel).forEach(e => out.push(e));
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) deep(e.shadowRoot, sel, out); });
    return out;
  };
  const visible = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const ids = ['#onetrust-reject-all-handler', '.ot-pc-refuse-all-handler',
    '#CybotCookiebotDialogBodyButtonDecline', '#CybotCookiebotDialogBodyLevelButtonLevelOptinDeclineAll',
    '#didomi-notice-disagree-button', '.cky-btn-reject', '.cmplz-deny', '.iubenda-cs-reject-btn',
    '#tarteaucitronAllDenied2', '[data-testid="uc-deny-all-button"]', '.cc-deny', '.cn-decline',
    '#cookiescript_reject', '._brlbs-refuse-btn', '[data-cookiefirst-action="reject"]',
    '#cn-refuse-cookie', '.moove-gdpr-modal-reject-all', '#wt-cli-reject-btn', '.cmpboxbtnno',
    '[data-action="reject"]', '[data-role="necessary"]'];
  for (const s of ids) {
    for (const e of deep(document, s)) { if (visible(e)) { e.click(); return s; } }
  }
  const RX = /^(reject( all)?( cookies)?|decline( all)?( cookies)?|deny( all)?|refuse( all)?|disagree|no,? thanks|tout refuser|refuser( tout| les cookies)?|continuer sans accepter|alle ablehnen|ablehnen|nur (notwendige|erforderliche|essenzielle|technisch notwendige)( cookies)?( akzeptieren| zulassen)?|(only|accept only|allow only|use only) (necessary|essential|required|strictly necessary)( cookies)?|(necessary|essential|required) (cookies )?only|rifiuta( tutto| tutti)?|solo necessari)$/i;
  for (const e of deep(document, 'button, [role=button], a[href="#"], a:not([href]), input[type=button]')) {
    const t = (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    if (t.length < 40 && RX.test(t) && visible(e)) { e.click(); return t; }
  }
  return '';
}"""

# « Afficher plus d'offres » : listes paginées côté navigateur.
_MORE_JS = r"""() => {
  const RX = /^(load|show|see|view|display) (more|all)( jobs| positions| results| offers| openings| vacancies| opportunities)?$|^more (jobs|positions|results)$|^mehr (anzeigen|laden|stellen|ergebnisse|jobs)$|^weitere (stellen|jobs|ergebnisse)( anzeigen| laden)?$|^(voir|afficher|charger) plus( d.offres| de postes| de résultats)?$|^plus d.offres$|^mostra (altro|di più)$/i;
  const els = Array.from(document.querySelectorAll('button, [role=button], a[href="#"], a:not([href]), a[href^="javascript"]'));
  for (const e of els) {
    const t = (e.innerText || e.getAttribute('aria-label') || '').trim().replace(/\s+/g, ' ');
    const r = e.getBoundingClientRect();
    if (t.length < 40 && RX.test(t) && r.width > 0 && !e.disabled) { e.scrollIntoView(); e.click(); return t; }
  }
  return '';
}"""

# Tous les liens, y compris dans les web components (shadow DOM) et les éléments
# cliquables qui ne sont pas des <a> (data-href, routerlink...).
_LINKS_JS = r"""() => {
  const out = [];
  const walk = root => {
    root.querySelectorAll('a[href], [data-href], [data-url], [routerlink]').forEach(a => {
      const href = a.href && typeof a.href === 'string' ? a.href :
        (a.getAttribute('href') || a.getAttribute('data-href') || a.getAttribute('data-url') || a.getAttribute('routerlink'));
      if (href) out.push([a.innerText || a.getAttribute('aria-label') || a.getAttribute('title') || '', new URL(href, document.baseURI).href]);
    });
    root.querySelectorAll('*').forEach(e => { if (e.shadowRoot) walk(e.shadowRoot); });
  };
  walk(document);
  return out;
}"""

_HTML_URL = re.compile(
    r"""(?:https?:)?(?:\\?/\\?/[\w.-]+)?(?:\\?/[\w%.~+-]+)*\\?/(?:careers?|karriere|carrieres?|carri%c3%a8res?|jobs?|"""
    r"""emplois?|stellen\w*|join-us|vacancies|offene-stellen|open-positions)(?=[/?#"'\s<&\\]|$)"""
    r"""(?:\\?/[\w%.~+-]*)*/?""", re.I)


def urls_in_html(page_html: str, base: str) -> list[str]:
    """URLs « carrière » écrites dans le code de la page mais pas dans un lien visible :
    menus en JSON (Vue/React), attributs data-*, scripts. Ex. Julius Bär."""
    out = []
    raw = htmllib.unescape(page_html or "").replace("\\/", "/")
    for m in _HTML_URL.finditer(raw):
        u = m.group(0)
        if len(u) < 5 or u.startswith("//") and "." not in u[2:].split("/")[0]:
            continue
        u = urljoin(base, u)
        # adresse d'UNE offre (…/open-positions/compliance-officer/) → la liste (…/open-positions/)
        cut = re.search(r"^(.*?/(?:careers?|karriere|carrieres?|carri%c3%a8res?|jobs?|emplois?|stellen\w*|"
                        r"join-us|vacancies|offene-stellen|open-positions))(/|$)", u, re.I)
        if cut:
            u = cut.group(1) + "/"
        if urlparse(u).scheme in ("http", "https") and u not in out and not SKIP_LINK.search(u) \
                and not re.search(r"\.(js|css|json|svg|png|jpe?g|webp|woff2?)(\?|$)|/assets?/|/build/|/static/", u, re.I):
            out.append(u)
    return out[:40]


@dataclass
class Scan:
    url: str
    final_url: str = ""
    ok: bool = False
    error: str = ""
    html: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)   # (texte, href absolu)
    seen_urls: list[str] = field(default_factory=list)          # requêtes + iframes
    payloads: list = field(default_factory=list)                # JSON reçus

    @property
    def haystack(self) -> str:
        return "\n".join([self.final_url, *self.seen_urls, *(h for _, h in self.links), self.html])


class Browser:
    def __init__(self, min_delay=4.0, max_delay=9.0, timeout=30.0, settle=6.0, sleep=time.sleep):
        self.min_delay, self.max_delay = min_delay, max_delay
        self.timeout_ms, self.settle_ms = int(timeout * 1000), int(settle * 1000)
        self._sleep = sleep
        self._last = 0.0
        self._pw = self._browser = self._ctx = None

    # -- cycle de vie ----------------------------------------------------
    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._launch()
        return self

    def _launch(self):
        # Chrome installé (moins souvent bloqué par les pare-feu anti-robots) ; sinon le
        # Chromium fourni par Playwright. Profil vierge et isolé : aucun accès à tes
        # cookies, sessions ou mots de passe.
        self._browser = None
        for kwargs in ({"channel": "chrome"}, {"channel": "msedge"}, {}):
            try:
                self._browser = self._pw.chromium.launch(
                    headless=True, args=["--disable-blink-features=AutomationControlled",
                                         "--disable-gpu", "--disable-dev-shm-usage"], **kwargs)
                break
            except Exception:  # noqa: BLE001
                continue
        if self._browser is None:
            raise RuntimeError("aucun navigateur utilisable (lance : python -m playwright install chromium)")
        ua = self._browser.version  # ex. 129.0.6668.29
        self._ctx = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        f"(KHTML, like Gecko) Chrome/{ua.split('.')[0]}.0.0.0 Safari/537.36"),
            locale="en-GB", timezone_id="Europe/Zurich", ignore_https_errors=True,
            viewport={"width": 1366, "height": 900})
        self._ctx.route("**/*", self._filter_route)

    def _relaunch(self):
        """Le navigateur a planté (ex. réveil de veille) : on le ferme et on le relance."""
        log.warning("Navigateur planté : redémarrage")
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2)
        self._launch()
        self.restarts = getattr(self, "restarts", 0) + 1

    def _new_page(self):
        try:
            return self._ctx.new_page()
        except Exception:  # noqa: BLE001  (Target crashed / browser has been closed)
            self._relaunch()
            return self._ctx.new_page()

    def __exit__(self, *exc):
        for obj in (self._ctx, self._browser):
            try:
                obj and obj.close()
            except Exception:  # noqa: BLE001
                pass
        if self._pw:
            self._pw.stop()

    @staticmethod
    def _filter_route(route):
        if route.request.resource_type in ("image", "media", "font"):
            return route.abort()
        return route.continue_()

    def _pause(self):
        wait = random.uniform(self.min_delay, self.max_delay) - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    # -- ouverture d'une page --------------------------------------------
    def scan(self, url: str, _retry: bool = True, expand: bool = False) -> Scan:
        """Ouvre url. expand=True : clique « Load more » (pages carrière)."""
        self._pause()
        sc = Scan(url=url)
        page = self._new_page()

        def on_response(resp):
            try:
                sc.seen_urls.append(resp.url)
                ctype = resp.headers.get("content-type", "")
                if resp.request.resource_type in ("xhr", "fetch") and "json" in ctype:
                    body = resp.body()
                    if len(body) < 4_000_000:
                        sc.payloads.append((resp.url, json.loads(body)))
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            if resp is not None and resp.status >= 400:
                sc.error = f"HTTP {resp.status}"
            try:
                page.wait_for_load_state("networkidle", timeout=self.settle_ms)
            except Exception:  # noqa: BLE001
                pass
            self._dismiss_consent(page)
            for _ in range(3):  # contenu chargé au défilement
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(700)
            if expand:
                self._expand(page)
            sc.final_url = page.url
            sc.html = page.content()
            for frame in page.frames:
                if frame != page.main_frame and frame.url and frame.url != "about:blank":
                    sc.seen_urls.append(frame.url)
                try:
                    sc.text += "\n" + frame.evaluate("() => document.body ? document.body.innerText : ''")
                    for text, href in frame.evaluate(_LINKS_JS):
                        if href and not SKIP_LINK.search(href):
                            lines = [re.sub(r"\s+", " ", x).strip() for x in (text or "").split("\n")]
                            sc.links.append(("\n".join(x for x in lines if x), href))
                except Exception:  # noqa: BLE001
                    pass
            known = {h for _, h in sc.links}
            for u in urls_in_html(sc.html, sc.final_url or url):
                if u not in known:
                    sc.links.append(("", u))
            sc.ok = not sc.error
        except Exception as exc:  # noqa: BLE001
            sc.error = type(exc).__name__ + ": " + str(exc).split("\n")[0][:160]
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
        if _retry and ("crashed" in sc.error.lower() or "has been closed" in sc.error.lower()):
            self._relaunch()
            return self.scan(url, _retry=False)
        return sc

    @staticmethod
    def _dismiss_consent(page):
        for frame in page.frames[:6]:
            try:
                if frame.evaluate(_CONSENT_JS):
                    page.wait_for_timeout(900)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    @staticmethod
    def _expand(page, max_clicks: int = 6):
        for _ in range(max_clicks):
            try:
                before = page.evaluate("() => document.querySelectorAll('a[href]').length")
                if not page.evaluate(_MORE_JS):
                    return
                try:
                    page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:  # noqa: BLE001
                    page.wait_for_timeout(1500)
                if page.evaluate("() => document.querySelectorAll('a[href]').length") <= before:
                    page.wait_for_timeout(1200)
                    if page.evaluate("() => document.querySelectorAll('a[href]').length") <= before:
                        return
            except Exception:  # noqa: BLE001  (navigation provoquée par le clic, etc.)
                return

    # -- trouver la page carrière depuis la page d'accueil ---------------
    def find_careers(self, homepage: str) -> tuple[str | None, Scan]:
        sc = self.scan(homepage)
        if not sc.ok and not sc.links:
            return None, sc
        return pick_careers_link(sc, homepage), sc


# ---------------------------------------------------------------------------
# Fonctions pures (testables sans navigateur)
# ---------------------------------------------------------------------------
def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


STRONG_CAREER = re.compile(r"career|karriere|carri(e|è|%c3%a8)re|\bjobs?\b|emplois?|stellen|vacanc|"
                           r"join[- ]?us|join the team|work(ing)?[- ](with|at)[- ]us|recrut|recruit|"
                           r"lavora con noi|offene stellen|open positions|nous rejoindre", re.I)
WEAK_CAREER = re.compile(r"\bpeople\b|\btalents?\b|\bteam\b|opportunit", re.I)
ATS_HOST = re.compile(r"workday|greenhouse|lever\.co|ashbyhq|smartrecruiters|personio|recruitee|"
                      r"workable|successfactors|umantis|abacuscity|softgarden|teamtailor|join\.com|"
                      r"breezy|bamboohr|onlyfy|prescreen|refline|jobs\.ch|jobup\.ch|taleo|icims|"
                      r"oraclecloud|avature|welcometothejungle|(?<!www)\.rexx-systems\.com|dvinci|"
                      r"eightfold|pinpointhq|homerun\.co|jobvite|hibob|factorialhr|ostendis", re.I)


def _same_site(href: str, home: str) -> bool:
    h = _host(href)
    base = ".".join(home.split(".")[-2:])          # ex. lombardodier.com
    return h == home or h.endswith("." + base) or h == base


def _tokens(host: str) -> set[str]:
    name = ".".join(host.split(".")[:-1])            # sans l'extension (.ch, .com…)
    return {w for w in re.split(r"[.\-_]", name) if len(w) >= 4 and w not in ("www", "group", "corporate")}


def _related(h1: str, h2: str) -> bool:
    """Deux domaines du même groupe (baloise-asset-management.com / helvetia-baloise.com),
    pas un éditeur de logiciel ou une agence web (rexx-systems.com)."""
    return bool(_tokens(h1) & _tokens(h2))


def pick_careers_link(sc: Scan, homepage: str) -> str | None:
    """Lien vers la page carrière : sur le site de la société (ou un ATS connu),
    libellé court de menu (« Careers », « Jobs », « Join us »...), pas un article."""
    home = _host(sc.final_url or homepage)
    best, best_score = None, 0
    for text, href in sc.links:
        label = text.split("\n")[0].strip()
        path = urlparse(href).path
        words = len(label.split())
        strong_label = bool(STRONG_CAREER.search(label)) and words <= 5
        strong_path = bool(STRONG_CAREER.search(path))
        weak = bool(WEAK_CAREER.search(label)) and words <= 3
        own = _same_site(href, home) or bool(ATS_HOST.search(_host(href)))
        # site du groupe / de la maison mère (ex. Baloise AM → helvetia-baloise.com/…/karriere) :
        # accepté seulement si le libellé ET l'adresse disent « carrière »
        last = path.rstrip("/").split("/")[-1]
        group = not own and _related(_host(href), home) and strong_path and (
            (strong_label and words <= 3) or
            (not label and re.fullmatch(r"(careers?|karriere|carrieres?|jobs)(\.html?)?", last, re.I)))
        if not (own or group):
            continue                                   # lien externe (agence web, presse...)
        if not (strong_label or strong_path or weak):
            continue
        if path.count("/") > (7 if group else 5) or re.search(r"/(news|insights?|blog|press|media|articles?|"
                                            r"publications?|products?|funds?|solutions?)/", path, re.I):
            continue                                   # article, fiche produit...
        score = (6 if strong_label else 0) + (4 if strong_path else 0) + (1 if weak else 0)
        if ATS_HOST.search(_host(href)):
            score += 2
        elif group:
            score -= 3
        if re.search(r"/(en|en-\w\w)/", href) or path.startswith("/en"):
            score += 1
        if score > best_score:
            best, best_score = href, score
    return best


def pick_openings_link(sc: Scan) -> str | None:
    """Sur une page carrière « vitrine », le lien vers la liste des postes."""
    current = (sc.final_url or sc.url).rstrip("/")
    best, best_score = None, 0
    for text, href in sc.links:
        if href.rstrip("/") == current or href.startswith(current + "#"):
            continue
        path = urlparse(href).path
        score = 0
        if OPENINGS_LINK.search(text):
            score = 3
        elif re.search(r"/(jobs|vacancies|open-positions|openings|job-offers|offres|stellen|postes|"
                       r"job-search|search-jobs|current-opportunities)(/|$|\?)", path, re.I):
            score = 2
        elif OPENINGS_WEAK.search(text):
            score = 1
        if score > best_score:
            best, best_score = href, score
    return best


def jobs_from_json(payloads, base_url: str) -> list[dict]:
    """Cherche dans les JSON reçus des listes d'objets qui ressemblent à des offres."""
    found: list[dict] = []

    def title_of(d):
        for k in TITLE_KEYS:
            v = d.get(k)
            if isinstance(v, str) and 4 <= len(v.strip()) <= 160:
                return v.strip()
        return None

    def loc_of(d):
        for k in LOC_KEYS:
            v = d.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                return ", ".join(str(x) for x in v.values() if isinstance(x, str))[:120]
            if isinstance(v, list) and v:
                parts = [x if isinstance(x, str) else
                         (x.get("name") or x.get("city") or x.get("location") or "")
                         for x in v if isinstance(x, (str, dict))]
                return " / ".join(p for p in parts if isinstance(p, str))[:160]
        return ""

    def url_of(d, src):
        for k in URL_KEYS:
            v = d.get(k)
            if isinstance(v, str) and v and not v.startswith(("mailto:", "#")):
                return urljoin(src if k in ("externalPath", "path", "slug") else base_url, v)
        return base_url

    def walk(node, src, depth=0):
        if depth > 8:
            return
        if isinstance(node, list) and node and all(isinstance(x, dict) for x in node[:20]):
            items = [d for d in node if title_of(d) and not NAV_TITLE.match(title_of(d))]
            jobish = sum(1 for d in node[:30] for k in d if k.lower() in JOBISH_KEYS)
            if items and len(items) >= 0.5 * len(node) and jobish >= 1:
                for d in items:
                    found.append({"title": title_of(d), "location": loc_of(d),
                                  "url": url_of(d, src),
                                  "description": str(d.get("description") or d.get("descriptionPlain")
                                                     or "")[:4000],
                                  "posted": str(d.get("postedOn") or d.get("publishedAt")
                                                or d.get("datePosted") or "")[:10]})
                return
        if isinstance(node, dict):
            for v in node.values():
                walk(v, src, depth + 1)
        elif isinstance(node, list):
            for v in node[:500]:
                walk(v, src, depth + 1)

    for src, data in payloads:
        walk(data, src)
    return found


NAV_TITLE = re.compile(
    r"^(students?|graduates?|internships?|early careers?|careers?|jobs?|vacancies|"
    r"students? (&|and) graduates?|graduates? (&|and) interns?|interns?(hips)? (&|and) graduates?|"
    r"(our|open|current|all) (jobs|positions|openings|vacancies|opportunities)|"
    r"(internship|graduate|trainee|talent|young talent|student)s? (program|programme)s?( @ .*| at .*)?|"
    r"(early careers?|young talents?|working students?|students|graduates|internships)( @ .*| at .*| - .*)?|"
    r"(read more|more)( about)?:? .*|analyst (coverage|recommendations?|consensus|estimates?)|"
    r"(apply|learn more|read more|more|details|view job|see more|postuler|en savoir plus)( now)?)$", re.I)


def jobs_from_links(sc: Scan) -> list[dict]:
    out = []
    for text, href in sc.links:
        first_line = text.split("\n")[0] if text else ""
        t = re.sub(r"\s+", " ", first_line).strip()
        if not (6 <= len(t) <= 160) or len(t.split()) < 2 or NAV_TITLE.match(t):
            continue
        if OPENINGS_LINK.search(t) and not JOB_WORD.search(t):   # « See all open positions »
            continue
        path = urlparse(href).path.lower()
        jobby_href = re.search(r"/(job|jobs|position|positions|vacanc|offre|stelle|posting|"
                               r"requisition|career/|careers/|opening)", path)
        if JOB_WORD.search(t) or (jobby_href and len(t.split()) >= 2):
            # la ligne suivante du lien porte souvent le lieu (« Zurich, Switzerland »)
            rest = text.split("\n")[1:3] if "\n" in text else []
            out.append({"title": t, "location": " ".join(rest)[:120], "url": href,
                        "description": "", "posted": ""})
    return out


def jobs_from_text(sc: Scan) -> list[dict]:
    """Dernier recours : lignes de texte qui ressemblent à un intitulé de poste
    (petites sociétés qui listent « Investment Analyst Intern » sans lien dédié)."""
    out, seen = [], set()
    for line in sc.text.split("\n"):
        t = re.sub(r"\s+", " ", line).strip(" •-–:|")
        if not (10 <= len(t) <= 110) or t.endswith((".", "?", "!")) or len(t.split()) > 14:
            continue
        if len(t.split()) < 2 or not JOB_WORD.search(t) or NAV_TITLE.match(t) or t.lower() in seen:
            continue
        if re.search(r"\b(at|chez|bei|@|formerly|previously|former)\b", t, re.I):   # biographie
            continue
        if re.search(r"specialized|focus(ed)? on|we invest|invests? in|portfolio compan", t, re.I):
            continue
        seen.add(t.lower())
        out.append({"title": t, "location": "", "url": sc.final_url or sc.url,
                    "description": "", "posted": ""})
    return out


def extract_jobs(sc: Scan) -> tuple[list[dict], str]:
    """Renvoie (offres, méthode). JSON + liens combinés ; le texte seulement en dernier recours."""
    methods, jobs = [], []
    for method, fn in (("jsonld", lambda: jobpostings_from_html(sc.html, sc.final_url or sc.url)),
                       ("json", lambda: jobs_from_json(sc.payloads, sc.final_url or sc.url)),
                       ("liens", lambda: jobs_from_links(sc))):
        got = fn()
        if got:
            methods.append(method)
            jobs += got
    if not jobs:
        jobs = jobs_from_text(sc)
        if jobs:
            methods.append("texte")
    page = sc.final_url or sc.url
    merged: dict[str, dict] = {}
    for j in jobs:
        key = re.sub(r"\s+", " ", j["title"].lower())
        cur = merged.get(key)
        if cur is None:
            merged[key] = dict(j)
            continue
        # même offre vue dans le JSON et dans les liens : on garde le meilleur de chaque
        if cur["url"] == page and j["url"] != page:
            cur["url"] = j["url"]
        for k in ("location", "description", "posted", "employment_type"):
            if not cur.get(k) and j.get(k):
                cur[k] = j[k]
    return list(merged.values()), "+".join(methods) or "aucune"


def looks_like_listing(jobs: list[dict]) -> bool:
    """Au moins une offre crédible (mot-clé de poste) parmi les éléments extraits."""
    return len(jobs) >= 3 or any(JOB_WORD.search(j["title"]) for j in jobs)
