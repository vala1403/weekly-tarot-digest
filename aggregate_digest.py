"""Aggregate a week's tagged readings for one sign into a cross-reader digest.

Usage: python3 aggregate_digest.py <sign> --week-of YYYY-MM-DD <video_id> [<video_id> ...]
  e.g. python3 aggregate_digest.py aries --week-of 2026-08-10 kOjdw2SqXpg CJ_4CKOkuYE ZGO49pePggo w82yDuanh2s 9eyf5NJuy5Y
Reads tagged/<video_id>.json for each video ID, writes digest_<sign>_week1.json.

--week-of must be an ISO date that falls on a Monday and is always required —
this script never infers the week from the run date, since digests are
routinely produced before the week in question starts.
"""
import argparse
import datetime
import json
import os
import sys
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
CATEGORIES = ["love", "finance", "career", "family"]

# Fixed vocabulary for the weekly overall-tone tag. Do not deviate from this
# list — it's also the enum used for theme-log.json archive entries.
THEME_VOCABULARY = [
    "cautious", "hopeful", "restless", "transformative",
    "reflective", "empowering", "turbulent", "liberating",
]

TAGGED_DIR = Path(__file__).parent / "tagged"
THEME_LOG_PATH = Path(__file__).parent / "data" / "theme-log.json"
THEME_LOG_SCHEMA_VERSION = 2

# From this week on, a sign's theme is allowed to repeat within its own
# history; before it, aggregate_tone() excludes the sign's last 4 weeks of
# themes from the choices. theme_rule on each theme-log entry records which
# regime was in effect when that week's theme was assigned.
REPEATS_ALLOWED_FROM = "2026-08-17"

EM_DASH = "—"
NO_EM_DASH_INSTRUCTION = (
    "Do not use em dashes (—) anywhere in your response. Use commas, "
    "colons, or separate sentences instead."
)


def strip_em_dashes(text):
    """Replace em dashes with a comma so style stays consistent even if the
    model ignores the no-em-dash instruction. Best-effort, not grammar-aware."""
    if not isinstance(text, str) or EM_DASH not in text:
        return text
    cleaned = text.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, ", ")
    return " ".join(cleaned.split())


def strip_em_dashes_deep(obj):
    if isinstance(obj, dict):
        return {k: strip_em_dashes_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_em_dashes_deep(v) for v in obj]
    return strip_em_dashes(obj)


