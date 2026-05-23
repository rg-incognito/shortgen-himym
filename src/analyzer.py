import json
import re
import time
import requests

_GEMINI_URL = 'https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent'

_PROMPT = """You are a viral short-form video editor working with How I Met Your Mother (US sitcom, 2005-2014).

Your task: Create a ~30-second reel that tells ONE complete storyline in tight, punchy cuts — like a TikTok story recap.

OUTPUT STRUCTURE (strictly in this order):
1. HOOK (first clip, 3-5 sec) — the single most shocking/funny/relatable moment from the ENTIRE storyline. Does NOT need to be the chronological start. CRITICAL: the very first frame must start MID-ACTION — the character must already be mid-sentence, mid-reaction, or mid-punchline. NEVER open on someone walking into MacLaren's, sitting down, looking around, or any establishing shot. Start on Barney's face already in frame mid-reveal, Marshall's reaction already happening, Ted already mid-disaster.
2. CONTEXT clips (2-4 clips, 3-6 sec each) — the minimum lines needed to understand why the hook moment is funny. Only the single KEY line or reaction per beat. Cut everything else.
3. PAYOFF (last clip, 3-5 sec) — the final punchline, resolution, or biggest laugh.

TOTAL target: 25-35 seconds across all clips combined.

Great storylines to look for:
1. Barney's elaborate scheme or play from the Playbook that backfires
2. Ted's romantic disaster or overly-romantic gesture that goes wrong
3. Marshall and Lily's couple argument with an absurd resolution
4. Robin's Canadian quirks or Robin Sparkles references causing embarrassment
5. A slap bet or callback punchline with a great reaction shot
6. Barney saying "Suit up!" or "Legendary!" in a ridiculous context
7. A lie or scheme that unravels with great reaction shots from the whole gang
8. A misunderstanding at MacLaren's that snowballs

Transcript (format: [start_sec - end_sec] text):
{transcript}

Previously used segments (AVOID these): {used_segments}

Return ONLY a valid JSON object — no markdown, no explanation:
{{
  "storyline_title": "barney_playbook_backfires",
  "storyline_summary": "Barney's latest play fails spectacularly, the gang finds out, Marshall delivers the slap",
  "clips": [
    {{
      "start_seconds": 87.0,
      "end_seconds": 92.0,
      "label": "hook",
      "description": "Marshall's face already mid-shock when he realises Barney used the Scuba Diver play — starts on his expression in frame"
    }}
  ],
  "score": 9
}}

Rules:
- 4 to 6 clips total
- FIRST clip = hook (most viral moment, any timestamp) — first frame must be mid-action, never an establishing shot
- LAST clip = payoff/punchline/resolution
- Hook clip: 3-5 seconds only
- Context clips: 3-6 seconds each — just the KEY line or reaction, nothing more
- Total combined duration: 25-35 seconds
- Clips (except the hook) should be in rough CHRONOLOGICAL ORDER
- Clips must NOT overlap each other or the previously-used segments
- CRITICAL: Every clip must end at a natural sentence or speech pause — NEVER cut mid-word or mid-sentence. Extend end_seconds by 1-2s if needed to catch the full line.
- Pick moments with a clear spoken punchline or strong visual reaction
- Score 1-10 for viral potential as a compiled reel (10 = highest)
- storyline_title: snake_case, max 40 chars"""


_YT_PROMPT = """You are a YouTube content strategist for a How I Met Your Mother clips channel called "Legen-dary Clips".

Generate YouTube metadata for a short-form vertical reel (under 60 seconds).

Episode : {episode_str}
Storyline: {storyline}
Summary  : {summary}
Score    : {score}/10

Return ONLY valid JSON, no markdown:
{{
  "title": "Barney's plan backfires BADLY 😭 | HIMYM S3E12",
  "description": "Barney tried his most elaborate play yet — and Marshall was watching the whole time.\\n\\nHow I Met Your Mother Season 3, Episode 12 | \\"The Platinum Rule\\"\\n\\n📌 Subscribe for daily HIMYM story reels — the funniest moments cut down to under a minute.\\n\\n#HIMYM #HowIMetYourMother #Barney #BarneyStinson #HIMYMClips #TVShows #Sitcom #FunnyMoments #2000sTV #HIMYMReels",
  "tags": "HIMYM, How I Met Your Mother, Barney Stinson, HIMYM clips, HIMYM funny moments, HIMYM Season 3, sitcom, 2000s TV, Neil Patrick Harris, HIMYM compilation, Playbook, HIMYM shorts, comedy, CBS, HIMYM rewatch",
  "pinned_comment": "Barney really thought this was going to work 😭 Team Barney or Team Marshall here? 👇"
}}

Rules:
- title: max 70 chars, punchy hook, episode code (e.g. S3E12), exactly 1 emoji
- description: 2-line punchy hook → blank line → episode info line → blank line → subscribe CTA line → blank line → exactly 10 hashtags on one line
- tags: exactly 15 tags, comma-separated, mix of broad (HIMYM) and specific (character, theme)
- pinned_comment: must be ONE of these formats — (a) polarizing take specific to this clip: "Team X or Team Y? 👇", (b) ranking prompt: "Rate this [character] moment 1-10 👇", (c) completion gap: "What did [character] say next? 👇". NEVER use generic questions like "which character causes the most chaos". Must reference the specific characters or situation from THIS clip."""


def generate_yt_metadata(story, episode_name, api_key, retries=5):
    import re
    api_key = api_key.strip()
    m = re.search(r'[Ss](\d+)[Ee](\d+)', episode_name)
    ep_str = f"S{int(m.group(1))}E{int(m.group(2))}" if m else episode_name

    prompt = _YT_PROMPT.format(
        episode_str=ep_str,
        storyline=story['storyline_title'].replace('_', ' '),
        summary=story['storyline_summary'],
        score=story['score'],
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.7},
    }
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                _GEMINI_URL,
                params={'key': api_key},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            raw = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
            return json.loads(raw)
        except Exception as e:
            print(f"  YT metadata attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(30)
    return None


def analyze_transcript(segments, api_key, used_segments=None, retries=5):
    api_key = api_key.strip()

    transcript_text = '\n'.join(
        f"[{s['start']} - {s['end']}] {s['text']}"
        for s in segments
    )
    used_str = (
        ', '.join(f"{s:.0f}s-{e:.0f}s" for s, e in used_segments)
        if used_segments else 'none'
    )
    prompt = _PROMPT.format(transcript=transcript_text, used_segments=used_str)

    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.2},
    }

    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                _GEMINI_URL,
                params={'key': api_key},
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            raw = resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
            story = json.loads(raw)
            total = sum(c['end_seconds'] - c['start_seconds'] for c in story['clips'])
            story['_total_seconds'] = round(total, 1)
            return story
        except requests.HTTPError as e:
            print(f"  Gemini attempt {attempt} failed: {e} — {e.response.text[:300]}")
            if attempt < retries:
                wait = 60 if e.response.status_code in (503, 429) else 15
                time.sleep(wait)
        except Exception as e:
            print(f"  Gemini attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(15)

    raise RuntimeError("Gemini analysis failed after all retries")
