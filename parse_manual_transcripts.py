"""Parse manually-saved YouTube transcript .txt files into clean per-video text
files under transcripts/, ready for tag_transcripts.py.

Expected input: a folder of files named "{sign}-{n}.txt" (n = 1..5, sign name
case-insensitive, tolerant of minor typos). Each file's first non-empty line
is the source YouTube URL; everything after is a raw YouTube transcript
copy-paste with timestamp prefixes like "0:000 seconds" or
"13:2913 minutes, 29 seconds" immediately followed by the spoken text, plus
YouTube UI boilerplate ("Transcript", "Search transcript", and partial words
like "nscript"/"anscript" where the copy started mid-word).

Header formats:

- Weeks BEFORE 2026-09-14 ("legacy"): the URL is followed directly by the
  transcript body. The reader's channel name, if any, is best-effort-extracted
  from the spoken opening by extract_channel_name(); there is no video-title or
  subscriber-count line.
- Weeks ON OR AFTER 2026-09-14 ("metadata", NEW_HEADER_FROM): the source paste
  now carries a fixed metadata block between the URL and the transcript body --
  a video-title line (sign name + date range), the channel name repeated on one
  or two consecutive lines, then an "N subscribers" line (e.g. "15.7K
  subscribers"). Blank-line counts vary between files, so this block is parsed
  by pattern, anchored on the "N subscribers" line, never by line number. The
  channel (channel_source "manual"), the video_title, and the raw
  subscribers_at_capture string are recorded in the <video_id>.channel.json
  sidecar. subscribers_at_capture is kept verbatim, not parsed to a number: it
  is point-in-time and must not be read as a current count. This format is not
  applied retroactively to earlier weeks.

Usage: python3 parse_manual_transcripts.py --week-of YYYY-MM-DD [--source-dir DIR]

Only parses and reports — never tags or aggregates. Re-running is safe and
idempotent: re-parsing a sign just rewrites its transcripts/<video_id>.txt
files with the same content.
"""
import argparse
import difflib
import json
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

# Weeks on or after this date use the "metadata" header format (video title,
# repeated channel name, "N subscribers" line between the URL and the transcript
# body). Earlier weeks are parsed as "legacy" and are never reprocessed under
# the new rules.
NEW_HEADER_FROM = "2026-09-14"

FILENAME_RE = re.compile(r"^([a-zA-Z]+)-(\d+)$")
TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}\d+ (?:minutes?|seconds?)(?:, \d+ seconds?)?")
# The metadata-header subscriber line, e.g. "15.7K subscribers", "1M
# subscribers", "652 subscribers". Kept verbatim as subscribers_at_capture.
SUBSCRIBER_RE = re.compile(r"^\d[\d.,]*[KMB]? subscribers?$", re.IGNORECASE)
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


# Ordered candidate patterns for a reader's self-introduced channel name. "welcome (back) to"
# is matched case-insensitively, but the captured name itself must start with a real capital
# letter -- otherwise generic lowercase leads like "your week ahead reading" or "my channel"
# would slip through as false positives.
CHANNEL_PATTERNS = [
    re.compile(r"(?i:welcome (?:back )?to) (?:the channel )?([A-Z][A-Za-z0-9'\-]*(?:\s+[A-Za-z0-9'\-]+){0,5})"),
    re.compile(r"(?i:welcome to) (?:uh |um )?([A-Z][A-Za-z0-9'\-]*(?:\s+[A-Za-z0-9'\-]+){0,5}) channel\b"),
]

_CHANNEL_STOPWORDS_AFTER = re.compile(
    r"\b(?:this is|my name|i am|i'm|for a|for this|hope|welcome|and welcome|let'?s|thank you)\b",
    re.IGNORECASE,
)


def _clean_channel_candidate(raw: str) -> str | None:
    text = re.sub(r"^(?:uh|um)\s+", "", raw.strip(), flags=re.IGNORECASE)
    if not text:
        return None
    low = text.lower()
    if low.startswith("my channel") or low.startswith("the channel") or low == "my":
        return None
    m = _CHANNEL_STOPWORDS_AFTER.search(text)
    if m:
        text = text[: m.start()].strip()
    text = re.sub(r"[.,!?]+$", "", text).strip()
    text = re.sub(r"\s+(?:and|channel)$", "", text, flags=re.IGNORECASE).strip()
    if not text or text.lower() in {"my channel", "the channel"}:
        return None
    if not re.search(r"[A-Za-z]{2,}", text) or len(text.split()) > 6:
        return None
    return text


def extract_channel_name(full_text: str) -> str | None:
    """Best-effort extraction of a reader's self-introduced channel name from the opening
    of the transcript (e.g. "...welcome to Northern Oracle. This is your reading..."). Returns
    the name exactly as transcribed -- including any ASR mishearing/typos -- never a normalized
    or guessed value. Returns None when no self-introduction is present, rather than guessing."""
    window = full_text[:400]
    for pat in CHANNEL_PATTERNS:
        m = pat.search(window)
        if m:
            candidate = _clean_channel_candidate(m.group(1))
            if candidate:
                return candidate
    return None


def video_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    if "v" in q and q["v"][0]:
        return q["v"][0]
    tail = parsed.path.rstrip("/").split("/")[-1]
    return tail or None


def _clean_body(lines: list[str]) -> str:
    """Collapse a run of raw transcript lines into one clean string: drop blank
    lines and YouTube UI boilerplate, strip the "0:000 seconds" style timestamp
    prefix off each remaining line, and normalize whitespace."""
    body_parts = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if BOILERPLATE_RE.match(stripped):
            continue
        m = TIMESTAMP_RE.match(stripped)
        text = stripped[m.end():].strip() if m else stripped
        if text:
            body_parts.append(text)
    return re.sub(r"\s+", " ", " ".join(body_parts)).strip()