def find_em_dashes(obj, path="digest"):
    """Post-generation check: return a list of 'path: text' for any string
    that still contains an em dash after stripping. Should normally be empty."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            hits.extend(find_em_dashes(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits.extend(find_em_dashes(v, f"{path}[{i}]"))
    elif isinstance(obj, str) and EM_DASH in obj:
        hits.append(f"{path}: {obj!r}")
    return hits

CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "reader_count": {"type": "integer"},
        "disagreement": {"type": ["string", "null"]},
    },
    "required": ["summary", "reader_count", "disagreement"],
    "additionalProperties": False,
}

TONE_SCHEMA = {
    "type": "object",
    "properties": {
        "theme": {"type": "string", "enum": THEME_VOCABULARY},
        "note": {"type": "string"},
    },
    "required": ["theme", "note"],
    "additionalProperties": False,
}

READERS_SCHEMA = {
    "type": "object",
    "properties": {
        "readers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                    "channel_theme": {"type": "string"},
                },
                "required": ["video_id", "channel_theme"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["readers"],
    "additionalProperties": False,
}


def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def is_placeholder_disagreement(text):
    if not text:
        return True
    lowered = text.lower()
    return "no notable disagreement" in lowered or "no strong disagreement" in lowered


def load_tagged(video_id: str) -> dict:
    path = TAGGED_DIR / f"{video_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"tagged file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


THEME_LOG_NOTES = {
    "theme": (
        "Aggregate one-word mood for the sign's whole week. Drawn from the "
        "fixed THEME_VOCABULARY in aggregate_digest.py (cautious, hopeful, "
        "restless, transformative, reflective, empowering, turbulent, "
        "liberating). While theme_rule='no-repeat-4wk', cannot repeat any "
        "theme used in this sign's prior 4 weeks. From theme_rule="
        "'repeats-allowed' (2026-08-17 on), the full vocabulary is "
        "available every week; the sign's own recent history is shown to "
        "the model as context only, not an exclusion list, and the choice "
        "is based purely on that week's 5 readings."
    ),
    "reader_tone": (
        "One-word tone tag for a single reading, assigned during tagging "
        "(tag_transcripts.py's overall_tone field). Free-form vocabulary, "
        "NOT constrained to THEME_VOCABULARY, not to be confused with "
        "`theme`."
    ),
    "agreement": (
        "Integer 0-5: how many of the 5 readers the aggregating model "
        "judged to have touched on / discussed a theme similar in meaning "
        "to this category's summary. This is a coverage count, not a "
        "directional-consensus count: two readers can both be counted here "
        "even if they took opposite positions (e.g. one predicts reunion, "
        "one predicts ending). Such conflicts are captured separately in "
        "`divergence`."
    ),
    "divergence": (
        "Notable disagreement between readers on this category, in the "
        "aggregating model's words. Null when it found no notable "
        "disagreement (placeholder phrases like 'No notable disagreement "
        "among readers...' are normalized to null rather than kept as text)."
    ),
    "repeat_streak": (
        "Number of consecutive most-recent weeks (including this one) this "
        "sign's theme has stayed the same. Always 1 for every entry through "
        "2026-08-10: theme_rule='no-repeat-4wk' forbids reusing any theme "
        "from the prior 4 weeks, so a back-to-back repeat was structurally "
        "impossible in that window. This is an artifact of the exclusion "
        "rule, not a signal that themes were volatile. From 2026-08-17, "
        "increments by 1 when the new theme matches the immediately "
        "preceding week's theme, and resets to 1 otherwise. Whenever "
        "repeat_streak >= 2, overall_tone_summary states this plainly and "
        "factually (e.g. 'Second week running.')."
    ),
    "theme_rule": (
        "Which exclusion rule was in effect when `theme` was assigned: "
        "'no-repeat-4wk' (weeks through 2026-08-10) or 'repeats-allowed' "
        f"({REPEATS_ALLOWED_FROM} on)."
    ),
    "category_tone_gap": (
        "Per-category (love/finance/career/family) tone was never "
        "generated by the pipeline, only reader_tone (per-reading) and "
        "theme (per-sign aggregate) exist. No `tone` key is included inside "
        "category objects."
    ),
    "channel_name_gap": (
        "Reader channel names were never captured by the pipeline (only "
        "video_id, url, and paraphrased content). No `channel_name` key is "
        "included in reader objects."
    ),
}


def load_theme_log() -> dict:
    if not THEME_LOG_PATH.exists():
        return {"schema_version": THEME_LOG_SCHEMA_VERSION, "notes": THEME_LOG_NOTES, "entries": []}
    doc = json.loads(THEME_LOG_PATH.read_text(encoding="utf-8"))
    if doc.get("schema_version") != THEME_LOG_SCHEMA_VERSION:
        raise SystemExit(
            f"ERROR: {THEME_LOG_PATH} is not schema_version {THEME_LOG_SCHEMA_VERSION} "
            f"(found {doc.get('schema_version')!r}). Run backfill_theme_log.py first, "
            f"or this script will write an inconsistent shape."
        )
    return doc


def save_theme_log(theme_log: dict):
    THEME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    THEME_LOG_PATH.write_text(json.dumps(theme_log, indent=2, ensure_ascii=False), encoding="utf-8")


def get_sign_theme_history(theme_log: dict, sign_slug: str, before_week: str, limit: int = 4) -> list:
    """Most-recent-first list of {week, theme} for this sign, strictly before `before_week`."""
    entries = [e for e in theme_log["entries"] if e["sign"] == sign_slug and e["week_of"] < before_week]
    entries.sort(key=lambda e: e["week_of"], reverse=True)
    return [{"week": e["week_of"], "theme": e["theme"]} for e in entries[:limit]]


def get_latest_sign_entry(theme_log: dict, sign_slug: str, before_week: str):
    """The single most recent entry for this sign strictly before `before_week`,
    unbounded by the 4-week lookback (used for repeat_streak, which tracks
    literal back-to-back repeats regardless of the exclusion window)."""
    entries = [e for e in theme_log["entries"] if e["sign"] == sign_slug and e["week_of"] < before_week]
    if not entries:
        return None
    return max(entries, key=lambda e: e["week_of"])


def build_theme_log_entry(digest: dict, sign_slug: str, categories_result: dict, repeat_streak: int, theme_rule: str) -> dict:
    categories = {}
    for cat in CATEGORIES:
        c = categories_result[cat]
        categories[cat] = {
            "summary": c["summary"],
            "agreement": c["reader_count"],
            "divergence": None if is_placeholder_disagreement(c["disagreement"]) else c["disagreement"],
        }

    readers = [
        {
            "video_id": r["video_id"],
            "url": r["url"],
            "distinctive_point": r["channel_theme"] or None,
            "reader_tone": r["tone"],
        }
        for r in digest["readers"]
    ]

    return {
        "week_of": digest["week_of"],
        "sign": sign_slug,
        "theme": digest["overall_tone"],
        "theme_rule": theme_rule,
        "repeat_streak": repeat_streak,
        "overall_tone_summary": digest["overall_tone_summary"],
        "categories": categories,
        "readers": readers,
    }


_STREAK_ORDINALS = {
    2: "Second", 3: "Third", 4: "Fourth", 5: "Fifth",
    6: "Sixth", 7: "Seventh", 8: "Eighth", 9: "Ninth", 10: "Tenth",
}


def streak_note(repeat_streak: int) -> str:
    """Factual, non-dramatized note for the digest copy, e.g. 'Second week running.'"""
    if repeat_streak in _STREAK_ORDINALS:
        ordinal = _STREAK_ORDINALS[repeat_streak]
    else:
        suffix = "th" if 10 <= repeat_streak % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(repeat_streak % 10, "th")
        ordinal = f"{repeat_streak}{suffix}"
    return f"{ordinal} week running."


def check_no_existing_entry(theme_log: dict, week: str, sign_slug: str):
    """Refuse to silently overwrite a prior theme-log entry for this sign + week."""
    for entry in theme_log["entries"]:
        if entry["week_of"] == week and entry["sign"] == sign_slug:
            raise SystemExit(
                f"ERROR: theme-log.json already has an entry for '{sign_slug}' / {week}: "
                f"theme={entry['theme']!r}, overall_tone_summary={entry['overall_tone_summary']!r}\n"
                f"Refusing to overwrite silently. If this is intentional, remove the "
                f"existing entry from data/theme-log.json first and re-run."
            )


def parse_week_of(value: str) -> str:
    try:
        d = datetime.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--week-of must be an ISO date (YYYY-MM-DD), got: {value!r}"
        )
    if d.weekday() != 0:
        raise argparse.ArgumentTypeError(
            f"--week-of must be a Monday, got {value} which is a {d.strftime('%A')}."
        )
    return value


def call_json(client: anthropic.Anthropic, prompt: str, schema: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def aggregate_category(client: anthropic.Anthropic, sign: str, category: str, readings: list) -> dict:
    lines = []
    for r in readings:
        theme = r["tags"].get(category)
        lines.append(f"- Reader {r['video_id']}: {theme if theme else 'not discussed'}")
    readers_block = "\n".join(lines)

    prompt = f"""Below are 5 different tarot readers' {category} themes for {sign} this week. Each is already paraphrased in the reader's own words, do not quote them directly, paraphrase further in your own summary.

