"""Alertes emploi reçues par e-mail (LinkedIn, jobs.ch / jobup.ch, Indeed).

Pourquoi : les alertes LinkedIn sont calculées par LinkedIn sur TON compte, côté serveur.
On n'a donc jamais à se connecter à LinkedIn avec tes identifiants ni à le « scraper »
(interdit par ses conditions d'utilisation, et ton compte risquerait d'être restreint) :
on lit simplement les e-mails d'alerte dans ta boîte, en lecture seule.

Configuration (variables d'environnement, ou secrets GitHub) :
  IMAP_USER       adresse de la boîte (ex. prenom.nom@gmail.com)
  IMAP_PASSWORD   mot de passe d'application (Gmail : myaccount.google.com/apppasswords)
  IMAP_HOST       facultatif, imap.gmail.com par défaut
  IMAP_FOLDER     facultatif, INBOX par défaut (ou "[Gmail]/All Mail")
"""
from __future__ import annotations

import email
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from urllib.parse import urlparse

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

SENDERS = {
    "linkedin": ["jobalerts-noreply@linkedin.com", "jobs-noreply@linkedin.com"],
    "jobs.ch": ["noreply@jobs.ch", "jobalert@jobs.ch", "info@jobs.ch"],
    "jobup": ["noreply@jobup.ch", "jobalert@jobup.ch", "info@jobup.ch"],
    "indeed": ["alert@indeed.com", "donotreply@jobalert.indeed.com", "alert@jobalert.indeed.com"],
}

# Lien vers UNE offre, par site
JOB_LINK = {
    "linkedin": re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)", re.I),
    "jobs.ch": re.compile(r"jobs\.ch/\w{2}/vacancies/detail/([0-9a-f-]{20,})", re.I),
    "jobup": re.compile(r"jobup\.ch/\w{2}/jobs/detail/([0-9a-f-]{20,})", re.I),
    "indeed": re.compile(r"indeed\.\w+(?:\.\w+)?/(?:rc/clk|viewjob|pagead/clk)\S*?jk=([0-9a-f]{16})", re.I),
}
CLEAN_URL = {
    "linkedin": "https://www.linkedin.com/jobs/view/{}/",
    "jobs.ch": "https://www.jobs.ch/en/vacancies/detail/{}/",
    "jobup": "https://www.jobup.ch/en/jobs/detail/{}/",
    "indeed": "https://ch.indeed.com/viewjob?jk={}",
}
_JUNK = re.compile(r"^(view job|voir l.offre|apply|postuler|easy apply|candidature simplifiée|"
                   r"see all jobs|voir toutes|new|nouveau|promoted|sponsorisé|actively recruiting|"
                   r"recrute activement|\d+ (applicants|candidats)|be an early applicant|"
                   r"\d+\s*(connection|relation)s?.*|.*alumni.*|school alumni.*|"
                   r"\d+ (hours?|days?|weeks?|heures?|jours?|semaines?) ago|il y a .*|"
                   r"this company is actively hiring|.*\bjobs? alert\b.*|unsubscribe|"
                   r"se désabonner|manage alerts?|gérer.*alertes?)$", re.I)


def _lines(node) -> list[str]:
    return [re.sub(r"\s+", " ", s).strip() for s in node.stripped_strings
            if re.sub(r"\s+", " ", s).strip()]


def _split_company_location(line: str) -> tuple[str, str]:
    for sep in (" · ", " • ", " - ", " | "):
        if sep in line:
            a, b = line.split(sep, 1)
            return a.strip(), b.strip()
    return line.strip(), ""


def jobs_from_alert_html(html: str, site: str) -> list[dict]:
    """Offres contenues dans un e-mail d'alerte. Chaque offre = un lien vers sa fiche ;
    l'intitulé est le texte du lien, l'entreprise et le lieu sont les lignes qui suivent
    dans la même « carte » (format LinkedIn : « Entreprise · Lieu »)."""
    rx = JOB_LINK[site]
    soup = BeautifulSoup(html or "", "html.parser")
    by_id: dict[str, list] = {}
    for a in soup.find_all("a", href=True):
        m = rx.search(a["href"])
        if m:
            by_id.setdefault(m.group(1), []).append(a)
    out = []
    for jid, anchors in by_id.items():
        # la plus petite « carte » qui contient tous les liens de cette offre
        card = anchors[0]
        while card.parent is not None and not all(card in x.parents or card is x for x in anchors):
            card = card.parent
        for _ in range(4):            # remonter jusqu'à avoir l'entreprise / le lieu
            if len(_lines(card)) >= 3 or card.parent is None or card.parent.name in ("body", "html"):
                break
            card = card.parent
        linked = {l for a in anchors for l in _lines(a)}
        lines = [l for l in _lines(card) if not _JUNK.match(l)]
        # intitulé = première ligne de la carte qui est le texte d'un lien vers l'offre
        title = next((l for l in lines if l in linked), lines[0] if lines else "")
        if not title:
            continue
        after = [l for l in lines[lines.index(title) + 1:] if l != title]
        company, location = ("", "")
        if after:
            company, location = _split_company_location(after[0])
            if not location and len(after) > 1 and len(after[1]) < 80:
                location = after[1]
        out.append({"title": title[:200], "company": company[:120], "location": location[:120],
                    "url": CLEAN_URL[site].format(jid), "description": "", "posted": "",
                    "source": f"alerte:{site}"})
    return out


def _site_of(sender: str) -> str | None:
    s = sender.lower()
    for site, addrs in SENDERS.items():
        if any(a in s for a in addrs) or (site in s and "alert" in s):
            return site
    return None


def _html_of(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8",
                                                            "replace")
            except Exception:  # noqa: BLE001
                continue
    return ""


def fetch(days: int = 3, imap_factory=None) -> list[dict]:
    """Lit (sans rien modifier) les alertes reçues ces `days` derniers jours."""
    user, pwd = os.getenv("IMAP_USER"), os.getenv("IMAP_PASSWORD")
    if not (user and pwd):
        return []
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    out, n_mails = [], 0
    try:
        M = (imap_factory or imaplib.IMAP4_SSL)(host)
        M.login(user, pwd)
        M.select(f'"{folder}"', readonly=True)        # lecture seule : rien n'est marqué lu
        ids = set()
        for addrs in SENDERS.values():
            for a in addrs:
                typ, data = M.search(None, "SINCE", since, "FROM", f'"{a}"')
                if typ == "OK" and data and data[0]:
                    ids.update(data[0].split())
        for i in sorted(ids):
            typ, data = M.fetch(i, "(BODY.PEEK[])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1])
            site = _site_of(str(make_header(decode_header(msg.get("From", "")))))
            if not site:
                continue
            jobs = jobs_from_alert_html(_html_of(msg), site)
            n_mails += 1
            log.info("Alerte %s « %s » : %d offre(s)", site,
                     str(make_header(decode_header(msg.get("Subject", ""))))[:60], len(jobs))
            out += jobs
        M.logout()
    except Exception as exc:  # noqa: BLE001
        log.warning("Lecture des alertes e-mail impossible : %s", exc)
    # même offre dans plusieurs alertes
    seen, uniq = set(), []
    for j in out:
        if j["url"] not in seen:
            seen.add(j["url"])
            uniq.append(j)
    log.info("Alertes e-mail : %d e-mail(s), %d offre(s) distincte(s)", n_mails, len(uniq))
    return uniq


def host_of(url: str) -> str:
    return urlparse(url).netloc
