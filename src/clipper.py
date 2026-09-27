import os
import subprocess
import tempfile

_SILENCE_GAP_THRESHOLD = 0.6   # seconds of no words = a cuttable internal pause
_SILENCE_PAD           = 0.15  # seconds of breathing room kept on each side of a cut
_MIN_SEGMENT_LEN        = 0.2  # drop degenerate slivers shorter than this


def _split_on_silence(clip_start, clip_end, all_words):
    """
    Split one clip's [start, end] episode-time window into sub-ranges with
    internal dead air removed, based on gaps between consecutive Whisper word
    timestamps that fall inside the window. Never trims leading/trailing time
    (a wordless reaction shot at the start/end of a clip is intentional, not
    dead air) — only pauses strictly BETWEEN two spoken words are cut.
    Returns the original [(clip_start, clip_end)] unchanged if there are
    fewer than 2 words in range (nothing to safely detect a gap between).
    """
    words_in_range = sorted(
        (w for w in all_words if w['start'] >= clip_start and w['end'] <= clip_end),
        key=lambda w: w['start']
    )
    if len(words_in_range) < 2:
        return [(clip_start, clip_end)]

    ranges = []
    seg_start = clip_start
    for i in range(len(words_in_range) - 1):
        gap = words_in_range[i + 1]['start'] - words_in_range[i]['end']
        if gap > _SILENCE_GAP_THRESHOLD:
            seg_end = min(words_in_range[i]['end'] + _SILENCE_PAD, clip_end)
            ranges.append((seg_start, seg_end))
            seg_start = max(words_in_range[i + 1]['start'] - _SILENCE_PAD, seg_end)
    ranges.append((seg_start, clip_end))

    ranges = [(s, e) for s, e in ranges if e - s > _MIN_SEGMENT_LEN]
    return ranges if ranges else [(clip_start, clip_end)]


def create_story_short(video_path, story, output_dir, episode_name,
                        pipeline=None, all_words=None):
    """
    Cuts every clip in a story arc (splitting out internal dead-air pauses
    first), reframes each piece to 9:16, concatenates into one compiled
    video, burns viral-style captions + the persistent hook banner if word
    timestamps are provided, then mixes in a background music bed.
    """
    from reframer import reframe_clip
    from captioner import burn_captions, mix_background_music

    clips = story['clips']
    title = story['storyline_title']
    score = story['score']

    parts_dir = os.path.join(output_dir, '_parts')
    os.makedirs(parts_dir, exist_ok=True)

    part_paths = []
    rendered_ranges = []   # flattened (start,end) actually present in the merged video, in order
    try:
        part_idx = 0
        for i, clip in enumerate(clips, 1):
            sub_ranges = _split_on_silence(clip['start_seconds'], clip['end_seconds'], all_words or [])
            trimmed = len(sub_ranges) - 1
            print(f"  Part {i}/{len(clips)}: [{clip['label']}] "
                  f"{clip['start_seconds']:.1f}s – {clip['end_seconds']:.1f}s" +
                  (f" ({trimmed} internal pause(s) trimmed)" if trimmed else ""))
            for sub_start, sub_end in sub_ranges:
                part_idx += 1
                part_path = os.path.join(parts_dir, f"part_{part_idx:02d}.mp4")
                reframe_clip(video_path, sub_start, sub_end, part_path, pipeline=pipeline)
                part_paths.append(part_path)
                rendered_ranges.append({'start_seconds': sub_start, 'end_seconds': sub_end})

        merged_path = os.path.join(output_dir, '_merged.mp4')
        print(f"  Merging {len(part_paths)} parts...")
        _merge_clips(part_paths, merged_path)

        captioned_path = os.path.join(output_dir, '_captioned.mp4')
        if all_words:
            print("  Burning captions...")
            burn_captions(merged_path, captioned_path, all_words, rendered_ranges,
                          hook_text=story.get('hook_text'), hook_emoji=story.get('hook_emoji'))
            os.unlink(merged_path)
        else:
            os.rename(merged_path, captioned_path)

        out_path = os.path.join(output_dir, f"{episode_name}_{title}_s{score}.mp4")
        story['music_credit'] = mix_background_music(captioned_path, out_path,
                                                     mood=story.get('music_mood') or 'upbeat')
        os.unlink(captioned_path)

        return out_path

    finally:
        for p in part_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        try:
            os.rmdir(parts_dir)
        except OSError:
            pass


def extract_thumbnail_frame(video_path, out_path, timestamp=0.6):
    """
    Grab a single JPEG frame from the finished short at `timestamp` (seconds).
    The hook banner is now persistent for the whole video, so any timestamp
    works — used as the video's explicit thumbnail so YouTube's grid/search
    surfaces don't fall back to an unpredictable auto-picked frame.
    """
    subprocess.run([
        'ffmpeg', '-y',
        '-ss', str(timestamp), '-i', video_path,
        '-frames:v', '1', '-q:v', '2',
        out_path,
    ], check=True, capture_output=True)


def _merge_clips(clip_paths, output_path):
    """Concatenate same-format clips using ffmpeg concat demuxer (no re-encode)."""
    list_file = tempfile.mktemp(suffix='.txt')
    try:
        with open(list_file, 'w') as f:
            for p in clip_paths:
                # escape single quotes in path for ffmpeg concat list
                safe = p.replace("'", "'\\''")
                f.write(f"file '{safe}'\n")
        subprocess.run([
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0',
            '-i', list_file,
            '-c', 'copy',
            output_path,
        ], check=True, capture_output=True)
    finally:
        try:
            os.unlink(list_file)
        except OSError:
            pass
