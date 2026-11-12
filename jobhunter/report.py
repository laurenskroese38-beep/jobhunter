"""Export Excel / CSV et notification email optionnelle."""
from __future__ import annotations

import csv
import logging
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

log = logging.getLogger(__name__)

COLUMNS = [  # (clé, en-tête, largeur)
    ("first_seen", "Vu le", 11), ("type", "Niveau", 19), ("domain", "Domaine", 30),
    ("title", "Intitulé", 50), ("company", "Entreprise", 26), ("location", "Lieu", 22),
    ("score", "Score", 7), ("posted", "Publié", 11), ("source", "Source", 16),
    ("url", "Lien", 10),
]
TYPE_FILL = {"Stage / Internship": "E2EFDA", "Graduate programme": "DDEBF7",
             "Analyst / Junior": "FFF2CC", "Associate": "F2F2F2"}


def _sheet(wb, name, rows):
    ws = wb.create_sheet(name)
    ws.append([h for _, h, _ in COLUMNS])
    for c, (_, _, w) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3864")
    for r in rows:
        values = [r[k] for k, _, _ in COLUMNS]
        values = ["" if v is None else v for v in values]
        values[0] = str(values[0])[:10]
        values[-1] = "Ouvrir"
        ws.append(values)
        row = ws.max_row
        link = ws.cell(row=row, column=len(COLUMNS))
        link.hyperlink = r["url"]
        link.font = Font(color="0563C1", underline="single")
        fill = TYPE_FILL.get(r["type"])
        if fill:
            ws.cell(row=row, column=2).fill = PatternFill("solid", fgColor=fill)
        ws.cell(row=row, column=3).alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def _coverage_sheet(wb, rows):
    ws = wb.create_sheet("Couverture sites")
    head = [("company", "Société", 34), ("method", "Méthode", 26), ("found", "Éléments lus", 12),
            ("kept", "Retenus", 9), ("error", "Problème", 45), ("target", "Page / ATS", 60),
            ("last_scan", "Dernier passage", 18)]
    ws.append([h for _, h, _ in head])
    for c, (_, _, w) in enumerate(head, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
        ws.cell(row=1, column=c).font = Font(bold=True, color="FFFFFF")
        ws.cell(row=1, column=c).fill = PatternFill("solid", fgColor="1F3864")
    for r in rows:
        ws.append(["" if r.get(k) is None else r.get(k) for k, _, _ in head])
        if r.get("error") or not r.get("found"):
            ws.cell(row=ws.max_row, column=1).fill = PatternFill("solid", fgColor="FCE4D6")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def write_reports(out_dir: str | Path, new_rows, all_rows, coverage=None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    _sheet(wb, f"Nouveaux ({len(new_rows)})", new_rows)
    _sheet(wb, "Stages", [r for r in all_rows if r["type"] == "Stage / Internship"])
    _sheet(wb, "Graduate programmes", [r for r in all_rows if r["type"] == "Graduate programme"])
    _sheet(wb, "Analyst - Junior - Associate",
           [r for r in all_rows if r["type"] in ("Analyst / Junior", "Associate")])
    _sheet(wb, "Toutes les offres actives", all_rows)
    if coverage:
        _coverage_sheet(wb, coverage)
    xlsx = out / "offres_corporate_finance_suisse.xlsx"
    try:
        wb.save(xlsx)
    except PermissionError:
        # fichier ouvert dans Excel : on enregistre une copie datée plutôt que d'échouer
        xlsx = out / f"offres_corporate_finance_suisse_{datetime.now():%Y-%m-%d_%Hh%M}.xlsx"
        log.warning("Rapport ouvert dans Excel : enregistré sous %s", xlsx.name)
        wb.save(xlsx)

    stamp = datetime.now().strftime("%Y-%m-%d")
    with open(out / f"nouveaux_{stamp}.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow([h for _, h, _ in COLUMNS])
        for r in new_rows:
            w.writerow([r[k] for k, _, _ in COLUMNS])
    return xlsx


def send_email(new_rows, attachment: Path | None = None) -> bool:
    """Active si les variables d'environnement SMTP_* sont définies (voir README)."""
    host, user, pwd = (os.getenv("SMTP_HOST"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
    to = os.getenv("NOTIFY_TO") or user
    if not (host and user and pwd and new_rows):
        return False
    msg = EmailMessage()
    msg["Subject"] = f"{len(new_rows)} nouvelle(s) offre(s) early career corporate finance en Suisse"
    msg["From"], msg["To"] = user, to
    lines = [f"- [{r['type']} | {r['domain']}] {r['title']} — {r['company']} ({r['location']})\n  {r['url']}"
             for r in new_rows[:60]]
    if len(new_rows) > 60:
        lines.append(f"... et {len(new_rows) - 60} autres dans le fichier Excel.")
    msg.set_content("\n".join(lines))
    if attachment and attachment.exists():
        msg.add_attachment(attachment.read_bytes(), maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=attachment.name)
    try:
        with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587")), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.send_message(msg)
        return True
    except Exception as exc:
        log.warning("Envoi de l'email impossible : %s", exc)
        return False
