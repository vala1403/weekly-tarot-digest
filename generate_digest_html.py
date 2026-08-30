"""Render a sign's digest JSON into a standalone digest-<sign>[-es].html page.

Usage: python3 generate_digest_html.py <sign> [lang]
  e.g. python3 generate_digest_html.py aries
       python3 generate_digest_html.py pisces es
lang defaults to "en". "en" reads digest_<sign>_week1.json and writes
digest-<sign>.html. "es" reads digest_<sign>_week1_es.json and writes
digest-<sign>-es.html.

Macondo Swash Caps is reserved for the sign headline and the four category
titles only. Everything else uses the body font (Antic), styled per its
role. Styling, layout, fonts, and colors are identical across signs and
languages — only text content (and date formatting) changes per lang.
"""
import datetime
import html
import json
import sys
from pathlib import Path

# Thin single-weight line-art icons, 24x24 viewBox, stroke="currentColor".
ICON_SVG = {
    "love": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20.5s-7.5-4.6-10-9.3C.6 8 2 4.5 5.3 4c2.2-.3 4 .9 6.7 3.6C14.7 4.9 16.5 3.7 18.7 4c3.3.5 4.7 4 3.3 7.2-2.5 4.7-10 9.3-10 9.3z"/></svg>',
    "finance": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 9 12 3l7.5 6-7.5 12-7.5-12z"/><path d="M4.5 9h15M9 9l3-6 3 6M9 9l3 12 3-12"/></svg>',
    "career": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 9.5h17a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1z"/><path d="M9 9.5V7a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2.5"/><path d="M3 14h18"/></svg>',
    "family": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><path d="M4 11.5 12 4l8 7.5"/><path d="M6 10v9.5h12V10"/><path d="M10 19.5v-6h4v6"/></svg>',
}

# Small 4-point sparkle, filled with currentColor, used for decorative accents.
SPARKLE_SVG = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7z"/></svg>'

CATEGORY_ORDER = ["love", "finance", "career", "family"]

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

EM_DASH = "—"


def strip_em_dashes(text):
    """Replace em dashes with a comma so style stays consistent, including in
    digests generated before this style rule existed. Best-effort, not
    grammar-aware."""
    if not isinstance(text, str) or EM_DASH not in text:
        return text
    cleaned = text.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, ", ")
    return " ".join(cleaned.split())


def strip_em_dashes_deep(obj):
    if isinstance(obj, dict):
        return {k: strip_em_dashes_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_em_dashes_deep(v) for v in obj]
    return strip_em_dashes(obj)

CATEGORY_LABELS = {
    "en": {"love": "Love", "finance": "Finance", "career": "Career", "family": "Family"},
    "es": {"love": "Amor", "finance": "Finanzas", "career": "Carrera", "family": "Familia"},
}

STRINGS = {
    "en": {
        "html_lang": "en",
        "week_of_prefix": "Week of",
        "subheadline": "This Week Across Tarot YouTube",
        "overall_mood_label": "Overall Mood",
        "different_perspective_label": "A different perspective",
        "readers_heading": "This Week's Readers",
        "table_theme": "Theme",
        "table_tone": "Tone",
        "table_watch": "Watch",
        "watch_link_text": "Watch →",
        "agreement_pill": lambda n: f"Echoed by {n} of 5 readers",
        "footer": lambda sign, date: f"Compiled from five independent {sign} readings published for the week of {date}. Themes are paraphrased and compared; interpretations remain those of the original creators.",
        "all_signs_link": "All signs",
        "back_to_all_signs": "Back to all signs",
        "index_href": "index.html",
    },
    "es": {
        "html_lang": "es",
        "week_of_prefix": "Semana del",
        "subheadline": "Esta semana en el tarot de YouTube",
        "overall_mood_label": "Ánimo general",
        "different_perspective_label": "Una perspectiva diferente",
        "readers_heading": "Lecturas de esta semana",
        "table_theme": "Tema",
        "table_tone": "Tono",
        "table_watch": "Ver",
        "watch_link_text": "Ver →",
        "agreement_pill": lambda n: f"Compartido por {n} de 5 lectores",
        "footer": lambda sign, date: f"Recopilado de cinco lecturas independientes de {sign} publicadas para la semana del {date}. Los temas están parafraseados y comparados; las interpretaciones siguen siendo las de sus creadores originales.",
        "all_signs_link": "Todos los signos",
        "back_to_all_signs": "Ver todos los signos",
        "index_href": "index-es.html",
    },
}

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def esc(text):
    return html.escape(text or "", quote=True)


def format_week_of(iso_date: str, lang: str) -> str:
    d = datetime.date.fromisoformat(iso_date)
    if lang == "es":
        return f"{d.day} de {MONTHS_ES[d.month - 1]} de {d.year}"
    return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else iso_date