{readers_block}

Analyze these 5 readings and identify:
a) ONE flowing paragraph (under ~35 words, 1-2 sentences) that blends the shared theme across readers with the single most repeated piece of advice for this category into one cohesive takeaway. Merge them naturally, do not write two separate statements (no "Theme: X. Advice: Y." structure). For example: "Most readers sense a financial turning point this week, so stay persistent and invest your energy in what truly gives back." If most readers did not discuss this category at all, reflect that honestly in the summary instead (e.g. "Few readers touched on family this week; the one who did pointed to...").
b) Roughly how many of the 5 readers touched on that theme, judge by similarity of meaning, not exact wording.
c) Any notable disagreement between readers (e.g. one says reunion, another says ending). If there is no notable disagreement, say so. For contrasting interpretations between readers, use plain, direct language in under 30 words. Prefer phrasing like "Some readers saw..." or "Others suggested..." or "One reading emphasized..." Avoid phrases like "mild tension between readers," "readers who emphasize," "ultimately point toward," or "one frames the shift as." State the two interpretations clearly and concisely.

Set reader_count based on how many of the 5 readers touched on the theme described in the summary.

{NO_EM_DASH_INSTRUCTION}"""

    return call_json(client, prompt, CATEGORY_SCHEMA)


def aggregate_tone(client: anthropic.Anthropic, sign: str, readings: list, history: list, repeats_allowed: bool) -> dict:
    tones = ", ".join(f"{r['video_id']}: {r['tags']['overall_tone']}" for r in readings)

    if repeats_allowed:
        allowed = THEME_VOCABULARY
    else:
        excluded = {h["theme"] for h in history}
        allowed = [t for t in THEME_VOCABULARY if t not in excluded]
        if not allowed:
            raise RuntimeError(
                f"All theme vocabulary words are excluded for {sign} by its last "
                f"{len(history)} week(s) of history ({sorted(excluded)}). "
                f"Refusing to silently pick one — expand THEME_VOCABULARY or "
                f"shorten the lookback window."
            )
    vocab_list = ", ".join(allowed)
    tone_schema = {
        "type": "object",
        "properties": {
            "theme": {"type": "string", "enum": allowed},
            "note": {"type": "string"},
        },
        "required": ["theme", "note"],
        "additionalProperties": False,
    }

    if history and repeats_allowed:
        history_lines = "\n".join(f"  {h['week']}: {h['theme']}" for h in history)
        history_block = f"""

