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

Your task: find the BEST short-form moment in this episode for a vertical reel of 15-58 seconds, and choose the FORMAT that fits it best.

WATCH-THROUGH IS WHAT MATTERS, NOT LENGTH: on this channel, shorts viewers watch all the way
through (or replay) get ~27k median views; ones where viewers drop off early get ~15k. Length
alone doesn't help — 30-45s clips actually average slightly fewer views, because padded setup
loses people. The one breakout (315k) was a 60-second mini-story that still held 69% of
viewers to the final second, because it set up a clear stake (Barney about to hit a milestone)
and paid it off with a twist. So:
- If the episode has a mini-story like that — a clear want/plan, it escalates or goes sideways,
  then a twist or punchline — take it at whatever length it needs, up to 58 seconds.
- Otherwise a tight, self-explanatory 15-25 second scene is better than stretching a weak one.
- Every extra second must earn its place; cut anything a viewer would swipe away during.

FORMAT "standalone_scene" — use when ONE scene already works as a complete moment on its own:
- A single continuous scene: an iconic monologue, a quotable line ("Suit up!", "Legendary!", a Barney speech), a tight back-and-forth with a clean punchline, or one big reaction beat
- 1-3 clips from that ONE scene, back-to-back (small dead-air/cutaway trims between them are fine)
- Total duration: 15-58 seconds — include the setup that makes the punchline land, but nothing more; never pad
- Must be fully funny/emotional WITHOUT any other clips for context
- First clip starts at the natural beginning of the moment — mid-sentence is fine if that's how it plays, but don't force an artificial "hook" cut from elsewhere

FORMAT "story_recap" — use when the best moment NEEDS setup from earlier in the episode to land:
1. HOOK (first clip, 3-5 sec) — the single most shocking/funny/relatable moment from the ENTIRE storyline. Does NOT need to be the chronological start. CRITICAL: the very first frame must start MID-ACTION — the character must already be mid-sentence, mid-reaction, or mid-punchline. NEVER open on someone walking into MacLaren's, sitting down, looking around, or any establishing shot. Start on Barney's face already in frame mid-reveal, Marshall's reaction already happening, Ted already mid-disaster.
2. CONTEXT clips (2-5 clips, 3-6 sec each) — the minimum lines needed to understand why the hook moment is funny. Only the single KEY line or reaction per beat. Cut everything else.
3. PAYOFF (last clip, 3-5 sec) — the final punchline, resolution, or biggest laugh.
TOTAL target: 40-58 seconds across all clips combined — prefer the longer end when the storyline has enough genuine beats, but never pad with dead air or a redundant context clip just to extend length.

Default to "standalone_scene" when a single scene is strong enough on its own — it feels like a real clip rather than an edit and often performs better. Use "story_recap" only when no single scene can stand alone and you genuinely need to connect a setup to a later payoff.

CHARACTER PRIORITY: Barney and Robin are this channel's best-performing characters —
Robin-centric clips have the highest median views of any character on the channel, and
Barney-centric clips are both high-volume and consistently strong. When multiple candidate
moments in this transcript are comparably funny/strong, PREFER the one where Barney and/or
Robin are the focal character(s) (on screen, driving the scene, or delivering the punchline)
over an equally-strong moment centered on Ted, Marshall, or Lily. Do NOT force a weaker
Barney/Robin moment over a genuinely funnier or more emotional scene involving other
characters — quality of the moment still comes first, this is a tiebreaker/weighting
preference, not an exclusion rule.

