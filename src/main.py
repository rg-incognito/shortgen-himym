import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from drive_client import download_video, upload_shorts, pick_video, move_to_archive, move_to_used_folder
from transcriber import transcribe_video
from analyzer import analyze_transcript, generate_yt_metadata
from clipper import create_story_short
from sheet_tracker import SheetTracker

VIDEOS_FOLDER_ID  = os.environ.get('VIDEOS_FOLDER_ID',  '1bIFaNpfBy1Bp9R14T22EV-hMsYYrLeTS')
SHORTS_FOLDER_ID  = os.environ.get('SHORTS_FOLDER_ID',  '1kzFXWZQu8QQVtZKeAVvSgHcLaRFfK6tg')
ARCHIVE_FOLDER_ID = os.environ.get('ARCHIVE_FOLDER_ID', '1nHZCaWO_KvkV52TekkF8ecC5JtIlXqJj')
MAX_RUNS = 4


def main():
    service_account_info = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'].lstrip('﻿'))
    gemini_api_key        = os.environ['GEMINI_API_KEY']
    spreadsheet_id        = os.environ['SPREADSHEET_ID'].strip()
    whisper_model         = os.environ.get('WHISPER_MODEL', 'small')
    hf_token              = os.environ.get('HF_TOKEN', '').strip()

    video_file_id = os.environ.get('VIDEO_FILE_ID', '').strip()
    episode_name  = os.environ.get('EPISODE_NAME', '').strip()

    tracker = SheetTracker(service_account_info, spreadsheet_id)

    diarization_pipeline = None
    if hf_token:
        try:
            from reframer import load_diarization_pipeline
            diarization_pipeline = load_diarization_pipeline(hf_token)
            print('  Diarization pipeline loaded (speaker-aware tracking active)')
        except Exception as e:
            print(f'  Diarization pipeline unavailable: {e} — using face-only tracking')

    # Auto-pick if no file ID provided
    if not video_file_id:
        print("[0/5] Auto-picking video from videos/ folder...")
        video_file_id, episode_name = pick_video(VIDEOS_FOLDER_ID, service_account_info, tracker, max_runs=MAX_RUNS)
        if not video_file_id:
            print("No unprocessed videos in videos/ folder. Upload one and re-run.")
            sys.exit(0)
        print(f"      Picked: {episode_name}")
    elif not episode_name:
        episode_name = 'episode'

    episode_name = episode_name.replace(' ', '_')

    prior_runs       = tracker.get_run_count(episode_name)
    current_run      = prior_runs + 1
    used_segments    = tracker.get_used_segments(episode_name)
    used_storylines  = tracker.get_used_storylines(episode_name)

    print(f"      Episode : {episode_name}")
    print(f"      Run     : {current_run} of {MAX_RUNS}")
    print(f"      Avoiding: {len(used_segments)} previously used segment(s)")

    work_dir = Path(tempfile.mkdtemp(prefix='shortgen_'))
    try:
        video_path = work_dir / f"{episode_name}.mp4"

        print("[1/5] Downloading video...")
        download_video(video_file_id, str(video_path), service_account_info)
        print(f"      {video_path.stat().st_size / 1e6:.1f} MB")

        print(f"[2/5] Transcribing with whisper-{whisper_model}...")
        segments, all_words = transcribe_video(str(video_path), model_size=whisper_model)
        print(f"      {len(segments)} segments, {len(all_words)} words transcribed")

        print("[3/5] Analyzing for best story arc (Gemini)...")
        story = analyze_transcript(segments, gemini_api_key, used_segments=used_segments, used_storylines=used_storylines)
        total_sec = story.get('_total_seconds', 0)
        print(f"      Story: [{story['score']}/10] {story['storyline_title']}  (~{total_sec:.0f}s total)")
        print(f"      Summary: {story['storyline_summary']}")
        print(f"      {len(story['clips'])} clips:")
        for c in story['clips']:
            dur = c['end_seconds'] - c['start_seconds']
            print(f"        [{c['label']}] {c['start_seconds']:.0f}s-{c['end_seconds']:.0f}s ({dur:.0f}s) — {c['description']}")

        print("      Generating YouTube metadata...")
        yt_meta = generate_yt_metadata(story, episode_name, gemini_api_key)
        if yt_meta:
            print(f"      YT title: {yt_meta.get('title', '')}")

        # Extend each clip end by a tail pad so sentence tone finishes naturally.
        _dur_out = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)],
            capture_output=True, text=True,
        )
        _src_dur = float(_dur_out.stdout.strip()) if _dur_out.stdout.strip() else float('inf')
        TAIL_PAD = 0.5
        for c in story['clips']:
            c['end_seconds'] = min(c['end_seconds'] + TAIL_PAD, _src_dur - 0.05)

        shorts_dir = work_dir / 'shorts'
        shorts_dir.mkdir()
        print("[4/5] Creating story compilation...")
        short_path = create_story_short(str(video_path), story, str(shorts_dir),
                                        episode_name, pipeline=diarization_pipeline,
                                        all_words=all_words)

        print("[5/5] Uploading to Drive...")
        uploaded = upload_shorts([short_path], SHORTS_FOLDER_ID, service_account_info)
        drive_file_id = uploaded[0][1] if uploaded else None

        _SERIES_PLAYLIST = {
            'barneys_schemes':    "Barney's Schemes",
            'teds_disasters':     "Ted's Disasters",
            'marshall_and_lily':  'Marshall & Lily',
            'robins_quirks':      'Robin Being Robin',
            'slap_bet':           'Slap Bet',
            'legendary_moments':  'Legendary Moments',
            'gang_at_maclarens':  'The Gang',
        }

        # Upload to YouTube as a scheduled post (requires YT_TOKEN_JSON secret)
        if not yt_meta:
            ep_upper = episode_name.replace('_', ' ').upper()
            yt_meta = {
                'title':          f"{story['storyline_title'].replace('_', ' ').title()} | HIMYM",
                'description':    f"{story['storyline_summary']}\n\nHow I Met Your Mother | {ep_upper}",
                'tags':           'HIMYM, How I Met Your Mother, funny moments, sitcom, CBS',
                'pinned_comment': '',
            }
            print("      YT metadata fallback used (Gemini unavailable)")
        yt_video_id = None
        from youtube_client import upload_scheduled, add_to_playlist
        publish_at = tracker.get_next_publish_slot()
        print(f"[5b] Scheduling on YouTube -> {publish_at}...")
        yt_video_id = upload_scheduled(
            short_path,
            yt_meta['title'],
            yt_meta['description'],
            yt_meta['tags'],
            publish_at,
        )
        print(f"      https://youtu.be/{yt_video_id}")
        tracker.update_yt_url(episode_name, current_run,
                              story['storyline_title'], yt_video_id, publish_at)

        series_tag = story.get('series_tag', '')
        playlist_title = _SERIES_PLAYLIST.get(series_tag)
        if playlist_title:
            try:
                add_to_playlist(yt_video_id, playlist_title)
                print(f"      Added to playlist: {playlist_title}")
            except Exception as pe:
                print(f"      Playlist add skipped: {pe}")

        # Move the uploaded short to shorts/used/
        if drive_file_id:
            try:
                move_to_used_folder(drive_file_id, SHORTS_FOLDER_ID)
                print("      Moved to shorts/used/")
            except Exception as e:
                print(f"      Move to used/ skipped: {e}")

        # Log each clip segment individually so future runs avoid them all
        clips_for_log = [
            {
                'title':         f"{story['storyline_title']}_p{i + 1}",
                'start_seconds': c['start_seconds'],
                'end_seconds':   c['end_seconds'],
                'score':         story['score'],
                'reason':        c['description'],
            }
            for i, c in enumerate(story['clips'])
        ]
        tracker.log_clips(episode_name, current_run, clips_for_log)
        if yt_meta:
            tracker.log_posting_metadata(episode_name, current_run, story, yt_meta)
        print(f"      Logged run {current_run} to tracker sheet")

        if current_run >= MAX_RUNS:
            print(f"      Run {current_run} = max runs reached — archiving video...")
            move_to_archive(video_file_id, ARCHIVE_FOLDER_ID, VIDEOS_FOLDER_ID, service_account_info)
            print(f"      Moved to archive/")

        print(f"\nDone! 1 story short in Drive → series_shorts/shorts/")

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
