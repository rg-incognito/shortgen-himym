"""YouTube Data API v3 — upload a vertical short as a scheduled private post."""
import json
import os
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

_SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'yt_token.json')


def _build_svc():
    """Load credentials from yt_token.json (written from YT_TOKEN_JSON secret at runtime)."""
    if not os.path.exists(_TOKEN_FILE):
        raise FileNotFoundError("yt_token.json not found — set YT_TOKEN_JSON secret")
    creds = Credentials.from_authorized_user_file(_TOKEN_FILE, _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(_TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('youtube', 'v3', credentials=creds)


def upload_scheduled(video_path, title, description, tags_str, publish_at_iso):
    """
    Upload a video to YouTube as a private scheduled post.

    publish_at_iso — ISO 8601 UTC string, e.g. '2026-05-23T09:00:00Z'
    Returns the YouTube video ID.
    """
    svc  = _build_svc()
    tags = [t.strip() for t in tags_str.split(',') if t.strip()]

    body = {
        'snippet': {
            'title':           title[:100],
            'description':     description,
            'tags':            tags,
            'categoryId':      '24',   # Entertainment
            'defaultLanguage': 'en',
        },
        'status': {
            'privacyStatus':          'private',
            'publishAt':              publish_at_iso,
            'selfDeclaredMadeForKids': False,
            'madeForKids':             False,
        },
    }

    media = MediaFileUpload(
        video_path, mimetype='video/mp4',
        resumable=True, chunksize=5 * 1024 * 1024,
    )
    req = svc.videos().insert(part='snippet,status', body=body, media_body=media)

    response = None
    while response is None:
        status, response = req.next_chunk()
        if status:
            print(f"    YT upload {int(status.progress() * 100)}%")

    return response['id']
