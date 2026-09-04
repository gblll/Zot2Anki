"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../core.js");

test("normalizes vocabulary text and creates a case-insensitive dedupe key", () => {
  assert.equal(core.normalizeFront("  Ａpple\n  pie  "), "Apple pie");
  assert.equal(core.makeDedupeKey(" Apple "), "apple");
  assert.equal(core.makeDedupeKey("APPLE"), "apple");
});

test("matches only non-empty highlights with exact color and a containing annotation tag", () => {
  const filter = { color: "#ff6666", tagKeyword: "生词" };
  const base = {
    annotationType: "highlight",
    annotationColor: "#FF6666",
    annotationText: "lexicon",
    tags: ["生词/单词", "论文A"]
  };

  assert.equal(core.matchesAnnotation(base, filter), true);
  assert.equal(core.matchesAnnotation({ ...base, annotationColor: "#ffd400" }, filter), false);
  assert.equal(core.matchesAnnotation({ ...base, annotationType: "underline" }, filter), false);
  assert.equal(core.matchesAnnotation({ ...base, tags: ["单词"] }, filter), false);
  assert.equal(core.matchesAnnotation({ ...base, annotationText: " \n " }, filter), false);
  assert.equal(core.matchesAnnotation({ ...base, tags: [{ tag: "生词/短语" }] }, filter), true);
});

test("merges duplicate words using the earliest display form and retains comments, sources, and tags", () => {
  const records = [
    {
      text: "APPLE",
      comment: "果实",
      tags: ["生词/短语"],
      dateAdded: "2026-02-03 10:00:00",
      annotationKey: "CCCCCCCC",
      source: { title: "Paper C", pageLabel: "7", url: "zotero://c" }
    },
    {
      text: " apple ",
      comment: "",
      tags: ["生词/单词", "needs review"],
      dateAdded: "2026-01-01 10:00:00",
      annotationKey: "AAAAAAAA",
      source: { title: "Paper A", pageLabel: "ii", url: "zotero://a" }
    },
    {
      text: "Apple",
      comment: "苹果\n常用词",
      tags: ["生词/单词"],
      dateAdded: "2026-01-02 10:00:00",
      annotationKey: "BBBBBBBB",
      source: { title: "Paper B", pageLabel: "3", url: "zotero://b" }
    }
  ];

  const groups = core.mergeRecords(records);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].front, "apple");
  assert.deepEqual(groups[0].comments, ["苹果\n常用词", "果实"]);
  assert.deepEqual(groups[0].sources.map((source) => source.url), ["zotero://a", "zotero://b", "zotero://c"]);
  assert.deepEqual(new Set(groups[0].tags), new Set(["生词/短语", "生词/单词", "needs_review"]));
});

test("sorts merged cards deterministically", () => {
  const cards = core.buildCards([
    { text: "banana", dateAdded: "2026", annotationKey: "B", source: { title: "B" } },
    { text: "Apple", dateAdded: "2026", annotationKey: "A", source: { title: "A" } }
  ]);
  assert.deepEqual(cards.map((card) => card.front), ["Apple", "banana"]);
});

test("escapes HTML and replaces tabs and newlines safely", () => {
  assert.equal(
    core.plainTextToHTML("A\t&B\n<C>\"'"),
    "A    &amp;B<br>&lt;C&gt;&quot;&#39;"
  );
  assert.equal(core.sanitizeTSVCell("a\tb\r\nc"), "a    b c");
  assert.equal(core.normalizeAnkiTag("  needs\t review\n"), "needs_review");
});

test("renders localized definition and source sections and keeps an empty definition valid", () => {
  const options = {
    labels: {
      definition: "释义",
      sources: "来源",
      pageTemplate: "第 {page} 页",
      untitledSource: "未命名来源"
    }
  };
  const withComment = core.buildCards([{
    text: "word",
    comment: "含义 & 用法",
    tags: [],
    dateAdded: "2026",
    annotationKey: "A",
    source: {
      title: "Title <One>",
      pageLabel: "iv",
      url: "zotero://open?x=1&annotation=A"
    }
  }], options)[0];

  assert.match(withComment.back, /<strong>释义<\/strong>/);
  assert.match(withComment.back, /含义 &amp; 用法/);
  assert.match(withComment.back, /Title &lt;One&gt; — 第 iv 页/);
  assert.match(withComment.back, /x=1&amp;annotation=A/);

  const withoutComment = core.buildCards([{
    text: "word",
    comment: "",
    dateAdded: "2026",
    annotationKey: "A",
    source: { title: "Source", url: "zotero://source" }
  }], options)[0];
  assert.doesNotMatch(withoutComment.back, /释义/);
  assert.match(withoutComment.back, /来源/);
});

test("serializes Anki headers and exactly three tab-separated columns", () => {
  const tsv = core.serializeTSV([{
    front: "alpha\tbeta",
    back: "line one\nline two",
    tags: ["Zotero2Anki", "生词/单词"]
  }]);
  const lines = tsv.trimEnd().split("\n");

  assert.deepEqual(lines.slice(0, 4), [
    "#separator:Tab",
    "#html:true",
    "#columns:Front\tBack\tTags",
    "#tags column:3"
  ]);
  assert.equal(lines[4].split("\t").length, 3);
  assert.equal(lines[4], "alpha    beta\tline one line two\tZotero2Anki 生词/单词");
  assert.equal(tsv.endsWith("\n"), true);
});
