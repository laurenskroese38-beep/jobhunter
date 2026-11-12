"""Tests hors-ligne : python -m pytest tests -q"""
import http.server
import sys
import threading
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import ats, filters, jobspy_source  # noqa: E402
from jobhunter.http import PoliteSession  # noqa: E402
from jobhunter.report import write_reports  # noqa: E402
from jobhunter.store import Store  # noqa: E402


# --------------------------------------------------------------- http poli
class Handler(http.server.BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        n = Handler.hits[self.path] = Handler.hits.get(self.path, 0) + 1
        if self.path == "/robots.txt":
            self._send(200, b"User-agent: *\nDisallow: /private\n")
        elif self.path == "/flaky" and n < 3:
            self.send_response(429)
            self.send_header("Retry-After", "1")
            self.end_headers()
        elif self.path == "/forbidden":
            self._send(403, b"no")
        else:
            self._send(200, b'{"ok": true}')

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def make(sleeps):
    s = PoliteSession(min_delay=0.5, max_delay=0.5, max_failures_per_domain=3,
                      sleep=lambda t: sleeps.append(t))
    s.session.trust_env = False  # pas de proxy pour le serveur local
    return s


def test_retry_after_is_respected(server):
    sleeps = []
    r = make(sleeps).get(server + "/flaky")
    assert r.status_code == 200 and Handler.hits["/flaky"] == 3
    assert sleeps.count(1.0) == 2  # deux pauses Retry-After de 1 s


def test_403_trips_circuit_breaker(server):
    s = make([])
    assert s.get(server + "/forbidden") is None
    assert s.get(server + "/forbidden") is None
    assert s.is_suspended(server + "/x")
    with pytest.raises(Exception):
        s.get(server + "/ok")
    assert Handler.hits["/forbidden"] == 2  # aucune insistance au-delà


def test_robots_txt(server):
    s = make([])
    assert s.get(server + "/private/jobs", check_robots=True) is None
    assert s.get(server + "/public/jobs", check_robots=True).status_code == 200


def test_delay_between_hits(server):
    sleeps = []
    s = make(sleeps)
    s.get(server + "/a")
    s.get(server + "/b")
    assert any(0 < t <= 0.5 for t in sleeps)


# --------------------------------------------------------------- connecteurs
class Resp:
    def __init__(self, data=None, status=200, text="", url=""):
        self.data, self.status_code, self.text, self.url = data, status, text, url

    def json(self):
        return self.data


class Fake:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        for k, v in self.routes.items():
            if k in url:
                return v(params) if callable(v) else v
        return Resp(None, 404)

    post = get


def test_greenhouse():
    s = Fake({"greenhouse": Resp({"jobs": [{"title": "Investment Analyst", "location": {"name": "Zurich"},
                                             "absolute_url": "https://x/1", "content": "&lt;p&gt;PE&lt;/p&gt;",
                                             "updated_at": "2026-10-01T00:00"}]})})
    j = ats.greenhouse(s, "Co", "co")[0]
    assert j["title"] == "Investment Analyst" and j["description"] == "PE" and j["posted"] == "2026-10-01"


def test_lever_falls_back_to_eu():
    s = Fake({"api.eu.lever.co": Resp([{"text": "VC Intern", "hostedUrl": "u", "createdAt": 1759000000000,
                                        "categories": {"location": "Geneva"}}])})
    j = ats.lever(s, "Co", "co")
    assert j[0]["location"] == "Geneva" and len(s.calls) == 2


def test_workday_pagination_and_dedup():
    def page(params):
        return Resp({"total": 25, "jobPostings": [{"title": "Analyst", "externalPath": "/job/1",
                                                     "locationsText": "Geneva"}] * 20})
    s = Fake({"wday/cxs": page})
    jobs = ats.workday(s, "Bank", url="https://bank.wd3.myworkdayjobs.com/en-US/Ext",
                       search_terms=["a", "b"], max_pages=5)
    assert len(jobs) == 1 and jobs[0]["url"] == "https://bank.wd3.myworkdayjobs.com/Ext/job/1"


def test_detect_ats_from_page():
    page = '<iframe src="https://boards.greenhouse.io/embed/job_board?for=acmecap"></iframe>'
    s = Fake({"acme.ch": Resp(None, 200, page, "https://acme.ch/careers")})
    assert ats.detect_ats(s, "https://acme.ch/careers") == {"ats": "greenhouse", "slug": "acmecap"}
    s = Fake({"bank.ch": Resp(None, 200, 'href="https://bnk.wd103.myworkdayjobs.com/fr-FR/Careers"', "")})
    assert ats.detect_ats(s, "https://bank.ch/jobs") == {"ats": "workday",
                                                         "url": "https://bnk.wd103.myworkdayjobs.com/fr-FR/Careers"}
    s = Fake({"x.ch": Resp(None, 200, "<html>rien</html>", "")})
    assert ats.detect_ats(s, "https://x.ch/jobs")["ats"] == "html"


def test_generic_html():
    page = """<a href="/jobs/123">Stagiaire Investissement (H/F) - Genève</a>
              <a href="/about">À propos de nous et de notre histoire</a>"""
    s = Fake({"x.ch": Resp(None, 200, page, "https://x.ch/carrieres")})
    jobs = ats.generic_html(s, "X", url="https://x.ch/carrieres")
    assert [j["url"] for j in jobs] == ["https://x.ch/jobs/123"]


# --------------------------------------------------------------- filtres
import yaml  # noqa: E402

FCFG = yaml.safe_load(open(Path(__file__).resolve().parents[1] / "config.yaml",
                           encoding="utf-8"))["filters"]
I, G, J, A = (filters.LEVEL_INTERN, filters.LEVEL_GRAD, filters.LEVEL_JUNIOR, filters.LEVEL_ASSOC)
MA, PE, AM = "M&A / Investment Banking", "Private Equity / VC / Private Markets", "Asset Management / Investments"


@pytest.mark.parametrize("title,loc,firm,expected", [
    # --- retenus ---
    ("M&A Intern (6 months)", "Zürich, ZH, Switzerland", False, (I, MA)),
    ("Summer Analyst 2027 - Investment Banking Division", "Geneva, CH", False, (I, MA)),
    ("Off-Cycle Internship – Leveraged Finance", "Zurich", False, (I, MA)),
    ("Praktikant/in Corporate Finance 100%", "Basel", False, None),         # allemand
    ("Stage en fusions & acquisitions (H/F)", "Genève", False, (I, MA)),
    ("Intern Transaction Services / Deals", "Zürich", False, (I, MA)),
    ("Private Equity Analyst", "Baar, Switzerland", False, (J, PE)),
    ("Investment Associate – Venture Capital", "Zug", False, (A, PE)),
    ("Stagiaire Private Markets", "Genève", False, (I, PE)),
    ("Graduate Programme – Asset Management", "Lausanne, VD", False, (G, AM)),
    ("Junior Portfolio Analyst", "Lugano", False, (J, AM)),
    ("Assistant Portfolio Manager", "Zurich", False, (J, AM)),
    ("Equity Research Intern", "Zürich", False, (I, AM)),
    ("Summer Internship 2027", "Zug", True, (I, "Programme général (société cible)")),
    ("Werkstudent Vermögensverwaltung", "Bern", False, None),                # allemand
    ("Trainee Associate Corporate Banking Swiss Corporates", "Zürich", False, (G, MA)),
    ("Corporate Finance Intern", "Basel", False, (I, MA)),
    ("Consultant - Deal Advisory Financial Services", "Zurich", False, (J, MA)),
    ("INTERNSHIP - CORPORATE FINANCE - DEBT ADVISORY - PARIS / NYON", "Nyon, VD", False, (I, MA)),
    # --- écartés ---
    ("Trainee – Junior Sales", "Zurich", False, None),
    ("2027 Internship – Tech – Agentic Testing Automation – Lausanne", "Lausanne", True, None),
    ("Generative AI Intern", "Geneva", True, None),
    ("Stagiaire universitaire 12 mois : Responsabilité sociale d'entreprise", "Lausanne", True, None),
    ("Two Ph.D. Positions in Entrepreneurial Finance", "St. Gallen", False, None),
    ("Manager, Tech M&A Advisory", "Zurich", False, None),
    ("Senior Associate, M&A", "Zurich", False, None),            # senior
    ("Vice President Private Equity", "Geneva", False, None),     # senior
    ("Portfolio Manager Fixed Income", "Zurich", False, None),    # manager = pas junior
    ("Head of Investment Banking", "Zurich", False, None),
    ("M&A Lawyer", "Zurich", False, None),                        # pas un niveau junior
    ("Audit Intern", "Zürich", False, None),                      # fonction exclue
    ("IT Graduate Programme – Software Engineering", "Zürich", True, None),
    ("Compliance Analyst", "Geneva", True, None),
    ("Fund Accounting Intern", "Luxembourg / Geneva", True, None),
    ("Summer Internship 2027", "Zug", False, None),                # société inconnue, intitulé vague
    ("Kauffrau/-mann EFZ Lehrstelle Bank", "Zürich", True, None),  # apprentissage
    ("M&A Intern", "London, UK", False, None),                    # hors Suisse
    ("Investment Analyst Intern", "Geneva, IL", False, None),     # Geneva USA
    ("Fraud Investigator Intern", "Bern", False, None),           # pas « invest »
])
def test_evaluate(title, loc, firm, expected):
    r = filters.evaluate({"title": title, "location": loc, "description": ""}, FCFG, firm)
    assert ((r["type"], r["domain"]) if r else None) == expected


def test_generic_title_kept_when_description_is_finance():
    job = {"title": "Internship 2027", "location": "Zurich", "company": "Boutique AG",
           "description": "Support the deal team with DCF valuation, due diligence and pitch books."}
    r = filters.evaluate(job, FCFG, False)
    assert r and r["type"] == I


# --------------------------------------------------------------- jobspy
def test_jobspy_disables_blocked_site():
    calls = []

    def fake_scrape(**kw):
        calls.append(kw["site_name"][0])
        if kw["site_name"] == ["linkedin"]:
            raise Exception("429 Too Many Requests")
        return pd.DataFrame([{"title": "Investment Intern", "company": "Pictet", "location": "Geneva, GE, CH",
                              "job_url": "https://indeed/1", "site": "indeed", "description": None,
                              "date_posted": "2026-10-05"}])
    sleeps = []
    jobs = jobspy_source.search({"sites": ["linkedin", "indeed"], "search_terms": ["a", "b", "c"],
                                 "locations": ["Switzerland"]}, sleep=sleeps.append, scrape_jobs=fake_scrape)
    assert calls.count("linkedin") == 1 and calls.count("indeed") == 3
    assert len(jobs) == 3 and jobs[0]["description"] == ""
    assert all(25 <= t <= 60 for t in sleeps)


# --------------------------------------------------------------- stockage + rapport
def test_store_dedup_and_report(tmp_path):
    st = Store(tmp_path / "db.sqlite")
    base = {"location": "Geneva", "description": "", "posted": "", "type": I, "tags": "", "domain": AM}
    a = {**base, "title": "Investment Intern", "company": "Pictet SA", "url": "li", "source": "jobspy", "score": 3}
    b = {**base, "title": "Investment Intern", "company": "Pictet", "url": "ats", "source": "workday", "score": 5}
    assert len(st.upsert([a])) == 1
    assert st.upsert([b]) == []                       # même poste, autre source
    row = st.rows()[0]
    assert row["url"] == "ats"                        # version la mieux notée gardée
    xlsx = write_reports(tmp_path / "out", st.rows(), st.rows())
    from openpyxl import load_workbook
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Nouveaux (1)", "Stages", "Graduate programmes",
                             "Analyst - Junior - Associate", "Toutes les offres actives"]
    assert wb["Stages"]["J2"].hyperlink.target == "ats"
    # refiltrage : un poste senior injecté est retiré
    st.upsert([{**a, "title": "Senior Investment Manager", "type": "Poste"}])
    kept, removed = st.refilter(lambda r: filters.evaluate(r, FCFG, True))
    assert (kept, removed) == (1, 1)