def parse_file(path: Path, header_format: str = "legacy", expected_sign: str | None = None) -> dict:
    """Parse one "{sign}-{n}.txt" source file.

    Returns a dict with keys: url, text, channel, channel_source, video_title,
    subscribers_at_capture, warnings.

    header_format="legacy" (weeks before NEW_HEADER_FROM): the URL is followed
    directly by the transcript body. channel is best-effort-extracted from the
    spoken opening (channel_source "transcript" when found, else None);
    video_title and subscribers_at_capture stay None. Byte-for-byte the previous
    behaviour.

    header_format="metadata" (NEW_HEADER_FROM on): a fixed block sits between the
    URL and the body -- a video-title line, the channel name repeated on one or
    two consecutive lines, then an "N subscribers" line. Parsed by pattern
    (anchored on the subscriber line), tolerant of varying blank-line counts.
    channel_source is "manual"; subscribers_at_capture is the raw string.
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    warnings: list[str] = []

    # URL: first non-empty line.
    idx = 0
    url = None
    while idx < len(lines):
        if lines[idx].strip():
            url = lines[idx].strip()
            idx += 1
            break
        idx += 1

    result = {
        "url": url,
        "text": "",
        "channel": None,
        "channel_source": None,
        "video_title": None,
        "subscribers_at_capture": None,
        "warnings": warnings,
    }

    if header_format == "metadata":
        # Anchor on the "N subscribers" line; everything between it and the URL
        # is the metadata block, everything after it is the transcript body.
        sub_i = next(
            (i for i in range(idx, len(lines)) if SUBSCRIBER_RE.match(lines[i].strip())),
            None,
        )
        if sub_i is None:
            warnings.append(
                "metadata header: no 'N subscribers' line found; treating "
                "everything after the URL as transcript body"
            )
            result["text"] = _clean_body(lines[idx:])
            return result

        result["subscribers_at_capture"] = lines[sub_i].strip()

        mid = [ln.strip() for ln in lines[idx:sub_i] if ln.strip()]
        if len(mid) >= 2 and mid[-1] == mid[-2]:
            result["channel"] = mid[-1]
            title_lines = mid[:-2]
        elif mid:
            result["channel"] = mid[-1]
            title_lines = mid[:-1]
        else:
            title_lines = []

        if result["channel"]:
            result["channel_source"] = "manual"
        else:
            warnings.append("metadata header: no channel name between URL and subscriber line")

        if title_lines:
            result["video_title"] = " ".join(title_lines)
            if len(title_lines) > 1:
                warnings.append(
                    f"metadata header: {len(title_lines)} lines before the channel "
                    f"name, expected 1 video-title line"
                )
            if expected_sign and expected_sign.lower() not in result["video_title"].lower():
                warnings.append(
                    f"metadata header: video title does not mention '{expected_sign}' "
                    f"({result['video_title']!r})"
                )
        else:
            warnings.append("metadata header: no video-title line found")

        result["text"] = _clean_body(lines[sub_i + 1:])
        return result

    # legacy
    result["text"] = _clean_body(lines[idx:])
    if result["text"]:
        channel = extract_channel_name(result["text"])
        if channel:
            result["channel"] = channel
            result["channel_source"] = "transcript"
    return result


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

    week_str = str(args.week_of)
    header_format = "metadata" if week_str >= NEW_HEADER_FROM else "legacy"
    print(f"Week of {week_str} -- header format: {header_format}"
          + (f" (video-title / channel / subscriber block, {NEW_HEADER_FROM} on)"
             if header_format == "metadata" else " (URL then transcript body)"))
    print()

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
            parsed = parse_file(path, header_format, expected_sign=sign)
            url = parsed["url"]
            text = parsed["text"]
            char_count = len(text)
            flags = []
            if char_count < MIN_CHARS_WARNING:
                flags.append(f"UNDER {MIN_CHARS_WARNING} CHARS")
            if url is None:
                flags.append("NO URL FOUND")

            video_id = video_id_from_url(url) if url else None
            if video_id is None:
                flags.append("NO VIDEO ID")

            flags.extend(parsed["warnings"])

            flag_str = f"  !! FLAG: {', '.join(flags)}" if flags else ""
            if flags:
                any_flags = True

            channel = parsed["channel"]

            print(f"\n  {path.name}")
            print(f"    url: {url or '(none)'}")
            print(f"    chars: {char_count}{flag_str}")
            print(f"    channel: {channel or '(not stated in source)'}"
                  + (f" [{parsed['channel_source']}]" if parsed["channel_source"] else ""))
            if header_format == "metadata":
                print(f"    video_title: {parsed['video_title'] or '(none found)'}")
                print(f"    subscribers_at_capture: {parsed['subscribers_at_capture'] or '(none found)'}")
            print(f"    preview: {text[:200]!r}")

            if video_id and text:
                out_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
                out_path.write_text(text, encoding="utf-8")
                channel_path = TRANSCRIPTS_DIR / f"{video_id}.channel.json"
                if header_format == "metadata":
                    sidecar = {
                        "channel": channel,
                        "channel_source": parsed["channel_source"],
                        "video_title": parsed["video_title"],
                        "subscribers_at_capture": parsed["subscribers_at_capture"],
                    }
                else:
                    sidecar = {
                        "channel": channel,
                        "channel_source": parsed["channel_source"],
                    }
                channel_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
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
