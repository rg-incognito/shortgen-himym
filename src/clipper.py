import os
import subprocess
import tempfile


def create_story_short(video_path, story, output_dir, episode_name,
                        pipeline=None, all_words=None):
    """
    Cuts every clip in a story arc, reframes each to 9:16, concatenates into
    one compiled video, then burns viral-style captions if word timestamps
    are provided.
    """
    from reframer import reframe_clip
    from captioner import burn_captions

    clips = story['clips']
    title = story['storyline_title']
    score = story['score']

    parts_dir = os.path.join(output_dir, '_parts')
    os.makedirs(parts_dir, exist_ok=True)

    part_paths = []
    try:
        for i, clip in enumerate(clips, 1):
            part_path = os.path.join(parts_dir, f"part_{i:02d}.mp4")
            print(f"  Part {i}/{len(clips)}: [{clip['label']}] "
                  f"{clip['start_seconds']:.1f}s – {clip['end_seconds']:.1f}s")
            reframe_clip(video_path, clip['start_seconds'], clip['end_seconds'],
                         part_path, pipeline=pipeline)
            part_paths.append(part_path)

        merged_path = os.path.join(output_dir, '_merged.mp4')
        print(f"  Merging {len(part_paths)} parts...")
        _merge_clips(part_paths, merged_path)

        out_path = os.path.join(output_dir, f"{episode_name}_{title}_s{score}.mp4")
        if all_words:
            print("  Burning captions...")
            burn_captions(merged_path, out_path, all_words, clips,
                          hook_text=story.get('hook_text'), hook_emoji=story.get('hook_emoji'))
            os.unlink(merged_path)
        else:
            os.rename(merged_path, out_path)

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
    Defaults inside the hook-card overlay window (captioner._HOOK_DURATION,
    currently 1.4s) so the frame shows both the character and the bold hook
    text/emoji — used as the video's explicit thumbnail so YouTube's grid/
    search surfaces don't fall back to an unpredictable auto-picked frame.
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