def test_jobspy_stops_after_empty_streak_and_logged_429():
    import logging
    calls = []

    def fake_scrape(**kw):
        site = kw["site_name"][0]
        calls.append(site)
        if site == "indeed":
            lg = logging.getLogger("JobSpy:Indeed")
            lg.propagate = False  # comme le vrai JobSpy
            lg.error("Indeed responded with status code: 429")
        return pd.DataFrame()
    jobspy_source.search({"sites": ["linkedin", "indeed"], "search_terms": list("abcdef"),
                          "locations": ["Switzerland"]}, sleep=lambda t: None, scrape_jobs=fake_scrape)
    assert calls.count("indeed") == 1 and calls.count("linkedin") == 3


def test_job_key_ignores_location_suffix_and_parentheses():
    from jobhunter.store import job_key
    a = {"company": "Swiss Re", "title": "Real Estate Investment Analyst (Hybrid; m/f/x/d )"}
    b = {"company": "Swiss Re", "title": "Real Estate Investment Analyst (Hybrid; m/f/x/d ), Zurich (Zurich, CH)"}
    c = {"company": "Swiss Re", "title": "Real Estate Investment Associate"}
    assert job_key(a) == job_key(b) != job_key(c)


# --------------------------------------------------------------- langue / catégories
@pytest.mark.parametrize("title,desc,german", [
    ("Praktikant/in Corporate Finance 100%", "", True),
    ("M&A Intern (m/w/d)", "", True),
    ("Analyst:in Private Equity", "", True),
    ("Praktikum im Asset Management", "", True),
    ("Trainee Associate Corporate Banking im Bereich Swiss Corporates", "", True),
    ("M&A Intern (f/m/d)", "", False),
    ("Investment Analyst Intern – Zürich", "", False),
    ("Stagiaire en fusions & acquisitions", "", False),
    ("Junior Analyst Private Equity (80-100%)", "", False),
    ("Analyst", "Wir suchen für unser Team in Zürich eine motivierte Person. Du bist verantwortlich "
                "für die Analyse von Unternehmen und die Unterstützung bei Transaktionen. Wir bieten "
                "dir eine spannende Tätigkeit mit viel Verantwortung in einem dynamischen Umfeld, in "
                "dem du dich entwickeln kannst, und ein Team, das auf dich wartet.", True),
    ("Analyst", "We are looking for a motivated analyst to join our team in Zurich. You will support "
                "the deal team with financial modelling and due diligence, and you will be part of an "
                "international team with strong growth. We offer a great environment for you to learn "
                "and grow in the role and in the firm.", False),
])
def test_is_german(title, desc, german):
    assert filters.is_german(title, desc) is german