This sign's theme history for the last {len(history)} week(s) (most recent first), for context only:
{history_lines}

This is background, not a restriction. Pick whichever theme genuinely fits this week's readings best, even if that means repeating one of the themes above. Do not avoid a theme just because it appears in this history, and do not favor it either, base the choice purely on this week's 5 readings."""
    elif history:
        history_lines = "\n".join(f"  {h['week']}: {h['theme']}" for h in history)
        history_block = f"""

This sign's theme history for the last {len(history)} week(s) (most recent first):
{history_lines}

Every one of those themes is excluded from the choices below: none of them may be reused within this lookback window, not just the most recent one."""
    else:
        history_block = ""

    prompt = f"""Here are the overall tones assigned to 5 different tarot readings for {sign} this week:

{tones}
{history_block}

Pick exactly ONE dominant theme word from this vocabulary, do not use any word outside this list:
{vocab_list}

If the 5 readings genuinely lean toward two different themes, choose the stronger or more specific one as dominant. Do not blend two theme words together into one phrase (e.g. never "transformative and hopeful" or "hopeful and empowering"), pick one.

Then write ONE short, natural sentence (under 14 words) capturing the week's mood around that single theme. Vary your sentence structure and word choice, don't default to a template like "Mostly [theme] with a note of caution" every time. Write it as if describing this specific week's energy, not filling in a fixed pattern.

{NO_EM_DASH_INSTRUCTION}"""

    return call_json(client, prompt, tone_schema)


def summarize_readers(client: anthropic.Anthropic, sign: str, readings: list) -> dict:
    blocks = []
    for r in readings:
        t = r["tags"]
        blocks.append(
            f"Reader {r['video_id']} (tone: {t['overall_tone']}):\n"
            f"  love: {t['love']}\n"
            f"  finance: {t['finance']}\n"
            f"  career: {t['career']}\n"
            f"  family: {t['family']}"
        )
    prompt = f"""Below are 5 tarot readings for {sign} this week, each already paraphrased.

{chr(10).join(blocks)}

For each reader, write ONE short sentence (your own paraphrase, not a quote) capturing that reader's single most distinctive or notable point this week: the thing that most sets their reading apart from the others. Keep it tight: under 12-15 words, short enough to fit on a single line in a table column. Return one entry per reader, using their exact video_id.

