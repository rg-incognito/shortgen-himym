"""
Viral-style caption overlay — 4-word sliding blocks.

Each block of 4 words is shown simultaneously.  The active word is highlighted
yellow; the rest are white with a black outline.  When the active word advances
past the 4th slot the entire block replaces itself with the next 4 words.

Timings come from Whisper word-level timestamps, remapped from episode time
into the merged video's timeline using the story clip list.
"""
import os
import subprocess
import tempfile
from pathlib import Path


# ASS style constants
_FONT      = "Arial"
_FONT_SIZE = 52          # pt, looks good at 1080 wide
_OUT_W     = 1080
_OUT_H     = 1920
_Y_POS     = 1660        # px from top — just above IG/TT username bar
_WHITE     = "&H00FFFFFF&"
_YELLOW    = "&H0000FFFF&"   # BGR in ASS = #FFFF00 = yellow
_SHADOW    = "&H80000000&"
_OUTLINE   = "&H00000000&"   # black outline


def _remap_words(all_words, story_clips):
    """
    Filter words that fall inside any story clip and remap episode timestamps
    to merged-video timestamps.

    story_clips: list of {start_seconds, end_seconds} in episode time.
    Returns [{word, start, end}] in merged-video time.
    """
    # Build cumulative offsets for each clip
    offsets = []
    t = 0.0
    for clip in story_clips:
        offsets.append((clip['start_seconds'], clip['end_seconds'], t))
        t += clip['end_seconds'] - clip['start_seconds']

    result = []
    for w in all_words:
        ws, we = w['start'], w['end']
        for cs, ce, offset in offsets:
            # word must start inside the clip window
            if ws >= cs and ws < ce:
                new_start = offset + (ws - cs)
                new_end   = offset + (min(we, ce) - cs)
                result.append({'word': w['word'], 'start': new_start, 'end': new_end})
                break
    return result


def _format_ass_time(seconds):
    h  = int(seconds // 3600)
    m  = int((seconds % 3600) // 60)
    s  = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_ass(mapped_words, total_duration):
    """Generate ASS subtitle content with 4-word block highlighting."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {_OUT_W}
PlayResY: {_OUT_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{_FONT},{_FONT_SIZE},{_WHITE},&H000000FF&,{_OUTLINE},{_SHADOW},-1,0,0,0,100,100,0,0,1,3,1,2,30,30,{_OUT_H - _Y_POS},1
Style: Active,{_FONT},{_FONT_SIZE},{_YELLOW},&H000000FF&,{_OUTLINE},{_SHADOW},-1,0,0,0,100,100,0,0,1,3,1,2,30,30,{_OUT_H - _Y_POS},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not mapped_words:
        return header

    events = []
    BLOCK       = 4
    MAX_WORD_S  = 0.9   # max seconds any single word stays highlighted

    # Group words into blocks of 4
    blocks = [mapped_words[i:i + BLOCK] for i in range(0, len(mapped_words), BLOCK)]

    for b_idx, block in enumerate(blocks):
        # Cap block end so it never bleeds into the next block
        next_block_start = blocks[b_idx + 1][0]['start'] if b_idx + 1 < len(blocks) else None
        block_end = min(block[-1]['end'], block[-1]['start'] + MAX_WORD_S)
        if next_block_start is not None:
            block_end = min(block_end, next_block_start)

        for active_idx, active_word in enumerate(block):
            seg_start = active_word['start']
            if active_idx + 1 < len(block):
                # cap intra-block gap too — handles long pauses between words
                seg_end = min(block[active_idx + 1]['start'], active_word['start'] + MAX_WORD_S)
            else:
                seg_end = block_end

            if seg_end <= seg_start:
                seg_end = seg_start + 0.05

            # Build the line: words before active=white, active=yellow, words after=white
            parts = []
            for j, w in enumerate(block):
                text = w['word']
                if j == active_idx:
                    parts.append(r"{\c" + _YELLOW + r"}" + text + r"{\c" + _WHITE + r"}")
                else:
                    parts.append(text)

            line = " ".join(parts).strip()

            start_str = _format_ass_time(seg_start)
            end_str   = _format_ass_time(seg_end)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{line}")

    return header + "\n".join(events) + "\n"


def burn_captions(video_path, output_path, all_words, story_clips):
    mapped = _remap_words(all_words, story_clips)
    if not mapped:
        print("  Captions: no words mapped — copying without captions")
        import shutil
        shutil.copy2(video_path, output_path)
        return

    print(f"  Captions: {len(mapped)} words across {len(story_clips)} clips")

    probe = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        capture_output=True, text=True
    )
    total_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 60.0

    ass_content = _build_ass(mapped, total_duration)
    ass_file = tempfile.mktemp(suffix='.ass')
    try:
        with open(ass_file, 'w', encoding='utf-8') as f:
            f.write(ass_content)

        ass_safe = ass_file.replace('\\', '/')
        enhance   = "unsharp=5:5:0.8:3:3:0,eq=contrast=1.05:saturation=1.1"

        cmd = [
            'ffmpeg', '-y',
            '-i', video_path,
            '-vf', f"ass={ass_safe},{enhance}",
            '-map', '0:v', '-map', '0:a?',
            '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
            '-c:a', 'aac', '-b:a', '128k',
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        try:
            os.unlink(ass_file)
        except OSError:
            pass
