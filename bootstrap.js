var Zotero2AnkiCore;
var Zotero2Anki;

function log(message) {
  Zotero.debug(`Zotero2Anki: ${message}`);
}

function install() {
  log("Installed");
}

async function startup({ id, version, rootURI }) {
  log(`Starting ${version}`);

  Services.scriptloader.loadSubScript(rootURI + "core.js");
  Services.scriptloader.loadSubScript(rootURI + "zotero2anki.js");

  Zotero2Anki.init({ id, version, rootURI });
  Zotero2Anki.addToAllWindows();
  Zotero2Anki.registerMenu();

  Zotero2Anki.preferencePaneID = await Zotero.PreferencePanes.register({
    pluginID: id,
    id: "zotero2anki-preferences",
    label: "Zotero2Anki",
    src: rootURI + "preferences/preferences.xhtml"
  });
}

function onMainWindowLoad({ window }) {
  Zotero2Anki?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  Zotero2Anki?.removeFromWindow(window);
}

function shutdown() {
  log("Shutting down");

  if (Zotero2Anki) {
    Zotero2Anki.shutdown();
  }

  Zotero2Anki = undefined;
  Zotero2AnkiCore = undefined;
}

function uninstall() {
  log("Uninstalled");
}
