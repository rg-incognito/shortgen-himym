import json
import re
import time
import requests

_GEMINI_BASE     = 'https://generativelanguage.googleapis.com/v1/models/{}:generateContent'
_FALLBACK_MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-2.0-flash']


def _gemini_post(payload, api_key, timeout=120):
    """POST to Gemini with automatic model fallback on 503/429."""
    for i, model in enumerate(_FALLBACK_MODELS):
        try:
            resp = requests.post(
                _GEMINI_BASE.format(model),
                params={'key': api_key},
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            if i > 0:
                print(f"  Success with fallback model: {model}")
            return resp.json()['candidates'][0]['content']['parts'][0]['text'].strip()
        except requests.HTTPError as e:
            if e.response.status_code in (503, 429) and i < len(_FALLBACK_MODELS) - 1:
                print(f"  {model} returned {e.response.status_code}, trying {_FALLBACK_MODELS[i+1]}")
                time.sleep(5)
            else:
                raise

_PROMPT = """You are a viral short-form video editor working with How I Met Your Mother (US sitcom, 2005-2014).

Your task: find the BEST short-form moment in this episode for a vertical reel under 35 seconds, and choose the FORMAT that fits it best.

FORMAT "standalone_scene" — use when ONE scene already works as a complete moment on its own:
- A single continuous scene: an iconic monologue, a quotable line ("Suit up!", "Legendary!", a Barney speech), a tight back-and-forth with a clean punchline, or one big reaction beat
- 1-3 clips from that ONE scene, back-to-back (small dead-air/cutaway trims between them are fine)
- Total duration: 10-25 seconds
- Must be fully funny/emotional WITHOUT any other clips for context
- First clip starts at the natural beginning of the moment — mid-sentence is fine if that's how it plays, but don't force an artificial "hook" cut from elsewhere

FORMAT "story_recap" — use when the best moment NEEDS setup from earlier in the episode to land:
1. HOOK (first clip, 3-5 sec) — the single most shocking/funny/relatable moment from the ENTIRE storyline. Does NOT need to be the chronological start. CRITICAL: the very first frame must start MID-ACTION — the character must already be mid-sentence, mid-reaction, or mid-punchline. NEVER open on someone walking into MacLaren's, sitting down, looking around, or any establishing shot. Start on Barney's face already in frame mid-reveal, Marshall's reaction already happening, Ted already mid-disaster.
2. CONTEXT clips (2-4 clips, 3-6 sec each) — the minimum lines needed to understand why the hook moment is funny. Only the single KEY line or reaction per beat. Cut everything else.
3. PAYOFF (last clip, 3-5 sec) — the final punchline, resolution, or biggest laugh.
TOTAL target: 25-35 seconds across all clips combined.

Default to "standalone_scene" when a single scene is strong enough on its own — it feels like a real clip rather than an edit and often performs better. Use "story_recap" only when no single scene can stand alone and you genuinely need to connect a setup to a later payoff.

Great storylines/moments to look for:
1. Barney's elaborate scheme or play from the Playbook that backfires
2. Ted's romantic disaster or overly-romantic gesture that goes wrong
3. Marshall and Lily's couple argument with an absurd resolution
4. Robin's Canadian quirks or Robin Sparkles references causing embarrassment
5. A slap bet or callback punchline with a great reaction shot
6. Barney saying "Suit up!" or "Legendary!" in a ridiculous context, or one of his iconic monologues/speeches
7. A lie or scheme that unravels with great reaction shots from the whole gang
8. A misunderstanding at MacLaren's that snowballs

Transcript (format: [start_sec - end_sec] text):
{transcript}

Previously used segments (AVOID these): {used_segments}

Return ONLY a valid JSON object — no markdown, no explanation:
{{
  "format": "standalone_scene",
  "storyline_title": "barney_whatever_you_do_speech",
  "storyline_summary": "Barney delivers his 'whatever you do in this life' speech to Ted at the bar",
  "series_tag": "legendary_moments",
  "clips": [
    {{
      "start_seconds": 87.0,
      "end_seconds": 105.0,
      "label": "scene",
      "description": "Barney's full speech to Ted, starting mid-sentence as he leans in"
    }}
  ],
  "score": 9
}}

Rules:
- If format = "standalone_scene": 1-3 clips from ONE scene, label each "scene", total 10-25 seconds, clips in chronological order, may skip small dead-air/cutaway gaps but must otherwise read as one continuous moment
- If format = "story_recap": 4-6 clips, FIRST clip labeled "hook" (most viral moment, any timestamp, first frame mid-action, never an establishing shot), LAST clip labeled "payoff" (punchline/resolution), middle clips labeled "context" (3-6 sec each, just the KEY line or reaction), total 25-35 seconds, clips other than the hook in rough CHRONOLOGICAL ORDER
- Clips must NOT overlap each other or the previously-used segments
- CRITICAL: Every clip must end at a natural sentence or speech pause — NEVER cut mid-word or mid-sentence. Extend end_seconds by 1-2s if needed to catch the full line.
- Pick moments with a clear spoken punchline or strong visual reaction
- Score 1-10 for viral potential (10 = highest)
- storyline_title: snake_case, max 40 chars
- series_tag: pick exactly one — barneys_schemes | teds_disasters | marshall_and_lily | robins_quirks | slap_bet | legendary_moments | gang_at_maclarens"""


_YT_PROMPT = """You are a YouTube content strategist for a How I Met Your Mother clips channel called "Legen-dary Clips".

Generate YouTube metadata for a short-form vertical reel (under 60 seconds).

Episode  : {episode_str}
Storyline: {storyline}
Summary  : {summary}
Series   : {series_tag}
Score    : {score}/10

The series_tag maps to these display names for the title:
barneys_schemes → "Barney's Schemes"
teds_disasters → "Ted's Disasters"
marshall_and_lily → "Marshall & Lily"
robins_quirks → "Robin Being Robin"
slap_bet → "Slap Bet"
legendary_moments → "Legendary Moments"
gang_at_maclarens → "The Gang"

Return ONLY valid JSON, no markdown:
{{
  "title": "Barney's Schemes 😭 | HIMYM S3E12",
  "description": "Barney tried his most elaborate play yet — and Marshall was watching the whole time.\\n\\nHow I Met Your Mother Season 3, Episode 12 | \\"The Platinum Rule\\"\\n\\n📌 Subscribe for daily HIMYM story reels — the funniest moments cut down to under a minute.\\n\\n#HIMYM #HowIMetYourMother #Barney #BarneyStinson #HIMYMClips #TVShows #Sitcom #FunnyMoments #2000sTV #HIMYMReels",
  "tags": "HIMYM, How I Met Your Mother, Barney Stinson, HIMYM clips, HIMYM funny moments, HIMYM Season 3, sitcom, 2000s TV, Neil Patrick Harris, HIMYM compilation, Playbook, HIMYM shorts, comedy, CBS, HIMYM rewatch",
  "pinned_comment": "Barney really thought this was going to work 😭 Team Barney or Team Marshall here? 👇"
}}

Rules:
- title: format MUST be "[Series Display Name] 😭 | HIMYM SxEx" — use the display name from the series_tag mapping above, max 70 chars, exactly 1 emoji, episode code at end
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
        series_tag=story.get('series_tag', 'gang_at_maclarens'),
        score=story['score'],
    )
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.7},
    }
    for attempt in range(1, retries + 1):
        try:
            raw = _gemini_post(payload, api_key, timeout=60)
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
            raw = _gemini_post(payload, api_key, timeout=120)
            raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
            story = json.loads(raw)
            total = sum(c['end_seconds'] - c['start_seconds'] for c in story['clips'])
            story['_total_seconds'] = round(total, 1)
            return story
        except Exception as e:
            print(f"  Gemini attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(15)

    raise RuntimeError("Gemini analysis failed after all retries")
