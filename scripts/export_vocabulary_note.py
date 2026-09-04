#!/usr/bin/env python3
"""Export a Zotero vocabulary note to an Anki-compatible UTF-8 TSV."""

from __future__ import annotations

import argparse
import html
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata

try:
    from scripts import local_config
    from scripts.vocabulary_examples import (
        AcademicExampleClient,
        ExampleCandidate,
        PdfExampleExtractor,
        SourceContext,
        extract_annotation_key,
        highlight_term,
        load_source_contexts,
    )
except ModuleNotFoundError:  # Direct execution from scripts/.
    import local_config
    from vocabulary_examples import (
        AcademicExampleClient,
        ExampleCandidate,
        PdfExampleExtractor,
        SourceContext,
        extract_annotation_key,
        highlight_term,
        load_source_contexts,
    )


DEFAULT_DATABASE = local_config.DEFAULT_DATABASE
ANKI_HEADERS = (
    "#separator:Tab",
    "#html:true",
    "#notetype:Zotero2Anki Vocabulary",
    "#columns:Word\tSymbol\tChn\tExample\tSource\tZoteroKeys\tTags",
    "#tags column:7",
)
WAL_HEADER_SIZE = 32
PRONUNCIATION_PATTERN = re.compile(
    r"^\s*🔉\s*"
    r"(?:(?:英\s*\[([^\]]+)\])(?:\s*[,，]\s*美\s*\[([^\]]+)\])?"
    r"|(?:美\s*\[([^\]]+)\]))"
    r"\s+(.+?)\s*$",
    re.DOTALL,
)
LABELED_MULTIBLOCK_PRONUNCIATION_PATTERN = re.compile(
    r"^\s*🔉\s*英\s*\[([^\]]+)\]\s*<br\s*/?>\s*"
    r"🔉\s*美\s*\[([^\]]+)\]\s*<br\s*/?>",
    re.IGNORECASE,
)


class ExportError(RuntimeError):
    """A user-facing export error."""


@dataclass
class NoteRecord:
    item_id: int
    key: str
    library_id: int
    title: str
    note_html: str


@dataclass
class ParagraphRecord:
    index: int
    front: str
    href: str
    definition_html: str
    code_count: int
    link_count: int
    review_reasons: list[str] = field(default_factory=list)
    zotero_key: str = ""
    source_context: SourceContext | None = None
    examples: list[ExampleCandidate] = field(default_factory=list)
    example_tags: list[str] = field(default_factory=list)


@dataclass
class Card:
    word: str
    symbol_html: str
    chn_html: str
    example_html: str
    source_html: str
    zotero_keys: list[str]
    tags: list[str]
    sources: list[str]
    examples: list[ExampleCandidate]
    review_reasons: list[str]
    original_definition_html: str


@dataclass
class ParsedDefinition:
    symbol_html: str
    chn_html: str
    parsed: bool


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_front(value: str) -> str:
    return normalize_text(value)


def dedupe_key(value: str) -> str:
    return normalize_front(value).casefold()


def sanitize_tsv_cell(value: str) -> str:
    return str(value or "").replace("\t", "    ").replace("\r", " ").replace("\n", " ")


PRONUNCIATION_NAMES = {
    "UK": ("uk", "英音"),
    "US": ("us", "美音"),
}


PART_OF_SPEECH_STYLES = {
    "n.": "noun",
    "excl.": "exclamation",
    "exclam.": "exclamation",
    "a.": "adjective",
    "adj.": "adjective",
    "ad.": "adverb",
    "adv.": "adverb",
    "v.": "verb",
    "vi.": "intransitive-verb",
    "vt.": "transitive-verb",
    "prep.": "preposition",
    "conj.": "conjunction",
    "pron.": "pronoun",
    "art.": "article",
    "num.": "number",
    "int.": "interjection",
    "interj.": "interjection",
    "modal.": "modal",
    "aux.": "auxiliary",
    "pl.": "plural",
    "abbr.": "abbreviation",
    "det.": "determiner",
    "na.": "na",
}
PART_OF_SPEECH_PATTERN = re.compile(
    r"(?<![A-Za-z])(" + "|".join(
        re.escape(part) for part in sorted(PART_OF_SPEECH_STYLES, key=len, reverse=True)
    )
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)


