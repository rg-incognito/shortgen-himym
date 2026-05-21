import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google.oauth2 import credentials as oauth2_credentials


def _svc():
    creds = oauth2_credentials.Credentials(
        token=None,
        refresh_token=os.environ['GOOGLE_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GOOGLE_CLIENT_ID'],
        client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    )
    return build('drive', 'v3', credentials=creds)


def list_videos(folder_id, credentials_info):
    res = _svc().files().list(
        q=f"'{folder_id}' in parents and mimeType contains 'video/' and trashed=false",
        fields='files(id, name)',
        orderBy='name',
    ).execute()
    return [(f['id'], f['name']) for f in res.get('files', [])]


def pick_video(folder_id, credentials_info, tracker, max_runs=3):
    """
    Return (file_id, episode_name) for the next video to process.
    Prefers videos closest to max_runs (complete partial episodes first).
    Skips videos already at max_runs (should have been archived).
    """
    videos = list_videos(folder_id, credentials_info)
    if not videos:
        return None, None

    buckets = {}
    for file_id, name in videos:
        episode = os.path.splitext(name)[0]
        count = tracker.get_run_count(episode)
        if count < max_runs:
            buckets.setdefault(count, []).append((file_id, episode))

    for count in sorted(buckets.keys(), reverse=True):
        if buckets[count]:
            return buckets[count][0]
    return None, None


def _get_or_create_folder(name, parent_id, svc):
    res = svc.files().list(
        q=(f"'{parent_id}' in parents and name='{name}' "
           f"and mimeType='application/vnd.google-apps.folder' and trashed=false"),
        fields='files(id)',
    ).execute()
    files = res.get('files', [])
    if files:
        return files[0]['id']
    meta = {'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_id]}
    return svc.files().create(body=meta, fields='id').execute()['id']


def move_to_used_folder(file_id, shorts_folder_id):
    """Move a file from shorts/ into shorts/used/ subfolder."""
    svc = _svc()
    used_id = _get_or_create_folder('used', shorts_folder_id, svc)
    svc.files().update(
        fileId=file_id,
        addParents=used_id,
        removeParents=shorts_folder_id,
        fields='id, parents',
    ).execute(num_retries=5)


def move_to_archive(file_id, archive_folder_id, videos_folder_id, credentials_info):
    _svc().files().update(
        fileId=file_id,
        addParents=archive_folder_id,
        removeParents=videos_folder_id,
        fields='id, parents',
    ).execute(num_retries=5)


def download_video(file_id, output_path, credentials_info):
    request = _svc().files().get_media(fileId=file_id)
    with open(output_path, 'wb') as f:
        dl = MediaIoBaseDownload(f, request, chunksize=10 * 1024 * 1024)
        done = False
        while not done:
            status, done = dl.next_chunk(num_retries=5)
            print(f"  Download {int(status.progress() * 100)}%")


def upload_shorts(file_paths, folder_id, credentials_info):
    """Upload files to Drive folder. Returns list of (name, file_id)."""
    svc = _svc()
    uploaded = []
    for path in file_paths:
        name = os.path.basename(path)
        metadata = {'name': name, 'parents': [folder_id]}
        media = MediaFileUpload(path, mimetype='video/mp4', resumable=True)
        result = svc.files().create(
            body=metadata, media_body=media, fields='id',
        ).execute()
        file_id = result.get('id')
        print(f"  Uploaded {name} → {file_id}")
        uploaded.append((name, file_id))
    return uploaded
