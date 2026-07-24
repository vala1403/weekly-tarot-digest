"""Test script: pull YouTube transcripts and save them as .txt files."""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import CouldNotRetrieveTranscript

TEST_URLS = [
    "https://www.youtube.com/watch?v=twhCm_X4FDc",
    "https://www.youtube.com/watch?v=s6oacZcd5lQ",
    "https://www.youtube.com/watch?v=_S0JHglt-G8",
    "https://www.youtube.com/watch?v=tgv0n6m_F1U",
    "https://www.youtube.com/watch?v=S55babUpMVc",
]

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"


def extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/")
    if parsed.hostname and "youtube.com" in parsed.hostname:
        if parsed.path == "/watch":
            qs = parse_qs(parsed.query)
            if "v" in qs:
                return qs["v"][0]
        match = re.match(r"/(embed|shorts)/([^/?]+)", parsed.path)
        if match:
            return match.group(2)
    raise ValueError(f"Could not extract video ID from URL: {url}")


def fetch_transcript_text(video_id: str) -> str:
    api = YouTubeTranscriptApi()
    fetched = api.fetch(video_id)
    return " ".join(snippet.text.strip() for snippet in fetched if snippet.text.strip())


def main():
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    for url in TEST_URLS:
        print("=" * 70)
        try:
            video_id = extract_video_id(url)
        except ValueError as e:
            print(f"URL: {url}")
            print(f"  FAILED: {e}")
            results.append((url, None, False, str(e)))
            continue

        print(f"Video ID: {video_id}  ({url})")
        try:
            text = fetch_transcript_text(video_id)
            length = len(text)
            preview = text[:200]

            out_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
            out_path.write_text(text, encoding="utf-8")

            print("  Status: SUCCESS")
            print(f"  Length: {length} characters")
            print(f"  Preview: {preview!r}")
            print(f"  Saved to: {out_path}")
            results.append((url, video_id, True, length))
        except CouldNotRetrieveTranscript as e:
            reason = str(e)
            print("  Status: FAILED")
            print(f"  Reason: {reason}")
            results.append((url, video_id, False, reason))
        except Exception as e:
            print("  Status: FAILED (unexpected error)")
            print(f"  Reason: {type(e).__name__}: {e}")
            results.append((url, video_id, False, f"{type(e).__name__}: {e}"))

    print("=" * 70)
    print("\nSummary:")
    succeeded = sum(1 for r in results if r[2])
    failed = len(results) - succeeded
    print(f"  {succeeded} succeeded, {failed} failed out of {len(results)} total")
    for url, video_id, ok, info in results:
        status = "OK" if ok else "FAIL"
        label = video_id or url
        detail = f"{info} chars" if ok else info
        print(f"  [{status}] {label}: {detail}")


if __name__ == "__main__":
    sys.exit(main())