def test_german_ads_are_dropped():
    job = {"title": "Praktikant/in M&A (m/w/d)", "location": "Zürich", "description": ""}
    assert filters.evaluate(job, FCFG, False) is None
    assert filters.evaluate(job, {**FCFG, "exclude_languages": []}, False) is not None


@pytest.mark.parametrize("title,profile,expected", [
    ("Analyst", {"investment_firm": True, "domain": PE}, (J, PE)),
    ("Investment Analyst Intern", {"investment_firm": True, "domain": PE}, (I, PE)),
    ("Associate", {"investment_firm": True, "domain": MA}, (A, MA)),
    ("Analyst", {"investment_firm": False, "domain": None}, None),        # Big 4 : intitulé trop vague
    ("Deals Analyst", {"investment_firm": False, "domain": None}, (J, MA)),
    ("Senior Associate", {"investment_firm": True, "domain": PE}, None),
])
def test_firm_category_gives_domain(title, profile, expected):
    r = filters.evaluate({"title": title, "location": "Zug", "description": ""}, FCFG, profile)
    assert ((r["type"], r["domain"]) if r else None) == expected


def test_firm_index_matches_linkedin_names():
    import run
    idx = run.FirmIndex([
        {"name": "Ufenau Capital Partners", "category": "pe", "aliases": ["Ufenau"]},
        {"name": "UBS", "category": "bank", "aliases": ["UBS AG"]},
        {"name": "EY", "category": "big4", "aliases": ["Ernst & Young"]},
        {"name": "Partners Group", "category": "pe"},
    ])
    assert idx.find("Ufenau Capital Partners AG")["name"] == "Ufenau Capital Partners"
    assert idx.find("UBS Switzerland AG")["name"] == "UBS"
    assert idx.find("EY")["name"] == "EY"
    assert idx.find("Ernst & Young AG")["name"] == "EY"
    assert idx.find("Partners Group (Schweiz) AG")["name"] == "Partners Group"
    assert idx.find("Teya")  is None            # « ey » ne doit pas matcher dans un mot
    assert idx.find("Hubs Logistics") is None   # ni « ubs »
    assert idx.profile("Partners Group AG") == {"investment_firm": True,
                                                 "domain": "Private Equity / VC / Private Markets"}


