"""Tests du navigateur sur de faux sites carrières servis en local."""
import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("playwright")
from jobhunter import browser as br, careers  # noqa: E402
from jobhunter.store import Store  # noqa: E402
from jobhunter import filters  # noqa: E402

PAGES = {
    "/home": """<html><body><nav><a href="/about">About us</a><a href="/news">News</a>
        <a href="/en/careers">Careers</a></nav><h1>Fake Capital</h1></body></html>""",
    # page carrière vitrine → lien vers la liste
    "/en/careers": """<html><body><h1>Join us</h1><p>We hire talented people.</p>
        <a href="/en/careers/students">Students</a>
        <a href="/en/careers/open-positions">See all open positions</a></body></html>""",
    # liste rendue en JavaScript à partir d'une API maison
    "/en/careers/open-positions": """<html><body><div id="list">Loading jobs...</div>
        <script>
        setTimeout(() => fetch('/api/v2/postings?lang=en').then(r => r.json()).then(d => {
          document.getElementById('list').innerHTML = d.results.items.map(j =>
            `<a href="/en/careers/job/${j.jobId}">${j.jobTitle}<br>${j.city}</a>`).join('');
        }), 300);
        </script></body></html>""",
    "/api/v2/postings": json.dumps({"results": {"total": 3, "items": [
        {"jobId": 11, "jobTitle": "Investment Analyst Intern (6 months)", "city": "Zurich",
         "department": "Private Equity"},
        {"jobId": 12, "jobTitle": "Senior Associate Direct Investments", "city": "Zug",
         "department": "Private Equity"},
        {"jobId": 13, "jobTitle": "Software Engineer", "city": "Zurich", "department": "IT"}]},
        "menu": [{"title": "Home", "url": "/"}, {"title": "Careers", "url": "/careers"}]}),
    # ATS intégré (iframe / lien Personio)
    "/ats/careers": """<html><body><h1>Careers</h1>
        <a href="https://fakecap.jobs.personio.de/job/42">Analyst M&A</a></body></html>""",
    # petite société : postes listés en texte, candidature par e-mail
    "/small/jobs": """<html><body><h1>Careers at Small Partners</h1>
        <p>We are always looking for talent.</p>
        <h3>Investment Analyst Intern (6 months, start 2027)</h3>
        <p>Send your CV to jobs@small.ch.</p>
        <h3>Students &amp; Graduates</h3></body></html>""",
    # --- moteur v2 -------------------------------------------------------
    # bandeau cookies : « Reject all » doit être cliqué (jamais « Accept all »)
    "/v2/home": """<html><body>
        <div id="cmp"><p>We use cookies.</p>
          <button onclick="document.getElementById('cmp').remove();
            document.body.insertAdjacentHTML('beforeend','<a href=/v2/jobs>Careers</a>')">Reject all</button>
          <button onclick="document.getElementById('cmp').remove();
            document.body.insertAdjacentHTML('beforeend','<a href=/accepted>Careers</a>')">Accept all</button>
        </div><h1>Fake Wealth</h1></body></html>""",
    # menu dans un web component (shadow DOM), invisible pour querySelectorAll
    "/v2/shadow": """<html><body><site-nav></site-nav><script>
        customElements.define('site-nav', class extends HTMLElement { connectedCallback() {
          this.attachShadow({mode: 'open'}).innerHTML = '<a href="/v2/jobs">Careers</a>'; } });
        </script></body></html>""",
    # liste avec bouton « Load more » ; fiche avec JSON-LD JobPosting
    "/v2/jobs": """<html><body><h1>Open positions</h1><ul id="l">
        <li><a href="/v2/jobs/1">Investment Analyst Intern</a></li>
        <li><a href="/v2/jobs/2">Senior Portfolio Manager</a></li></ul>
        <button onclick="document.getElementById('l').insertAdjacentHTML('beforeend',
          '<li><a href=/v2/jobs/3>Graduate Programme M&amp;A 2027</a></li>'); this.remove()">Load more</button>
        </body></html>""",
    "/v2/jobs/1": """<html><head><script type="application/ld+json">{"@context":"https://schema.org",
        "@type":"JobPosting","title":"Investment Analyst Intern","datePosted":"2026-10-01",
        "employmentType":"INTERN","description":"<p>Join our private equity team in Geneva.</p>",
        "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressLocality":"Geneva",
        "addressCountry":"CH"}}}</script></head><body>Investment Analyst Intern</body></html>""",
    # site sans lien carrière : la page est déclarée dans le sitemap
    "/robots.txt": "User-agent: *\nSitemap: {HOST}/sitemap_index.xml\n",
    "/sitemap_index.xml": """<?xml version="1.0"?><sitemapindex><sitemap><loc>{HOST}/page-sitemap.xml</loc>
        </sitemap><sitemap><loc>{HOST}/job-sitemap.xml</loc></sitemap></sitemapindex>""",
    "/page-sitemap.xml": """<?xml version="1.0"?><urlset><url><loc>{HOST}/</loc></url>
        <url><loc>{HOST}/en/about</loc></url><url><loc>{HOST}/en/karriere/</loc></url></urlset>""",
    "/job-sitemap.xml": """<?xml version="1.0"?><urlset>
        <url><loc>{HOST}/job/m-a-analyst-intern-zurich/</loc></url></urlset>""",
    "/nolink": """<html><body><h1>Tiny Partners</h1><a href="/en/about">About</a></body></html>""",
}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        body = PAGES.get(path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        ctype = ("application/json" if path.startswith("/api") else
                 "application/xml" if path.endswith(".xml") else
                 "text/plain" if path.endswith(".txt") else "text/html")
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.replace("{HOST}", "http://" + self.headers["Host"]).encode())


