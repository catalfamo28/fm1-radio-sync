#!/usr/bin/env python3
"""
FM-1 → YouTube Playlist Sync
Fetches the Muzak FM-1 "What's Playing Now" track list,
searches YouTube for each song, and adds them to a YouTube
playlist called "FM-1 Live Radio".

Run it anytime to add newly played tracks to your playlist.
The playlist lives on YouTube — play it on any device.

Quick start:
  pip install -r requirements.txt
  # Fill in CLIENT_SECRETS_FILE path below (downloaded from Google Cloud Console)
  python fm1_sync.py
"""

import re
import json
import logging
import webbrowser
from datetime import date as _date
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── Configuration ─────────────────────────────────────────────────────────────
# Path to the client_secret_xxxx.json you download from Google Cloud Console
CLIENT_SECRETS_FILE = str(Path(__file__).parent / "client_secret.json")

PLAYLIST_NAME = "FM-1 Live Radio"
FM1_URL       = "https://muzakwpn.muzak.com/wpn/030.html"
TOKEN_FILE    = Path(__file__).parent / ".youtube_token.pickle"

SCOPES = ["https://www.googleapis.com/auth/youtube"]
CACHE_FILE = Path(__file__).parent / "song_cache.json"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Track:
    title: str
    artist: str

    def __str__(self) -> str:
        return f'"{self.title}" by {self.artist}'


# ── Scraper ───────────────────────────────────────────────────────────────────
_SKIP       = re.compile(
    r"(now on fm|last ten songs|what.?s playing|last update|fm-1 -"
    r"|^(mon|tue|wed|thu|fri|sat|sun)|updated:|^\s*$|^close)",
    re.IGNORECASE,
)
_TRACK_LINE = re.compile(r"^(.+?),\s+by\s+(.+)$", re.IGNORECASE)


def fetch_tracks() -> list[Track]:
    """Scrape FM-1 and return current + recent tracks."""
    try:
        resp = requests.get(FM1_URL, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning(f"Page fetch failed: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    raw_lines = [ln.strip() for ln in soup.get_text("\n").splitlines() if ln.strip()]

    tracks: list[Track] = []
    for line in raw_lines:
        if _SKIP.search(line):
            continue
        m = _TRACK_LINE.match(line)
        if m:
            tracks.append(Track(title=m.group(1).strip(), artist=m.group(2).strip()))
    return tracks


# ── YouTube auth ──────────────────────────────────────────────────────────────
def get_youtube_client():
    """Return an authenticated YouTube API client, using cached token if available."""
    creds = None

    if TOKEN_FILE.exists():
        creds = pickle.loads(TOKEN_FILE.read_bytes())

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=8888, open_browser=True)
        TOKEN_FILE.write_bytes(pickle.dumps(creds))

    return build("youtube", "v3", credentials=creds)


# ── YouTube helpers ───────────────────────────────────────────────────────────
def get_or_create_playlist(yt, name: str) -> str:
    """Return playlist ID, creating it if it doesn't exist."""
    response = yt.playlists().list(part="snippet", mine=True, maxResults=50).execute()
    for item in response.get("items", []):
        if item["snippet"]["title"] == name:
            pl_id = item["id"]
            log.info(f"Using existing playlist '{name}'  ({pl_id})")
            return pl_id

    result = yt.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": name, "description": "Live mirror of Muzak FM-1 — auto-synced"},
            "status":  {"privacyStatus": "public"},
        },
    ).execute()
    pl_id = result["id"]
    log.info(f"Created playlist '{name}'  ({pl_id})")
    return pl_id


