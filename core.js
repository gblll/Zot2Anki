"use strict";

var Zot2AnkiCore = (() => {
  // Keep the existing sync tag so older exports remain compatible.
  const DEFAULT_FIXED_TAG = "Zotero2Anki";
  const TSV_HEADER = [
    "#separator:Tab",
    "#html:true",
    "#columns:Front\tBack\tTags",
    "#tags column:3"
  ].join("\n");

  function asString(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function normalizeUnicode(value) {
    return asString(value).normalize("NFKC");
  }

  function decodeFront(value) {
    const entities = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " " };
    const decoded = asString(value).replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/giu, (whole, key) => {
      if (key[0] !== "#") return entities[key.toLowerCase()];
      const number = key[1].toLowerCase() === "x" ? parseInt(key.slice(2), 16) : parseInt(key.slice(1), 10);
      return number > 0 && number <= 0x10ffff ? String.fromCodePoint(number) : whole;
    });
    return decoded;
  }

  function normalizeFront(value) {
    return normalizeUnicode(decodeFront(value)).trim().replace(/\s+/gu, " ");
  }

  function makeDedupeKey(value) {
    return normalizeFront(value).toLowerCase();
  }

  function normalizeComment(value) {
    return normalizeUnicode(value)
      .replace(/\r\n?/g, "\n")
      .replace(/\t/g, "    ")
      .trim();
  }

  function normalizeColor(value) {
    const color = asString(value).trim().toLowerCase();
    return /^#[0-9a-f]{6}$/.test(color) ? color : "";
  }

  function tagName(tag) {
    if (typeof tag === "string") return tag;
    return tag && typeof tag.tag === "string" ? tag.tag : "";
  }

  function matchesAnnotation(annotation, { color, tagKeyword }) {
    if (!annotation || annotation.annotationType !== "highlight") return false;
    if (normalizeColor(annotation.annotationColor) !== normalizeColor(color)) return false;

    const keyword = asString(tagKeyword).trim();
    if (!keyword) return false;

    const tags = Array.isArray(annotation.tags) ? annotation.tags : [];
    if (!tags.some((tag) => tagName(tag).includes(keyword))) return false;

    return Boolean(normalizeFront(annotation.annotationText));
  }

  function normalizeAnkiTag(value) {
    return normalizeUnicode(value)
      .trim()
      .replace(/[\u0000-\u001f\u007f]+/g, "")
      .replace(/\s+/gu, "_");
  }

  function escapeHTML(value) {
    return asString(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function plainTextToHTML(value) {
    return escapeHTML(normalizeComment(value)).replace(/\n/g, "<br>");
  }

  function sanitizeTSVCell(value) {
    return asString(value).replace(/\t/g, "    ").replace(/[\r\n]+/g, " ");
  }

  function compareOrdinal(left, right) {
    const a = asString(left);
    const b = asString(right);
    return a < b ? -1 : a > b ? 1 : 0;
  }

  function compareRecords(left, right) {
    const leftDate = asString(left.dateAdded) || "9999";
    const rightDate = asString(right.dateAdded) || "9999";
    return compareOrdinal(leftDate, rightDate)
      || compareOrdinal(left.annotationKey, right.annotationKey);
  }

  function mergeRecords(records) {
    const groups = new Map();
    const sortedRecords = [...(records || [])].sort(compareRecords);

    for (const record of sortedRecords) {
      const front = normalizeFront(record.text);
      const key = makeDedupeKey(front);
      if (!key) continue;

      let group = groups.get(key);
      if (!group) {
        group = {
          key,
          front,
          comments: [],
          sources: [],
          tags: [],
          _commentSet: new Set(),
          _sourceSet: new Set(),
          _tagSet: new Set()
        };
        groups.set(key, group);
      }

      const comment = normalizeComment(record.comment);
      if (comment && !group._commentSet.has(comment)) {
        group._commentSet.add(comment);
        group.comments.push(comment);
      }

      const source = record.source || {};
      const sourceKey = [source.url, source.title, source.pageLabel]
        .map(asString)
        .join("\u0000");
      if (sourceKey.replace(/\u0000/g, "") && !group._sourceSet.has(sourceKey)) {
        group._sourceSet.add(sourceKey);
        group.sources.push({
          title: asString(source.title),
          pageLabel: asString(source.pageLabel),
          url: asString(source.url)
        });
      }

      for (const rawTag of record.tags || []) {
        const normalizedTag = normalizeAnkiTag(tagName(rawTag));
        if (normalizedTag && !group._tagSet.has(normalizedTag)) {
          group._tagSet.add(normalizedTag);
          group.tags.push(normalizedTag);
        }
      }
    }

    return [...groups.values()]
      .map((group) => {
        delete group._commentSet;
        delete group._sourceSet;
        delete group._tagSet;
        group.tags.sort(compareOrdinal);
        return group;
      })
      .sort((left, right) => compareOrdinal(left.key, right.key)
        || compareOrdinal(left.front, right.front));
  }

  function formatPage(pageLabel, pageTemplate) {
    if (!pageLabel) return "";
    return asString(pageTemplate || "p. {page}").replace("{page}", pageLabel);
  }

  function renderBack(group, options = {}) {
    const labels = {
      definition: "Definition",
      sources: "Sources",
      pageTemplate: "p. {page}",
      untitledSource: "Untitled source",
      ...(options.labels || {})
    };
    const sections = [];

    if (group.comments.length) {
      const comments = group.comments
        .map((comment) => `<div>${plainTextToHTML(comment)}</div>`)
        .join("");
      sections.push(`<div><strong>${escapeHTML(labels.definition)}</strong>${comments}</div>`);
    }

    if (group.sources.length) {
      const sources = group.sources.map((source) => {
        const title = source.title || labels.untitledSource;
        const page = formatPage(source.pageLabel, labels.pageTemplate);
        const display = page ? `${title} — ${page}` : title;
        const content = source.url
          ? `<a href="${escapeHTML(source.url)}">${escapeHTML(display)}</a>`
          : escapeHTML(display);
        return `<li>${content}</li>`;
      }).join("");
      sections.push(`<div><strong>${escapeHTML(labels.sources)}</strong><ul>${sources}</ul></div>`);
    }

    return sections.join("<hr>");
  }

  function buildCards(records, options = {}) {
    const fixedTag = normalizeAnkiTag(options.fixedTag || DEFAULT_FIXED_TAG);
    return mergeRecords(records).map((group) => {
      const tags = [];
      const seen = new Set();
      for (const tag of [fixedTag, ...group.tags]) {
        if (tag && !seen.has(tag)) {
          seen.add(tag);
          tags.push(tag);
        }
      }
      return {
        front: group.front,
        back: renderBack(group, options),
        tags
      };
    });
  }

  function serializeTSV(cards) {
    const rows = (cards || []).map((card) => [
      sanitizeTSVCell(escapeHTML(decodeFront(card.front))),
      sanitizeTSVCell(card.back),
      sanitizeTSVCell((card.tags || []).join(" "))
    ].join("\t"));
    return `${TSV_HEADER}${rows.length ? `\n${rows.join("\n")}` : ""}\n`;
  }

  return Object.freeze({
    DEFAULT_FIXED_TAG,
    TSV_HEADER,
    normalizeFront,
    makeDedupeKey,
    normalizeComment,
    normalizeColor,
    normalizeAnkiTag,
    matchesAnnotation,
    escapeHTML,
    plainTextToHTML,
    sanitizeTSVCell,
    mergeRecords,
    renderBack,
    buildCards,
    serializeTSV
  });
})();

if (typeof module !== "undefined" && module.exports) {
  module.exports = Zot2AnkiCore;
}