# Faux positifs réellement rencontrés sur les sites carrières (7 oct.)
@pytest.mark.parametrize("title", [
    "Specialized in early stage", "Cycle de vie de l'entreprise", "Vie active",
    "Analyst recommendations", "Read More about: Analyst coverage",
    "Internship Strategic Partnerships – Tenity Singapore", "Working Student - IT User Support (40-80%)",
    "Internship - Workstation Architect", "Operational Support Intern - 6-9 months",
    "Investment Analyst (London)",
])
def test_real_false_positives_rejected(title):
    prof = {"investment_firm": True, "domain": PE}
    assert filters.evaluate({"title": title, "location": "Switzerland", "description": ""}, FCFG, prof) is None


@pytest.mark.parametrize("title", [
    "Internship (6 months) - Private Equity", "Private Equity Intern", "Financial Analyst Program",
    "Trainee / Summer intern (m / f)", "Junior Analyst - Geneva", "Venture Associate",
    "V.I.E Investment Banking", "Stage en Private Equity",
])
def test_real_true_positives_kept(title):
    prof = {"investment_firm": True, "domain": PE}
    assert filters.evaluate({"title": title, "location": "Switzerland", "description": ""}, FCFG, prof)


def test_stale_lock_is_ignored(tmp_path, monkeypatch):
    import run
    monkeypatch.setattr(run, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".lock").write_text("999999")       # processus inexistant
    lock = run.acquire_lock()
    assert lock is not None and lock.read_text() == str(__import__("os").getpid())
    assert run.acquire_lock() is None                          # notre propre verrou, vivant