{NO_EM_DASH_INSTRUCTION}"""
    return call_json(client, prompt, READERS_SCHEMA)["readers"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Aggregate a week's tagged readings for one sign into a cross-reader digest."
    )
    parser.add_argument("sign", help="Zodiac sign slug, e.g. aries")
    parser.add_argument(
        "--week-of",
        required=True,
        type=parse_week_of,
        help="ISO date (must be a Monday) for this digest's week, e.g. 2026-08-10",
    )
    parser.add_argument("video_ids", nargs="+", help="Tagged reading video IDs")
    return parser.parse_args()


def main():
    args = parse_args()
    sign_slug = args.sign.strip().lower()
    sign = sign_slug.capitalize()
    video_ids = args.video_ids
    week_of = args.week_of
    output_path = Path(__file__).parent / f"digest_{sign_slug}_week1.json"

    load_env_file(Path(__file__).parent / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        return 1

    try:
        readings = [{"video_id": vid, "tags": load_tagged(vid)} for vid in video_ids]
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    theme_log = load_theme_log()
    check_no_existing_entry(theme_log, week_of, sign_slug)
    history = get_sign_theme_history(theme_log, sign_slug, before_week=week_of)
    repeats_allowed = week_of >= REPEATS_ALLOWED_FROM
    theme_rule = "repeats-allowed" if repeats_allowed else "no-repeat-4wk"

    client = anthropic.Anthropic(api_key=api_key)

    categories_result = {}
    for category in CATEGORIES:
        print(f"Aggregating category: {category}...")
        categories_result[category] = aggregate_category(client, sign, category, readings)

    print("Aggregating overall tone...")
    tone_result = aggregate_tone(client, sign, readings, history, repeats_allowed)

    print("Summarizing each reader's distinctive point...")
    reader_summaries = {r["video_id"]: r["channel_theme"] for r in summarize_readers(client, sign, readings)}

    digest = {
        "sign": sign,
        "week_of": week_of,
        "categories": categories_result,
        "overall_tone": tone_result["theme"],
        "overall_tone_summary": tone_result["note"],
        "readers": [
            {
                "video_id": r["video_id"],
                "channel_theme": reader_summaries.get(r["video_id"], ""),
                "tone": r["tags"]["overall_tone"],
                "url": f"https://www.youtube.com/watch?v={r['video_id']}",
            }
            for r in readings
        ],
    }

    digest = strip_em_dashes_deep(digest)
    remaining = find_em_dashes(digest)
    if remaining:
        print("\nWARNING: em dash(es) survived stripping, flagging for manual review:")
        for hit in remaining:
            print(f"  {hit}")

    latest = get_latest_sign_entry(theme_log, sign_slug, before_week=week_of)
    repeat_streak = latest["repeat_streak"] + 1 if latest and latest["theme"] == digest["overall_tone"] else 1

    if repeats_allowed and repeat_streak >= 2:
        digest["overall_tone_summary"] = f"{digest['overall_tone_summary']} {streak_note(repeat_streak)}"

    output_path.write_text(json.dumps(digest, indent=2), encoding="utf-8")

    theme_log_entry = build_theme_log_entry(digest, sign_slug, digest["categories"], repeat_streak, theme_rule)
    remaining_entry = find_em_dashes(theme_log_entry, path="theme_log_entry")
    if remaining_entry:
        print("\nWARNING: em dash(es) survived stripping in theme-log entry, flagging for manual review:")
        for hit in remaining_entry:
            print(f"  {hit}")

    theme_log["entries"].append(theme_log_entry)
    save_theme_log(theme_log)

    print("\n" + "=" * 70)
    print(f"{sign.upper()} DIGEST, week of {digest['week_of']}")
    print("=" * 70)
    print(f"\nOverall theme: {digest['overall_tone']}")
    print(f"Overall tone note: {digest['overall_tone_summary']}\n")

    for category in CATEGORIES:
        c = digest["categories"][category]
        print(f"--- {category.upper()} ---")
        print(f"  Summary: {c['summary']}")
        print(f"  Readers touching on this: {c['reader_count']}/{len(readings)}")
        print(f"  Disagreement: {c['disagreement'] or 'None noted'}")
        print()

    print("--- READERS ---")
    for r in digest["readers"]:
        print(f"  [{r['video_id']}] ({r['tone']}) {r['channel_theme']}")
        print(f"    {r['url']}")

    print(f"\nSaved full digest to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
