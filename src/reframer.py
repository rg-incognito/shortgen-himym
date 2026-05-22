"""
9:16 reframing with blurry background letterbox.

Pipeline:
  - Background : full 16:9 frame stretched to 1080x1920, heavily blurred
  - Foreground : full 16:9 frame scaled to fit 1080 wide (~607 tall), centred
  - Result     : cinematic blurry top/bottom bars with clear full scene in middle
"""
import subprocess

_OUT_W, _OUT_H = 1080, 1920


def load_diarization_pipeline(hf_token: str):
    from pyannote.audio import Pipeline
    print('  Loading pyannote diarization model...')
    return Pipeline.from_pretrained('pyannote/speaker-diarization-3.1')


def reframe_clip(video_path: str, start_sec: float, end_sec: float,
                 output_path: str, pipeline=None) -> None:
    """
    Produce a 1080x1920 vertical clip.
    Full 16:9 frame is letterboxed in the centre; top/bottom bars are a
    blurred, stretched version of the same frame.
    """
    filter_complex = (
        "[0:v]split=2[bg_in][fg_in];"
        f"[bg_in]scale={_OUT_W}:{_OUT_H}:flags=lanczos,"
        f"gblur=sigma=30[bg];"
        f"[fg_in]scale={_OUT_W}:-2:flags=lanczos[fg];"
        "[bg][fg]overlay=0:(H-h)/2[v]"
    )
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(start_sec), '-to', str(end_sec),
        '-i', video_path,
        '-filter_complex', filter_complex,
        '-map', '[v]', '-map', '0:a?',
        '-c:v', 'libx264', '-preset', 'slow', '-crf', '18',
        '-c:a', 'aac', '-b:a', '128k',
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