def _format_pronunciation(label: str, value: str) -> str:
    normalized = normalize_text(value).strip("/")
    dialect, accessible_name = PRONUNCIATION_NAMES[label]
    return (
        f'<span class="pronunciation-item pronunciation-{dialect}">'
        f'<span class="pronunciation-label" aria-label="{accessible_name}">{label}</span>'
        f'<span class="pronunciation-ipa">/{html.escape(normalized, quote=True)}/</span>'
        "</span>"
    )


def style_parts_of_speech(value: str) -> str:
    """Wrap known part-of-speech markers without changing HTML tags."""

    def replace_text(text: str) -> str:
        def replace_match(match: re.Match[str]) -> str:
            marker = match.group(1)
            style_name = PART_OF_SPEECH_STYLES.get(marker.casefold())
            if style_name is None:
                return marker
            return (
                f'<span class="z2a-pos z2a-pos-{style_name}">'
                f"{html.escape(marker, quote=False)}</span>"
            )

        return PART_OF_SPEECH_PATTERN.sub(replace_match, text)

    return "".join(
        part if part.startswith("<") else replace_text(part)
        for part in re.split(r"(<[^>]+>)", value or "")
    )


def split_definition(definition_html: str) -> ParsedDefinition:
    """Split one safe definition into pronunciation HTML and meaning HTML.

    Only a single, complete pronunciation prefix is accepted. Multi-block content
    is deliberately preserved as-is so that potentially mismatched definitions are
    never rearranged or guessed.
    """

    if not definition_html:
        return ParsedDefinition("", definition_html, False)
    if re.search(r"<(?:br|hr)\b", definition_html, re.IGNORECASE):
        labeled = LABELED_MULTIBLOCK_PRONUNCIATION_PATTERN.match(
            html.unescape(definition_html)
        )
        if labeled:
            uk, us = labeled.groups()
            return ParsedDefinition(
                _format_pronunciation("UK", uk) + _format_pronunciation("US", us),
                definition_html,
                True,
            )
        return ParsedDefinition("", definition_html, False)
    plain = normalize_text(html.unescape(definition_html))
    match = PRONUNCIATION_PATTERN.fullmatch(plain)
    if not match:
        return ParsedDefinition("", definition_html, False)
    uk, us_after_uk, us_only, meaning = match.groups()
    pronunciations = []
    if uk:
        pronunciations.append(_format_pronunciation("UK", uk))
    us = us_after_uk or us_only
    if us:
        pronunciations.append(_format_pronunciation("US", us))
    if not pronunciations or not normalize_text(meaning):
        return ParsedDefinition("", definition_html, False)
    return ParsedDefinition(
        "".join(pronunciations),
        html.escape(normalize_text(meaning), quote=True),
        True,
    )


class _VocabularyNoteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.records: list[ParagraphRecord] = []
        self._paragraph: dict | None = None
        self._paragraph_index = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "p":
            if self._paragraph is not None:
                self._finish_paragraph()
            self._paragraph = {
                "front_parts": [],
                "href": "",
                "capturing_front": False,
                "after_source": False,
                "segments": [[]],
                "code_count": 0,
                "link_count": 0,
            }
            return
        paragraph = self._paragraph
        if paragraph is None:
            return
        if tag == "a":
            paragraph["link_count"] += 1
            href = dict(attrs).get("href") or ""
            if not paragraph["href"]:
                paragraph["href"] = href
                paragraph["capturing_front"] = True
            return
        if tag == "code" and paragraph["after_source"]:
            paragraph["code_count"] += 1
        elif tag == "br" and paragraph["after_source"]:
            paragraph["segments"].append([])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._paragraph is None:
            return
        if tag == "a" and self._paragraph["capturing_front"]:
            self._paragraph["capturing_front"] = False
            self._paragraph["after_source"] = True
        elif tag == "p":
            self._finish_paragraph()

    def handle_data(self, data: str) -> None:
        paragraph = self._paragraph
        if paragraph is None:
            return
        if paragraph["capturing_front"]:
            paragraph["front_parts"].append(data)
        elif paragraph["after_source"]:
            paragraph["segments"][-1].append(data)

    def close(self) -> None:
        super().close()
        if self._paragraph is not None:
            self._finish_paragraph()

    def _finish_paragraph(self) -> None:
        paragraph = self._paragraph
        if paragraph is None:
            return
        front = normalize_front("".join(paragraph["front_parts"]))
        segments = [normalize_text("".join(parts)) for parts in paragraph["segments"]]
        if segments:
            segments[0] = re.sub(r"^\s*[:：]\s*", "", segments[0], count=1)
        segments = [segment for segment in segments if segment]
        definition_html = "<br>".join(html.escape(segment, quote=True) for segment in segments)
        reasons: list[str] = []
        if front and paragraph["href"]:
            if not definition_html:
                reasons.append("missing_definition")
            if paragraph["code_count"] == 0:
                reasons.append("definition_without_code")
            elif paragraph["code_count"] > 1:
                reasons.append("multiple_code_blocks")
        self.records.append(
            ParagraphRecord(
                index=self._paragraph_index,
                front=front,
                href=paragraph["href"],
                definition_html=definition_html,
                code_count=paragraph["code_count"],
                link_count=paragraph["link_count"],
                review_reasons=reasons,
            )
        )
        self._paragraph_index += 1
        self._paragraph = None


