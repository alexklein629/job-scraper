import os
import csv
import smtplib
import hashlib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from jobspy import scrape_jobs

# ── Config ────────────────────────────────────────────────────────────────────

GMAIL_USER         = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']
SEEN_JOBS_FILE     = 'seen_jobs.csv'
HOURS_LOOKBACK     = 48

MUST_HAVE_KEYWORDS = [
    'power bi', 'data analytics', 'business intelligence', 'bi developer',
    'data engineer', 'analytics engineer', 'business analytics', 'dax',
]

NICE_TO_HAVE_KEYWORDS = [
    'microsoft fabric', 'lakehouse', 'etl', 'pipeline', 'sql', 'python',
    'machine learning', 'ml', 'artificial intelligence', 'azure',
    'power query', 'kpi', 'dashboard', 'tableau', 'looker', 'fabric',
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def job_id(job):
    """Stable hash for deduplication."""
    unique = f"{job.get('title','')}{job.get('company','')}{job.get('job_url','')}"
    return hashlib.md5(unique.encode()).hexdigest()

def load_seen_jobs():
    if not os.path.exists(SEEN_JOBS_FILE):
        return set()
    with open(SEEN_JOBS_FILE, newline='') as f:
        return {row['id'] for row in csv.DictReader(f)}

def save_seen_jobs(seen_ids):
    with open(SEEN_JOBS_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'date_seen'])
        writer.writeheader()
        for id_ in seen_ids:
            writer.writerow({'id': id_, 'date_seen': datetime.now().isoformat()})

def score_job(job):
    """Return (passed, score, matched_keywords)."""
    text = f"{job.get('title', '')} {job.get('description', '')}".lower()

    must_matched = [kw for kw in MUST_HAVE_KEYWORDS if kw.lower() in text]
    nice_matched = [kw for kw in NICE_TO_HAVE_KEYWORDS if kw.lower() in text]

    passed = len(must_matched) > 0
    score  = len(must_matched) * 2 + len(nice_matched)

    return passed, score, must_matched + nice_matched

def is_remote(job):
    location = (job.get('location') or '').lower()
    remote   = (job.get('is_remote') or False)
    return remote or 'remote' in location

def within_timeframe(job):
    date_posted = job.get('date_posted')
    if date_posted is None:
        return True
    try:
        if isinstance(date_posted, float) or isinstance(date_posted, int):
            return True  # can't determine date, include it
        if hasattr(date_posted, 'date'):
            date_posted = date_posted.date()
        cutoff = (datetime.now() - timedelta(hours=HOURS_LOOKBACK)).date()
        return date_posted >= cutoff
    except Exception:
        return True  # if anything goes wrong, include the job

# ── Scrape ────────────────────────────────────────────────────────────────────

def fetch_jobs():
    print("Scraping jobs...")
    all_jobs = []
    sources  = ['indeed', 'linkedin', 'glassdoor', 'zip_recruiter']

    for source in sources:
        try:
            print(f"  → {source}")
            df = scrape_jobs(
                site_name       = source,
                search_term     = 'business intelligence data analytics',
                location        = 'United States',
                results_wanted  = 50,
                hours_old       = HOURS_LOOKBACK,
                is_remote       = True,
                country_indeed  = 'USA',
            )
            all_jobs.extend(df.to_dict('records'))
            print(f"     {len(df)} results")
        except Exception as e:
            print(f"     Failed: {e}")

    return all_jobs

# ── Email ─────────────────────────────────────────────────────────────────────

def send_email(jobs):
    if not jobs:
        print("No new matching jobs — skipping email.")
        return

    # Sort by score descending
    jobs.sort(key=lambda j: j['score'], reverse=True)

    html = "<h2>New Matching Jobs</h2>"
    html += f"<p>{len(jobs)} new jobs found in the last {HOURS_LOOKBACK} hours.</p>"

    for j in jobs:
        salary = j.get('min_amount')
        salary_str = f"${salary:,.0f}+" if salary else "Not listed"
        keywords_str = ', '.join(j['keywords'][:6])

        html += f"""
        <div style="border:1px solid #ddd; padding:12px; margin:12px 0; border-radius:6px;">
            <h3 style="margin:0 0 4px">
                <a href="{j.get('job_url', '#')}">{j.get('title', 'N/A')}</a>
            </h3>
            <p style="margin:2px 0; color:#555">{j.get('company', 'N/A')} — {j.get('location', 'Remote')}</p>
            <p style="margin:2px 0">💰 {salary_str} &nbsp;|&nbsp; ⭐ Score: {j['score']} &nbsp;|&nbsp; 📅 {j.get('date_posted', 'N/A')}</p>
            <p style="margin:4px 0; font-size:0.9em; color:#777">Keywords: {keywords_str}</p>
        </div>
        """

    msg                = MIMEMultipart('alternative')
    msg['Subject']     = f"🧑‍💻 {len(jobs)} New Job Matches — {datetime.now().strftime('%b %d')}"
    msg['From']        = GMAIL_USER
    msg['To']          = GMAIL_USER
    msg.attach(MIMEText(html, 'html'))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print(f"Email sent with {len(jobs)} jobs.")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seen_ids  = load_seen_jobs()
    raw_jobs  = fetch_jobs()
    new_jobs  = []

    for job in raw_jobs:
        jid = job_id(job)
        if jid in seen_ids:
            continue
        if not is_remote(job):
            continue
        if not within_timeframe(job):
            continue

        passed, score, keywords = score_job(job)
        if not passed:
            continue

        job['score']    = score
        job['keywords'] = keywords
        seen_ids.add(jid)
        new_jobs.append(job)

    print(f"{len(new_jobs)} new matching jobs found.")
    save_seen_jobs(seen_ids)
    send_email(new_jobs)

if __name__ == '__main__':
    main()
