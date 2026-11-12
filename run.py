#!/usr/bin/env python3
"""JobHunter — early career en corporate finance / investissement en Suisse.

    python run.py                 # passage complet (sites carrières + LinkedIn/Indeed)
    python run.py --no-jobspy     # seulement les sites carrières
    python run.py --no-sites      # seulement LinkedIn / Indeed
    python run.py --only Capvis   # tester une société (ou toutes celles contenant ce texte)
    python run.py --jitter 30     # attend 0-30 min avant de démarrer (pour la planification)
    python run.py seed-seca       # importe l'annuaire des membres SECA (data/seca_members.csv)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from jobhunter import careers, filters, jobspy_source  # noqa: E402
from jobhunter.http import PoliteSession  # noqa: E402
from jobhunter.report import send_email, write_reports  # noqa: E402
from jobhunter.store import Store  # noqa: E402

log = logging.getLogger("jobhunter")


def setup_logging(verbose: bool) -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(ROOT / "logs" / f"{datetime.now():%Y-%m-%d}.log",
                                      encoding="utf-8")])
    for noisy in ("urllib3", "JobSpy", "jobspy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def load_dotenv(path: Path) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans dépendance externe."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_session(cfg: dict) -> PoliteSession:
    p = cfg.get("politeness", {})
    return PoliteSession(
        min_delay=p.get("min_delay", 3), max_delay=p.get("max_delay", 7),
        max_retries=p.get("max_retries", 4),
        max_failures_per_domain=p.get("max_failures_per_domain", 3),
        respect_robots_txt=p.get("respect_robots_txt", True),
        timeout=p.get("timeout", 25), user_agent=p.get("user_agent"))


class FirmIndex:
    """Retrouve une société de firms.yaml à partir d'un nom d'employeur LinkedIn/Indeed."""
    _LEGAL = re.compile(r"\b(ag|sa|ltd|llc|gmbh|sarl|s a|plc|inc|kgaa|"
                        r"schweiz|suisse|switzerland|\(schweiz\)|\(suisse\)|& cie|& co)\b")
    _GENERIC = {"partners", "capital", "group", "holding", "invest", "investments", "bank",
                "finance", "advisors", "ventures", "management", "asset management", "private",
                "capital partners", "swiss", "global"}

    def __init__(self, firms):
        keys = []
        for f in firms:
            for n in [f["name"], *f.get("aliases", [])]:
                k = re.sub(r"\s+", " ", self._LEGAL.sub(" ", filters.norm(n))).strip(" .,-")
                if len(k) >= 2 and k not in self._GENERIC:
                    keys.append((k, f))
        keys.sort(key=lambda kf: -len(kf[0]))   # le nom le plus précis d'abord
        self.keys = [(re.compile(rf"(?<![\w&]){re.escape(k)}(?![\w&])"), f) for k, f in keys]

    def find(self, company: str):
        c = filters.norm(company or "")
        if not c:
            return None
        for rx, f in self.keys:
            if rx.search(c):
                return f
        return None

    def profile(self, company: str):
        f = self.find(company)
        return careers.firm_profile(f) if f else False


def collect_sites(cfg, s, store, use_browser: bool, only: str | None = None, on_kept=None) -> list[dict]:
    fcfg = cfg.get("filters", {})
    sub = dict(cfg)
    if only:
        sub["firms"] = [f for f in cfg["firms"] if only.lower() in f["name"].lower()]
        log.info("Sociétés testées : %s", ", ".join(f["name"] for f in sub["firms"]) or "aucune")
    log.info("Sites carrières : %d sociétés", len([f for f in sub["firms"] if f.get("site", True)]))
    if only:
        sub["careers"] = {**sub.get("careers", {}), "resume_hours": 0}
    return careers.collect(sub, s, store, lambda j, prof: filters.evaluate(j, fcfg, prof),
                           use_browser=use_browser, on_kept=on_kept)


JOBSPY_OK = ROOT / "data" / ".jobspy_last_complete"


def jobspy_window(jcfg: dict, first_run: bool) -> int:
    """Fenêtre de recherche (heures). Si des passages ont été manqués (PC éteint, LinkedIn
    bloqué), on remonte jusqu'au dernier passage complet + 1 jour, pour ne rien rater."""
    base = int(jcfg.get("hours_old", 72))
    longest = int(jcfg.get("first_run_hours_old", 720))
    if os.getenv("JOBHUNTER_LOOKBACK_HOURS"):      # forcé (bouton « Run workflow »)
        return int(os.environ["JOBHUNTER_LOOKBACK_HOURS"])
    if first_run:
        return longest
    try:
        last = datetime.fromisoformat(JOBSPY_OK.read_text().strip())
        gap = (datetime.now() - last).total_seconds() / 3600 + 24
    except (OSError, ValueError):
        return longest
    return int(min(longest, max(base, gap)))