def parse_note_html(note_html: str) -> list[ParagraphRecord]:
    parser = _VocabularyNoteParser()
    parser.feed(note_html or "")
    parser.close()
    return parser.records


def _database_uri(database: Path, *, immutable: bool = False) -> str:
    suffix = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    return database.resolve().as_uri() + suffix


def open_database_readonly(database: Path) -> tuple[sqlite3.Connection, str]:
    database = database.expanduser().resolve()
    if not database.is_file():
        raise ExportError(f"Zotero 数据库不存在：{database}")
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(_database_uri(database), uri=True, timeout=0)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
        return connection, "read-only"
    except sqlite3.OperationalError as exc:
        if connection is not None:
            connection.close()
        if "locked" not in str(exc).lower():
            raise ExportError(f"无法读取 Zotero 数据库：{exc}") from exc
        wal_path = Path(str(database) + "-wal")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0
        if wal_size > WAL_HEADER_SIZE:
            raise ExportError(
                "Zotero 数据库正在使用且 WAL 中存在未落盘数据。请关闭 Zotero 后重新运行，"
                "以免导出到不完整的笔记版本。"
            ) from exc
        try:
            connection = sqlite3.connect(
                _database_uri(database, immutable=True), uri=True, timeout=0
            )
            connection.execute("PRAGMA query_only = ON")
            connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
            return connection, "immutable-read-only"
        except sqlite3.Error as fallback_exc:
            if connection is not None:
                connection.close()
            raise ExportError(
                "Zotero 数据库当前无法安全读取。请关闭 Zotero 后重新运行。"
            ) from fallback_exc


def find_note(connection: sqlite3.Connection, note_title: str) -> NoteRecord:
    rows = connection.execute(
        """
        SELECT i.itemID, i.key, i.libraryID, n.title, n.note
        FROM itemNotes AS n
        JOIN items AS i ON i.itemID = n.itemID
        LEFT JOIN deletedItems AS d ON d.itemID = i.itemID
        WHERE d.itemID IS NULL AND n.title = ?
        ORDER BY i.itemID
        """,
        (note_title,),
    ).fetchall()
    if not rows:
        raise ExportError(f"未找到标题完全匹配的 Zotero 笔记：{note_title}")
    if len(rows) > 1:
        keys = ", ".join(str(row[1]) for row in rows)
        raise ExportError(f"找到多条同名笔记（{keys}）；请先在 Zotero 中保留唯一一条。")
    row = rows[0]
    return NoteRecord(int(row[0]), str(row[1]), int(row[2]), str(row[3]), str(row[4] or ""))


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def enrich_records_with_examples(
    connection: sqlite3.Connection,
    records: list[ParagraphRecord],
    data_dir: Path,
    *,
    cache_path: Path,
    online_fallback: bool = True,
) -> dict[str, int]:
    """Attach Zotero metadata and at most one local/online result per source record."""

    hrefs = [record.href for record in records if record.href]
    contexts = load_source_contexts(connection, hrefs, data_dir)
    local_sentences = 0
    local_fragments = 0
    online_sentences = 0
    missing_sources = 0
    online_client = AcademicExampleClient(cache_path) if online_fallback else None
    with PdfExampleExtractor() as extractor:
        for record in records:
            if not record.front or not record.href:
                continue
            record.zotero_key = extract_annotation_key(record.href)
            if not record.zotero_key:
                _append_unique(record.example_tags, "MissingSource")
                _append_unique(record.review_reasons, "missing_annotation_key")
                missing_sources += 1
            else:
                context = contexts.get(record.zotero_key)
                record.source_context = context
                if context is None:
                    _append_unique(record.example_tags, "MissingSource")
                    _append_unique(record.review_reasons, "annotation_not_found")
                    missing_sources += 1
                else:
                    outcome = extractor.extract(context, record.front)
                    for tag in outcome.tags:
                        _append_unique(record.example_tags, tag)
                    for reason in outcome.reasons:
                        _append_unique(record.review_reasons, reason)
                    if outcome.example is not None:
                        record.examples.append(outcome.example)
                        if outcome.example.kind == "local_sentence":
                            local_sentences += 1
                        elif outcome.example.kind == "local_fragment":
                            local_fragments += 1
            needs_online = not any(example.kind == "local_sentence" for example in record.examples)
            if needs_online and online_client is not None:
                online = online_client.find(record.front)
                if online is not None:
                    if all(example.identity() != online.identity() for example in record.examples):
                        record.examples.append(online)
                    _append_unique(record.example_tags, "OnlineExample")
                    online_sentences += 1
                else:
                    _append_unique(record.example_tags, "NoExample")
                    _append_unique(record.review_reasons, "online_example_not_found")
            elif needs_online:
                _append_unique(record.example_tags, "NoExample")
    return {
        "resolved_contexts": len(contexts),
        "missing_sources": missing_sources,
        "local_sentences": local_sentences,
        "local_fragments": local_fragments,
        "online_sentences": online_sentences,
    }