def get_playlist_video_ids(yt, playlist_id: str) -> set[str]:
    """Return the set of video IDs already in the playlist."""
    ids: set[str] = set()
    page_token = None
    while True:
        try:
            resp = yt.playlistItems().list(
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            ).execute()
        except Exception as exc:
            if _is_quota_error(exc):
                raise  # let caller handle quota errors — don't silently return partial results
            break  # new playlist not yet visible — treat as empty
        for item in resp.get("items", []):
            ids.add(item["contentDetails"]["videoId"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def search_youtube(yt, track: Track, cache: dict) -> Optional[str]:
    """Search YouTube for a track, using cache to avoid repeat API calls."""
    cache_key = track.title.lower().strip()
    if cache_key in cache:
        log.info(f"  (cached) {track}  →  {cache[cache_key]}")
        return cache[cache_key]

    query = f"{track.artist} - {track.title}"
    resp = yt.search().list(
        part="snippet",
        q=query,
        type="video",
        videoCategoryId="10",   # Music category
        maxResults=1,
    ).execute()
    items = resp.get("items", [])
    if items:
        vid_id = items[0]["id"]["videoId"]
        vid_title = items[0]["snippet"]["title"]
        log.info(f"  + {track}  →  '{vid_title}'")
        cache[cache_key] = vid_id
        return vid_id
    log.warning(f"  ✗ Not found on YouTube: {track}")
    return None


def add_to_playlist(yt, playlist_id: str, video_id: str) -> None:
    import time as _time
    for attempt in range(3):
        try:
            yt.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            return
        except Exception as exc:
            if attempt < 2:
                _time.sleep(2)
            else:
                log.warning(f"  Skipping video {video_id} after 3 attempts: {exc}")


def bump_to_top(yt, playlist_id: str, video_id: str) -> None:
    """Delete a track from the playlist and re-add it so it gets the newest timestamp."""
    import time as _time
    try:
        # Find the playlist item ID for this video
        resp = yt.playlistItems().list(
            part="id,contentDetails",
            playlistId=playlist_id,
            videoId=video_id,
            maxResults=1,
        ).execute()
        items = resp.get("items", [])
        if items:
            yt.playlistItems().delete(id=items[0]["id"]).execute()
            _time.sleep(1)
        add_to_playlist(yt, playlist_id, video_id)
    except Exception as exc:
        log.warning(f"  Could not bump track to top: {exc}")


POLL_INTERVAL = 30  # seconds between checks

PLAYLIST_DESCRIPTION_TEMPLATE = (
    "Live mirror of Muzak FM-1 — auto-synced daily | Updated: {date}\n\n"
    "The soft rock and pop you hear while shopping at Home Depot, CVS, "
    "T.J. Maxx, Whole Foods, Napili Market, and thousands of other retail "
    "locations — streamed live and added here automatically."
)

_QUOTA_KEYWORDS = ("quotaExceeded", "rateLimitExceeded", "403", "429")

def _is_quota_error(exc: Exception) -> bool:
    s = str(exc)
    return any(k in s for k in _QUOTA_KEYWORDS)

# ── Main loop ─────────────────────────────────────────────────────────────────
def main(oneshot: bool = False) -> None:
    import time

    log.info("Connecting to YouTube…")
    yt = get_youtube_client()
    try:
        pl_id = get_or_create_playlist(yt, PLAYLIST_NAME)
    except Exception as exc:
        if _is_quota_error(exc):
            log.warning("Quota exhausted at startup — skipping this run.")
            return
        raise

    playlist_url = f"https://www.youtube.com/playlist?list={pl_id}"
    log.info(f"Playlist: {playlist_url}")
    if not oneshot:
        webbrowser.open(playlist_url)

    song_cache: dict = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    log.info(f"Song cache loaded: {len(song_cache)} entries")

    # Load playlist IDs from cache to avoid fetching from YouTube every run.
    # On first run (cache empty), fall back to the API once to bootstrap.
    cached_playlist_ids = song_cache.get("_playlist_ids")
    if cached_playlist_ids is not None:
        in_playlist: set[str] = set(cached_playlist_ids)
        log.info(f"Playlist IDs loaded from cache: {len(in_playlist)} videos")
    else:
        log.info("Fetching playlist contents from YouTube (first run)…")
        try:
            in_playlist = get_playlist_video_ids(yt, pl_id)
        except Exception as exc:
            if _is_quota_error(exc):
                log.warning("Quota exhausted fetching playlist — skipping this run.")
                return
            raise
        song_cache["_playlist_ids"] = list(in_playlist)
        log.info(f"Playlist bootstrapped: {len(in_playlist)} videos")

    # Update the playlist description once per day with today's date.
    today_str = _date.today().strftime("%B %d, %Y")
    if song_cache.get("_last_description_date") != today_str:
        new_desc = PLAYLIST_DESCRIPTION_TEMPLATE.format(date=today_str)
        try:
            yt.playlists().update(
                part="snippet",
                body={"id": pl_id, "snippet": {"title": PLAYLIST_NAME, "description": new_desc}},
            ).execute()
            song_cache["_last_description_date"] = today_str
            log.info(f"Playlist description updated for {today_str}.")
        except Exception as exc:
            if _is_quota_error(exc):
                log.warning("Quota exhausted updating description — will retry tomorrow.")
            else:
                log.warning(f"Could not update description: {exc}")

    # Persistent title-based dedup: survives across runs so the same song
    # is never added twice even if the video ID or cache changes.
    added_titles: set[str] = set(song_cache.get("_added_titles", []))
    log.info(f"Added-titles cache: {len(added_titles)} titles")

    while True:
        log.info("── Polling FM-1 ────────────────────────────────────")
        try:
            tracks = fetch_tracks()

            if not tracks:
                log.warning("No tracks retrieved — retrying next cycle.")
            else:
                now_playing = tracks[0]
                log.info(f"Now playing: {now_playing}")

                added = 0

                for track in tracks:
                    title_key = track.title.lower().strip()
                    if title_key in added_titles:
                        log.info(f"  (already added) {track}")
                        continue
                    vid_id = search_youtube(yt, track, song_cache)
                    if vid_id and vid_id not in in_playlist:
                        add_to_playlist(yt, pl_id, vid_id)
                        in_playlist.add(vid_id)
                        added_titles.add(title_key)
                        song_cache["_playlist_ids"] = list(in_playlist)
                        song_cache["_added_titles"] = list(added_titles)
                        added += 1
                    elif vid_id:
                        # video already in playlist — record title so we skip next time
                        added_titles.add(title_key)
                        song_cache["_added_titles"] = list(added_titles)

                if added:
                    log.info(f"Added {added} new track(s).")
                else:
                    log.info("No new tracks since last check.")

        except Exception as exc:
            log.warning(f"Error during sync: {exc}")
            # Exit cleanly on quota exhaustion so the run shows green
            if _is_quota_error(exc):
                log.warning("Quota exhausted — skipping until next reset.")
                CACHE_FILE.write_text(json.dumps(song_cache, indent=2, ensure_ascii=False))
                return

        CACHE_FILE.write_text(json.dumps(song_cache, indent=2, ensure_ascii=False))

        if oneshot:
            log.info(f"One-shot run complete. Cache now has {len(song_cache)} entries.")
            return
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import sys
    oneshot = "--oneshot" in sys.argv
    main(oneshot=oneshot)
