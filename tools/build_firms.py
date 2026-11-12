#!/usr/bin/env python3
"""Construit firms.yaml = liste de base (tools/base_firms.py) + membres SECA
pertinents (data/seca_members.csv, produit par `run.py seed-seca`).

    python tools/build_firms.py [chemin/seca_members.csv] > firms.yaml
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from base_firms import BASE  # noqa: E402

SKIP_TYPE = re.compile(r"law|legal|attorney|notar|association|verband|network|angel|foundation|"
                       r"stiftung|public|government|university|school|media|press|software|"
                       r"it services|data room|insurance broker|recruit|executive search|"
                       r"audit|accounting|tax|fiduciar|treuhand|trust company|administrat", re.I)
SKIP_NAME = re.compile(r"rechtsanw|avocat|attorneys|\blaw\b|\blegal\b|notar|association|verband|"
                       r"bundesverband|invest\.austria|business angels|startangels|sictic|"
                       r"\bsuva\b|swisscom|migros-genossenschafts|executive mirror|w executive|"
                       r"executive consulting|patent|markenanw|drooms|ideals|eleks|clearstream|"
                       r"csc corporate|iq-eq|profidata|qashqade|vaultinum|sefid|revision|"
                       r"european investment fund|seca\b|fondation pour|kloepfel|ebury|"
                       r"\bsix\b|six digital|kessler|marsh|aon m&a|carey ag|wineus|"
                       r"multiplicity|one creation|paguasca|imci", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\b(ag|sa|ltd|llc|gmbh|sarl|s\.a\.|plc|inc|lp|kgaa|se|ch|"
               r"schweiz|suisse|switzerland)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


GENERIC = {"swiss", "the", "banque", "bank", "banca", "capital", "partners", "group", "invest",
           "investment", "investments", "asset", "management", "private", "global", "first", "new",
           "fund", "funds", "corporate", "finance", "ventures", "venture", "equity", "advisory"}


def head(name: str) -> str:
    """Premier mot distinctif du nom (« afinum management » → « afinum »)."""
    for tok in norm(name).split():
        if tok not in GENERIC and len(tok) >= 5:
            return tok
    return ""


def domain(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return urlparse(url).netloc.lower().removeprefix("www.")


SECA_SKIP = re.compile(
    r"^(c/o|-)|asset management association|csc corporate|six digital|^six$|drooms|migros-genossenschafts|"
    r"executive mirror|carrel|composite recycling|cbre|embassy|fehr legal|zrg partners|swiss mc|"
    r"jochen prinz|inflex.on|imagine you know|mme legal|climefi|engyn|copresence|ulubay|willhaus|"
    r"clearstream|marsh invest|wenger|schellenberg|paguasca|ideals|cetim|stanford|fis \(|pg3|qashqade|"
    r"be bio energy|ebury|mitoqi|one creation|capital markets company|acano|fs partners|cfo company|"
    r"globalbroker|aon m&a|eleks|h\.i\. executive|imci|^irf$|kessler|kloepfel|profidata|wineus|jeger|"
    r"devis|roic labs|mnty|t schwarz|cfp business|w executive|carey ag|keller schneider|lifco|"
    r"bundesverband|invest\.austria|iq-eq|vp fund solutions|l1 digital|altum management|"
    r"c & s immobilien|storskogen|tschopp|robarth|bald eagle|hoffmann & partner|aralon|"
    r"swisscom|suva|sictic|startangels|business angels|business school|venture kick|"
    r"helvetische bank|lpx ag|association", re.I)
M_A_NAMES = re.compile(r"corporate finance|m&a|alantra|lincoln|oaklins|investec|oddo|proventis|nordstein|"
                       r"bridgelink|helbling|ramus|valorion|primefactor|leverage experts|ellstone|codex|"
                       r"thalia|rosedge|camino|bao capital|lfpe|capstan|platinum partners|avencia|montis|"
                       r"daneo|broadgate|verdine|houlihan|ubs corporate finance|remaco|vicenda|quantus|"
                       r"paprico|alvarez|forvis|bdo|grant thornton|interpath|global m&a|smc corporate", re.I)
ADVISORY = re.compile(r"alvarez|forvis|bdo|grant thornton|interpath|helbling", re.I)
VC_NAMES = re.compile(r"venture|\bvc\b|founderful|redalpine|b2venture|lakestar|tenity|snglr|spicehaus|"
                      r"bootstrap|creadd|tiventure|bloomhaus|equitypitcher|new ventures|futurewave", re.I)


def seca_category(row: dict) -> str | None:
    name, ftype = row.get("Company Name", "").strip(), row.get("Type of Firm", "")
    stages = (row.get("Investment Stages") or "").lower()
    if not name or SECA_SKIP.search(name):
        return None
    if re.search(r"law firm|accountancy|association|government|business school|incubator", ftype, re.I) \
            and not M_A_NAMES.search(name):
        return None
    if M_A_NAMES.search(name) or "merchant bank" in ftype.lower():
        return "advisory" if ADVISORY.search(name) else "ma"
    if VC_NAMES.search(name) or (re.search(r"seed|start-?up|early", stages) and
                                 not re.search(r"buyout|buy-?in|replacement", stages)):
        return "vc"
    if "family office" in ftype.lower():
        return "mfo"
    if "bank subsidiary" in ftype.lower() or re.search(r"\bbank\b|banque|kantonalbank", name, re.I):
        return "bank"
    if re.search(r"fund management|fund of funds|private partnership|institutional|corporate venturer|"
                 r"placement agent", ftype, re.I) or \
            re.search(r"capital|partners|equity|invest|beteiligung|unternehmerkapital|holding|"
                      r"asset|fund|anlagestiftung|management", name, re.I):
        if "consulting" in ftype.lower() and not re.search(r"capital|partners|invest|fund", name, re.I):
            return None
        return "pe" if re.search(r"buyout|buy-?in|replacement|expansion|growth|later", stages) else "privmkt"
    return None


OVERRIDES = {
    "Verdine Partners": {"site": False},       # domaine de l'annuaire SECA introuvable
    # pages carrière introuvables depuis la page d'accueil (vérifiées à la main)
    "Lakestar": {"ats": "personio", "slug": "lakestar"},
    "Unigestion": {"careers_url": "https://www.unigestion.com/home/join-unigestion"},
    "Julius Baer": {"careers_url": "https://www.juliusbaer.com/en/careers/"},
    "Ufenau Capital Partners": {"ats": "personio", "slug": "ufenau-capital-partners"},
    "Pictet": {"careers_url": "https://career012.successfactors.eu/career?company=banquepict"},
}


def main(csv_path: str | None):
    firms: dict[str, dict] = {}
    by_domain: dict[str, str] = {}
    heads: dict[str, list[str]] = {}
    for name, site, cat, extra in BASE:
        f = {"name": name, "website": site, "category": cat, **extra}
        firms[norm(name)] = f
        if head(name):
            heads.setdefault(head(name), []).append(norm(name))
        if site:
            by_domain.setdefault(domain(site), norm(name))
    aliases = {norm(a): norm(n) for n, _, _, ex in BASE for a in ex.get("aliases", [])}

    added = skipped = 0
    if csv_path and Path(csv_path).exists():
        with open(csv_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("Company Name") or "").strip()
                if not name:
                    continue
                country = (row.get("Country") or "").lower()
                if country and not re.search(r"switzerland|schweiz|suisse|liechtenstein", country):
                    skipped += 1
                    continue
                cat = seca_category(row)
                if not cat:
                    skipped += 1
                    continue
                site = (row.get("Homepage") or "").strip()
                key, dom = norm(name), domain(site)
                existing = firms.get(key) or (firms.get(aliases[key]) if key in aliases else None) or \
                    (firms.get(by_domain[dom]) if dom in by_domain else None)
                if not existing and len(heads.get(head(name), [])) == 1:
                    existing = firms[heads[head(name)][0]]
                if existing:
                    if site and existing.get("site", True) and not existing.get("ats"):
                        existing["website"] = site          # l'annuaire SECA fait foi
                    existing.setdefault("location", row.get("Town") or "Switzerland")
                    continue
                f = {"name": name, "website": site, "category": cat,
                     "location": row.get("Town") or "Switzerland",
                     "source": "SECA (" + (row.get("Type of Firm") or "?") + ")"}
                if not site:
                    f["site"] = False
                firms[key] = f
                if dom:
                    by_domain[dom] = key
                added += 1

    # Corrections manuelles après vérification (domaines SECA introuvables, etc.)
    for key, patch in OVERRIDES.items():
        for f in firms.values():
            if f["name"] == key:
                f.update(patch)

    order = ["pe", "privmkt", "vc", "ma", "ib", "big4", "advisory", "am", "hf", "mfo", "bank", "insurer"]
    labels = {"pe": "Private equity", "privmkt": "Private markets / fonds de fonds / infrastructure",
              "vc": "Venture capital", "ma": "M&A / corporate finance / banques d'affaires",
              "ib": "Banques d'investissement mondiales (postes via LinkedIn)",
              "big4": "Big 4 (équipes Deals / Transaction Services)",
              "advisory": "Conseil transactionnel / restructuring",
              "am": "Gestion d'actifs", "hf": "Hedge funds / stratégies quantitatives",
              "mfo": "Family offices", "bank": "Banques privées, cantonales et universelles",
              "insurer": "Assureurs (équipes d'investissement)"}
    out = ["# Généré par tools/build_firms.py — base + annuaire SECA.",
           "# Champs : name, website, category, [location], [global], [site: false], [aliases],",
           "#          [careers_url] (force la page carrière), [ats/slug/url] (force l'ATS).",
           f"# {len(firms)} sociétés ({added} ajoutées depuis SECA, {skipped} membres SECA écartés :",
           "#  cabinets d'avocats, associations, prestataires, sociétés hors Suisse).",
           "firms:"]
    import json
    for cat in order:
        group = sorted((f for f in firms.values() if f["category"] == cat), key=lambda f: f["name"].lower())
        if not group:
            continue
        out.append(f"\n  # ===== {labels[cat]} ({len(group)}) =====")
        for f in group:
            out.append(f"  - name: {json.dumps(f['name'], ensure_ascii=False)}")
            for k in ("website", "category", "location", "global", "site", "aliases", "careers_url",
                      "ats", "slug", "url", "source"):
                if k in f and f[k] not in (None, ""):
                    out.append(f"    {k}: {json.dumps(f[k], ensure_ascii=False)}")
    print("\n".join(out))
    print(f"{len(firms)} sociétés, +{added} SECA, {skipped} écartées", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
