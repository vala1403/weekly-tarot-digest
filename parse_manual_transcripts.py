"""Parse manually-saved YouTube transcript .txt files into clean per-video text
files under transcripts/, ready for tag_transcripts.py.

Expected input: a folder of files named "{sign}-{n}.txt" (n = 1..5, sign name
case-insensitive, tolerant of minor typos). Each file's first non-empty line
is the source YouTube URL; everything after is a raw YouTube transcript
copy-paste with timestamp prefixes like "0:000 seconds" or
"13:2913 minutes, 29 seconds" immediately followed by the spoken text, plus
YouTube UI boilerplate ("Transcript", "Search transcript", and partial words
like "nscript"/"anscript" where the copy started mid-word).

Usage: python3 parse_manual_transcripts.py --week-of YYYY-MM-DD [--source-dir DIR]

Only parses and reports — never tags or aggregates. Re-running is safe and
idempotent: re-parsing a sign just rewrites its transcripts/<video_id>.txt
files with the same content.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from aggregate_digest import parse_week_of

BASE_DIR = Path(__file__).parent
TRANSCRIPTS_DIR = BASE_DIR / "transcripts"

SIGNS = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
]

MIN_CHARS_WARNING = 3000
EXPECTED_FILES_PER_SIGN = 5

FILENAME_RE = re.compile(r"^([a-zA-Z]+)-(\d+)$")
TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}\d+ (?:minutes?|seconds?)(?:, \d+ seconds?)?")
# Covers every point a copy-paste could start mid-word inside "Transcript"
# (ript/cript/script/nscript/anscript/ranscript/transcript), not just the
# n-prefixed forms.
_TRANSCRIPT_SUFFIXES = ["ript", "cript", "script", "nscript", "anscript", "ranscript", "transcript"]
BOILERPLATE_RE = re.compile(
    r"^(?:" + "|".join(_TRANSCRIPT_SUFFIXES) + r"|search transcript|sync to video time)$",
    re.IGNORECASE,
)


def match_sign(raw_name: str) -> str | None:
    name = raw_name.lower()
    if name in SIGNS:
        return name
    close = difflib.get_close_matches(name, SIGNS, n=1, cutoff=0.7)
    return close[0] if close else None


def video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    if "v" in q and q["v"][0]:
        return q["v"][0]
    tail = parsed.path.rstrip("/").split("/")[-1]
    return tail or None


def parse_file(path: Path) -> tuple[str | None, str]:
    """Returns (url_or_None, cleaned_text)."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    idx = 0
    url = None
    while idx < len(lines):
        if lines[idx].strip():
            url = lines[idx].strip()
            idx += 1
            break
        idx += 1

    body_parts = []
    for line in lines[idx:]:
        stripped = line.strip()
        if not stripped:
            continue
        if BOILERPLATE_RE.match(stripped):
            continue
        m = TIMESTAMP_RE.match(stripped)
        text = stripped[m.end():].strip() if m else stripped
        if text:
            body_parts.append(text)

    full_text = re.sub(r"\s+", " ", " ".join(body_parts)).strip()
    return url, full_text


def discover_files(source_dir: Path) -> dict[str, list[Path]]:
    """Maps canonical sign -> sorted list of matched files. Also prints unmatched files."""
    by_sign: dict[str, list[Path]] = {s: [] for s in SIGNS}
    unmatched = []
    for path in sorted(source_dir.glob("*.txt")):
        m = FILENAME_RE.match(path.stem)
        if not m:
            unmatched.append(path)
            continue
        raw_sign, _n = m.groups()
        sign = match_sign(raw_sign)
        if sign is None:
            unmatched.append(path)
            continue
        by_sign[sign].append(path)

    if unmatched:
        print("WARNING: files that did not match any sign pattern (ignored):")
        for p in unmatched:
            print(f"  {p}")
        print()

    return by_sign


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--week-of",
        required=True,
        type=parse_week_of,
        help="ISO date (must be a Monday) identifying the week these transcripts cover, e.g. 2026-08-10",
    )
    parser.add_argument(
        "--source-dir",
        default=None,
        help="Folder containing {sign}-{n}.txt files. Defaults to /mnt/c/tarot/<week-of>/",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir) if args.source_dir else Path(f"/mnt/c/tarot/{args.week_of}")
    if not source_dir.exists():
        print(f"ERROR: source folder not found: {source_dir}")
        return 1

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    by_sign = discover_files(source_dir)

    any_flags = False
    for sign in SIGNS:
        files = by_sign[sign]
        print("=" * 70)
        print(f"{sign.upper()}  ({len(files)} file{'s' if len(files) != 1 else ''} found)")
        if len(files) != EXPECTED_FILES_PER_SIGN:
            print(f"  !! FLAG: expected {EXPECTED_FILES_PER_SIGN} files, found {len(files)}")
            any_flags = True
        print("=" * 70)

        for path in files:
            url, text = parse_file(path)
            char_count = len(text)
            flags = []
            if char_count < MIN_CHARS_WARNING:
                flags.append(f"UNDER {MIN_CHARS_WARNING} CHARS")
            if url is None:
                flags.append("NO URL FOUND")

            video_id = video_id_from_url(url) if url else None
            if video_id is None:
                flags.append("NO VIDEO ID")

            flag_str = f"  !! FLAG: {', '.join(flags)}" if flags else ""
            if flags:
                any_flags = True

            print(f"\n  {path.name}")
            print(f"    url: {url or '(none)'}")
            print(f"    chars: {char_count}{flag_str}")
            print(f"    preview: {text[:200]!r}")

            if video_id and text:
                out_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
                out_path.write_text(text, encoding="utf-8")
                print(f"    -> wrote {out_path}")
            else:
                print(f"    -> SKIPPED writing (missing url/video_id or empty text)")
        print()

    print("=" * 70)
    print("DONE PARSING." + (" Some files were flagged above — review before tagging." if any_flags else " No flags."))
    print("Nothing was tagged or aggregated. Aries's existing tagged/theme-log data was not touched.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
