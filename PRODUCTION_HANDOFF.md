# Illustrated Weekly Tarot Digest: Candidate Source

This directory is the candidate source. Work only in
`/home/vala/tarot_transcripts_animated`. The original
`/home/vala/tarot_transcripts` is read-only and must not be changed.
No deployment has been performed or authorized by this handoff.

## Build and Preview

From this directory in WSL/Linux:

```sh
python3 build_site.py
python3 verify_site.py
python3 -m http.server 8766 --bind 127.0.0.1 --directory public
```

The existing Windows-hosted preview may already occupy port 8765. The command
above uses 8766 instead. Open `http://localhost:8766/index.html`.

`build_site.py` calls the existing digest generator for all twelve signs in
English and Spanish, then the homepage generator. It performs no API calls,
translation, aggregation, git operations, or deployment. It checks required
digest JSON and illustrations before rendering.

Individual commands remain supported:

```sh
python3 generate_digest_html.py gemini
python3 generate_digest_html.py gemini es
python3 generate_index_html.py
```

Each generator now writes both its existing root HTML output and its matching
`public/` copy. Preview and publish `public/`, not the root directory: shared
assets live under `public/assets/`. Root HTML is retained for the original
workflow and should not be edited manually. Vercel configuration still points
to `public/`; no automatic build/deployment integration was added.

## Source Files

- `generate_index_html.py`: homepage content and illustrated sign links.
- `generate_digest_html.py`: all sign pages, translated labels, printed section
  emblems, reader tallies, correct sign artwork and language links.
- `public/assets/deck.css`: approved responsive visual system and animation rules.
- `public/assets/deck.js`: once-only viewport reveals and production analytics.
- `public/assets/<sign>.webp`: artwork for all twelve signs. Newer signs also
  have PNG masters for Canva and `-600.webp` copies used by the website.
- `verify_site.py`: standard-library validation of all 26 generated pages,
  local links/assets, language links, artwork, and digest content preservation.

Gemini, Pisces, and Leo retain their existing 600 x 900 WebP artwork. The nine
new signs have 1024 x 1536 PNG/WebP masters and 600 x 900 website copies.
Do not overwrite illustrations during weekly generation.

## Weekly Content Workflow

The existing transcript parsing, tagging, aggregation, and translation pipeline
is unchanged. Follow `CLAUDE.md` for its rules, including explicit Monday
`--week-of` dates. Once all twelve English and Spanish digest JSON files are
ready, run the build and verification commands above. Never rerun aggregation
just to change presentation; never rerun the one-time theme-log migration.

`data/theme-log.json` and all current digest JSON remain unchanged by this
integration. No React, npm build, or replacement framework is required.

## Verification and Remaining Scope

The local browser audit is `work/verify_candidate.cjs`; it uses this machine's
bundled Playwright and Edge. Its report is `work/candidate-verification.json`.
It covers all 26 pages at 1440, 390, and 320 pixels, language/sign/home
navigation, artwork decoding, overflow, reduced motion, and JavaScript errors.
It also checks settled animation on all twelve signs and a no-JavaScript page.
This machine-specific script is supplementary; `verify_site.py` is portable.

External Watch links are preserved and validated against source data, not
guaranteed playable by this audit. Real-device Safari and TikTok/Instagram
in-app browser checks remain a pre-release task. Native cross-page transitions
are progressive enhancement; ordinary links still work without them.

The copied git repository retains its existing origin. This handoff does not
authorize pushing, replacing the original checkout, or publishing to Vercel.
Keep `.env` private; it is not needed for the static build. `work/` contains
local previews and audit artifacts and is not part of the deployed site.
