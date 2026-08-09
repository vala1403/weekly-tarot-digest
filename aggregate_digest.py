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


def load_tagged(video_id: str) -> dict:
    path = TAGGED_DIR / f"{video_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"tagged file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_theme_log() -> list:
    if not THEME_LOG_PATH.exists():
        return []
    return json.loads(THEME_LOG_PATH.read_text(encoding="utf-8"))


def save_theme_log(theme_log: list):
    THEME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    THEME_LOG_PATH.write_text(json.dumps(theme_log, indent=2), encoding="utf-8")


def get_sign_theme_history(theme_log: list, sign_slug: str, before_week: str, limit: int = 4) -> list:
    """Most-recent-first list of {week, theme} for this sign, strictly before `before_week`."""
    entries = [w for w in theme_log if w["week"] < before_week and sign_slug in w.get("signs", {})]
    entries.sort(key=lambda w: w["week"], reverse=True)
    return [{"week": w["week"], "theme": w["signs"][sign_slug]["theme"]} for w in entries[:limit]]


def upsert_theme_log_entry(theme_log: list, week: str, sign_slug: str, theme: str, note: str) -> list:
    for entry in theme_log:
        if entry["week"] == week:
            entry.setdefault("signs", {})[sign_slug] = {"theme": theme, "note": note}
            return theme_log
    theme_log.append({"week": week, "signs": {sign_slug: {"theme": theme, "note": note}}})
    return theme_log


def check_no_existing_entry(theme_log: list, week: str, sign_slug: str):
    """Refuse to silently overwrite a prior theme-log entry for this sign + week."""
    for entry in theme_log:
        if entry["week"] == week and sign_slug in entry.get("signs", {}):
            existing = entry["signs"][sign_slug]
            raise SystemExit(
                f"ERROR: theme-log.json already has an entry for '{sign_slug}' / {week}: "
                f"theme={existing['theme']!r}, note={existing['note']!r}\n"
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


def aggregate_tone(client: anthropic.Anthropic, sign: str, readings: list, history: list) -> dict:
    tones = ", ".join(f"{r['video_id']}: {r['tags']['overall_tone']}" for r in readings)

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

    if history:
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

    client = anthropic.Anthropic(api_key=api_key)

    categories_result = {}
    for category in CATEGORIES:
        print(f"Aggregating category: {category}...")
        categories_result[category] = aggregate_category(client, sign, category, readings)

    print("Aggregating overall tone...")
    tone_result = aggregate_tone(client, sign, readings, history)

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

    output_path.write_text(json.dumps(digest, indent=2), encoding="utf-8")

    theme_log = upsert_theme_log_entry(
        theme_log, week_of, sign_slug, digest["overall_tone"], digest["overall_tone_summary"]
    )
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
