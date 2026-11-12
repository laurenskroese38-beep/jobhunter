from jobhunter import email_alerts as ea

LINKEDIN_A = """<html><body><table>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=x"><img alt="logo"></a></td>
<td><a href="https://www.linkedin.com/comm/jobs/view/4012345678/?trk=y">Investment Analyst Intern</a>
<p>Lombard Odier · Geneva, Switzerland</p><p>Actively recruiting</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4099999999/">M&amp;A Summer Analyst 2027</a>
<p>Partners Group · Baar, Zug, Switzerland</p></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/search/?x">See all jobs</a></td></tr>
</table></body></html>"""

# variante : toute la carte est un seul lien
LINKEDIN_B = """<div><a href="https://www.linkedin.com/comm/jobs/view/4111111111/?refId=z">
<div>Private Equity Intern</div><div>Capvis · Baar</div><div>2 connections work here</div></a></div>"""

JOBSCH = """<div><a href="https://www.jobs.ch/en/vacancies/detail/b295f695-96f7-45a1-936e-fb66b081e942/?utm=x">
Internship Corporate Finance</a><span>Kepler Cheuvreux</span><span>Nyon</span></div>"""


def test_linkedin_alert_cards():
    jobs = ea.jobs_from_alert_html(LINKEDIN_A, "linkedin")
    assert [(j["title"], j["company"], j["location"]) for j in jobs] == [
        ("Investment Analyst Intern", "Lombard Odier", "Geneva, Switzerland"),
        ("M&A Summer Analyst 2027", "Partners Group", "Baar, Zug, Switzerland")]
    assert jobs[0]["url"] == "https://www.linkedin.com/jobs/view/4012345678/"
    assert jobs[0]["source"] == "alerte:linkedin"


def test_linkedin_alert_whole_card_link():
    (j,) = ea.jobs_from_alert_html(LINKEDIN_B, "linkedin")
    assert (j["title"], j["company"], j["location"]) == ("Private Equity Intern", "Capvis", "Baar")


def test_jobsch_alert():
    (j,) = ea.jobs_from_alert_html(JOBSCH, "jobs.ch")
    assert (j["title"], j["company"], j["location"]) == ("Internship Corporate Finance", "Kepler Cheuvreux", "Nyon")


def test_fetch_reads_mailbox_readonly(monkeypatch):
    raw = ("From: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\r\nSubject: 2 new jobs\r\n"
           "Content-Type: text/html; charset=utf-8\r\n\r\n" + LINKEDIN_A).encode()
    calls = {}

    class M:
        def __init__(self, host): calls["host"] = host
        def login(self, u, p): calls["login"] = u
        def select(self, folder, readonly=False): calls["readonly"] = readonly; return "OK", [b"1"]
        def search(self, _c, *crit):
            return ("OK", [b"7"]) if "jobalerts-noreply@linkedin.com" in crit[-1] else ("OK", [b""])
        def fetch(self, i, what): calls["fetch"] = what; return "OK", [(b"7", raw)]
        def logout(self): pass
    monkeypatch.setenv("IMAP_USER", "me@example.com")
    monkeypatch.setenv("IMAP_PASSWORD", "app-password")
    jobs = ea.fetch(days=2, imap_factory=M)
    assert len(jobs) == 2 and calls["readonly"] is True and "PEEK" in calls["fetch"]


def test_fetch_disabled_without_credentials(monkeypatch):
    monkeypatch.delenv("IMAP_USER", raising=False)
    assert ea.fetch() == []