# --------------------------------------------------------------------------- moteur v2
def test_urls_in_html_json_menu():
    from jobhunter.browser import urls_in_html
    h = ('{&quot;href&quot;:&quot;https:\\/\\/www.juliusbaer.com\\/en\\/careers\\/&quot;}'
         '<script src="/static/jobs.js"></script> https://jobs.example.ch/x')
    assert urls_in_html(h, "https://www.juliusbaer.com/ch/en/") == ["https://www.juliusbaer.com/en/careers/"]


def test_pick_careers_link_group_domain():
    from jobhunter import browser as br
    sc = br.Scan(url="https://www.baloise-asset-management.com/",
                 final_url="https://www.baloise-asset-management.com/ch/en.html")
    sc.links = [("Jobs & Kariere", "https://www.helvetia-baloise.com/corporate/hb/de/home/ueber-uns/karriere.html"),
                ("Our partner Webagentur", "https://agency.ch/careers")]
    assert br.pick_careers_link(sc, sc.url) == \
        "https://www.helvetia-baloise.com/corporate/hb/de/home/ueber-uns/karriere.html"
    sc.links = [("", "https://www.helvetia-baloise.com/corporate/hb/en/home/about-us/career.html"),
                ("", "https://portfolio-co.com/blog/how-we-hire/careers-day-recap")]
    assert br.pick_careers_link(sc, sc.url).endswith("/about-us/career.html")


def test_jsonld_intern_and_expired():
    from jobhunter.structured import jobpostings_from_html
    h = ('<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Summer 2027",'
         '"employmentType":["INTERN"],"jobLocation":{"address":{"addressLocality":"Zurich",'
         '"addressCountry":"CH"}}}]}</script>')
    j = jobpostings_from_html(h, "https://x.ch/j/1")[0]
    assert j["location"] == "Zurich, CH" and j["employment_type"] == "INTERN"
    job = {**j, "company": "X", "source": "site:jsonld"}
    assert filters.evaluate(job, FCFG, {"investment_firm": True, "domain": "M&A / Investment Banking"})
    assert filters.evaluate({**job, "valid_through": "2020-01-01"}, FCFG, True) is None


