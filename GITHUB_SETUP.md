# JobHunter on GitHub Actions (every day at 17:00 Swiss time)

The same scraper as on your PC, but run by GitHub in the cloud: no need for your PC to be on.
It runs at 17:00 Zurich time (summer and winter), and you can also start it any time with the
**Run workflow** button.

Each run does:

1. LinkedIn + Indeed searches (JobSpy).
2. Your **job-alert e-mails**, if you connect your mailbox (see step 4). This is optional and
   is the safe way to use your LinkedIn account.
3. The ~250 career sites (ATS APIs + headless browser).
4. The Excel report, kept for 30 days in the run's **Artifacts**, and an e-mail with the new
   offers, if set up (step 5).

History (offers already seen, how each career site is read) is kept between runs in the
GitHub cache. The first run starts from your PC's history (`data/seed.sqlite`).

---

## 1. Create the repository

1. On github.com: **New repository** → name `jobhunter`.
2. **Public or private?**
   - **Public**: GitHub Actions minutes are free and unlimited. The code and the Excel reports
     (job offers) are visible to others. Your passwords are **never** visible, because they
     live in *Secrets*.
   - **Private**: 2,000 free minutes per month. A full run takes about 60–80 min, so a daily
     run uses roughly 1,800–2,400 min a month. That's at the limit: GitHub stops the runs once
     the quota is used up, or bills you if you set a spending limit.

## 2. Upload the files

- **Simplest:** on the empty repository page, click **uploading an existing file** and drag
  in the *content* of the `jobhunter` folder from this zip, including the `.github` folder.
  Then click **Commit changes**.
  - On Windows, hidden folders: if `.github` doesn't appear, enable *View → Show → Hidden
    items* in File Explorer.
- **Or with GitHub Desktop:** *File → Add local repository* → choose the folder → **Publish
  repository**.
- **Or let Claude do it:** connect GitHub to Claude (see the bottom of this file) and ask
  Claude to push it.

## 3. Turn on Actions

**Actions** tab → **I understand my workflows, go ahead and enable them**. Then open
**JobHunter** → **Run workflow** to test it straight away (about 1 h).

## 4. (Recommended) Use your LinkedIn account safely: job alerts by e-mail

Logging the scraper into LinkedIn with your password or cookies breaks LinkedIn's terms, and
LinkedIn regularly restricts accounts that do it. Instead:

1. On LinkedIn, run your searches (e.g. *investment banking intern*, *private equity analyst*,
   *M&A*, *asset management graduate*) with **Location: Switzerland**. Click **Set alert** →
   **Daily**, by e-mail. Do the same on jobs.ch / jobup.ch if you like.
2. Gmail: turn on 2-step verification, then create an **app password** at
   https://myaccount.google.com/apppasswords. It's a 16-character code. **Do not** use your
   normal password.
3. In the repository: **Settings → Secrets and variables → Actions → New repository secret**:
   - `IMAP_USER`: your Gmail address
   - `IMAP_PASSWORD`: the app password

The script then reads, **read-only**, the alert e-mails from the last 3 days. It applies the
same filters (level, field, no German-language ads) and adds the offers to the report.
LinkedIn computes these alerts on its own servers for your account, so they're usually the
**most complete** LinkedIn source. They aren't affected by the limits LinkedIn puts on anonymous
searches from GitHub's servers.

Other mail provider? Also add `IMAP_HOST` (e.g. `outlook.office365.com`).

## 5. (Optional) Receive new offers by e-mail

Secrets: `SMTP_HOST` = `smtp.gmail.com`, `SMTP_PORT` = `587`, `SMTP_USER` = your Gmail,
`SMTP_PASSWORD` = an app password (it can be the same one), `NOTIFY_TO` = where to send.

## Where's the report?

**Actions** tab → the run → **Artifacts** at the bottom → `jobhunter-report-N`. It's a zip
with the Excel file and the log.

## Good to know

- GitHub sometimes starts scheduled runs 5–30 min late.
- LinkedIn limits anonymous searches more from cloud servers than from a home connection. The
  script detects this, waits 45 min and tries again. If it's still blocked, the next run looks
  back over the days it missed. The e-mail alerts (step 4) compensate fully.
- A few career sites block cloud servers. Their offers keep coming in through LinkedIn and the
  alerts.
- Your PC's 20:00 scheduled task can keep running in parallel as a backup, or you can delete it
  in the Windows Task Scheduler. The two keep separate histories.

## Connecting GitHub to Claude

On claude.ai: **Settings → Connectors → GitHub → Connect**, and allow access to the
`jobhunter` repository. Claude can then push changes, read the run logs and fix the scraper
directly in the repository.