def collect_jobspy(cfg, index: FirmIndex, first_run: bool = False, state: dict | None = None,
                   sites: list | None = None) -> list[dict]:
    jcfg, fcfg = dict(cfg.get("jobspy", {})), cfg.get("filters", {})
    jcfg["hours_old"] = jobspy_window(jcfg, first_run)
    if sites:
        jcfg["sites"] = sites
    log.info("JobSpy : offres des %d dernières heures (%s)", jcfg["hours_old"],
             ", ".join(jcfg.get("sites", [])))
    raw = jobspy_source.search(jcfg, state=state)
    kept = []
    for j in raw:
        ev = filters.evaluate(j, fcfg, index.profile(j["company"]))
        if ev:
            kept.append(ev)
    log.info("JobSpy : %d offres brutes → %d retenues", len(raw), len(kept))
    return kept


def collect_alerts(cfg, index: FirmIndex) -> list[dict]:
    """Alertes emploi reçues par e-mail (LinkedIn, jobs.ch, jobup, Indeed) si IMAP_* est défini."""
    from jobhunter import email_alerts
    fcfg = cfg.get("filters", {})
    days = int(cfg.get("email_alerts", {}).get("days", 3))
    raw = email_alerts.fetch(days=days)
    kept = []
    for j in raw:
        j["location"] = j["location"] or "Switzerland"
        ev = filters.evaluate(j, fcfg, index.profile(j["company"]))
        if ev:
            kept.append(ev)
    if raw:
        log.info("Alertes e-mail : %d offres → %d retenues", len(raw), len(kept))
    return kept


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259                                    # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def keep_awake(on: bool) -> None:
    """Windows : empêche la mise en veille automatique pendant le passage (sinon il est
    coupé au milieu). L'écran peut s'éteindre ; fermer le capot met quand même en veille."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(
            ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:  # noqa: BLE001
        pass


def acquire_lock() -> Path | None:
    """Verrou anti double-passage. Un verrou laissé par un passage interrompu (PC éteint,
    fenêtre fermée) est ignoré : on vérifie que le processus qui l'a posé existe encore."""
    lock = ROOT / "data" / ".lock"
    lock.parent.mkdir(exist_ok=True)
    if lock.exists() and time.time() - lock.stat().st_mtime < 6 * 3600:
        try:
            pid = int(lock.read_text().strip() or 0)
        except (ValueError, OSError):
            pid = 0
        if _pid_alive(pid):
            return None
        log.warning("Verrou laissé par un passage interrompu (PID %s) : ignoré", pid)
    lock.write_text(str(os.getpid()))
    return lock


