#!/usr/bin/env python3
"""Diagnostic : pour chaque entreprise dont l'ATS n'a pas été trouvé, cherche
dans la page carrière et ses scripts des indices de portail de recrutement.
Résultat dans logs/diagnostic.txt. Lent et poli (mêmes règles que run.py)."""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import yaml  # noqa: E402

from jobhunter.http import PoliteSession  # noqa: E402

HINT = re.compile(
    r"https?://[^\s\"'<>()\\]*(?:workday|successfactors|smartrecruiters|greenhouse|lever\.co|"
    r"ashbyhq|taleo|icims|softgarden|personio|recruitee|jobvite|teamtailor|workable|"
    r"umantis|abacus|refline|jobs\.|careers\.|career\.|/api/[^\s\"'<>]*job)[^\s\"'<>()\\]*", re.I)

cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
s = PoliteSession(min_delay=2, max_delay=4, max_retries=1, respect_robots_txt=False)
out = []
targets = [c for c in cfg["companies"] if not c.get("ats")]
for c in targets:
    url = c.get("careers_url") or c.get("url")
    out.append(f"\n=== {c['name']}  {url}")
    try:
        r = s.get(url)
    except Exception as e:  # noqa: BLE001
        out.append(f"  erreur : {e}")
        continue
    if r is None:
        out.append("  pas de réponse (bloqué ?)")
        continue
    out.append(f"  HTTP {r.status_code}  final={r.url}  taille={len(r.text)}")
    found = set(HINT.findall(r.text))
    scripts = [urljoin(r.url, m) for m in re.findall(r'<script[^>]+src="([^"]+)"', r.text)][:6]
    for sc in scripts:
        if any(k in sc for k in ("jquery", "gtm", "analytics", "cookie", "onetrust")):
            continue
        try:
            rs = s.get(sc)
            if rs is not None and rs.status_code == 200:
                found |= set(HINT.findall(rs.text[:3_000_000]))
        except Exception:  # noqa: BLE001
            pass
    for f in sorted(found)[:25]:
        out.append("  " + f)
    print(f"{c['name']} : {len(found)} indice(s)", flush=True)

# Test du flux XML SuccessFactors (Pictet)
for feed in ["https://career012.successfactors.eu/career?company=banquepict&career_ns=job_listing_summary&resultType=XML"]:
    r = s.get(feed)
    out.append(f"\n=== SuccessFactors XML {feed}\n  " +
               (f"HTTP {r.status_code} {r.headers.get('content-type')} {r.text[:600]!r}" if r is not None else "pas de réponse"))

(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "logs" / "diagnostic.txt").write_text("\n".join(out), encoding="utf-8")
print("\nTerminé : logs\\diagnostic.txt")