def test_workday_paginates_past_page_two():
    calls = []

    class S:
        def post(self, url, json):
            calls.append(json["offset"])
            n = 20 if json["offset"] < 60 else 5
            total = 65 if json["offset"] == 0 else 0      # Workday : total seulement en page 1

            class R:
                status_code = 200
                def json(self_):
                    return {"total": total, "jobPostings": [
                        {"title": f"Analyst {json['offset'] + i}", "externalPath": f"/job/{json['offset'] + i}",
                         "locationsText": "Zurich"} for i in range(n)]}
            return R()
    out = ats.workday(S(), "Acme", "https://acme.wd3.myworkdayjobs.com/External", max_pages=5)
    assert calls == [0, 20, 40, 60] and len(out) == 65


def test_v2_real_regressions():
    from jobhunter import browser as br
    # Rahn+Bodmer : lien vers le site de l'éditeur du logiciel RH, pas vers leurs offres
    sc = br.Scan(url="https://www.rahnbodmer.ch/", final_url="https://www.rahnbodmer.ch/en/")
    sc.links = [("Jobs", "https://www.rexx-systems.com/jobs/")]
    assert br.pick_careers_link(sc, sc.url) is None
    sc.links = [("Jobs", "https://rahnbodmer.rexx-systems.com/stellenangebote.html")]
    assert br.pick_careers_link(sc, sc.url) == "https://rahnbodmer.rexx-systems.com/stellenangebote.html"
    # Bordier : URL d'une offre précise trouvée dans le code → on remonte à la liste
    assert br.urls_in_html('"https://www.bordier.com/open-positions/compliance-officer-100/"',
                           "https://www.bordier.com/") == ["https://www.bordier.com/open-positions/"]


def test_cached_vendor_page_is_rediscovered():
    from jobhunter import careers
    state = {"resolved": {"ats": "browser", "url": "https://www.rexx-systems.com/jobs/"},
             "resolved_at": "2099-01-01T00:00:00", "found": 11}
    r = careers._process({"name": "Rahn+Bodmer", "website": "rahnbodmer.ch"}, state, None, None, {}, 30, 1)
    assert r["resolved"] is None            # cache écarté → nouvelle recherche de la page


def test_team_page_titles_are_not_jobs():
    base = {"location": "Zurich", "description": "", "company": "Cape Capital"}
    j = {**base, "title": "Equity Analyst", "url": "https://www.capecapital.com/our-people", "source": "site:texte"}
    assert filters.evaluate(j, FCFG, True) is None
    j = {**base, "title": "Financial Analyst", "url": "https://www.bwm.ch/en/about-us/team", "source": "site:liens"}
    assert filters.evaluate(j, FCFG, True) is None
    j = {**base, "title": "Equity Analyst Intern", "url": "https://www.x.ch/careers/equity-analyst-intern",
         "source": "site:liens"}
    assert filters.evaluate(j, FCFG, True)


def test_jobspy_hung_query_is_abandoned():
    import time as _t

    def scrape_jobs(**kw):
        if kw["site_name"] == ["indeed"]:
            _t.sleep(5)                     # requête figée
        return pd.DataFrame([{"title": "M&A Intern", "company": "X", "location": "Zurich",
                              "job_url": "https://x/1", "site": kw["site_name"][0]}])
    cfg = {"sites": ["linkedin", "indeed"], "search_terms": ["m&a intern", "pe intern"],
           "locations": ["Switzerland"], "delay_seconds": [0, 0], "query_timeout": 0.5}
    t0 = _t.monotonic()
    out = jobspy_source.search(cfg, sleep=lambda s: None, scrape_jobs=scrape_jobs)
    assert _t.monotonic() - t0 < 3
    assert {j["source"] for j in out} == {"jobspy:linkedin"}


