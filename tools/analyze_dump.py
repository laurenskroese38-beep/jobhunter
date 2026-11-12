#!/usr/bin/env python3
"""Analyse des captures data/dump : quelles techniques marcheraient sur chaque site."""
import json
import re
import sys
from pathlib import Path
from collections import Counter

D = Path(sys.argv[1] if len(sys.argv) > 1 else "data/dump")
LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
ATS = re.compile(r"(workday|myworkdayjobs|successfactors|greenhouse|lever\.co|ashbyhq|smartrecruiters|"
                 r"personio|recruitee|workable|teamtailor|umantis|abacuscity|softgarden|join\.com|"
                 r"jobs\.ch|jobup|refline|oraclecloud|taleo|icims|avature|phenom|eightfold|breezy|"
                 r"bamboohr|onlyfy|prescreen|jobvite|dvinci|rexx|haufe|concludis|coveto|"
                 r"jobbase|ostendis|talentsoft|cornerstone|csod|pinpointhq|homerun|"
                 r"recruiterbox|zohorecruit|jazzhr|comeet|dover|rippling|hibob|factorial)", re.I)
JOBWORD = re.compile(r"\b(intern(ship)?|stage|stagiaire|praktik\w*|analyst|associate|graduate|trainee|"
                     r"junior|vacanc\w*|open positions?|job openings?|current openings|offene stellen|"
                     r"postes? ouverts?|no (open )?(positions|vacancies)|keine offenen|aucun poste|"
                     r"unsolicited|spontan\w*|candidature spontan\w*|initiativbewerbung)\b", re.I)
NOJOBS = re.compile(r"(no (current )?(open )?(positions|vacancies|openings)|currently no|"
                    r"keine (offenen|aktuellen) (stellen|vakanzen)|aucun poste|pas de poste|"
                    r"no job openings|there are currently no)", re.I)
CONSENT = re.compile(r"(onetrust|cookiebot|usercentrics|didomi|cookieyes|borlabs|complianz|"
                     r"klaro|iubenda|cookie-law|tarteaucitron|quantcast)", re.I)

stats = Counter()
rows = []
for d in sorted(p for p in D.iterdir() if p.is_dir()):
    info = {}
    try:
        info = json.loads((d / "info.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    pages = sorted(d.glob("*.json"))
    r = {"firm": d.name, "cands": len(info.get("candidates", [])), "ld_job": 0, "ats": set(),
         "jobword": 0, "nojobs": False, "consent": set(), "sitemap_jobs": 0, "payload_titles": 0,
         "err": ""}
    for pj in pages:
        if pj.name == "info.json":
            continue
        try:
            m = json.loads(pj.read_text(encoding="utf-8"))
        except Exception:
            continue
        h = (d / (pj.stem + ".html"))
        html = h.read_text(encoding="utf-8", errors="ignore") if h.exists() else ""
        for blk in LD.findall(html):
            if "JobPosting" in blk:
                r["ld_job"] += blk.count("JobPosting")
        r["ats"] |= {a.lower() for a in ATS.findall(" ".join(m.get("requests", [])) + " " +
                                                     " ".join(l[1] for l in m.get("links", [])))}
        r["consent"] |= {c.lower() for c in CONSENT.findall(html[:400000])}
        if pj.stem != "home":
            r["jobword"] += len(JOBWORD.findall(m.get("text", "")))
            r["nojobs"] |= bool(NOJOBS.search(m.get("text", "")))
        for p in m.get("payloads", []):
            if re.search(r'"(title|jobTitle|Title|postingTitle)"\s*:', p.get("sample", "")):
                r["payload_titles"] += 1
        if m.get("error"):
            r["err"] = m["error"][:60]
    sm = d / "sitemap.xml"
    if sm.exists():
        t = sm.read_text(encoding="utf-8", errors="ignore")
        r["sitemap_jobs"] = len(re.findall(r"<loc>[^<]*/(job|jobs|stelle|offre|position|vacanc)[^<]*</loc>", t, re.I))
        r["sitemap"] = True
    rows.append(r)
    stats["firms"] += 1
    stats["no_candidate"] += r["cands"] == 0
    stats["ld_job"] += r["ld_job"] > 0
    stats["ats_seen"] += bool(r["ats"])
    stats["nojobs_text"] += r["nojobs"]
    stats["consent"] += bool(r["consent"])
    stats["sitemap_jobs"] += r["sitemap_jobs"] > 0
    stats["payload_titles"] += r["payload_titles"] > 0
    stats["error"] += bool(r["err"])

print(dict(stats))
print()
for r in rows:
    print(f"{r['firm'][:30]:30} cand={r['cands']} ld={r['ld_job']} sm={r['sitemap_jobs']} pay={r['payload_titles']} "
          f"jw={r['jobword']:3} nojobs={int(r['nojobs'])} ats={','.join(sorted(r['ats']))[:40]} "
          f"consent={','.join(sorted(r['consent']))[:20]} {r['err']}")
