#!/usr/bin/env python3
"""
One-time cleanup: remove duplicate videos from FM-1 Live Radio playlist.
Keeps the FIRST occurrence of each video, deletes all later copies.
Run once from your local machine: python cleanup_duplicates.py
"""
import pickle
import time
from pathlib import Path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_FILE  = Path(__file__).parent / ".youtube_token.pickle"
PLAYLIST_ID = "PLYyAqltThpxcymrDPruUW-ROCraKotFqn"


def get_youtube_client():
    creds = pickle.loads(TOKEN_FILE.read_bytes())
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        TOKEN_FILE.write_bytes(pickle.dumps(creds))
    return build("youtube", "v3", credentials=creds)


def fetch_all_items(yt):
    items = []
    page_token = None
    while True:
        resp = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=PLAYLIST_ID,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            items.append({
                "item_id": item["id"],
                "video_id": item["contentDetails"]["videoId"],
                "title":    item["snippet"]["title"],
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return items


def main():
    yt = get_youtube_client()

    print("Fetching all playlist items…")
    items = fetch_all_items(yt)
    print(f"Total items in playlist: {len(items)}\n")

    seen_video_ids: set[str] = set()
    to_delete = []

    for item in items:
        if item["video_id"] in seen_video_ids:
            to_delete.append(item)
        else:
            seen_video_ids.add(item["video_id"])

    if not to_delete:
        print("No duplicates found — playlist is clean!")
        return

    print(f"Found {len(to_delete)} duplicate(s) to remove:\n")
    for item in to_delete:
        print(f"  • {item['title']}")

    print()
    confirm = input(f"Delete these {len(to_delete)} entries? Type YES to confirm: ")
    if confirm.strip() != "YES":
        print("Aborted — nothing changed.")
        return

    for i, item in enumerate(to_delete, 1):
        print(f"  [{i}/{len(to_delete)}] Removing: {item['title']}")
        yt.playlistItems().delete(id=item["item_id"]).execute()
        time.sleep(0.5)

    print(f"\nDone! Removed {len(to_delete)} duplicate(s).")


if __name__ == "__main__":
    main()
