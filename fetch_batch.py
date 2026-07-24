"""Fetch YouTube transcripts for a given list of URLs and save as .txt files.

Usage: python3 fetch_batch.py <url> [<url> ...]
"""
import sys
from pathlib import Path

from test_transcript import TRANSCRIPTS_DIR, extract_video_id, fetch_transcript_text
from youtube_transcript_api._errors import CouldNotRetrieveTranscript


def main():
    urls = sys.argv[1:]
    if not urls:
        print("Usage: python3 fetch_batch.py <url> [<url> ...]")
        return 1

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    for url in urls:
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

    return [vid for _, vid, ok, _ in results if ok]


if __name__ == "__main__":
    main()
