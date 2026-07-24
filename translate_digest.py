"""Translate a sign's digest JSON into natural, idiomatic Spanish.

Usage: python3 translate_digest.py <sign>
  e.g. python3 translate_digest.py pisces
Reads digest_<sign>_week1.json, writes digest_<sign>_week1_es.json.

Video IDs, URLs, dates, and reader_count are copied through unchanged.
Everything else (the combined theme+advice summary per category,
disagreement text, tone words, overall mood summary, each reader's
one-line theme) is translated by the API.
The zodiac sign name itself is mapped via a fixed table, not translated
freely, so it's always the correct standard Spanish name.
"""
import json
import os
import sys
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
CATEGORIES = ["love", "finance", "career", "family"]

ZODIAC_ES = {
    "aries": "Aries",
    "taurus": "Tauro",
    "gemini": "Géminis",
    "cancer": "Cáncer",
    "leo": "Leo",
    "virgo": "Virgo",
    "libra": "Libra",
    "scorpio": "Escorpio",
    "sagittarius": "Sagitario",
    "capricorn": "Capricornio",
    "aquarius": "Acuario",
    "pisces": "Piscis",
}

TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_tone_summary": {"type": "string"},
        "categories": {
            "type": "object",
            "properties": {
                cat: {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "disagreement": {"type": ["string", "null"]},
                    },
                    "required": ["summary", "disagreement"],
                    "additionalProperties": False,
                }
                for cat in CATEGORIES
            },
            "required": CATEGORIES,
            "additionalProperties": False,
        },
        "readers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "video_id": {"type": "string"},
                    "channel_theme": {"type": "string"},
                    "tone": {"type": "string"},
                },
                "required": ["video_id", "channel_theme", "tone"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["overall_tone_summary", "categories", "readers"],
    "additionalProperties": False,
}


def is_placeholder_disagreement(text):
    if not text:
        return True
    lowered = text.lower()
    return "no notable disagreement" in lowered or "no strong disagreement" in lowered


def load_env_file(path: Path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def build_prompt(digest: dict) -> str:
    lines = [
        f"Overall mood summary: {digest['overall_tone_summary']}",
        "",
    ]
    for cat in CATEGORIES:
        c = digest["categories"][cat]
        lines.append(f"[{cat}]")
        lines.append(f"  summary: {c['summary']}")
        lines.append(f"  disagreement: {c['disagreement']}")
        lines.append("")
    lines.append("[readers]")
    for r in digest["readers"]:
        lines.append(f"  video_id: {r['video_id']}")
        lines.append(f"  channel_theme: {r['channel_theme']}")
        lines.append(f"  tone: {r['tone']}")
        lines.append("")
    content_block = "\n".join(lines)

    return f"""Translate the following tarot-reading digest content from English to natural, idiomatic Spanish. This is for a Spanish-speaking audience reading a weekly astrology/tarot digest — the tone should read as if originally written in Spanish, not as a literal word-for-word translation.

{content_block}

Instructions:
- Translate every text field (each category's combined summary, disagreement text, the overall mood summary, and each reader's channel_theme) into natural, idiomatic Spanish. Paraphrase as needed to sound native — do not translate word-for-word.
- The "summary" field blends a theme with advice into one cohesive takeaway — keep that same merged, single-paragraph structure in the Spanish translation. Do not split it back into two separate statements.
- Translate tone words into their natural Spanish equivalents (e.g. "hopeful" -> "esperanzador", "cautionary" -> "cauteloso", "liberating" -> "liberador", "transformative" -> "transformador"). Use single-word adjectives matching the grammatical gender/form of the originals where natural.
- If a "disagreement" value is null, keep it null. If it says there's no notable disagreement, translate that statement naturally too (don't invent content).
- Do NOT translate the video_id values — copy them through exactly as given, used only to match entries.
- Keep the same number of readers, in the same video_id order, one output entry per reader.
- Return only the translated fields per the schema — do not add commentary."""


def call_translation(client: anthropic.Anthropic, digest: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        output_config={"format": {"type": "json_schema", "schema": TRANSLATION_SCHEMA}},
        messages=[{"role": "user", "content": build_prompt(digest)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 translate_digest.py <sign>")
        print("  e.g. python3 translate_digest.py pisces")
        return 1

    sign_slug = sys.argv[1].strip().lower()
    input_path = Path(__file__).parent / f"digest_{sign_slug}_week1.json"
    output_path = Path(__file__).parent / f"digest_{sign_slug}_week1_es.json"

    if not input_path.exists():
        print(f"ERROR: {input_path} not found")
        return 1

    if sign_slug not in ZODIAC_ES:
        print(f"ERROR: unknown zodiac sign '{sign_slug}'. Known signs: {', '.join(ZODIAC_ES)}")
        return 1

    load_env_file(Path(__file__).parent / ".env")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        return 1

    digest = json.loads(input_path.read_text(encoding="utf-8"))
    client = anthropic.Anthropic(api_key=api_key)

    print(f"Translating {input_path.name} to Spanish...")
    translated = call_translation(client, digest)

    reader_lookup = {r["video_id"]: r for r in translated["readers"]}

    digest_es = {
        "sign": ZODIAC_ES[sign_slug],
        "week_of": digest["week_of"],
        "categories": {
            cat: {
                "summary": translated["categories"][cat]["summary"],
                "reader_count": digest["categories"][cat]["reader_count"],
                # Decide null-vs-text from the English source, not the translated
                # text — the "no disagreement" placeholder phrase this checks
                # for is English-only, so checking the translation would
                # silently fail to suppress the callout once translated.
                "disagreement": None if is_placeholder_disagreement(digest["categories"][cat]["disagreement"]) else translated["categories"][cat]["disagreement"],
            }
            for cat in CATEGORIES
        },
        "overall_tone_summary": translated["overall_tone_summary"],
        "readers": [
            {
                "video_id": r["video_id"],
                "channel_theme": reader_lookup[r["video_id"]]["channel_theme"],
                "tone": reader_lookup[r["video_id"]]["tone"],
                "url": r["url"],
            }
            for r in digest["readers"]
        ],
    }

    output_path.write_text(json.dumps(digest_es, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"TRANSLATION SUMMARY — {digest['sign']} -> {digest_es['sign']}")
    print("=" * 70)
    print(f"\nOverall tone summary:\n  EN: {digest['overall_tone_summary']}\n  ES: {digest_es['overall_tone_summary']}\n")

    for cat in CATEGORIES:
        en_c = digest["categories"][cat]
        es_c = digest_es["categories"][cat]
        print(f"--- {cat.upper()} ---")
        print(f"  Summary EN: {en_c['summary']}")
        print(f"  Summary ES: {es_c['summary']}")
        print(f"  Disagreement EN: {en_c['disagreement']}")
        print(f"  Disagreement ES: {es_c['disagreement']}")
        print()

    print("--- READERS ---")
    for en_r, es_r in zip(digest["readers"], digest_es["readers"]):
        print(f"  [{en_r['video_id']}] tone: {en_r['tone']} -> {es_r['tone']}")
        print(f"    EN: {en_r['channel_theme']}")
        print(f"    ES: {es_r['channel_theme']}")

    print(f"\nSaved Spanish digest to: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
