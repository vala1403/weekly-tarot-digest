"""Tag saved tarot transcripts with Claude API analysis and save results as JSON."""
import json
import os
import sys
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-4-6"
MIN_TRANSCRIPT_CHARS = 200

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"
TAGGED_DIR = Path(__file__).parent / "tagged"

TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "video_id": {"type": "string"},
        "love": {"type": ["string", "null"]},
        "finance": {"type": ["string", "null"]},
        "career": {"type": ["string", "null"]},
        "family": {"type": ["string", "null"]},
        "cards_mentioned": {"type": "array", "items": {"type": "string"}},
        "overall_tone": {"type": "string"},
    },
    "required": ["video_id", "love", "finance", "career", "family", "cards_mentioned", "overall_tone"],
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


def build_prompt(video_id: str, transcript: str) -> str:
    return f"""Analyze this tarot reading transcript (video ID: {video_id}) and identify the themes discussed.

For each of love, finance, career, and family: write ONE sentence paraphrasing the theme discussed for that topic, IN YOUR OWN WORDS — do not quote the transcript directly. If a topic isn't discussed, use null.

Also list any tarot card names mentioned, and describe the overall tone in one word (e.g. hopeful, cautionary, transformative).

Transcript:
{transcript}"""


def tag_transcript(client: anthropic.Anthropic, video_id: str, transcript: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        output_config={"format": {"type": "json_schema", "schema": TAG_SCHEMA}},
        messages=[{"role": "user", "content": build_prompt(video_id, transcript)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def main():
    load_env_file(Path(__file__).parent / ".env")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set.")
        return 1

    if not TRANSCRIPTS_DIR.exists():
        print(f"ERROR: transcripts folder not found at {TRANSCRIPTS_DIR}")
        return 1

    TAGGED_DIR.mkdir(parents=True, exist_ok=True)
    client = anthropic.Anthropic(api_key=api_key)

    requested_ids = sys.argv[1:]
    if requested_ids:
        txt_files = [TRANSCRIPTS_DIR / f"{vid}.txt" for vid in requested_ids]
        missing = [str(p) for p in txt_files if not p.exists()]
        if missing:
            print(f"ERROR: transcript file(s) not found: {', '.join(missing)}")
            return 1
    else:
        txt_files = sorted(TRANSCRIPTS_DIR.glob("*.txt"))

    if not txt_files:
        print(f"No .txt files found in {TRANSCRIPTS_DIR}")
        return 0

    results = []
    for txt_path in txt_files:
        video_id = txt_path.stem
        print("=" * 70)
        print(f"Video ID: {video_id}")

        transcript = txt_path.read_text(encoding="utf-8").strip()
        if len(transcript) < MIN_TRANSCRIPT_CHARS:
            reason = f"transcript too short ({len(transcript)} chars, minimum {MIN_TRANSCRIPT_CHARS})"
            print(f"  Status: SKIPPED — {reason}")
            results.append((video_id, False, reason))
            continue

        try:
            tags = tag_transcript(client, video_id, transcript)
        except anthropic.APIStatusError as e:
            reason = f"API error ({e.status_code}): {e.message}"
            print(f"  Status: FAILED — {reason}")
            results.append((video_id, False, reason))
            continue
        except anthropic.APIConnectionError as e:
            reason = f"connection error: {e}"
            print(f"  Status: FAILED — {reason}")
            results.append((video_id, False, reason))
            continue
        except (json.JSONDecodeError, StopIteration) as e:
            reason = f"could not parse model response: {e}"
            print(f"  Status: FAILED — {reason}")
            results.append((video_id, False, reason))
            continue

        out_path = TAGGED_DIR / f"{video_id}.json"
        out_path.write_text(json.dumps(tags, indent=2), encoding="utf-8")

        print("  Status: SUCCESS")
        print(f"  Love: {tags['love']}")
        print(f"  Finance: {tags['finance']}")
        print(f"  Career: {tags['career']}")
        print(f"  Family: {tags['family']}")
        print(f"  Cards mentioned: {', '.join(tags['cards_mentioned']) or '(none)'}")
        print(f"  Overall tone: {tags['overall_tone']}")
        print(f"  Saved to: {out_path}")
        results.append((video_id, True, None))

    print("=" * 70)
    print("\nSummary:")
    succeeded = sum(1 for r in results if r[1])
    failed = len(results) - succeeded
    print(f"  {succeeded} succeeded, {failed} failed/skipped out of {len(results)} total")
    for video_id, ok, reason in results:
        status = "OK" if ok else "SKIP/FAIL"
        line = f"  [{status}] {video_id}"
        if reason:
            line += f": {reason}"
        print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
