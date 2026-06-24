# FM-1 → YouTube Playlist Sync — Setup Guide

This project automatically mirrors the Muzak FM-1 "What's Playing Now" radio station to a YouTube playlist that updates every 5 minutes — no laptop required. It runs free in the cloud via GitHub Actions.

---

## How It Works

1. A script scrapes the FM-1 "What's Playing Now" page every 5 minutes
2. It searches YouTube for each track and adds new songs to a playlist
3. GitHub Actions runs the script in the cloud on a schedule
4. cron-job.org triggers GitHub Actions reliably every 5 minutes
5. A local song cache means each song is only searched once — protecting your daily API quota

---

## What You'll Need

- A **Google account** (for YouTube)
- A **GitHub account** (free at github.com)
- **Python 3.11+** installed on your computer (only needed once for token setup)

---

## Step 1 — Enable the YouTube Data API

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown at the top → **New Project** → give it any name → **Create**
3. In the left menu go to **APIs & Services → Library**
4. Search for **YouTube Data API v3** → click it → click **Enable**
5. Go to **APIs & Services → OAuth consent screen**
   - Choose **External** → **Create**
   - Fill in App name (e.g. "FM-1 Sync"), your email for support and developer contact
   - Click **Save and Continue** through all screens until done
   - On the **Test users** screen, click **Add Users** and add your Google/YouTube email
6. Go to **APIs & Services → Credentials**
   - Click **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Name it anything → **Create**
   - Click **Download JSON** — save this file as `client_secret.json`

---

## Step 2 — Create the GitHub Repository

1. Go to [github.com](https://github.com) and click **New repository**
2. Name it `fm1-radio-sync` (or anything you like)
3. Set it to **Private** → **Create repository**
4. On your computer, open Terminal and run:
   ```bash
   mkdir fm1-radio-sync
   cd fm1-radio-sync
   git init
   git remote add origin https://github.com/YOUR_USERNAME/fm1-radio-sync.git
   ```
5. Copy all the project files into this folder:
   - `fm1_sync.py`
   - `cleanup_duplicates.py`
   - `requirements.txt`
   - `.github/workflows/fm1_sync.yml`

---

## Step 3 — Install Dependencies & Generate the YouTube Token

This step only runs once on your local machine to authorize the app with YouTube.

```bash
cd fm1-radio-sync
pip3 install -r requirements.txt
python3 fm1_sync.py
```

A browser window will open asking you to sign in to Google and grant access.  
Click **Allow** — this creates a file called `.youtube_token.pickle` in the folder.

> **Note:** If you see a warning that the app is unverified, click **Advanced → Go to [app name] (unsafe)**. This is normal for personal developer apps.

---

## Step 4 — Add Secrets to GitHub

GitHub needs two secrets to run the script in the cloud.

### Encode the token

In Terminal, run:
```bash
base64 -i .youtube_token.pickle
```
Copy the entire output (it will be a long string of letters and numbers).

### Add secrets to GitHub

1. Go to your GitHub repository → **Settings → Secrets and variables → Actions**
2. Click **New repository secret** and add these two:

| Secret Name | Value |
|---|---|
| `YOUTUBE_TOKEN_B64` | The base64 string you just copied |
| `CLIENT_SECRET_JSON` | The full contents of your `client_secret.json` file (open it in a text editor and copy everything) |

---

## Step 5 — Push the Code to GitHub

```bash
git add .
git commit -m "Initial setup"
git push -u origin main
```

---

## Step 6 — Set Up cron-job.org (External Trigger)

GitHub's built-in scheduler is unreliable for new repositories. cron-job.org pings GitHub to trigger runs reliably every 5 minutes.

1. Go to [cron-job.org](https://cron-job.org) and create a free account
2. Click **CREATE CRONJOB**
3. Fill in:
   - **Title:** FM-1 Sync Trigger
   - **URL:** `https://api.github.com/repos/YOUR_USERNAME/fm1-radio-sync/actions/workflows/fm1_sync.yml/dispatches`
   - **Schedule:** Every 5 minutes (select "Every minute" then change the minute field to `*/5`)
4. Click **Headers** tab and add:
   - `Authorization` → `Bearer YOUR_GITHUB_PERSONAL_ACCESS_TOKEN`
   - `Accept` → `application/vnd.github.v3+json`
5. Click **Body** tab, set type to **JSON**, and paste:
   ```json
   {"ref": "main"}
   ```
6. Save the cron job

### Getting a GitHub Personal Access Token

1. Go to GitHub → **Settings** (your profile) → **Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Name it "FM-1 Sync" and check the `workflow` permission
4. Copy the token and use it in the cron-job.org Authorization header above

---

## Step 7 — Test It

1. Go to your GitHub repo → **Actions** tab
2. Click **FM-1 Sync** in the left sidebar
3. Click **Run workflow → Run workflow**
4. Wait ~30 seconds and refresh — you should see a green checkmark
5. Visit your YouTube playlist to confirm songs are being added

---

## Step 8 — One-Time Duplicate Cleanup (if needed)

If you already have duplicates in the playlist, run this once locally **after** the quota resets (midnight Pacific time):

```bash
python3 cleanup_duplicates.py
```

It will list all duplicates and ask you to type **YES** before deleting anything.

---

## Understanding the Daily Quota

The YouTube Data API gives you **10,000 units per day**. Here's how this project uses them:

| Action | Units | When |
|---|---|---|
| Search YouTube for a song | 100 | Once per song title (cached forever after) |
| Add song to playlist | 50 | Once per new song |
| Read playlist contents | 3 | Once ever (then cached locally) |
| Update playlist description | 50 | Once per day |

Once the song cache is populated, most runs cost **0 quota units** because all songs are already known. You have headroom for ~65 new song searches per day.

Quota resets every day at **midnight Pacific time** (3 AM Eastern / 9 PM Hawaii).

---

## File Reference

| File | Purpose |
|---|---|
| `fm1_sync.py` | Main sync script |
| `cleanup_duplicates.py` | One-time duplicate remover |
| `requirements.txt` | Python dependencies |
| `.github/workflows/fm1_sync.yml` | GitHub Actions workflow |
| `song_cache.json` | Cached song→video ID mappings (auto-managed) |
| `client_secret.json` | Google OAuth credentials (keep private) |
| `.youtube_token.pickle` | Your YouTube auth token (keep private, never commit) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Workflow fails with "quotaExceeded" | Quota is exhausted for today — it resets at midnight Pacific. The script exits cleanly and resumes automatically. |
| "No such file: client_secret.json" | Make sure the `CLIENT_SECRET_JSON` secret is set in GitHub |
| Workflow never triggers | Check cron-job.org — make sure the Authorization header has a valid token with `workflow` permission |
| Duplicate songs appearing | Run `python3 cleanup_duplicates.py` once locally after quota resets |
| Token expired | Re-run `python3 fm1_sync.py` locally to refresh `.youtube_token.pickle`, then re-encode and update the `YOUTUBE_TOKEN_B64` secret |
| Songs not found on YouTube | Some Muzak library tracks are obscure instrumentals — these are skipped automatically |