def _example_metadata(example: ExampleCandidate) -> str:
    parts = [part for part in (example.title, example.journal, example.year) if part]
    if example.page_label:
        parts.append(f"p. {example.page_label}")
    text = " · ".join(html.escape(normalize_text(part), quote=True) for part in parts)
    links: list[str] = []
    if example.source_href:
        links.append(
            '<a class="z2a-example-link" '
            f'href="{html.escape(example.source_href, quote=True)}">Zotero</a>'
        )
    if example.doi:
        url = example.url or f"https://doi.org/{example.doi}"
        links.append(
            '<a class="z2a-example-link" '
            f'href="{html.escape(url, quote=True)}">DOI</a>'
        )
    if links:
        text = (text + " · " if text else "") + " ".join(links)
    return text


def render_examples(examples: list[ExampleCandidate], word: str) -> str:
    blocks: list[str] = []
    for example in examples[:3]:
        label = {
            "local_sentence": "Zotero 原文例句",
            "local_fragment": "Zotero 原文片段",
            "online": "开放学术例句",
        }.get(example.kind, "例句")
        metadata = _example_metadata(example)
        blocks.append(
            f'<article class="z2a-example z2a-example-{html.escape(example.kind, quote=True)}">'
            f'<div class="z2a-example-kind">{label}</div>'
            f'<div class="z2a-example-text">{highlight_term(example.text, word)}</div>'
            + (f'<div class="z2a-example-meta">{metadata}</div>' if metadata else "")
            + "</article>"
        )
    return '<div class="z2a-examples">' + "".join(blocks) + "</div>" if blocks else ""


def render_sources(source_records: list[tuple[str, SourceContext | None]]) -> str:
    multiple = len(source_records) > 1
    links: list[str] = []
    for index, (href, context) in enumerate(source_records, start=1):
        label = "在 Zotero 中打开来源"
        if multiple:
            label += f" {index}"
        if context is not None:
            detail = context.item_title
            if context.page_label:
                detail = f"{detail} · p. {context.page_label}" if detail else f"p. {context.page_label}"
            if detail:
                label += f" · {detail}"
        links.append(
            '<a class="zotero2anki-source-link" '
            f'href="{html.escape(href, quote=True)}">{html.escape(label, quote=True)}</a>'
        )
    return '<div class="zotero2anki-source">' + "<br>".join(links) + "</div>"


