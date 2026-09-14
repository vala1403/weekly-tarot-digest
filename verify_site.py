"""Validate all generated pages against existing content and local assets."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, unquote
import json

from generate_index_html import ZODIAC_ORDER
from generate_digest_html import strip_em_dashes_deep, STRINGS

ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / 'public'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.words = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.words.append(data)


def normalized(text):
    return ' '.join(text.split())


def main():
    pages = list(PUBLIC.glob('*.html'))
    assert len(pages) == 26
    for path in pages:
        assert path.read_bytes() == (ROOT / path.name).read_bytes(), f'Stale public copy: {path}'
        page = Page(path.read_text(encoding='utf-8'))
        for tag, attrs in page.nodes:
            for key in ('href', 'src'):
                value = attrs.get(key, '')
                parsed = urlsplit(value)
                if not value or parsed.scheme or parsed.netloc or value.startswith('#'):
                    continue
                target = PUBLIC / unquote(parsed.path.lstrip('/'))
                assert target.is_file(), (path.name, value)
        for lang in ('en', 'es'):
            suffix = '' if lang == 'en' else '-es'
            if path.name == f'index{suffix}.html':
                links = [a['href'] for tag, a in page.nodes if tag == 'a' and 'sign-card' in a.get('class', '').split()]
                assert links == [f'digest-{s}{suffix}.html' for s in ZODIAC_ORDER]
        if not path.name.startswith('digest-'):
            continue
        lang = 'es' if path.stem.endswith('-es') else 'en'
        sign = path.stem.removeprefix('digest-').removesuffix('-es')
        suffix = '_es' if lang == 'es' else ''
        data = strip_em_dashes_deep(json.loads((ROOT / f'digest_{sign}_week1{suffix}.json').read_text(encoding='utf-8')))
        text = normalized(' '.join(page.words))
        for value in (data['sign'], data['overall_tone_summary']):
            assert normalized(value) in text, (path, value)
        expected_counts = []
        for category in data['categories'].values():
            assert normalized(category['summary']) in text, path
            note = category.get('disagreement')
            if note and not any(skip in note.lower() for skip in ('no notable disagreement', 'no strong disagreement')):
                assert normalized(note) in text, path
            assert STRINGS[lang]['agreement_pill'](category['reader_count']) in text
            expected_counts.append(category['reader_count'])
        links = [a['href'] for tag, a in page.nodes if tag == 'a']
        for reader in data['readers']:
            assert reader['url'] in links
            assert normalized(reader['channel_theme']) in text
            assert reader['tone'] in text
        images = [a['src'] for tag, a in page.nodes if tag == 'img']
        expected = f'assets/{sign}-600.webp' if (PUBLIC / 'assets' / f'{sign}-600.webp').exists() else f'assets/{sign}.webp'
        assert images == [expected], (path, images)
        opposite = f'digest-{sign}{"-es" if lang == "en" else ""}.html'
        assert opposite in links
        assert len([a for tag, a in page.nodes if tag == 'a' and a.get('aria-current') == 'page']) == 1
    print('PASS: 26 synchronized pages; all local assets/links, correct sign artwork, full digest text, counts, readers, Watch URLs, and language destinations.')


if __name__ == '__main__':
    main()
