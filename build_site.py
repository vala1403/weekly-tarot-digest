"""Render all existing digest JSON into the static site; no API calls or deployment."""
from pathlib import Path
import subprocess
import sys

from generate_index_html import ZODIAC_ORDER

ROOT = Path(__file__).resolve().parent


def main():
    for lang in ('en', 'es'):
        for sign in ZODIAC_ORDER:
            suffix = '' if lang == 'en' else '_es'
            for path in (ROOT / f'digest_{sign}_week1{suffix}.json', ROOT / 'public' / 'assets' / f'{sign}.webp'):
                if not path.is_file():
                    raise FileNotFoundError(path)
    for lang in ('en', 'es'):
        for sign in ZODIAC_ORDER:
            subprocess.run([sys.executable, str(ROOT / 'generate_digest_html.py'), sign, lang], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'generate_index_html.py')], cwd=ROOT, check=True)
    print('Built 26 pages. Preview public/; nothing deployed.')


if __name__ == '__main__':
    main()