def build_cards(records: list[ParagraphRecord]) -> tuple[list[Card], dict[str, int]]:
    groups: OrderedDict[str, dict] = OrderedDict()
    skipped_empty = 0
    skipped_invalid_source = 0
    for record in records:
        if not record.front and not record.href and not record.definition_html:
            skipped_empty += 1
            continue
        if not record.front or not record.href.startswith("zotero://open-pdf/"):
            skipped_invalid_source += 1
            continue
        key = dedupe_key(record.front)
        group = groups.get(key)
        if group is None:
            group = {
                "word": normalize_front(record.front),
                "definitions": [],
                "sources": [],
                "source_records": [],
                "zotero_keys": [],
                "examples": [],
                "example_tags": [],
                "reasons": [],
            }
            groups[key] = group
        if record.definition_html and record.definition_html not in group["definitions"]:
            group["definitions"].append(record.definition_html)
        if record.href not in group["sources"]:
            group["sources"].append(record.href)
            group["source_records"].append((record.href, record.source_context))
        if record.zotero_key and record.zotero_key not in group["zotero_keys"]:
            group["zotero_keys"].append(record.zotero_key)
        for example in record.examples:
            if example.identity() and all(
                current.identity() != example.identity() for current in group["examples"]
            ):
                group["examples"].append(example)
        for tag in record.example_tags:
            if tag not in group["example_tags"]:
                group["example_tags"].append(tag)
        for reason in record.review_reasons:
            if reason not in group["reasons"]:
                group["reasons"].append(reason)
    cards: list[Card] = []
    parsed_definitions = 0
    unparsed_definitions = 0
    for group in groups.values():
        definitions = group["definitions"] or ["<em>暂无释义</em>"]
        symbols: list[str] = []
        meanings: list[str] = []
        for definition in definitions:
            parsed = split_definition(definition)
            if parsed.parsed:
                parsed_definitions += 1
            else:
                unparsed_definitions += 1
                if "unparsed_pronunciation" not in group["reasons"]:
                    group["reasons"].append("unparsed_pronunciation")
            if parsed.symbol_html and parsed.symbol_html not in symbols:
                symbols.append(parsed.symbol_html)
            if parsed.chn_html and parsed.chn_html not in meanings:
                meanings.append(parsed.chn_html)
        symbol_html = "<br>".join(symbols)
        chn_html = style_parts_of_speech(
            "<hr>".join(meanings) or "<em>暂无释义</em>"
        )
        original_definition_html = "<hr>".join(definitions)
        examples = list(group["examples"][:3])
        example_html = render_examples(examples, group["word"])
        source_html = render_sources(group["source_records"])
        tags = ["Zotero2Anki"]
        tags.extend(group["example_tags"])
        if group["reasons"] or any(tag in tags for tag in ("NoExample", "ExampleNeedsReview", "MissingSource")):
            tags.append("NeedsReview")
        tags = list(dict.fromkeys(tags))
        cards.append(
            Card(
                word=group["word"],
                symbol_html=symbol_html,
                chn_html=chn_html,
                example_html=example_html,
                source_html=source_html,
                zotero_keys=list(group["zotero_keys"]),
                tags=tags,
                sources=list(group["sources"]),
                examples=examples,
                review_reasons=list(group["reasons"]),
                original_definition_html=original_definition_html,
            )
        )
    source_records = sum(
        bool(record.front and record.href.startswith("zotero://open-pdf/"))
        for record in records
    )
    stats = {
        "paragraphs": len(records),
        "source_records": source_records,
        "cards": len(cards),
        "duplicates_merged": source_records - len(cards),
        "needs_review": sum("NeedsReview" in card.tags for card in cards),
        "skipped_empty": skipped_empty,
        "skipped_invalid_source": skipped_invalid_source,
        "source_links": sum(len(card.sources) for card in cards),
        "zotero_keys": sum(len(card.zotero_keys) for card in cards),
        "example_cards": sum(bool(card.examples) for card in cards),
        "example_count": sum(len(card.examples) for card in cards),
        "context_fragments": sum("ContextFragment" in card.tags for card in cards),
        "online_example_cards": sum("OnlineExample" in card.tags for card in cards),
        "missing_example_cards": sum("NoExample" in card.tags for card in cards),
        "parsed_definitions": parsed_definitions,
        "unparsed_definitions": unparsed_definitions,
    }
    return cards, stats


def serialize_anki_tsv(cards: list[Card]) -> str:
    lines = list(ANKI_HEADERS)
    for card in cards:
        word = html.escape(normalize_front(card.word), quote=True)
        fields = [
            word,
            card.symbol_html,
            card.chn_html,
            card.example_html,
            card.source_html,
            " ".join(card.zotero_keys),
            " ".join(card.tags),
        ]
        lines.append("\t".join(sanitize_tsv_cell(field) for field in fields))
    return "\n".join(lines) + "\n"