Great storylines/moments to look for:
1. Barney's elaborate scheme or play from the Playbook that backfires
2. Robin's Canadian quirks, Robin Sparkles references, or Robin's blunt/deadpan reactions causing embarrassment
3. Barney saying "Suit up!" or "Legendary!" in a ridiculous context, or one of his iconic monologues/speeches
4. A slap bet or callback punchline with a great reaction shot (especially if Robin or Barney is involved)
5. Ted's romantic disaster or overly-romantic gesture that goes wrong
6. Marshall and Lily's couple argument with an absurd resolution
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
  "hook_text": "THE SPEECH THAT CHANGED EVERYTHING",
  "hook_emoji": "😳",
  "music_mood": "epic",
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
- If format = "standalone_scene": 1-3 clips from ONE scene, label each "scene", total 15-58 seconds (include the setup the punchline needs, nothing more; never pad), clips in chronological order, may skip small dead-air/cutaway gaps but must otherwise read as one continuous moment
- If format = "story_recap": 4-7 clips, FIRST clip labeled "hook" (most viral moment, any timestamp, first frame mid-action, never an establishing shot), LAST clip labeled "payoff" (punchline/resolution), middle clips labeled "context" (3-6 sec each, just the KEY line or reaction), total 40-58 seconds (prefer longer when there are enough genuine beats, never pad), clips other than the hook in rough CHRONOLOGICAL ORDER
- Clips must NOT overlap each other or the previously-used segments
- CRITICAL: Every clip must end at a natural sentence or speech pause — NEVER cut mid-word or mid-sentence. Extend end_seconds by 1-2s if needed to catch the full line.
- Pick moments with a clear spoken punchline or strong visual reaction
- Score 1-10 for viral potential (10 = highest)
- storyline_title: snake_case, max 40 chars
- series_tag: pick exactly one — barneys_schemes | teds_disasters | marshall_and_lily | robins_quirks | slap_bet | legendary_moments | gang_at_maclarens
- hook_text: 3-8 words, ALL CAPS, describing the clip's premise/moment WITHOUT giving away the punchline (e.g. "HE TRIED TO RIZZ UP A COP", "BARNEY'S GYM INVESTMENT SCHEME", "THE DECAF COFFEE DISASTER"). This is burned onto the video as a persistent white banner across the top of the ENTIRE video (not just the opening) — it can be a touch more descriptive than a quick flash-hook since it stays visible throughout. Still separate from and shorter than the YouTube title.
- hook_emoji: 1-2 emoji matching the COMEDIC reaction to this specific moment (e.g. 😳 😂 💀 🤦 😬 😏 👀 🍆🙈 — pick whatever actually fits the clip's humor, don't default to the same one or two every time), or "" if none fit naturally — never force one
- music_mood: the background music bed that fits how this moment FEELS, played quietly under the dialogue. Pick exactly one:
  upbeat — light, playful comedy; a fun bit, banter, a silly gag
  awkward — cringe, sneaky or scheming energy; a plan in motion, a lie being covered, an uncomfortable silence
  romantic — a sweet or tender couple moment, flirting that lands, a heartfelt gesture
  emotional — sad, bittersweet or sincere; a breakup, a goodbye, a serious heart-to-heart
  epic — a big buildup, a dramatic reveal, a "legendary" speech or over-the-top moment
  none — the joke depends on timing, silence or rapid dialogue that music would step on
  Match the mood of the scene, not the show overall — a sad scene gets "emotional" even though HIMYM is a comedy"""


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
  "title": "Barney tries the platinum rule —it backfires instantly | Barney's Schemes S3E12",
  "description": "Barney tried his most elaborate play yet — and Marshall was watching the whole time.\\n\\nHow I Met Your Mother Season 3, Episode 12 | \\"The Platinum Rule\\"\\n\\n📌 Subscribe for daily HIMYM story reels — the funniest moments cut down to under a minute.\\n\\n#HIMYM #HowIMetYourMother #Barney #BarneyStinson #HIMYMClips #TVShows #Sitcom #FunnyMoments #2000sTV #HIMYMReels",
  "tags": "HIMYM, How I Met Your Mother, Barney Stinson, HIMYM clips, HIMYM funny moments, HIMYM Season 3, sitcom, 2000s TV, Neil Patrick Harris, HIMYM compilation, Playbook, HIMYM shorts, comedy, CBS, HIMYM rewatch",
  "pinned_comment": "Barney really thought this was going to work 😭 Team Barney or Team Marshall here? 👇"
}}

Rules:
- title: format is "{{specific curiosity-gap phrase describing THIS clip's moment, using an em-dash or ellipsis to withhold the punchline}} | {{Series Display Name}} SxEx" — use the display name from the series_tag mapping above, max 90 chars total. The phrase must be specific to what actually happens in this clip, not a generic character/series label — e.g. "Ted tries to ask the doctor out —she drops the bomb", "Lily asked for decaf... it did not go well". Emoji optional — include at most 1 only if it fits naturally, never forced.
- description: 2-line punchy hook → blank line → episode info line → blank line → subscribe CTA line → blank line → exactly 10 hashtags on one line
- tags: exactly 15 tags, comma-separated, mix of broad (HIMYM) and specific (character, theme) — a fixed set of broader adjacent-sitcom tags is appended automatically after this, so keep these 15 HIMYM-specific
- pinned_comment: must be ONE of these formats — (a) polarizing take specific to this clip: "Team X or Team Y? 👇", (b) ranking prompt: "Rate this [character] moment 1-10 👇", (c) completion gap: "What did [character] say next? 👇". NEVER use generic questions like "which character causes the most chaos". Must reference the specific characters or situation from THIS clip."""


# Appended to whatever HIMYM-specific tags Gemini generates, so every video also
# surfaces in broader "sitcom clips" search/suggested traffic, not just HIMYM search.
# Other shows' names (Friends, The Office, ...) were dropped: they misdescribe the
# video, which YouTube treats as misleading metadata.
# YouTube caps combined tags at 500 chars — _append_cross_show_tags truncates to fit.
_CROSS_SHOW_TAGS = [
    "sitcom clips", "TV show moments", "2000s sitcoms",
    "classic sitcoms", "relatable humor",
]
_MAX_TAGS_CHARS = 480  # leave a little headroom under YouTube's 500-char cap


def _append_cross_show_tags(tags_str):
    existing = [t.strip() for t in tags_str.split(',') if t.strip()]
    seen = {t.lower() for t in existing}
    combined = list(existing)
    for tag in _CROSS_SHOW_TAGS:
        if tag.lower() in seen:
            continue
        candidate = combined + [tag]
        if len(', '.join(candidate)) > _MAX_TAGS_CHARS:
            break
        combined = candidate
        seen.add(tag.lower())
    return ', '.join(combined)


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
            meta = json.loads(raw)
            meta['tags'] = _append_cross_show_tags(meta.get('tags', ''))
            return meta
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