def render_category_card(key: str, data: dict, index: int, is_last: bool, lang: str) -> str:
    label = CATEGORY_LABELS[lang][key]
    strings = STRINGS[lang]
    reader_count = data["reader_count"]

    disagreement_html = ""
    if data.get("disagreement") and "no notable disagreement" not in data["disagreement"].lower() and "no strong disagreement" not in data["disagreement"].lower():
        disagreement_html = f"""
          <div class="callout callout-disagreement">
            <span class="callout-label">{strings['different_perspective_label']}</span>
            <p>{esc(data['disagreement'])}</p>
          </div>"""

    divider_sparkle_html = "" if is_last else f'\n          <span class="card-divider-sparkle">{SPARKLE_SVG}</span>'

    return f"""
        <article class="card" style="animation-delay: {0.4 + index * 0.12}s">
          <div class="card-icon">{ICON_SVG[key]}</div>
          <h3 class="card-title">{label}</h3>
          <p class="card-headline">{esc(data['summary'])}</p>
          <div class="agreement-pill">{strings['agreement_pill'](reader_count)}</div>{disagreement_html}{divider_sparkle_html}
        </article>"""


def sign_display_name(slug: str, lang: str) -> str:
    return ZODIAC_ES[slug] if lang == "es" else slug.capitalize()


def render_all_signs_button(lang: str) -> str:
    strings = STRINGS[lang]
    return f'<div class="all-signs-button-wrap"><a class="all-signs-button" href="{esc(strings["index_href"])}">{esc(strings["back_to_all_signs"])}</a></div>'


def render_all_signs_link(lang: str) -> str:
    strings = STRINGS[lang]
    return f'<div class="all-signs-link"><a href="{esc(strings["index_href"])}">{esc(strings["all_signs_link"])}</a></div>'


def render_sign_selector(current_slug: str, lang: str) -> str:
    pills = []
    for slug in ZODIAC_ORDER:
        href = f"digest-{slug}{'' if lang == 'en' else '-es'}.html"
        cls = "sign-pill sign-pill-current" if slug == current_slug else "sign-pill"
        pills.append(f'<a class="{cls}" href="{esc(href)}">{esc(sign_display_name(slug, lang))}</a>')
    return f'<nav class="sign-selector">{"".join(pills)}</nav>'


def render_reader_row(reader: dict, index: int, lang: str) -> str:
    strings = STRINGS[lang]
    return f"""
          <tr style="animation-delay: {0.5 + index * 0.08}s">
            <td data-label="{strings['table_theme']}">{esc(reader['channel_theme'])}</td>
            <td data-label="{strings['table_tone']}"><span class="tone-tag tone-{esc(reader['tone'].lower())}">{esc(reader['tone'])}</span></td>
            <td data-label="{strings['table_watch']}"><a class="watch-link" href="{esc(reader['url'])}" target="_blank" rel="noopener">{strings['watch_link_text']}</a></td>
          </tr>"""