def _definition_as_plain_text(definition_html: str) -> str:
    value = re.sub(r"<br\s*/?>", " / ", definition_html, flags=re.IGNORECASE)
    value = re.sub(r"<hr\s*/?>", " | ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    return normalize_text(html.unescape(value))


def serialize_review_tsv(cards: list[Card]) -> str:
    lines = [
        "Word\tReasons\tOriginalDefinition\tParsedSymbol\tParsedChn\tExample\tSource\tZoteroKeys"
    ]
    for card in cards:
        if not card.review_reasons:
            continue
        fields = [
            card.word,
            ";".join(card.review_reasons),
            _definition_as_plain_text(card.original_definition_html),
            _definition_as_plain_text(card.symbol_html),
            _definition_as_plain_text(card.chn_html),
            _definition_as_plain_text(card.example_html),
            " ".join(card.sources),
            " ".join(card.zotero_keys),
        ]
        lines.append("\t".join(sanitize_tsv_cell(field) for field in fields))
    return "\n".join(lines) + "\n"


def write_exports(cards: list[Card], output_dir: Path, timestamp: str | None = None) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M")
    vocabulary_path = output_dir / f"zot2anki-vocabulary-{stamp}.tsv"
    review_path = output_dir / f"zot2anki-vocabulary-{stamp}.review.tsv"
    vocabulary_path.write_text(serialize_anki_tsv(cards), encoding="utf-8", newline="")
    review_path.write_text(serialize_review_tsv(cards), encoding="utf-8", newline="")
    return vocabulary_path, review_path


def export_note(
    database: Path,
    note_title: str,
    output_dir: Path,
    timestamp: str | None = None,
    *,
    extract_examples: bool = True,
    online_fallback: bool = True,
    cache_path: Path | None = None,
    review_annotation_keys: list[str] | None = None,
):
    connection, connection_mode = open_database_readonly(database)
    try:
        note = find_note(connection, note_title)
        records = parse_note_html(note.note_html)
        review_keys = {key.upper() for key in (review_annotation_keys or [])}
        for record in records:
            record.zotero_key = extract_annotation_key(record.href)
            if record.zotero_key.upper() in review_keys:
                record.review_reasons.append("manual_review")
        example_stats = {}
        if extract_examples:
            example_stats = enrich_records_with_examples(
                connection,
                records,
                database.expanduser().resolve().parent,
                cache_path=cache_path or output_dir / "cache" / "academic-examples.json",
                online_fallback=online_fallback,
            )
    finally:
        connection.close()
    cards, stats = build_cards(records)
    stats.update(example_stats)
    vocabulary_path, review_path = write_exports(cards, output_dir, timestamp)
    return note, cards, stats, vocabulary_path, review_path, connection_mode


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 Zotero 汇总生词笔记生成 Anki 可导入的 UTF-8 TSV。")
    parser.add_argument("--config", type=Path, help="Private JSON settings (default: config.local.json)")
    parser.add_argument("--database", type=Path, help="Zotero SQLite database")
    parser.add_argument("--note-title", help="Exact Zotero Note title")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--no-examples", action="store_true", help="不读取 PDF 或生成例句")
    parser.add_argument("--no-online", action="store_true", default=None, help="只提取本地 PDF 例句，不访问开放学术 API")
    parser.add_argument("--cache", type=Path, help="在线例句缓存路径")
    return parser


def _configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_console()
    args = _build_argument_parser().parse_args(argv)
    try:
        local_config.apply_config(args, require_collection=False)
        note, _cards, stats, vocabulary_path, review_path, mode = export_note(
            args.database,
            args.note_title,
            args.output_dir,
            extract_examples=not args.no_examples,
            online_fallback=not args.no_online,
            cache_path=args.cache,
            review_annotation_keys=args.review_annotation_keys,
        )
    except (ExportError, sqlite3.Error, OSError, RuntimeError) as exc:
        print(f"导出失败：{exc}", file=sys.stderr)
        return 2
    print(f"笔记：{note.title}（{note.key}）")
    print(f"数据库模式：{mode}")
    print(
        "统计："
        f"段落 {stats['paragraphs']}，来源记录 {stats['source_records']}，"
        f"卡片 {stats['cards']}，合并重复 {stats['duplicates_merged']}，"
        f"成功拆分 {stats['parsed_definitions']}，未拆分 {stats['unparsed_definitions']}，"
        f"待复核 {stats['needs_review']}，跳过空段落 {stats['skipped_empty']}，"
        f"跳过无效来源 {stats['skipped_invalid_source']}，来源链接 {stats['source_links']}，"
        f"例句卡片 {stats['example_cards']}，例句 {stats['example_count']}，"
        f"上下文片段 {stats['context_fragments']}，在线例句卡片 {stats['online_example_cards']}"
    )
    print(f"Anki TSV：{vocabulary_path.resolve()}")
    print(f"复核清单：{review_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
