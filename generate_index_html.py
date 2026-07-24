"""Render index.html and index-es.html — a landing page linking to all 12 sign digests.

Usage: python3 generate_index_html.py

For each of the 12 signs, reads digest_<sign>_week1.json (or the _es
variant) to pull the real overall_tone_summary as a one-line teaser. Signs
without a digest file yet are rendered as a non-clickable "coming soon"
card instead of a broken link or fabricated teaser — re-run this script
after processing a new sign to fill its card in automatically.

Styling matches generate_digest_html.py exactly (same fonts, colors,
spacing) so the index reads as part of the same site.
"""
import html
import json
import sys
from pathlib import Path

ZODIAC_ORDER = [
    "aries", "taurus", "gemini", "cancer", "leo", "virgo",
    "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces",
]

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

STRINGS = {
    "en": {
        "html_lang": "en",
        "page_title": "This Week's Tarot Digest",
        "title": "This Week's Tarot Digest",
        "subtitle": "Pick your sign to see what five independent readers agree on this week.",
        "lang_toggle_text": "Leer en español",
        "lang_toggle_href": "index-es.html",
        "pending_label": "Coming soon",
        "output_path": Path(__file__).parent / "index.html",
    },
    "es": {
        "html_lang": "es",
        "page_title": "El Tarot de Esta Semana",
        "title": "El Tarot de Esta Semana",
        "subtitle": "Elige tu signo para ver en qué coinciden cinco lectores independientes esta semana.",
        "lang_toggle_text": "Read in English",
        "lang_toggle_href": "index.html",
        "pending_label": "Próximamente",
        "output_path": Path(__file__).parent / "index-es.html",
    },
}


def esc(text):
    return html.escape(text or "", quote=True)


def load_sign_card(sign_slug: str, lang: str) -> dict:
    suffix = "" if lang == "en" else "_es"
    digest_path = Path(__file__).parent / f"digest_{sign_slug}_week1{suffix}.json"
    html_href = f"digest-{sign_slug}{'' if lang == 'en' else '-es'}.html"

    if not digest_path.exists():
        display_name = ZODIAC_ES[sign_slug] if lang == "es" else sign_slug.capitalize()
        return {"available": False, "name": display_name, "href": None, "teaser": None}

    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "name": digest["sign"],
        "href": html_href,
        "teaser": digest["overall_tone_summary"],
    }


def render_card(card: dict, strings: dict, index: int) -> str:
    delay = round(0.1 + index * 0.05, 2)
    if card["available"]:
        return f"""
        <a class="sign-card" href="{esc(card['href'])}" style="animation-delay: {delay}s">
          <h2 class="sign-card-name">{esc(card['name'])}</h2>
          <p class="sign-card-teaser">{esc(card['teaser'])}</p>
        </a>"""
    return f"""
        <div class="sign-card sign-card-pending" style="animation-delay: {delay}s">
          <h2 class="sign-card-name">{esc(card['name'])}</h2>
          <p class="sign-card-teaser sign-card-teaser-pending">{esc(strings['pending_label'])}</p>
        </div>"""


def build_html(cards_html: str, strings: dict) -> str:
    return f"""<!doctype html>
<html lang="{strings['html_lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(strings['page_title'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Macondo+Swash+Caps&family=Antic&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #fcfaf6;
    --bg-card: #fcfaf6;
    --text: #29231f;
    --text-soft: #6e655d;
    --accent: #c1642b;
    --accent-soft: #e8d9c4;
    --border: #e3d7c4;
  }}

  * {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Antic', -apple-system, sans-serif;
    line-height: 1.65;
    -webkit-font-smoothing: antialiased;
  }}

  .wrap {{
    max-width: 1080px;
    margin: 0 auto;
    padding: 48px 20px 80px;
  }}

  .lang-toggle {{
    text-align: center;
    margin-bottom: 32px;
  }}

  .lang-toggle a {{
    color: var(--accent);
    font-size: 0.95rem;
    font-weight: 600;
    text-decoration: none;
    border-bottom: 1px solid var(--accent-soft);
    padding-bottom: 2px;
  }}
  .lang-toggle a:hover {{ border-bottom-color: var(--accent); }}

  header {{
    text-align: center;
    margin-bottom: 48px;
    animation: fadeSlideIn 0.7s ease-out both;
  }}

  h1 {{
    font-family: 'Macondo Swash Caps', cursive;
    font-weight: 400;
    font-size: clamp(2.75rem, 8vw, 5rem);
    line-height: 1;
    margin: 0 0 14px;
    letter-spacing: 0.01em;
    color: var(--text);
  }}

  .subtitle {{
    font-size: clamp(1rem, 2.2vw, 1.15rem);
    color: var(--accent);
    font-style: italic;
    margin: 0;
  }}

  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 20px;
  }}

  .sign-card {{
    display: block;
    text-decoration: none;
    color: inherit;
    padding: 28px 22px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--bg-card);
    opacity: 0;
    animation: fadeSlideIn 0.5s ease-out both;
    transition: border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
  }}

  a.sign-card:hover {{
    border-color: var(--accent);
    transform: translateY(-2px);
    box-shadow: 0 6px 16px rgba(43, 36, 32, 0.08);
  }}

  .sign-card-pending {{
    opacity: 0.55;
    animation: fadeSlideIn 0.5s ease-out both;
  }}

  .sign-card-name {{
    font-family: 'Macondo Swash Caps', cursive;
    font-size: 1.9rem;
    font-weight: 400;
    letter-spacing: 0.01em;
    margin: 0 0 10px;
    color: var(--text);
  }}

  .sign-card-teaser {{
    font-size: 0.95rem;
    color: var(--text-soft);
    margin: 0;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}

  .sign-card-teaser-pending {{
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 600;
    color: var(--text-soft);
  }}

  @keyframes fadeSlideIn {{
    from {{ opacity: 0; transform: translateY(14px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  @media (max-width: 640px) {{
    .wrap {{ padding: 32px 16px 56px; }}
    .grid {{ grid-template-columns: repeat(2, 1fr); gap: 14px; }}
    .sign-card {{ padding: 20px 16px; }}
    .sign-card-name {{ font-size: 1.5rem; }}
  }}

  @media (max-width: 400px) {{
    .grid {{ grid-template-columns: repeat(2, 1fr); }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <div class="lang-toggle">
      <a href="{esc(strings['lang_toggle_href'])}">{esc(strings['lang_toggle_text'])}</a>
    </div>

    <header>
      <h1>{esc(strings['title'])}</h1>
      <p class="subtitle">{esc(strings['subtitle'])}</p>
    </header>

    <section class="grid">{cards_html}
    </section>
  </div>
</body>
</html>
"""


def main():
    for lang, strings in STRINGS.items():
        cards_html = "".join(
            render_card(load_sign_card(sign_slug, lang), strings, i)
            for i, sign_slug in enumerate(ZODIAC_ORDER)
        )
        html_out = build_html(cards_html, strings)
        strings["output_path"].write_text(html_out, encoding="utf-8")
        available = sum(1 for s in ZODIAC_ORDER if load_sign_card(s, lang)["available"])
        print(f"Wrote {strings['output_path']}  ({available}/12 signs available)")


if __name__ == "__main__":
    sys.exit(main())
