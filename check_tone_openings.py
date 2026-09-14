"""Flag exact or near-duplicate overall_tone_summary openings across this
week's 12 signs, in each language. Read-only: reports only, never rewrites
digest JSON or reroll anything. Run after all 12 aggregate_digest.py calls
for the week, before build_site.py.

Compares the first sentence of each sign's overall_tone_summary (the part
aggregate_tone() writes; any appended repeat_streak sentence, e.g. "Second
week running.", is a separate trailing sentence and is excluded by taking
only the first one). Two kinds of flag:
  EXACT - the first few words match verbatim (normalized) across signs.
  NEAR  - the opening sentences are highly similar (difflib ratio) without
          matching verbatim.
Exit code is 1 if anything was flagged, 0 otherwise; this is informational
only; nothing in this repo currently acts on it automatically.
"""
from pathlib import Path
from difflib import SequenceMatcher
import json
import re
import sys

from generate_index_html import ZODIAC_ORDER

ROOT = Path(__file__).resolve().parent

EXACT_PREFIX_WORDS = 4
NEAR_RATIO_THRESHOLD = 0.6


def first_sentence(text: str) -> str:
    match = re.match(r"[^.!?]*[.!?]", text.strip())
    return (match.group(0) if match else text).strip()


def normalized_prefix(sentence: str, word_count: int) -> str:
    words = re.findall(r"[a-z']+", sentence.lower())
    return " ".join(words[:word_count])


def load_openings(lang: str) -> dict:
    suffix = "" if lang == "en" else "_es"
    openings = {}
    for sign in ZODIAC_ORDER:
        path = ROOT / f"digest_{sign}_week1{suffix}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        openings[sign] = first_sentence(data["overall_tone_summary"])
    return openings


def find_duplicates(openings: dict) -> list[dict]:
    signs = list(openings)
    flags = []
    for i, sign_a in enumerate(signs):
        for sign_b in signs[i + 1:]:
            sentence_a, sentence_b = openings[sign_a], openings[sign_b]
            prefix_a = normalized_prefix(sentence_a, EXACT_PREFIX_WORDS)
            prefix_b = normalized_prefix(sentence_b, EXACT_PREFIX_WORDS)
            if prefix_a and prefix_a == prefix_b:
                flags.append({
                    "kind": "exact",
                    "signs": (sign_a, sign_b),
                    "openings": (sentence_a, sentence_b),
                })
                continue
            ratio = SequenceMatcher(None, sentence_a.lower(), sentence_b.lower()).ratio()
            if ratio >= NEAR_RATIO_THRESHOLD:
                flags.append({
                    "kind": "near",
                    "signs": (sign_a, sign_b),
                    "openings": (sentence_a, sentence_b),
                    "ratio": round(ratio, 2),
                })
    return flags


def main():
    any_flags = False
    for lang in ("en", "es"):
        openings = load_openings(lang)
        if not openings:
            continue
        flags = find_duplicates(openings)
        print(f"== {lang.upper()}: {len(openings)}/12 signs checked ==")
        if not flags:
            print("  no exact or near-duplicate openings found")
            continue
        any_flags = True
        flags.sort(key=lambda f: (f["kind"] != "exact", f["signs"]))
        for flag in flags:
            sign_a, sign_b = flag["signs"]
            opening_a, opening_b = flag["openings"]
            label = "EXACT" if flag["kind"] == "exact" else f"NEAR({flag['ratio']})"
            print(f"  {label}  {sign_a} / {sign_b}")
            print(f"    {sign_a}: {opening_a}")
            print(f"    {sign_b}: {opening_b}")
        print()
    if not any_flags:
        print("PASS: no duplicate or near-duplicate overall_tone_summary openings this week.")
    return 1 if any_flags else 0


if __name__ == "__main__":
    sys.exit(main())
