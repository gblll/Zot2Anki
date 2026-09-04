"""Resolve Zotero annotation sources and extract verifiable example sentences."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    from .source_identity import source_identity, word_identity
    from .sync_storage import atomic_json
except ImportError:
    from source_identity import source_identity, word_identity
    from sync_storage import atomic_json


ANNOTATION_KEY_PATTERN = re.compile(r"[?&]annotation=([A-Z0-9]+)", re.IGNORECASE)
ATTACHMENT_KEY_PATTERN = re.compile(r"zotero://open-pdf/(?:library|groups/\d+)/items/([A-Z0-9]+)", re.IGNORECASE)
MANAGED_EXAMPLE_TAGS = {
    "ContextFragment",
    "OnlineExample",
    "NoExample",
    "ExampleNeedsReview",
    "OCRRequired",
    "MissingSource",
}


@dataclass(frozen=True)
class SourceContext:
    annotation_key: str
    attachment_key: str
    attachment_path: Path | None
    annotation_text: str
    page_label: str
    page_index: int
    rects: tuple[tuple[float, float, float, float], ...]
    item_title: str
    doi: str
    href: str


@dataclass(frozen=True)
class ExampleCandidate:
    text: str
    kind: str
    title: str = ""
    journal: str = ""
    year: str = ""
    page_label: str = ""
    doi: str = ""
    url: str = ""
    source_href: str = ""
    verified_provider: str = ""

    def identity(self) -> str:
        return normalize_for_match(self.text)


@dataclass(frozen=True)
class ExtractionOutcome:
    example: ExampleCandidate | None
    tags: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def extract_annotation_key(href: str) -> str:
    match = ANNOTATION_KEY_PATTERN.search(href or "")
    return match.group(1).upper() if match else ""


def extract_attachment_key(href: str) -> str:
    match = ATTACHMENT_KEY_PATTERN.search(href or "")
    return match.group(1).upper() if match else ""


def normalize_for_match(value: str) -> str:
    value = html.unescape(value or "").casefold()
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "", value)
    return re.sub(r"[^\w]+", "", value, flags=re.UNICODE)


def _chunks(values: list[str], size: int = 400) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _resolve_attachment_path(data_dir: Path, attachment_key: str, stored_path: str | None) -> Path | None:
    if not stored_path:
        return None
    if stored_path.startswith("storage:"):
        root = (data_dir / 'storage' / attachment_key).resolve()
        candidate = (root / stored_path.removeprefix('storage:')).resolve()
        return candidate if candidate.is_relative_to(root) else None
    candidate = Path(stored_path)
    if candidate.is_absolute():
        return candidate
    return None


def load_source_contexts(
    connection: sqlite3.Connection,
    hrefs: Iterable[str],
    data_dir: Path,
) -> dict[str, SourceContext]:
    """Resolve note links to Zotero annotation/PDF metadata without modifying Zotero."""

    contexts: dict[str, SourceContext] = {}
    for href in dict.fromkeys(hrefs):
        identity = source_identity(href)
        if not identity:
            continue
        namespace, attachment_key, annotation_key = identity.rsplit('/', 2)
        if namespace == 'library':
            libraries = connection.execute("SELECT libraryID FROM libraries WHERE type = 'user'").fetchall()
        else:
            libraries = connection.execute('SELECT libraryID FROM groups WHERE groupID = ?', (int(namespace.split('/')[1]),)).fetchall()
        if len(libraries) != 1:
            continue
        rows = connection.execute(
            """
            SELECT
                ann.key,
                attachment.key,
                attachmentData.path,
                annotation.text,
                annotation.pageLabel,
                annotation.position,
                COALESCE((
                    SELECT value.value
                    FROM itemData AS data
                    JOIN fields AS field ON field.fieldID = data.fieldID
                    JOIN itemDataValues AS value ON value.valueID = data.valueID
                    WHERE data.itemID = attachmentData.parentItemID
                      AND field.fieldName = 'title'
                    LIMIT 1
                ), ''),
                COALESCE((
                    SELECT value.value
                    FROM itemData AS data
                    JOIN fields AS field ON field.fieldID = data.fieldID
                    JOIN itemDataValues AS value ON value.valueID = data.valueID
                    WHERE data.itemID = attachmentData.parentItemID
                      AND field.fieldName = 'DOI'
                    LIMIT 1
                ), '')
            FROM itemAnnotations AS annotation
            JOIN items AS ann ON ann.itemID = annotation.itemID
            JOIN items AS attachment ON attachment.itemID = annotation.parentItemID
            LEFT JOIN itemAttachments AS attachmentData ON attachmentData.itemID = attachment.itemID
            LEFT JOIN deletedItems AS deleted ON deleted.itemID = ann.itemID
            WHERE deleted.itemID IS NULL AND ann.key = ? AND attachment.key = ?
              AND ann.libraryID = attachment.libraryID
              AND ann.libraryID = ?
              AND NOT EXISTS (SELECT 1 FROM deletedItems WHERE itemID = attachment.itemID)
              AND NOT EXISTS (SELECT 1 FROM deletedItems WHERE itemID = attachmentData.parentItemID)
            """,
            (annotation_key, attachment_key, libraries[0][0]),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError('Ambiguous Zotero source identity')
        for row in rows:
            annotation_key = str(row[0]).upper()
            try:
                position = json.loads(row[5] or "{}")
                rects = tuple(tuple(float(value) for value in rect) for rect in position.get("rects", ()))
                import math
                if any(len(rect) != 4 or not all(math.isfinite(value) for value in rect) for rect in rects):
                    raise ValueError('Invalid annotation rectangle')
                page_index = int(position.get("pageIndex", -1))
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                rects = ()
                page_index = -1
            attachment_key = str(row[1]).upper()
            contexts[identity] = SourceContext(
                annotation_key=annotation_key,
                attachment_key=attachment_key,
                attachment_path=_resolve_attachment_path(data_dir, attachment_key, row[2]),
                annotation_text=str(row[3] or ""),
                page_label=str(row[4] or ""),
                page_index=page_index,
                rects=rects,
                item_title=str(row[6] or ""),
                doi=str(row[7] or ""),
                href=href,
            )
    return contexts


def _join_tokens(words: list[tuple]) -> str:
    lines: dict[tuple[int, int], list[tuple]] = {}
    for word in words:
        lines.setdefault((int(word[5]), int(word[6])), []).append(word)
    rendered_lines: list[str] = []
    for key in sorted(lines):
        ordered = sorted(lines[key], key=lambda item: int(item[7]))
        ordered = [
            word
            for word in ordered
            if not (
                re.fullmatch(r"\d{1,4}", str(word[4]))
                and float(word[0]) < 65
            )
        ]
        if not ordered:
            continue
        if (
            len(ordered) > 1
            and re.fullmatch(r"\d{1,4}", str(ordered[0][4]))
            and float(ordered[1][0]) - float(ordered[0][2]) > 8
        ):
            ordered = ordered[1:]
        tokens = [str(word[4]) for word in ordered]
        line = " ".join(tokens)
        line = re.sub(r"\s+([,.;:!?%\)\]\}])", r"\1", line)
        line = re.sub(r"([\(\[\{])\s+", r"\1", line)
        rendered_lines.append(line.strip())
    output = ""
    for line in rendered_lines:
        if not line:
            continue
        if output.endswith("-") and re.match(r"^[a-z]", line):
            output = output[:-1] + line
        else:
            output = f"{output} {line}".strip()
    return re.sub(r"\s+", " ", output).strip()


def _normalized_with_map(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "-" and index + 1 < len(value):
            match = re.match(r"-\s+(?=\w)", value[index:])
            if match:
                index += len(match.group(0))
                continue
        folded = unicodedata.normalize('NFKC', char).casefold()
        for folded_char in folded:
            normalized.append(folded_char)
            positions.append(index)
        index += 1
    return "".join(normalized), positions


def find_term_span(text: str, term: str) -> tuple[int, int] | None:
    normalized_text, positions = _normalized_with_map(text)
    normalized_term, _ = _normalized_with_map(html.unescape(term))
    if not normalized_term.strip():
        return None
    pattern = r'(?<!\w)' + r'\s+'.join(re.escape(part) for part in normalized_term.split()) + r'(?!\w)'
    match = re.search(pattern, normalized_text)
    if match:
        return positions[match.start()], positions[match.end() - 1] + 1
    return None


def _sentence_containing(text: str, term: str) -> str | None:
    span = find_term_span(text, term)
    if span is None:
        return None
    start, end = span
    boundary_start = 0
    for match in re.finditer(r"[.!?][\"'\)\]]*\s+", text[:start]):
        boundary_start = match.end()
    boundary_end = len(text)
    match = re.search(r"[.!?][\"'\)\]]*(?:\s|$)", text[end:])
    if match:
        boundary_end = end + match.end()
    sentence = text[boundary_start:boundary_end].strip()
    word_count = len(re.findall(r"\b[\w'-]+\b", sentence, flags=re.UNICODE))
    if word_count < 6 or word_count > 80:
        return None
    if not re.search(r"[.!?][\"'\)\]]*$", sentence):
        return None
    return sentence


def _trim_fragment(text: str, term: str, maximum_words: int = 40) -> str:
    span = find_term_span(text, term)
    if span is None:
        return ""
    tokens = list(re.finditer(r"\S+", text))
    anchor = next((i for i, token in enumerate(tokens) if token.start() <= span[0] < token.end()), 0)
    start = max(0, anchor - maximum_words // 2)
    end = min(len(tokens), start + maximum_words)
    start = max(0, end - maximum_words)
    return " ".join(token.group(0) for token in tokens[start:end]).strip()


def highlight_term(text: str, term: str) -> str:
    span = find_term_span(text, term)
    if span is None:
        return html.escape(text, quote=True)
    start, end = span
    return (
        html.escape(text[:start], quote=True)
        + '<strong class="z2a-example-word">'
        + html.escape(text[start:end], quote=True)
        + "</strong>"
        + html.escape(text[end:], quote=True)
    )


class PdfExampleExtractor:
    def __init__(self) -> None:
        try:
            import pymupdf  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "缺少 PyMuPDF。请先运行：python -m pip install -r requirements.txt"
            ) from exc
        self._pymupdf = pymupdf
        self._documents: dict[Path, object] = {}

    def close(self) -> None:
        for document in self._documents.values():
            document.close()
        self._documents.clear()

    def __enter__(self) -> "PdfExampleExtractor":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _document(self, path: Path):
        if path not in self._documents:
            self._documents[path] = self._pymupdf.open(path)
        return self._documents[path]

    @staticmethod
    def _overlaps(word: tuple, rect: tuple[float, float, float, float]) -> bool:
        x0, y0, x1, y1 = rect
        return (
            min(float(word[2]), x1) - max(float(word[0]), x0) > 0.2
            and min(float(word[3]), y1) - max(float(word[1]), y0) > 0.2
        )

    def extract(self, context: SourceContext, term: str) -> ExtractionOutcome:
        path = context.attachment_path
        if path is None or not path.is_file():
            return ExtractionOutcome(None, ("MissingSource",), ("missing_pdf",))
        if context.page_index < 0 or not context.rects:
            return ExtractionOutcome(None, ("ExampleNeedsReview",), ("missing_position",))
        try:
            document = self._document(path)
            if context.page_index >= len(document):
                return ExtractionOutcome(None, ("ExampleNeedsReview",), ("invalid_page",))
            page = document[context.page_index]
            words = page.get_text("words", sort=False)
        except Exception as exc:
            return ExtractionOutcome(None, ("ExampleNeedsReview",), (f"pdf_error:{type(exc).__name__}",))
        if not words:
            return ExtractionOutcome(None, ("OCRRequired",), ("pdf_has_no_text",))
        mapped_rects = [
            tuple(self._pymupdf.Rect(rect) * page.transformation_matrix)
            for rect in context.rects
        ]
        hits = [
            word
            for word in words
            if any(self._overlaps(word, rect) for rect in mapped_rects)
        ]
        if not hits:
            return ExtractionOutcome(None, ("ExampleNeedsReview",), ("coordinate_miss",))
        anchor_blocks = {int(word[5]) for word in hits}
        block_rows = page.get_text("blocks", sort=False)
        text_blocks = [row for row in block_rows if len(row) > 6 and int(row[6]) == 0 and str(row[4]).strip()]
        selected_words = [word for word in words if int(word[5]) in anchor_blocks]
        selected_text = _join_tokens(selected_words)
        sentence = _sentence_containing(selected_text, term)
        if sentence is None:
            anchor_box = next((row for row in text_blocks if int(row[5]) in anchor_blocks), None)
            if anchor_box is not None:
                ax0, ay0, ax1, ay1 = map(float, anchor_box[:4])
                neighbours = []
                for row in text_blocks:
                    bx0, by0, bx1, by1 = map(float, row[:4])
                    overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0))
                    width = max(1.0, min(ax1 - ax0, bx1 - bx0))
                    vertical_gap = max(0.0, max(ay0, by0) - min(ay1, by1))
                    if overlap / width >= 0.55 and vertical_gap <= 70:
                        neighbours.append(row)
                neighbour_ids = {int(row[5]) for row in neighbours}
                combined = _join_tokens([word for word in words if int(word[5]) in neighbour_ids])
                sentence = _sentence_containing(combined, term)
                if sentence is not None:
                    selected_text = combined
        if sentence is not None:
            return ExtractionOutcome(
                ExampleCandidate(
                    text=sentence,
                    kind="local_sentence",
                    title=context.item_title,
                    page_label=context.page_label,
                    doi=context.doi,
                    source_href=context.href,
                )
            )
        fragment = _trim_fragment(selected_text, term)
        if fragment:
            return ExtractionOutcome(
                ExampleCandidate(
                    text=fragment,
                    kind="local_fragment",
                    title=context.item_title,
                    page_label=context.page_label,
                    doi=context.doi,
                    source_href=context.href,
                ),
                ("ContextFragment",),
                ("context_is_not_complete_sentence",),
            )
        return ExtractionOutcome(None, ("ExampleNeedsReview",), ("term_not_found_in_block",))


def _plain_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _year_from_parts(parts) -> str:
    try:
        return str(parts[0][0])
    except (TypeError, IndexError):
        return ""


class AcademicExampleClient:
    def __init__(self, cache_path: Path, timeout: float = 15.0, *, refresh: bool = False) -> None:
        self.cache_path = cache_path
        self.timeout = timeout
        self.refresh = refresh
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        atomic_json(self.cache_path, self.cache)

    def _json(self, url: str) -> dict:
        request = Request(url, headers={"User-Agent": "Zot2Anki/0.2.0"})
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code != 429 or attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
            except URLError:
                if attempt == 2:
                    raise
                time.sleep(0.5 * (attempt + 1))
        return {}

    @staticmethod
    def _acceptable_sentence(text: str, term: str) -> str | None:
        for sentence in re.split(r"(?<=[.!?])\s+", _plain_text(text)):
            if find_term_span(sentence, term) is None:
                continue
            count = len(re.findall(r"\b[\w'-]+\b", sentence, flags=re.UNICODE))
            if 6 <= count <= 80 and re.search(r"[.!?][\"'\)\]]*$", sentence):
                return sentence.strip()
        return None

    def _crossref(self, term: str) -> ExampleCandidate | None:
        params = urlencode(
            {
                "query": term,
                "filter": "type:journal-article,has-abstract:true",
                "rows": 20,
                "select": "DOI,title,container-title,published,abstract,URL",
            }
        )
        payload = self._json(f"https://api.crossref.org/works?{params}")
        for item in payload.get("message", {}).get("items", []):
            sentence = self._acceptable_sentence(item.get("abstract", ""), term)
            doi = str(item.get("DOI", ""))
            if sentence and doi:
                return ExampleCandidate(
                    text=sentence,
                    kind="online",
                    title=" ".join(item.get("title") or []),
                    journal=" ".join(item.get("container-title") or []),
                    year=_year_from_parts(item.get("published", {}).get("date-parts")),
                    doi=doi,
                    url=f"https://doi.org/{quote(doi, safe='/')}",
                    verified_provider="crossref"
                )
        return None

    def _europe_pmc(self, term: str) -> ExampleCandidate | None:
        query = f'TITLE_ABS:"{term}"'
        params = urlencode({"query": query, "format": "json", "pageSize": 25, "resultType": "core"})
        payload = self._json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}")
        for item in payload.get("resultList", {}).get("result", []):
            sentence = self._acceptable_sentence(item.get("abstractText", ""), term)
            doi = str(item.get("doi", ""))
            if sentence and doi:
                return ExampleCandidate(
                    text=sentence,
                    kind="online",
                    title=str(item.get("title", "")),
                    journal=str(item.get("journalTitle", "")),
                    year=str(item.get("pubYear", "")),
                    doi=doi,
                    url=f"https://doi.org/{quote(doi, safe='/')}",
                    verified_provider="europe_pmc"
                )
        return None

    def find(self, term: str) -> ExampleCandidate | None:
        key = word_identity(term)
        cached = self.cache.get(key)
        if not self.refresh and isinstance(cached, dict) and cached.get('status') in ('found', 'empty'):
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(cached['fetched_at'])).total_seconds()
                ttl = 30 * 86400 if cached['status'] == 'found' else 86400
                if 0 <= age < ttl:
                    return ExampleCandidate(**cached['result']) if cached['status'] == 'found' else None
            except (KeyError, TypeError, ValueError):
                pass
        result = None
        errors: list[str] = []
        for provider in (self._crossref, self._europe_pmc):
            try:
                result = provider(term)
            except (OSError, TimeoutError, ValueError, TypeError, AttributeError) as exc:
                errors.append(f"{provider.__name__}:{type(exc).__name__}: {exc}")
                continue
            if result is not None:
                break
        if result is not None or not errors:
            self.cache[key] = {
                'fetched_at': datetime.now(timezone.utc).isoformat(),
                'status': 'found' if result else 'empty',
                'result': asdict(result) if result else None,
            }
            self._save_cache()
        elif key in self.cache:
            del self.cache[key]
            self._save_cache()
        return result
