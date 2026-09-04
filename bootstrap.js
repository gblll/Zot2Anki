var Zot2AnkiCore;
var Zot2Anki;

function log(message) {
  Zotero.debug(`Zot2Anki: ${message}`);
}

function install() {
  log("Installed");
}

async function startup({ id, version, rootURI }) {
  log(`Starting ${version}`);

  Services.scriptloader.loadSubScript(rootURI + "core.js");
  Services.scriptloader.loadSubScript(rootURI + "zot2anki.js");

  Zot2Anki.init({ id, version, rootURI });
  Zot2Anki.addToAllWindows();
  Zot2Anki.registerMenu();

  Zot2Anki.preferencePaneID = await Zotero.PreferencePanes.register({
    pluginID: id,
    id: "zot2anki-preferences",
    label: "Zot2Anki",
    src: rootURI + "preferences/preferences.xhtml"
  });
}

function onMainWindowLoad({ window }) {
  Zot2Anki?.addToWindow(window);
}

function onMainWindowUnload({ window }) {
  Zot2Anki?.removeFromWindow(window);
}

function shutdown() {
  log("Shutting down");

  if (Zot2Anki) {
    Zot2Anki.shutdown();
  }

  Zot2Anki = undefined;
  Zot2AnkiCore = undefined;
}

function uninstall() {
  log("Uninstalled");
}