def build_html(digest: dict, sign_slug: str, week_of_display: str, cards_html: str, rows_html: str, lang: str) -> str:
    strings = STRINGS[lang]
    html_out = f"""<!doctype html>
<html lang="{strings['html_lang']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(digest['sign'])}: {strings['week_of_prefix']} {esc(week_of_display)}</title>
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
    --disagree-bg: #f7f1e8;
    --disagree-border: #d27a42;
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
    max-width: 960px;
    margin: 0 auto;
    padding: 48px 20px 80px;
  }}

  header {{
    position: relative;
    text-align: center;
    margin-bottom: 48px;
    animation: fadeSlideIn 0.7s ease-out both;
  }}

  .header-sparkle {{
    position: absolute;
    top: 2px;
    right: 8%;
    width: 22px;
    height: 22px;
    color: var(--accent);
    opacity: 0.55;
  }}

  .sign-name {{
    font-family: 'Macondo Swash Caps', cursive;
    font-weight: 400;
    text-transform: none;
    font-size: clamp(3.75rem, 14vw, 8.5rem);
    line-height: 0.9;
    margin: 0 0 6px;
    letter-spacing: 0.01em;
    color: var(--text);
  }}

  .week-line {{
    font-family: 'Antic', -apple-system, sans-serif;
    font-weight: 400;
    font-size: clamp(1.5rem, 4.5vw, 2.4rem);
    margin: 0 0 14px;
    letter-spacing: 0;
    color: var(--text);
  }}

  .subheadline {{
    font-family: 'Antic', -apple-system, sans-serif;
    font-size: clamp(1.05rem, 2.5vw, 1.3rem);
    color: var(--accent);
    font-weight: 400;
    font-style: italic;
    letter-spacing: 0;
    margin: 0;
  }}

  .all-signs-button-wrap {{
    text-align: center;
    margin-bottom: 28px;
  }}

  .all-signs-button {{
    display: inline-block;
    background: var(--accent);
    color: #fff;
    font-family: 'Antic', -apple-system, sans-serif;
    font-weight: 700;
    font-size: 0.95rem;
    text-decoration: none;
    padding: 12px 30px;
    border-radius: 10px;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }}
  .all-signs-button:hover {{
    transform: translateY(-1px);
    box-shadow: 0 6px 16px rgba(43, 36, 32, 0.18);
  }}

  .all-signs-link {{
    text-align: center;
    margin-top: 40px;
  }}

  .all-signs-link a {{
    color: var(--accent);
    font-size: 0.95rem;
    font-weight: 600;
    text-decoration: none;
    border-bottom: 1px solid var(--accent-soft);
    padding-bottom: 2px;
  }}
  .all-signs-link a:hover {{ border-bottom-color: var(--accent); }}

  .sign-selector {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    margin-top: 40px;
    margin-bottom: 28px;
  }}

  .sign-pill {{
    display: inline-block;
    text-decoration: none;
    color: var(--text-soft);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 6px 14px;
    font-size: 0.85rem;
    font-weight: 600;
    transition: border-color 0.15s ease, color 0.15s ease;
  }}
  .sign-pill:hover {{ border-color: var(--accent); color: var(--accent); }}

  .sign-pill-current {{
    background: var(--accent-soft);
    border-color: var(--accent-soft);
    color: var(--text);
  }}
  .sign-pill-current:hover {{ border-color: var(--accent-soft); color: var(--text); }}

  .cards {{
    margin-bottom: 44px;
  }}

  .card {{
    position: relative;
    padding: 40px 0;
    border-bottom: 1px solid var(--border);
    opacity: 0;
    animation: fadeSlideIn 0.6s ease-out both;
  }}

  .card:first-child {{
    padding-top: 0;
  }}

  .card:last-child {{
    border-bottom: none;
    padding-bottom: 0;
  }}

  .card-divider-sparkle {{
    position: absolute;
    bottom: -10px;
    left: 50%;
    transform: translateX(-50%);
    width: 18px;
    height: 18px;
    background: var(--bg);
    padding: 0 8px;
    color: var(--accent);
    opacity: 0.7;
  }}

  .card-icon {{
    display: inline-flex;
    color: var(--accent);
    margin-bottom: 10px;
  }}

  .card-icon svg {{
    width: 48px;
    height: 48px;
    display: block;
  }}

  .card-title {{
    font-family: 'Macondo Swash Caps', cursive;
    font-size: clamp(1.6rem, 4vw, 2.1rem);
    margin: 0 0 14px;
    font-weight: 400;
    letter-spacing: 0.01em;
    color: var(--text);
  }}

  .card-headline {{
    font-size: 1.08rem;
    font-weight: 500;
    color: var(--text);
    margin: 0 0 16px;
  }}

  .agreement-pill {{
    display: inline-block;
    background: var(--accent-soft);
    color: var(--text);
    font-size: 0.82rem;
    font-weight: 600;
    padding: 5px 12px;
    border-radius: 999px;
    margin-bottom: 4px;
  }}

  .callout {{
    margin-top: 18px;
    font-size: 0.92rem;
  }}

  .callout p {{
    margin: 4px 0 0;
    font-size: 1.05rem;
    color: var(--text-soft);
  }}

  .callout-label {{
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}

  .callout-disagreement {{
    background: var(--disagree-bg);
    border-left: 2px solid var(--disagree-border);
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .callout-disagreement .callout-label {{
    color: var(--disagree-border);
    text-transform: none;
    letter-spacing: 0.02em;
  }}
  .callout-disagreement p {{
    font-size: 1rem;
  }}

  .tone-section {{
    text-align: center;
    padding: 28px 0;
    margin-bottom: 48px;
    opacity: 0;
    animation: fadeSlideIn 0.6s ease-out both;
    animation-delay: 0.2s;
  }}

  .tone-section h2 {{
    font-family: 'Antic', -apple-system, sans-serif;
    font-size: 0.95rem;
    margin: 0 0 10px;
    color: var(--accent);
    font-weight: 400;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }}

  .tone-section p {{
    font-family: 'Antic', -apple-system, sans-serif;
    font-size: clamp(1.2rem, 3vw, 1.6rem);
    font-style: italic;
    color: var(--text);
    margin: 0;
  }}

  .readers-section {{
    opacity: 0;
    animation: fadeSlideIn 0.6s ease-out both;
    animation-delay: 0.7s;
  }}

  .readers-section h2 {{
    font-family: 'Antic', -apple-system, sans-serif;
    font-size: 1.75rem;
    margin: 0 0 18px;
    font-weight: 400;
    letter-spacing: 0;
    color: var(--text);
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
  }}

  thead th {{
    text-align: left;
    font-size: 0.76rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--text-soft);
    font-weight: 700;
    padding: 14px 18px 14px 0;
    border-bottom: 1px solid var(--border);
  }}

  tbody tr {{
    opacity: 0;
    animation: fadeSlideIn 0.5s ease-out both;
  }}

  tbody tr:not(:last-child) td {{
    border-bottom: 1px solid var(--border);
  }}

  td {{
    padding: 16px 18px 16px 0;
    vertical-align: top;
    font-size: 0.93rem;
  }}

  th:first-child, td:first-child {{ padding-left: 0; }}
  th:last-child, td:last-child {{ padding-right: 0; }}

  .tone-tag {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 0.78rem;
    font-weight: 600;
    background: var(--accent-soft);
    color: var(--text);
    white-space: nowrap;
  }}

  .watch-link {{
    color: var(--accent);
    text-decoration: none;
    font-weight: 600;
    white-space: nowrap;
  }}
  .watch-link:hover {{ text-decoration: underline; }}

  footer {{
    text-align: center;
    margin-top: 56px;
    color: var(--text-soft);
    font-size: 0.82rem;
  }}

  @keyframes fadeSlideIn {{
    from {{ opacity: 0; transform: translateY(14px); }}
    to {{ opacity: 1; transform: translateY(0); }}
  }}

  @media (max-width: 640px) {{
    .wrap {{ padding: 32px 16px 56px; }}
    .header-sparkle {{ display: none; }}

    table, thead, tbody, th, td, tr {{ display: block; }}
    thead {{ display: none; }}
    tbody tr {{
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
    }}
    tbody tr:last-child {{ border-bottom: none; }}
    td {{
      border: none !important;
      padding: 6px 0;
    }}
    td[data-label]::before {{
      content: attr(data-label);
      display: block;
      font-size: 0.68rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--text-soft);
      font-weight: 700;
      margin-bottom: 2px;
    }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    {render_all_signs_button(lang)}

    <header>
      <span class="header-sparkle">{SPARKLE_SVG}</span>
      <h1 class="sign-name">{esc(digest['sign'])}</h1>
      <p class="week-line">{strings['week_of_prefix']} {esc(week_of_display)}</p>
      <p class="subheadline">{strings['subheadline']}</p>
    </header>

    <section class="tone-section">
      <h2>{strings['overall_mood_label']}</h2>
      <p>{esc(digest['overall_tone_summary'])}</p>
    </section>

    <section class="cards">{cards_html}
    </section>

    <section class="readers-section">
      <h2>{strings['readers_heading']}</h2>
      <div style="overflow-x:auto;">
      <table>
        <thead>
          <tr>
            <th>{strings['table_theme']}</th>
            <th>{strings['table_tone']}</th>
            <th>{strings['table_watch']}</th>
          </tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
      </table>
      </div>
    </section>

    <footer>
      {strings['footer'](esc(digest['sign']), esc(week_of_display))}
    </footer>

    {render_sign_selector(sign_slug, lang)}

    {render_all_signs_link(lang)}
  </div>
  <script defer src="/_vercel/insights/script.js"></script>
</body>
</html>
"""
    return html_out


