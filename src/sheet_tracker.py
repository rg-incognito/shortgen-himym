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
# Fixed publish slots in UTC: 00:00 and 02:00 (7 PM / 9 PM US Eastern EST/UTC-5 —
# North America evening prime time). We snap to the nearest upcoming slot
# instead of publishing run-finish+buffer, because GitHub Actions' schedule
# queue delays the 02:00 UTC trigger by ~2-3 hours on a regular basis (the
# 00:00 trigger slips ~7-11h) — left unsnapped, that run's video was
# landing around midnight ET instead of 9 PM ET.
# NOTE: revert to [(23, 0), (1, 0)] when US clocks spring forward to EDT (Mar 2027).
_PUBLISH_SLOTS_UTC = [(0, 0), (2, 0)]


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

    def _booked_slots(self):
        """scheduled_at values already written to PostingTracker (column J)."""
        self._ensure_posting_sheet()
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=self._sid,
            range=f'{_POSTING_SHEET}!J:J',
        ).execute(num_retries=5)
        return {row[0].strip() for row in res.get('values', []) if row and row[0].strip()}

    def get_next_publish_slot(self):
        """Return the next free fixed publish slot (00:00 or 02:00 UTC) at least 5 minutes away.

        Slots already booked by an earlier run are skipped. The delayed 02:00 trigger
        usually finishes after 02:00 has passed, so without this both daily runs
        snapped onto the same 00:00 slot and the two shorts split each other's reach.
        """
        now = datetime.datetime.utcnow()
        booked = self._booked_slots()
        for day_offset in range(14):
            candidates = []
            for hour, minute in _PUBLISH_SLOTS_UTC:
                t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                t += datetime.timedelta(days=day_offset)
                if t > now + datetime.timedelta(minutes=5):
                    candidates.append(t)
            for t in sorted(candidates):
                iso = t.strftime('%Y-%m-%dT%H:%M:%SZ')
                if iso not in booked:
                    return iso
        raise RuntimeError('No free publish slot in the next 14 days')

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

    def get_due_comments(self, max_age_hours=48):
        """Shorts that have gone public but haven't had their comment prompt posted yet.

        Returns [(row_num, video_id, comment_text)]. Only looks back max_age_hours so
        the first run after this was added doesn't comment on the whole back catalogue
        (commentThreads.insert costs 50 quota units each).
        """
        self._ensure_posting_sheet()
        res = self._svc.spreadsheets().values().get(
            spreadsheetId=self._sid,
            range=f'{_POSTING_SHEET}!A:L',
        ).execute(num_retries=5)
        now = datetime.datetime.utcnow()
        due = []
        for i, row in enumerate(res.get('values', [])[1:], start=2):
            row = row + [''] * (12 - len(row))
            comment, status, scheduled_at, yt_url = row[7].strip(), row[8], row[9], row[10]
            if status != 'Scheduled' or not comment or 'youtu.be/' not in yt_url:
                continue
            try:
                t = datetime.datetime.strptime(scheduled_at, '%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                continue
            if t <= now <= t + datetime.timedelta(hours=max_age_hours):
                due.append((i, yt_url.rsplit('/', 1)[-1], comment))
        return due

    def mark_commented(self, row_num):
        self._svc.spreadsheets().values().update(
            spreadsheetId=self._sid,
            range=f'{_POSTING_SHEET}!I{row_num}',
            valueInputOption='RAW',
            body={'values': [['Commented']]},
        ).execute(num_retries=5)

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