@pytest.fixture(scope="module")
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_collect_end_to_end(site, tmp_path):
    store = Store(tmp_path / "db.sqlite")
    cfg = {"firms": [{"name": "Fake Capital", "website": site + "/home", "category": "pe"},
                     {"name": "Dead Firm", "website": "http://127.0.0.1:9/"},
                     {"name": "Small Partners", "careers_url": site + "/small/jobs", "category": "pe"},
                     {"name": "Global Bank", "website": "x", "site": False}],
           "careers": {"min_delay": 0, "max_delay": 0, "timeout": 10, "settle": 2, "parallel": 2}}
    fcfg = {"swiss_only": True, "early_career_only": True, "include_associate": True}
    kept = careers.collect(cfg, None, store, lambda j, p: filters.evaluate(j, fcfg, p))
    assert sorted((j["company"], j["title"], j["domain"]) for j in kept) == [
        ("Fake Capital", "Investment Analyst Intern (6 months)", "Private Equity / VC / Private Markets"),
        ("Small Partners", "Investment Analyst Intern (6 months, start 2027)",
         "Private Equity / VC / Private Markets")]
    assert all(j["location"] for j in kept)
    cov = {r["company"]: r for r in store.coverage()}
    assert "Global Bank" not in cov                       # site: false → pas visité
    assert cov["Fake Capital"]["kept"] == 1 and cov["Fake Capital"]["method"].startswith("navigateur")
    assert cov["Dead Firm"]["error"]
    # 2e passage : la page de la liste est mémorisée, plus besoin de la page d'accueil
    assert store.firm_state("Fake Capital")["resolved"]["url"].endswith("/open-positions")


@pytest.fixture(scope="module")
def b():
    with br.Browser(min_delay=0, max_delay=0, timeout=15, settle=2) as bb:
        yield bb


def test_homepage_to_js_listing(site, b):
    url, _ = b.find_careers(site + "/home")
    assert url == site + "/en/careers"
    jobs, resolved, method, err = careers._browser_jobs(b, url)
    titles = {j["title"] for j in jobs}
    assert "Investment Analyst Intern (6 months)" in titles
    assert "Home" not in titles                                  # menu JSON ignoré
    assert resolved == {"ats": "browser", "url": site + "/en/careers/open-positions"}
    assert "json" in method
    job = next(j for j in jobs if j["title"].startswith("Investment Analyst Intern"))
    assert job["location"] == "Zurich" and job["url"] == site + "/en/careers/job/11"


