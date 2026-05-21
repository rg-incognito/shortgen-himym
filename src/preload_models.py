"""Pre-downloads Whisper + pyannote models into HF cache before main.py runs."""
import os

whisper_model = os.environ.get('WHISPER_MODEL', 'small')
hf_token      = os.environ.get('HF_TOKEN', '').strip()

print(f'Pre-downloading whisper-{whisper_model}...')
from faster_whisper import WhisperModel
WhisperModel(whisper_model, device='cpu', compute_type='int8')
print('  Whisper done.')

if hf_token:
    print('Pre-downloading pyannote/speaker-diarization-3.1...')
    try:
        from pyannote.audio import Pipeline
        Pipeline.from_pretrained('pyannote/speaker-diarization-3.1')
        print('  Pyannote done.')
    except Exception as e:
        print(f'  Pyannote download failed: {e}')
        print('  Run will use face-only tracking. Accept all gated models on HuggingFace.')
else:
    print('HF_TOKEN not set — skipping pyannote download (face-only tracking will be used).')
