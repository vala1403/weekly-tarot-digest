"""Generate a ~30-second video script per sign from data/theme-log.json.

Usage: python3 generate_video_script.py --week-of YYYY-MM-DD
Reads data/theme-log.json (read-only, never written to here) for the given
week's 12 sign entries and writes scripts/<week-of>/<sign>.txt, one file per
sign.

--week-of must be an ISO date that falls on a Monday and is always required,
matching aggregate_digest.py's convention: this script never infers the week
from the run date.

Selection rules are applied here in Python, never left to the model's
judgment:
  - Lead with the highest-agreement category. Categories tied at the top are
    named as a tie, never collapsed to a single "strongest" one.
  - A runner-up category (or categories, if more than one is equally
    qualified) is added only when it sits exactly one agreement count behind
    a single, untied leader. If the lead is already a tie, no runner-up is
    added on top of it.
  - Every lead category's divergence becomes the closing beat before the
    CTA. A single leader contributes its one divergence (if it has one); a
    tie contributes each tied category's divergence that exists, attributed
    to its category, rather than picking just one to stand in for "the"
    lead.
  - repeat_streak is mentioned only at 2 or more.
  - Anything above that the data doesn't actually contain (a null
    divergence, a streak of 1) is simply omitted from what the model is
    told exists -- never invented to fill the gap.

The model (claude-sonnet-4-6) only turns this pre-selected fact packet into
the ~90-word spoken script; it does not decide what facts appear, and is
told not to add anything beyond them.
"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

import anthropic

from generate_digest_html import CATEGORY_ORDER, CATEGORY_LABELS
from generate_index_html import ZODIAC_ORDER

ROOT = Path(__file__).resolve().parent
MODEL = "claude-sonnet-4-6"

WORDS_PER_SECOND = 2.5  # 150 wpm; 85-95 words lands at 34-38s, so 38s is the flag line.
FLAG_SECONDS = 38.0

NUMBER_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
ORDINAL_WORDS = {2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth"}

NO_EM_DASH_INSTRUCTION = (
    "Do not use em dashes (—) anywhere in your response. Use commas, "
    "colons, or separate sentences instead."
)

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {"script": {"type": "string"}},
    "required": ["script"],
    "additionalProperties": False,
}


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


def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def reader_count_phrase(count: int) -> str:
    if count == 5:
        return "all five readers"
    return f"{NUMBER_WORDS[count]} of the five readers"


def ordinal_word(n: int) -> str:
    return ORDINAL_WORDS.get(n, f"{n}th")


def load_theme_log() -> dict:
    return json.loads((ROOT / "data" / "theme-log.json").read_text(encoding="utf-8"))


def get_entry(theme_log: dict, week_of: str, sign_slug: str) -> dict:
    for entry in theme_log["entries"]:
        if entry["week_of"] == week_of and entry["sign"] == sign_slug:
            return entry
    raise LookupError(f"No theme-log entry for {sign_slug}, week_of {week_of}.")


def category_fact(categories: dict, cat: str) -> dict:
    data = categories[cat]
    return {
        "category": cat,
        "label": CATEGORY_LABELS["en"][cat].lower(),
        "count_phrase": reader_count_phrase(data["agreement"]),
        "summary": data["summary"],
    }


def select_facts(entry: dict) -> dict:
    categories = entry["categories"]
    present = [cat for cat in CATEGORY_ORDER if cat in categories]
    max_agreement = max(categories[cat]["agreement"] for cat in present)
    leaders = [cat for cat in present if categories[cat]["agreement"] == max_agreement]
    is_tie = len(leaders) > 1

    second = []
    if not is_tie:
        second = [
            cat for cat in present
            if cat != leaders[0] and categories[cat]["agreement"] == max_agreement - 1
        ]

    divergences = [
        {"label": CATEGORY_LABELS["en"][cat].lower(), "text": categories[cat]["divergence"]}
        for cat in leaders if categories[cat].get("divergence")
    ]

    repeat_streak = entry.get("repeat_streak", 1)
    streak_ordinal = ordinal_word(repeat_streak) if repeat_streak and repeat_streak >= 2 else None

    return {
        "sign": entry["sign"].capitalize(),
        "is_tie": is_tie,
        "leaders": [category_fact(categories, cat) for cat in leaders],
        "second": [category_fact(categories, cat) for cat in second],
        "divergences": divergences,
        "streak_ordinal": streak_ordinal,
    }


def build_facts_block(facts: dict) -> str:
    lines = []
    if facts["is_tie"]:
        labels = [l["label"] for l in facts["leaders"]]
        names = labels[0] + " and " + labels[1] if len(labels) == 2 else ", ".join(labels[:-1]) + f", and {labels[-1]}"
        all_of_them = "both" if len(labels) == 2 else f"all {NUMBER_WORDS[len(labels)]}"
        counts = facts["leaders"][0]["count_phrase"]
        lines.append(
            f"- {names} are tied for the most reader agreement this week, {all_of_them} touched "
            f"on by {counts}. Present this explicitly as a tie between them; do not "
            f"present one as leading over the other."
        )
        for l in facts["leaders"]:
            lines.append(f"  {l['label']}: {l['summary']}")
    else:
        leader = facts["leaders"][0]
        lines.append(f"- Leading category: {leader['label']}, touched on by {leader['count_phrase']}.")
        lines.append(f"  {leader['label']}: {leader['summary']}")
        for s in facts["second"]:
            lines.append(
                f"- Runner-up, one behind the leader: {s['label']}, touched on by {s['count_phrase']}. "
                f"Mention this briefly alongside the leader."
            )
            lines.append(f"  {s['label']}: {s['summary']}")

    divergences = facts["divergences"]
    if not divergences:
        lines.append("- No disagreement beat: do not invent one.")
    elif len(divergences) == 1:
        lines.append(
            "- Closing beat, right before the sign-off: readers notably disagreed on the "
            f"lead category. {divergences[0]['text']}"
        )
    else:
        lines.append(
            "- Closing beat, right before the sign-off: the tied lead categories each had "
            "their own reader disagreement. Mention both (briefly, attributed to their "
            "category), not just one:"
        )
        for div in divergences:
            lines.append(f"  {div['label']} disagreement: {div['text']}")

    if facts["streak_ordinal"]:
        lines.append(
            f"- This sign's theme has now repeated for the {facts['streak_ordinal']} week in a "
            f"row. Work this in naturally, spelled out in words, not as a numeral."
        )

    return "\n".join(lines)


def build_prompt(facts: dict) -> str:
    facts_block = build_facts_block(facts)
    return f"""You are writing a 30-second vertical video script for {facts['sign']}'s weekly tarot digest, to be read aloud by a host.