def test_ats_detected_from_page(site, b):
    jobs, resolved, _, _ = careers._browser_jobs(b, site + "/ats/careers")
    assert jobs is None and resolved == {"ats": "personio", "slug": "fakecap"}


def test_text_only_listing(site, b):
    jobs, _, method, _ = careers._browser_jobs(b, site + "/small/jobs")
    assert method == "texte"
    assert [j["title"] for j in jobs] == ["Investment Analyst Intern (6 months, start 2027)"]


@pytest.mark.parametrize("links,expected", [
    ([("Insights\nCredit opportunities remain intact", "https://www.firm.ch/en/insights/credit-opportunities"),
      ("Careers", "https://www.firm.ch/en/careers")], "https://www.firm.ch/en/careers"),
    ([("Website erstellen lassen", "https://webkoenig.ch/x"), ("Jobs", "https://www.firm.ch/jobs")],
     "https://www.firm.ch/jobs"),                                   # lien externe ignoré
    ([("Join us", "https://firm.jobs.personio.de/")], "https://firm.jobs.personio.de/"),  # ATS externe OK
    ([("Our solutions", "https://www.firm.ch/en/our-solutions")], None),
    ([("Karriere", "https://karriere.firm.ch/")], "https://karriere.firm.ch/"),       # sous-domaine
    ([("Read more", "https://www.firm.ch/en/news/2026/we-are-hiring-careers-day")], None),  # article
])
def test_pick_careers_link(links, expected):
    sc = br.Scan(url="https://www.firm.ch/en/", final_url="https://www.firm.ch/en/")
    sc.links = links
    assert br.pick_careers_link(sc, "https://www.firm.ch") == expected


def test_portal_ignores_assets():
    from jobhunter import ats
    h = ('<link href="https://rmkcdn.successfactors.com/c84f/abc.css">'
         '<a href="https://career5.successfactors.eu/career?company=postfinance">Jobs</a>')
    assert ats.find_portal(h) == "https://career5.successfactors.eu/career?company=postfinance"


def test_browser_recovers_after_crash(site, b):
    """Après un plantage du navigateur (ex. réveil de veille), il redémarre tout seul."""
    before = getattr(b, "restarts", 0)
    b._browser.close()                           # simule « Target crashed »
    sc = b.scan(site + "/small/jobs")
    assert sc.ok and "Investment Analyst Intern" in sc.text
    assert b.restarts == before + 1


# --------------------------------------------------------------------------- moteur v2
def test_cookie_banner_is_rejected(site, b):
    url, _ = b.find_careers(site + "/v2/home")
    assert url == site + "/v2/jobs"              # « Reject all » cliqué, pas « Accept all »


def test_links_inside_shadow_dom(site, b):
    url, _ = b.find_careers(site + "/v2/shadow")
    assert url == site + "/v2/jobs"


def test_load_more_and_jsonld_detail(site, b):
    from jobhunter.http import PoliteSession
    jobs, _, _, _ = careers._browser_jobs(b, site + "/v2/jobs")
    titles = [j["title"] for j in jobs]
    assert "Graduate Programme M&A 2027" in titles            # ajouté par « Load more »
    s = PoliteSession(min_delay=0, max_delay=0, respect_robots_txt=False)
    careers.enrich(s, jobs, site + "/v2/jobs")
    j = next(j for j in jobs if j["title"] == "Investment Analyst Intern")
    assert j["location"].startswith("Geneva") and "private equity" in j["description"]
    assert j["employment_type"] == "INTERN" and j["posted"] == "2026-10-01"


def test_sitemap_fallback(site):
    from jobhunter.http import PoliteSession
    s = PoliteSession(min_delay=0, max_delay=0, respect_robots_txt=False)
    page, jobs = careers.sitemap_lookup(s, site)
    assert page == site + "/en/karriere/"
    assert [j["title"] for j in jobs] == ["M A Analyst Intern Zurich"]


def test_find_careers_uses_sitemap_when_no_link(site, b):
    from jobhunter.http import PoliteSession
    s = PoliteSession(min_delay=0, max_delay=0, respect_robots_txt=False)
    url, err, sm_jobs = careers._find_careers(b, s, site + "/nolink")
    assert url == site + "/en/karriere/" and not err and len(sm_jobs) == 1