def test_jobspy_blocked_queries_are_retried_later():
    import logging as _l
    calls = []

    def scrape_jobs(**kw):
        site, term = kw["site_name"][0], kw["search_term"]
        calls.append((site, term))
        if site == "linkedin" and term == "b" and len([c for c in calls if c == ("linkedin", "b")]) == 1:
            _l.getLogger("JobSpy:LinkedIn").error("LinkedIn response status code 429")
            return pd.DataFrame()
        return pd.DataFrame([{"title": f"{term} intern", "company": "X", "location": "Zurich",
                              "job_url": f"https://x/{site}/{term}", "site": site}])
    cfg = {"sites": ["linkedin"], "search_terms": ["a", "b", "c"], "locations": ["Switzerland"],
           "delay_between_queries": [0, 0]}
    state = {"done": set(), "blocked": set()}
    first = jobspy_source.search(cfg, sleep=lambda s: None, scrape_jobs=scrape_jobs, state=state)
    assert state["blocked"] == {"linkedin"} and [j["url"][-1] for j in first] == ["a"]
    state["blocked"] = set()
    second = jobspy_source.search(cfg, sleep=lambda s: None, scrape_jobs=scrape_jobs, state=state)
    assert sorted(j["url"][-1] for j in second) == ["b", "c"]      # « a » n'est pas refait
    assert not state["blocked"]


def test_jobspy_window_catches_up_missed_days(tmp_path, monkeypatch):
    import run as runmod
    from datetime import datetime, timedelta
    monkeypatch.setattr(runmod, "JOBSPY_OK", tmp_path / "ok")
    j = {"hours_old": 72, "first_run_hours_old": 720}
    assert runmod.jobspy_window(j, False) == 720                     # jamais complet → 30 j
    (tmp_path / "ok").write_text((datetime.now() - timedelta(days=6)).isoformat())
    assert 160 <= runmod.jobspy_window(j, False) <= 170              # 6 j manqués + 1 j
    (tmp_path / "ok").write_text(datetime.now().isoformat())
    assert runmod.jobspy_window(j, False) == 72


def test_oracle_connector_and_detection():
    url = "https://iaadtu.fa.ocs.oraclecloud.eu/hcmUI/CandidateExperience/en/sites/CX_1/jobs?mode=location"
    assert ats.detect_in(url)["ats"] == "oracle"

    class R:
        status_code = 200
        def __init__(self, d): self.d = d
        def json(self): return self.d

    class S:
        def get(self, api, params=None):
            assert api.endswith("/recruitingCEJobRequisitions") and "siteNumber=CX_1" in params["finder"]
            return R({"items": [{"TotalJobsCount": 2, "requisitionList": [
                {"Id": "101", "Title": "Investment Analyst Intern", "PrimaryLocation": "Geneva, Switzerland",
                 "PostedDate": "2026-10-20"},
                {"Id": "102", "Title": "IT Support", "PrimaryLocation": "Lugano, Switzerland"}]}]})
    out = ats.oracle(S(), "UBP", url)
    assert [j["title"] for j in out] == ["Investment Analyst Intern", "IT Support"]
    assert out[0]["url"].endswith("/sites/CX_1/job/101") and out[0]["location"].startswith("Geneva")


def test_workday_multi_location_and_swiss_spellings():
    assert filters.is_swiss("Pfaeffikon SZ") and filters.is_swiss("Pfäffikon, SZ")
    assert not filters.is_swiss("Geneva, NE, US") and not filters.is_swiss("Paris, FR")
    j = {"title": "Graduate Programme Manager 80-100%", "location": "Zurich", "description": ""}
    assert filters.evaluate(j, FCFG, True) is None


def test_jobspy_transient_429_with_partial_results_keeps_going():
    import logging as _l

    def scrape_jobs(**kw):
        term = kw["search_term"]
        if term == "b":
            _l.getLogger().error("response status code 429 (blocked: use a proxy)")
        return pd.DataFrame([{"title": f"{term} intern", "company": "X", "location": "Zurich",
                              "job_url": f"https://x/{term}", "site": "linkedin"}])
    cfg = {"sites": ["linkedin"], "search_terms": ["a", "b", "c"], "locations": ["Switzerland"],
           "delay_between_queries": [0, 0]}
    state = {"done": set(), "blocked": set()}
    out = jobspy_source.search(cfg, sleep=lambda s: None, scrape_jobs=scrape_jobs, state=state)
    assert sorted(j["url"][-1] for j in out) == ["a", "b", "c"]     # « c » a bien été fait
    assert state["blocked"] == {"linkedin"}                          # « b » sera refait
    assert ("linkedin", "b", "Switzerland") not in state["done"]
