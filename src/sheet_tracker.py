import datetime
from googleapiclient.discovery import build
from google.oauth2 import service_account

_SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
_HEADERS = ['episode_name', 'run_number', 'clip_title',
            'start_seconds', 'end_seconds', 'score', 'reason', 'created_at']
_RANGE = 'A:H'

_POSTING_SHEET    = 'PostingTracker'
_POSTING_HEADERS  = [
    'episode_name', 'run_number', 'storyline_title', 'score',
    'yt_title', 'description', 'tags', 'pinned_comment',
    'status', 'scheduled_at', 'yt_url', 'created_at',
]
_PUBLISH_DELAY_MIN = 10  # publish this many minutes after upload


class SheetTracker:
    def __init__(self, credentials_info, spreadsheet_id):
        creds = service_account.Credentials.from_service_account_info(
            credentials_info, scopes=_SCOPES
        )
        self._svc = build('sheets', 'v4', credentials=creds)
        self._sid = spreadsheet_id
        self._ensure_headers()

    def _ensure_headers(self):
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=self._sid, range='A1:H1'
        ).execute(num_retries=5)
        if not res.get('values'):
            self._svc.spreadsheets().values().update(
                spreadsheetId=self._sid,
                range='A1',
                valueInputOption='RAW',
                body={'values': [_HEADERS]}
            ).execute(num_retries=5)

    def _rows(self):
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=self._sid, range=_RANGE
        ).execute(num_retries=5)
        rows = res.get('values', [])
        return rows[1:] if len(rows) > 1 else []

    def get_run_count(self, episode_name):
        runs = {r[1] for r in self._rows() if r and r[0] == episode_name}
        return len(runs)

    def get_used_segments(self, episode_name):
        segs = []
        for r in self._rows():
            if r and r[0] == episode_name and len(r) >= 5:
                try:
                    segs.append((float(r[3]), float(r[4])))
                except (ValueError, IndexError):
                    pass
        return segs

    def _ensure_posting_sheet(self):
        meta   = self._svc.spreadsheets().get(spreadsheetId=self._sid).execute(num_retries=5)
        titles = [s['properties']['title'] for s in meta['sheets']]
        if _POSTING_SHEET not in titles:
            self._svc.spreadsheets().batchUpdate(
                spreadsheetId=self._sid,
                body={'requests': [{'addSheet': {'properties': {'title': _POSTING_SHEET}}}]},
            ).execute(num_retries=5)
            self._svc.spreadsheets().values().update(
                spreadsheetId=self._sid,
                range=f'{_POSTING_SHEET}!A1',
                valueInputOption='RAW',
                body={'values': [_POSTING_HEADERS]},
            ).execute(num_retries=5)

    def log_posting_metadata(self, episode_name, run_number, story, yt_meta):
        self._ensure_posting_sheet()
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        row = [
            episode_name,
            str(run_number),
            story['storyline_title'],
            str(story['score']),
            yt_meta.get('title', ''),
            yt_meta.get('description', ''),
            yt_meta.get('tags', ''),
            yt_meta.get('pinned_comment', ''),
            'Pending',
            '',   # upload_date — fill in manually after posting
            '',   # yt_url     — fill in manually after posting
            now,
        ]
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._sid,
            range=f'{_POSTING_SHEET}!A:L',
            valueInputOption='RAW',
            body={'values': [row]},
        ).execute(num_retries=5)

    def get_next_publish_slot(self):
        """Return a publish time 10 minutes from now — video goes live shortly after upload."""
        slot = datetime.datetime.utcnow() + datetime.timedelta(minutes=_PUBLISH_DELAY_MIN)
        return slot.strftime('%Y-%m-%dT%H:%M:%SZ')

    def update_yt_url(self, episode_name, run_number, storyline_title, yt_video_id, scheduled_at):
        """Write YouTube video ID and scheduled_at back into the PostingTracker row."""
        self._ensure_posting_sheet()
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=self._sid,
            range=f'{_POSTING_SHEET}!A:L',
        ).execute(num_retries=5)
        rows = res.get('values', [])
        for i, row in enumerate(rows):
            if (len(row) >= 3 and
                    row[0] == episode_name and
                    row[1] == str(run_number) and
                    row[2] == storyline_title):
                row_num = i + 1
                self._svc.spreadsheets().values().update(
                    spreadsheetId=self._sid,
                    range=f'{_POSTING_SHEET}!I{row_num}:K{row_num}',
                    valueInputOption='RAW',
                    body={'values': [['Scheduled', scheduled_at, f'https://youtu.be/{yt_video_id}']]},
                ).execute(num_retries=5)
                return

    def log_clips(self, episode_name, run_number, clips):
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
        rows = [
            [episode_name, str(run_number), c['title'],
             str(c['start_seconds']), str(c['end_seconds']),
             str(c['score']), c['reason'], now]
            for c in clips
        ]
        self._svc.spreadsheets().values().append(
            spreadsheetId=self._sid,
            range=_RANGE,
            valueInputOption='RAW',
            body={'values': rows}
        ).execute(num_retries=5)
