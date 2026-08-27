"""YouTube Data API v3 — upload a vertical short as a scheduled private post."""
import json
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# youtube scope is a superset of youtube.upload and also covers playlist management.
# NOTE: if the stored token only has youtube.upload, re-run setup_yt_oauth.py locally
# and update the YT_TOKEN_JSON secret with the new token.
_SCOPES = ['https://www.googleapis.com/auth/youtube']
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', 'yt_token.json')


def _build_svc():
    if not os.path.exists(_TOKEN_FILE):
        raise FileNotFoundError("yt_token.json not found — set YT_TOKEN_JSON secret")
    raw = open(_TOKEN_FILE, encoding='utf-8-sig').read()
    info = json.loads(raw)
    creds = Credentials.from_authorized_user_info(info, _SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(_TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())
    return build('youtube', 'v3', credentials=creds)


def _get_or_create_playlist(svc, title):
    """Return playlist ID for the named playlist on the channel, creating it if absent."""
    resp = svc.playlists().list(part='snippet', mine=True, maxResults=50).execute()
    for item in resp.get('items', []):
        if item['snippet']['title'] == title:
            return item['id']
    created = svc.playlists().insert(
        part='snippet,status',
        body={
            'snippet': {'title': title, 'defaultLanguage': 'en'},
            'status':  {'privacyStatus': 'public'},
        }
    ).execute()
    return created['id']


def add_to_playlist(video_id, playlist_title):
    """Add video_id to the named playlist, creating the playlist if it doesn't exist."""
    svc = _build_svc()
    playlist_id = _get_or_create_playlist(svc, playlist_title)
    svc.playlistItems().insert(
        part='snippet',
        body={
            'snippet': {
                'playlistId': playlist_id,
                'resourceId': {'kind': 'youtube#video', 'videoId': video_id},
            }
        }
    ).execute()
    return playlist_id


def set_thumbnail(video_id, image_path):
    """
    Set a video's thumbnail to a specific local image (JPEG/PNG, <2MB).
    Requires the channel to be verified for custom thumbnails — raises on
    failure so the caller can decide whether that's fatal (it shouldn't be;
    the video still uploads and publishes fine without a custom thumbnail).
    """
    svc = _build_svc()
    media = MediaFileUpload(image_path, mimetype='image/jpeg')
    svc.thumbnails().set(videoId=video_id, media_body=media).execute()


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