def cmd_run(args, cfg) -> int:
    if args.jitter:
        wait = random.uniform(0, args.jitter * 60)
        log.info("Démarrage différé de %.0f min", wait / 60)
        time.sleep(wait)
    lock = acquire_lock()
    if lock is None:
        log.error("Un autre passage semble en cours (data/.lock). Abandon.")
        return 1
    started = datetime.now().isoformat(timespec="seconds")
    keep_awake(True)
    try:
        store = Store(ROOT / cfg.get("database", "data/jobs.sqlite"))
        # « Premier passage » = base vide, ou recherches / filtres modifiés depuis la
        # dernière fois : on remonte alors plus loin dans le temps pour rattraper.
        profile = hashlib.sha1(json.dumps(
            [cfg.get("filters"), cfg.get("jobspy", {}).get("search_terms")],
            sort_keys=True, default=str).encode()).hexdigest()
        profile_file = ROOT / "data" / ".profile"
        old_profile = profile_file.read_text().strip() if profile_file.exists() else ""
        first_run = store.is_empty() or old_profile != profile
        # Les filtres ont pu changer depuis le dernier passage : on remet l'historique à jour.
        fcfg = cfg.get("filters", {})
        index = FirmIndex(cfg.get("firms", []))
        kept, removed = store.refilter(
            lambda r: filters.evaluate(r, fcfg, index.profile(r.get("company", ""))))
        if removed:
            log.info("Historique refiltré : %d offres gardées, %d retirées", kept, removed)
        s = make_session(cfg)
        jobs: list[dict] = []
        new_ids: list[str] = []

        def save(batch):            # chaque lot est enregistré aussitôt (reprise possible)
            jobs.extend(batch)
            new_ids.extend(store.upsert(batch))

        use_js = not args.no_jobspy and not args.only and cfg.get("jobspy", {}).get("enabled", True)
        jstate = {"done": set(), "blocked": set()}
        # 1) LinkedIn / Indeed d'abord (rapide, et la limitation LinkedIn aura le temps
        #    de retomber pendant les sites)
        if use_js:
            save(collect_jobspy(cfg, index, first_run, jstate))
        js_done_at = time.monotonic()
        if os.getenv("IMAP_USER") and not args.only:
            save(collect_alerts(cfg, index))
        # 2) sites carrières
        if not args.no_sites:
            collect_sites(cfg, s, store, use_browser=not args.no_browser, only=args.only, on_kept=save)
        # 3) recherches empêchées par une limitation : nouvel essai, 1 h plus tard
        if use_js and jstate["blocked"]:
            retry = sorted(jstate["blocked"])
            jstate["blocked"] = set()
            # la limitation LinkedIn dure en général 30 à 60 min : on attend au besoin
            wait = cfg.get("jobspy", {}).get("retry_cooldown_minutes", 45) * 60 \
                - (time.monotonic() - js_done_at)
            if wait > 0:
                log.info("Pause de %d min avant le nouvel essai (limitation)", wait // 60 + 1)
                time.sleep(wait)
            log.info("Nouvel essai des recherches bloquées sur : %s", ", ".join(retry))
            save(collect_jobspy(cfg, index, first_run, jstate, sites=retry))
        if use_js:
            if jstate["blocked"]:
                log.warning("Recherches encore bloquées sur %s : elles seront rattrapées au "
                            "prochain passage (fenêtre élargie)", ", ".join(sorted(jstate["blocked"])))
            else:
                JOBSPY_OK.write_text(datetime.now().isoformat(timespec="seconds"))

        new_ids = list(dict.fromkeys(new_ids))
        all_rows = store.rows(cfg.get("active_days", 21))
        # « Nouveaux » = apparues dans les dernières 24 h (y compris celles enregistrées par
        # un passage interrompu puis repris)
        since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        seen = set(new_ids)
        new_rows = store.by_ids(new_ids) + [r for r in all_rows
                                            if r["first_seen"] >= since and r["id"] not in seen]
        xlsx = write_reports(ROOT / cfg.get("output_dir", "output"), new_rows, all_rows,
                             store.coverage())
        mailed = send_email(new_rows, xlsx)
        notes = f"requêtes={s.stats['requests']} retries={s.stats['retries']} " \
                f"suspendus={sorted(s.stats['suspended'])}"
        store.log_run(started, len(jobs), len(new_ids), notes)
        if not args.no_jobspy and not args.only:
            profile_file.write_text(profile)

        log.info("Terminé : %d offres pertinentes, %d nouvelles%s.", len(jobs), len(new_ids),
                 " (email envoyé)" if mailed else "")
        log.info("Rapport : %s", xlsx)
        if s.stats["suspended"]:
            log.warning("Domaines suspendus ce passage : %s", ", ".join(sorted(s.stats["suspended"])))
        return 0
    finally:
        keep_awake(False)
        lock.unlink(missing_ok=True)


def cmd_seed_seca(args, cfg) -> int:
    from jobhunter import seed
    s = make_session(cfg)
    out = ROOT / "data" / "seca_members.csv"
    n = seed.seca_members(s, out)
    log.info("%d membres SECA enregistrés dans %s", n, out)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", nargs="?", default="run", choices=["run", "seed-seca"])
    p.add_argument("--config", default=str(ROOT / "config.yaml"))
    p.add_argument("--no-jobspy", action="store_true")
    p.add_argument("--no-sites", "--no-ats", dest="no_sites", action="store_true",
                   help="ne pas visiter les sites carrières")
    p.add_argument("--no-browser", action="store_true",
                   help="sites carrières : seulement les API d'ATS déjà connues")
    p.add_argument("--only", help="ne traiter que les sociétés dont le nom contient ce texte (test)")
    p.add_argument("--jitter", type=float, default=0, help="délai aléatoire max (minutes)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(args.verbose)
    load_dotenv(ROOT / ".env")
    cfg = load_config(Path(args.config))
    firms_file = ROOT / cfg.get("firms_file", "firms.yaml")
    cfg["firms"] = (load_config(firms_file) or {}).get("firms", []) if firms_file.exists() else []
    return cmd_seed_seca(args, cfg) if args.command == "seed-seca" else cmd_run(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
