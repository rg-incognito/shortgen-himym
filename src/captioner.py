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

from PIL import Image, ImageDraw, ImageFont


# ASS style constants
_FONT      = "Arial"
_FONT_SIZE = 52          # pt, looks good at 1080 wide
_OUT_W     = 1080
_OUT_H     = 1920
_Y_POS     = 1450        # px from top — clear of UI chrome at bottom
_WHITE     = "&H00FFFFFF&"
_YELLOW    = "&H0000FFFF&"   # BGR in ASS = #FFFF00 = yellow
_SHADOW    = "&H80000000&"
_OUTLINE   = "&H00000000&"   # black outline

# --- Hook-card overlay (big bold text shown for the opening ~1.5s) ---
_HOOK_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # ubuntu-latest (CI runner)
    "C:/Windows/Fonts/arialbd.ttf",                            # Windows local dev
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
]
_HOOK_EMOJI_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/noto-color-emoji/NotoColorEmoji.ttf",
    "C:/Windows/Fonts/seguiemj.ttf",                            # Windows local dev
]
_HOOK_FONT_SIZE  = 108
_HOOK_MIN_SIZE   = 70     # shrink text down to this size if it doesn't fit in 3 lines
_HOOK_EMOJI_SIZE = 132
_HOOK_MAX_WIDTH  = 940    # px — leaves ~70px margin each side of the 1080-wide frame
_HOOK_MAX_LINES  = 3
_HOOK_Y_CENTER   = 620    # px from top — upper-middle third, clear of the rolling captions
_HOOK_DURATION   = 1.4    # seconds the hook card stays on screen


def _find_font(candidates):
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


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
Style: Default,{_FONT},{_FONT_SIZE},{_WHITE},&H000000FF&,{_OUTLINE},{_SHADOW},-1,0,0,0,100,100,0,0,1,3,1,8,30,30,{_Y_POS},1
Style: Active,{_FONT},{_FONT_SIZE},{_YELLOW},&H000000FF&,{_OUTLINE},{_SHADOW},-1,0,0,0,100,100,0,0,1,3,1,8,30,30,{_Y_POS},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not mapped_words:
        return header

    events = []
    BLOCK       = 4
    MAX_WORD_S  = 0.9   # max seconds any single word stays highlighted
    CAPTION_LEAD = 0.15  # captions appear this many seconds before the word is spoken

    # Group words into blocks of 4
    blocks = [mapped_words[i:i + BLOCK] for i in range(0, len(mapped_words), BLOCK)]

    for b_idx, block in enumerate(blocks):
        # Cap block end so it never bleeds into the next block
        next_block_start = blocks[b_idx + 1][0]['start'] if b_idx + 1 < len(blocks) else None
        block_end = min(block[-1]['end'], block[-1]['start'] + MAX_WORD_S)
        if next_block_start is not None:
            block_end = min(block_end, next_block_start - CAPTION_LEAD)

        for active_idx, active_word in enumerate(block):
            seg_start = max(0.0, active_word['start'] - CAPTION_LEAD)
            if active_idx + 1 < len(block):
                next_start = block[active_idx + 1]['start']
                raw_end = min(next_start, active_word['start'] + MAX_WORD_S)
                seg_end = max(seg_start + 0.05, raw_end - CAPTION_LEAD)
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


def _wrap_lines(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_hook_png(hook_text, hook_emoji, out_path):
    """
    Render a big bold hook-text card (transparent PNG, full 1080x1920 canvas)
    for the opening ~1.5s overlay. Shrinks font size until the text fits within
    _HOOK_MAX_LINES; falls back to Pillow's built-in font if no system font is found
    so a missing font can never crash the pipeline. Emoji is best-effort — if no
    color-emoji font is available on the machine, it's silently skipped.
    """
    img = Image.new('RGBA', (_OUT_W, _OUT_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_path = _find_font(_HOOK_FONT_CANDIDATES)
    size = _HOOK_FONT_SIZE
    lines = [hook_text]
    font = None
    while size >= _HOOK_MIN_SIZE:
        font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
        lines = _wrap_lines(draw, hook_text, font, _HOOK_MAX_WIDTH)
        if len(lines) <= _HOOK_MAX_LINES:
            break
        size -= 8

    line_height = int(size * 1.25)
    total_height = line_height * len(lines)
    y = _HOOK_Y_CENTER - total_height // 2

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (_OUT_W - w) / 2
        # thick black outline for legibility over any background, then white fill
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255),
                   stroke_width=6, stroke_fill=(0, 0, 0, 255))
        y += line_height

    if hook_emoji:
        emoji_font_path = _find_font(_HOOK_EMOJI_FONT_CANDIDATES)
        if emoji_font_path:
            try:
                emoji_font = ImageFont.truetype(emoji_font_path, _HOOK_EMOJI_SIZE)
                w = draw.textlength(hook_emoji, font=emoji_font)
                draw.text(((_OUT_W - w) / 2, y + 10), hook_emoji, font=emoji_font,
                          embedded_color=True)
            except Exception as exc:
                print(f"  Hook emoji skipped ({exc})")

    img.save(out_path)


def burn_captions(video_path, output_path, all_words, story_clips,
                   hook_text=None, hook_emoji=None):
    mapped = _remap_words(all_words, story_clips)

    hook_png = None
    if hook_text:
        hook_png = tempfile.mktemp(suffix='.png')
        try:
            render_hook_png(hook_text, hook_emoji or '', hook_png)
        except Exception as exc:
            print(f"  Hook card skipped ({exc})")
            hook_png = None

    try:
        if not mapped:
            print("  Captions: no words mapped" +
                  (" — hook card only" if hook_png else " — copying without captions"))
            if hook_png:
                _overlay_only(video_path, hook_png, output_path)
            else:
                import shutil
                shutil.copy2(video_path, output_path)
            return

        print(f"  Captions: {len(mapped)} words across {len(story_clips)} clips" +
              (" + hook card" if hook_png else ""))

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

            # Escape ':' (e.g. a Windows drive letter) so ffmpeg's filter-option
            # parser doesn't mistake it for a key=value separator.
            ass_safe = ass_file.replace('\\', '/').replace(':', '\\:')
            enhance  = "unsharp=5:5:0.8:3:3:0,eq=contrast=1.05:saturation=1.1"

            if hook_png:
                filter_complex = (
                    f"[0:v]ass={ass_safe},{enhance}[capped];"
                    f"[capped][1:v]overlay=0:0:enable='between(t,0,{_HOOK_DURATION})'[vout]"
                )
                cmd = [
                    'ffmpeg', '-y',
                    '-i', video_path,
                    '-i', hook_png,
                    '-filter_complex', filter_complex,
                    '-map', '[vout]', '-map', '0:a?',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
                    '-c:a', 'aac', '-b:a', '128k',
                    output_path,
                ]
            else:
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
    finally:
        if hook_png:
            try:
                os.unlink(hook_png)
            except OSError:
                pass


def _overlay_only(video_path, hook_png, output_path):
    """Composite just the hook card (no dialogue captions available)."""
    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-i', hook_png,
        '-filter_complex',
        f"[0:v][1:v]overlay=0:0:enable='between(t,0,{_HOOK_DURATION})'[vout]",
        '-map', '[vout]', '-map', '0:a?',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-c:a', 'aac', '-b:a', '128k',
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
