"""Strict Zotero source identities shared by parsing, lookup and sync planning."""
import html
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit


def source_identity(href: str) -> str | None:
    try:
        url = urlsplit(html.unescape(href or ''))
        if url.scheme != 'zotero' or url.netloc != 'open-pdf' or url.fragment:
            return None
        match = re.fullmatch(r'/(library|groups/[0-9]+)/items/([A-Za-z0-9]+)', url.path)
        keys = parse_qs(url.query).get('annotation', [])
        if not match or len(keys) != 1 or not re.fullmatch(r'[A-Za-z0-9]+', keys[0]):
            return None
        return f'{match[1]}/{match[2].upper()}/{keys[0].upper()}'
    except ValueError:
        return None


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.hrefs.extend(value or '' for key, value in attrs if key == 'href')


def identities_from_html(value: str) -> list[str]:
    parser = _Links()
    parser.feed(value or '')
    return list(dict.fromkeys(identity for href in parser.hrefs if (identity := source_identity(href))))


def escaped_word(value: str) -> str:
    # Decode one legacy HTML-escaped layer, then encode once at the rendering boundary.
    return html.escape(html.unescape(value), quote=True)


def word_identity(value: str) -> str:
    import unicodedata
    return ' '.join(unicodedata.normalize('NFKC', html.unescape(value)).split()).casefold()