def main():
    if len(sys.argv) not in (2, 3):
        print("Usage: python3 generate_digest_html.py <sign> [lang]")
        print("  e.g. python3 generate_digest_html.py aries")
        print("       python3 generate_digest_html.py pisces es")
        return 1

    sign_slug = sys.argv[1].strip().lower()
    lang = sys.argv[2].strip().lower() if len(sys.argv) == 3 else "en"
    if lang not in STRINGS:
        print(f"ERROR: unsupported lang '{lang}'. Supported: {', '.join(STRINGS)}")
        return 1

    suffix = "" if lang == "en" else f"_{lang}"
    digest_path = Path(__file__).parent / f"digest_{sign_slug}_week1{suffix}.json"
    output_path = Path(__file__).parent / f"digest-{sign_slug}{'' if lang == 'en' else '-' + lang}.html"

    if not digest_path.exists():
        print(f"ERROR: {digest_path} not found")
        return 1

    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    digest = strip_em_dashes_deep(digest)

    week_of_display = format_week_of(digest["week_of"], lang)
    cards_html = "".join(
        render_category_card(key, digest["categories"][key], i, i == len(CATEGORY_ORDER) - 1, lang)
        for i, key in enumerate(CATEGORY_ORDER)
    )
    rows_html = "".join(
        render_reader_row(reader, i, lang) for i, reader in enumerate(digest["readers"])
    )

    html_out = build_html(digest, sign_slug, week_of_display, cards_html, rows_html, lang)

    if EM_DASH in html_out:
        count = html_out.count(EM_DASH)
        print(f"WARNING: {count} em dash(es) slipped through into {output_path.name}, flagging for manual review.")

    output_path.write_text(html_out, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
