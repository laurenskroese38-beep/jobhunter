"""Base SQLite : historique des offres, détection des nouveautés, cache des ATS."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .filters import SWISS, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT, company TEXT, location TEXT, url TEXT, source TEXT,
    type TEXT, score INTEGER, tags TEXT, posted TEXT, description TEXT,
    domain TEXT DEFAULT '',
    first_seen TEXT, last_seen TEXT,
    status TEXT DEFAULT ''          -- libre : postulé, refusé, à voir...
);
CREATE TABLE IF NOT EXISTS ats_cache (
    company TEXT PRIMARY KEY, resolved TEXT, checked TEXT
);
CREATE TABLE IF NOT EXISTS firm_state (
    company TEXT PRIMARY KEY,
    resolved TEXT, resolved_at TEXT,          -- comment lire le site (ATS / URL), et quand
    last_scan TEXT, method TEXT, found INTEGER, kept INTEGER, error TEXT, target TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    started TEXT, finished TEXT, found INTEGER, new INTEGER, notes TEXT
);
"""


def job_key(job: dict) -> str:
    """Même poste vu sur LinkedIn et sur le site de l'entreprise = une seule ligne."""
    company = re.sub(r"\b(sa|ag|ltd|llc|gmbh|group|groupe|holding|s\.a\.)\b", "", norm(job["company"])).strip()
    title = re.sub(r"\([^)]*\)", " ", norm(job["title"]))      # (Hybrid; m/f/d), (80-100%)...
    head, sep, tail = title.rpartition(",")
    if sep and SWISS.search(tail):                               # ..., Zurich
        title = head
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    key = re.sub(r"\s+", " ", f"{company}|{title}").strip()
    return hashlib.sha1(key.encode()).hexdigest()[:16]


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
        if "domain" not in cols:  # base créée par une version précédente
            self.db.execute("ALTER TABLE jobs ADD COLUMN domain TEXT DEFAULT ''")
            self.db.commit()

    def is_empty(self) -> bool:
        return self.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def refilter(self, evaluate_fn) -> tuple[int, int]:
        """Réapplique les filtres actuels à l'historique (si la config a changé).
        evaluate_fn(row_dict) -> dict enrichi ou None. Renvoie (gardées, retirées)."""
        kept = removed = 0
        seen: set[str] = set()
        rows = self.db.execute("SELECT * FROM jobs ORDER BY score DESC").fetchall()
        for row in rows:
            ev = evaluate_fn(dict(row))
            key = job_key(dict(row))
            if ev is not None and key not in seen and key != row["id"]:
                try:   # identifiant recalculé (règle de dédoublonnage revue)
                    self.db.execute("UPDATE jobs SET id=? WHERE id=?", (key, row["id"]))
                except sqlite3.IntegrityError:
                    ev = None  # une autre ligne porte déjà cet identifiant : doublon
            if ev is None or key in seen:     # écartée, ou doublon
                self.db.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
                removed += 1
            else:
                seen.add(key)
                self.db.execute("UPDATE jobs SET type=?, domain=?, score=?, tags=? WHERE id=?",
                                (ev["type"], ev["domain"], ev["score"], ev["tags"], key))
                kept += 1
        self.db.commit()
        return kept, removed

    def upsert(self, jobs: list[dict], now: str | None = None) -> list[str]:
        """Enregistre les offres ; renvoie les ids des nouvelles."""
        now = now or datetime.now().isoformat(timespec="seconds")
        new_ids = []
        for j in jobs:
            jid = job_key(j)
            row = self.db.execute("SELECT score FROM jobs WHERE id=?", (jid,)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO jobs (id,title,company,location,url,source,type,score,tags,"
                    "posted,description,domain,first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (jid, j["title"], j["company"], j["location"], j["url"], j["source"],
                     j["type"], j["score"], j["tags"], j["posted"], j["description"],
                     j.get("domain", ""), now, now))
                new_ids.append(jid)
            else:
                # Déjà connue : on garde la version la mieux notée (souvent celle de l'ATS)
                if j["score"] > row["score"]:
                    self.db.execute(
                        "UPDATE jobs SET url=?, source=?, score=?, tags=?, location=?, domain=? WHERE id=?",
                        (j["url"], j["source"], j["score"], j["tags"], j["location"],
                         j.get("domain", ""), jid))
                self.db.execute("UPDATE jobs SET last_seen=? WHERE id=?", (now, jid))
        self.db.commit()
        return new_ids

    def rows(self, active_days: int = 21) -> list[sqlite3.Row]:
        since = (datetime.now() - timedelta(days=active_days)).isoformat()
        return self.db.execute(
            "SELECT * FROM jobs WHERE last_seen >= ? ORDER BY first_seen DESC, score DESC",
            (since,)).fetchall()

    def by_ids(self, ids: list[str]) -> list[sqlite3.Row]:
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        return self.db.execute(
            f"SELECT * FROM jobs WHERE id IN ({q}) ORDER BY score DESC", ids).fetchall()

    # -- état par société (sites carrières) -------------------------------
    def firm_state(self, company: str) -> dict | None:
        row = self.db.execute("SELECT * FROM firm_state WHERE company=?", (company,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["resolved"] = json.loads(d["resolved"]) if d.get("resolved") else None
        return d

    def save_firm_resolution(self, company: str, resolved: dict | None) -> None:
        if not resolved:
            return
        self.db.execute("INSERT INTO firm_state (company) VALUES (?) ON CONFLICT(company) DO NOTHING",
                        (company,))
        self.db.execute("UPDATE firm_state SET resolved=?, resolved_at=? WHERE company=?",
                        (json.dumps(resolved), datetime.now().isoformat(timespec="seconds"), company))
        self.db.commit()

    def save_firm_scan(self, company, method, found, kept, error, target) -> None:
        self.db.execute("INSERT INTO firm_state (company) VALUES (?) ON CONFLICT(company) DO NOTHING",
                        (company,))
        self.db.execute("UPDATE firm_state SET last_scan=?, method=?, found=?, kept=?, error=?, target=? "
                        "WHERE company=?", (datetime.now().isoformat(timespec="seconds"), method,
                                            found, kept, error, target, company))
        self.db.commit()

    def coverage(self) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT company, method, found, kept, error, target, last_scan FROM firm_state "
            "ORDER BY kept DESC, found DESC, company")]

    # -- cache de détection ATS ------------------------------------------
    def cached_ats(self, company: str, max_age_days: int):
        row = self.db.execute("SELECT resolved, checked FROM ats_cache WHERE company=?",
                              (company,)).fetchone()
        if row and datetime.fromisoformat(row["checked"]) > datetime.now() - timedelta(days=max_age_days):
            return json.loads(row["resolved"])
        return None

    def save_ats(self, company: str, resolved: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO ats_cache VALUES (?,?,?)",
                        (company, json.dumps(resolved), datetime.now().isoformat()))
        self.db.commit()

    def log_run(self, started, found, new, notes=""):
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
                        (started, datetime.now().isoformat(timespec="seconds"), found, new, notes))
        self.db.commit()