Use ONLY the facts below. Do not add any category, count, or claim that isn't listed here, and do not give advice or make a prediction of your own; report only what the readers collectively noticed.

{facts_block}

Voice: warm, observational, conversational, like catching a friend up on something real, not a fortune teller putting on a show. Open the script with "Hi {facts['sign']}." as the first two words, exactly. Spell out every count as words (e.g. "four of the five readers"), never as digits. Close with one line pointing the viewer to the full digest, linked in bio; exact wording is up to you.

Length: 85 to 95 words total, no more. Count as you write. This is a hard ceiling, not a rough target: if you are running long, compress by cutting connective throat-clearing ("here is what your readers picked up on," "worth noting though") and shortening clauses, never by dropping any of the facts above. Every sentence should carry information. Revise your draft down to the ceiling before answering.

{NO_EM_DASH_INSTRUCTION}

Return only the finished spoken script as plain text: no stage directions, no headers, no bullet points."""


def call_script(client: anthropic.Anthropic, prompt: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        output_config={"format": {"type": "json_schema", "schema": SCRIPT_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["script"].strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def flag_reason(facts: dict) -> str:
    """Distinguish length driven by real content (multiple divergences to
    report faithfully) from length that's just verbose phrasing, so a
    reviewer can tell at a glance which flags need a trim and which are
    long because the week's data genuinely has that much to say."""
    divergence_count = len(facts["divergences"])
    if divergence_count >= 2:
        return f"content-heavy: {divergence_count} divergences"
    return "verbose"


def render_file(script: str, facts: dict) -> tuple[str, int, float, bool, str | None]:
    count = word_count(script)
    seconds = count / WORDS_PER_SECOND
    flagged = seconds > FLAG_SECONDS
    reason = flag_reason(facts) if flagged else None
    header = f"WORDS: {count}  |  EST: {seconds:.1f}s"
    if flagged:
        header += f"  |  FLAG: exceeds {FLAG_SECONDS:.0f}s target ({reason})"
    return f"{header}\n\n{script}\n", count, seconds, flagged, reason


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a ~30-second video script per sign from data/theme-log.json."
    )
    parser.add_argument(
        "--week-of",
        required=True,
        type=parse_week_of,
        help="ISO date (must be a Monday) for the week to script, e.g. 2026-09-14",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    week_of = args.week_of

    load_env_file(ROOT / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        return 1

    theme_log = load_theme_log()
    try:
        entries = {sign: get_entry(theme_log, week_of, sign) for sign in ZODIAC_ORDER}
    except LookupError as e:
        print(f"ERROR: {e}")
        return 1

    out_dir = ROOT / "scripts" / week_of
    out_dir.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic(api_key=api_key)
    flagged_signs = []
    for sign in ZODIAC_ORDER:
        facts = select_facts(entries[sign])
        prompt = build_prompt(facts)
        script = call_script(client, prompt)
        content, count, seconds, flagged, reason = render_file(script, facts)
        (out_dir / f"{sign}.txt").write_text(content, encoding="utf-8")
        flag_note = f"  <-- FLAG ({reason})" if flagged else ""
        print(f"{sign:12s} {count:3d} words  {seconds:5.1f}s{flag_note}")
        if flagged:
            flagged_signs.append((sign, reason))

    print(f"\nWrote {len(ZODIAC_ORDER)} scripts to {out_dir}")
    if flagged_signs:
        summary = ", ".join(f"{sign} ({reason})" for sign, reason in flagged_signs)
        print(f"Flagged for review (over {FLAG_SECONDS:.0f}s): {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
