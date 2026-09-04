"use strict";

var Zotero2Anki = (() => {
  const MENU_ID = "zotero2anki-tools-menu";
  const PREF_COLOR = "extensions.zotero2anki.filterColor";
  const PREF_KEYWORD = "extensions.zotero2anki.tagKeyword";
  const DEFAULT_COLOR = "#ff6666";
  const DEFAULT_KEYWORD = "生词";

  let exportInProgress = false;

  function isChinese() {
    return /^zh(?:-|$)/i.test(Zotero.locale || "");
  }

  function strings() {
    if (isChinese()) {
      return {
        title: "Zotero2Anki",
        selectOneLibrary: "请在 Zotero 左侧栏中选择一个资料库后再导出。不能同时导出多个资料库。",
        alreadyRunning: "另一个单词表导出任务正在运行。",
        scanning: "正在整理 Anki 单词表",
        scanningDescription: "正在扫描当前资料库中的批注……",
        noMatches: (color, keyword) => `没有找到颜色为 ${color}、且批注标签包含“${keyword}”的高亮。`,
        saveDialogTitle: "保存 Anki 单词表",
        tsvFiles: "TSV 文本文件",
        definition: "释义",
        sources: "来源",
        pageTemplate: "第 {page} 页",
        untitledSource: "未命名来源",
        success: (stats, path) => [
          "导出完成。",
          "",
          `扫描批注：${stats.scanned}`,
          `匹配高亮：${stats.matched}`,
          `合并后单词：${stats.unique}`,
          `合并重复项：${stats.merged}`,
          `空评论：${stats.emptyComments}`,
          `跳过错误：${stats.skippedErrors}`,
          "",
          `文件：${path}`
        ].join("\n"),
        failed: (error) => `导出失败：\n${error}`
      };
    }

    return {
      title: "Zotero2Anki",
      selectOneLibrary: "Select one library in the Zotero sidebar before exporting. Multiple libraries cannot be exported together.",
      alreadyRunning: "Another vocabulary export is already running.",
      scanning: "Preparing Anki vocabulary",
      scanningDescription: "Scanning annotations in the current library…",
      noMatches: (color, keyword) => `No highlights matched color ${color} and an annotation tag containing “${keyword}”.`,
      saveDialogTitle: "Save Anki Vocabulary",
      tsvFiles: "TSV text files",
      definition: "Definition",
      sources: "Sources",
      pageTemplate: "p. {page}",
      untitledSource: "Untitled source",
      success: (stats, path) => [
        "Export complete.",
        "",
        `Annotations scanned: ${stats.scanned}`,
        `Highlights matched: ${stats.matched}`,
        `Unique entries: ${stats.unique}`,
        `Duplicates merged: ${stats.merged}`,
        `Empty comments: ${stats.emptyComments}`,
        `Skipped errors: ${stats.skippedErrors}`,
        "",
        `File: ${path}`
      ].join("\n"),
      failed: (error) => `Export failed:\n${error}`
    };
  }

  function showAlert(window, message) {
    Services.prompt.alert(window || null, strings().title, message);
  }

  function pad(number) {
    return String(number).padStart(2, "0");
  }

  function defaultFilename(date = new Date()) {
    return [
      "zotero2anki-vocabulary-",
      date.getFullYear(),
      pad(date.getMonth() + 1),
      pad(date.getDate()),
      "-",
      pad(date.getHours()),
      pad(date.getMinutes()),
      ".tsv"
    ].join("");
  }

  function getPreference(name, fallback) {
    const value = Zotero.Prefs.get(name);
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  }

  async function findAnnotations(libraryID) {
    try {
      const search = new Zotero.Search();
      search.libraryID = libraryID;
      search.addCondition("itemType", "is", "annotation");
      const ids = await search.search();
      return ids.length ? await Zotero.Items.getAsync(ids) : [];
    }
    catch (error) {
      Zotero.debug(`Zotero2Anki: Annotation search failed; falling back to item scan: ${error}`);
      const items = await Zotero.Items.getAll(libraryID, false, false);
      return items.filter((item) => item.isAnnotation());
    }
  }

  function getLibraryPrefix(libraryID) {
    if (Zotero.API && typeof Zotero.API.getLibraryPrefix === "function") {
      return Zotero.API.getLibraryPrefix(libraryID);
    }

    const library = Zotero.Libraries.get(libraryID);
    if (library && library.libraryType === "group" && library.groupID) {
      return `groups/${library.groupID}`;
    }
    return "library";
  }

  async function getSource(annotation, localizedStrings) {
    const attachment = await Zotero.Items.getAsync(annotation.parentID);
    if (!attachment || attachment.deleted) {
      throw new Error(`Missing attachment for annotation ${annotation.key}`);
    }
    await attachment.loadAllData();

    let sourceItem = attachment;
    if (attachment.parentID) {
      const parent = await Zotero.Items.getAsync(attachment.parentID);
      if (parent && !parent.deleted) {
        await parent.loadAllData();
        sourceItem = parent;
      }
    }

    let title = "";
    try {
      title = sourceItem.getField("title") || attachment.getField("title");
    }
    catch (_error) {}
    if (!title) {
      try {
        title = attachment.attachmentFilename;
      }
      catch (_error) {}
    }
    title ||= localizedStrings.untitledSource;

    const prefix = getLibraryPrefix(attachment.libraryID);
    const url = attachment.isPDFAttachment()
      ? `zotero://open-pdf/${prefix}/items/${attachment.key}?annotation=${annotation.key}`
      : `zotero://select/${prefix}/items/${attachment.key}`;

    return {
      title,
      pageLabel: annotation.annotationPageLabel || "",
      url
    };
  }

  async function collectRecords(libraryID, filter, localizedStrings) {
    const annotations = await findAnnotations(libraryID);
    const records = [];
    const stats = {
      scanned: annotations.length,
      matched: 0,
      unique: 0,
      merged: 0,
      emptyComments: 0,
      skippedErrors: 0
    };

    for (const annotation of annotations) {
      try {
        if (!annotation || annotation.deleted || !annotation.isAnnotation()) continue;
        await annotation.loadAllData();

        const tags = annotation.getTags().map((tag) => tag.tag);
        const candidate = {
          annotationType: annotation.annotationType,
          annotationColor: annotation.annotationColor,
          annotationText: annotation.annotationText,
          tags
        };
        if (!Zotero2AnkiCore.matchesAnnotation(candidate, filter)) continue;

        const source = await getSource(annotation, localizedStrings);
        records.push({
          text: annotation.annotationText,
          comment: annotation.annotationComment || "",
          tags,
          dateAdded: annotation.dateAdded || "",
          annotationKey: annotation.key || "",
          source
        });
        stats.matched += 1;
        if (!Zotero2AnkiCore.normalizeComment(annotation.annotationComment)) {
          stats.emptyComments += 1;
        }
      }
      catch (error) {
        stats.skippedErrors += 1;
        Zotero.logError(error);
      }
    }

    return { records, stats };
  }

  async function chooseOutputPath(window, localizedStrings) {
    const { FilePicker } = ChromeUtils.importESModule(
      "chrome://zotero/content/modules/filePicker.mjs"
    );
    const picker = new FilePicker();
    picker.init(window, localizedStrings.saveDialogTitle, picker.modeSave);
    picker.defaultString = defaultFilename();
    picker.defaultExtension = "tsv";
    picker.appendFilter(localizedStrings.tsvFiles, "*.tsv");
    picker.appendFilters(picker.filterAll);

    const result = await picker.show();
    if (result !== picker.returnOK && result !== picker.returnReplace) {
      return null;
    }
    return picker.file;
  }

  async function exportCurrentLibrary(window) {
    const localizedStrings = strings();
    if (exportInProgress) {
      showAlert(window, localizedStrings.alreadyRunning);
      return;
    }

    exportInProgress = true;
    let progressWindow;
    try {
      const pane = window?.ZoteroPane || Zotero.getActiveZoteroPane();
      const libraryIDs = pane?.getSelectedLibraryIDs?.() || [];
      if (libraryIDs.length !== 1) {
        showAlert(window, localizedStrings.selectOneLibrary);
        return;
      }

      const filter = {
        color: Zotero2AnkiCore.normalizeColor(getPreference(PREF_COLOR, DEFAULT_COLOR)) || DEFAULT_COLOR,
        tagKeyword: getPreference(PREF_KEYWORD, DEFAULT_KEYWORD)
      };

      progressWindow = new Zotero.ProgressWindow({ window });
      progressWindow.changeHeadline(localizedStrings.scanning);
      progressWindow.addDescription(localizedStrings.scanningDescription);
      progressWindow.show();

      const { records, stats } = await collectRecords(libraryIDs[0], filter, localizedStrings);
      const cards = Zotero2AnkiCore.buildCards(records, {
        fixedTag: Zotero2AnkiCore.DEFAULT_FIXED_TAG,
        labels: {
          definition: localizedStrings.definition,
          sources: localizedStrings.sources,
          pageTemplate: localizedStrings.pageTemplate,
          untitledSource: localizedStrings.untitledSource
        }
      });
      stats.unique = cards.length;
      stats.merged = Math.max(0, stats.matched - stats.unique);

      progressWindow.close();
      progressWindow = null;

      if (!cards.length) {
        showAlert(window, localizedStrings.noMatches(filter.color, filter.tagKeyword));
        return;
      }

      const outputPath = await chooseOutputPath(window, localizedStrings);
      if (!outputPath) return;

      const tsv = Zotero2AnkiCore.serializeTSV(cards);
      await IOUtils.writeUTF8(outputPath, tsv);
      showAlert(window, localizedStrings.success(stats, outputPath));
    }
    catch (error) {
      Zotero.logError(error);
      showAlert(window, localizedStrings.failed(error?.message || String(error)));
    }
    finally {
      progressWindow?.close();
      exportInProgress = false;
    }
  }

  return {
    id: null,
    version: null,
    rootURI: null,
    menuID: null,
    preferencePaneID: null,

    init({ id, version, rootURI }) {
      this.id = id;
      this.version = version;
      this.rootURI = rootURI;
    },

    addToWindow(window) {
      window?.MozXULElement?.insertFTLIfNeeded("zotero2anki.ftl");
    },

    addToAllWindows() {
      for (const window of Zotero.getMainWindows()) {
        if (window.ZoteroPane) this.addToWindow(window);
      }
    },

    removeFromWindow(window) {
      window?.document
        ?.querySelector('link[href="zotero2anki.ftl"]')
        ?.remove();
    },

    removeFromAllWindows() {
      for (const window of Zotero.getMainWindows()) {
        if (window.ZoteroPane) this.removeFromWindow(window);
      }
    },

    registerMenu() {
      const registered = Zotero.MenuManager.registerMenu({
        menuID: MENU_ID,
        pluginID: this.id,
        target: "main/menubar/tools",
        menus: [{
          menuType: "menuitem",
          l10nID: "zotero2anki-menu-export",
          enableForTabTypes: ["library", "reader/*"],
          onCommand: (event) => {
            const window = event?.target?.ownerGlobal || Zotero.getMainWindow();
            void exportCurrentLibrary(window);
          }
        }]
      });
      this.menuID = registered || MENU_ID;
    },

    shutdown() {
      if (this.menuID) {
        Zotero.MenuManager.unregisterMenu(this.menuID);
        this.menuID = null;
      }
      if (this.preferencePaneID) {
        Zotero.PreferencePanes.unregister(this.preferencePaneID);
        this.preferencePaneID = null;
      }
      this.removeFromAllWindows();
    },

    exportCurrentLibrary
  };
})();
