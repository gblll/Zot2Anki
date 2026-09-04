"""Resolve private machine settings without embedding them in source control."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config.local.json"
DEFAULT_DATABASE = Path.home() / "Zotero" / "zotero.sqlite"
DEFAULT_ANKI_ROOT = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Anki2"
DEFAULT_ANKI_INSTALL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "Anki"
DEFAULT_ANKI_PACKAGES = DEFAULT_ANKI_INSTALL / "app_packages"
PATH_KEYS = {"database", "anki_root", "collection", "anki_packages", "anki_exe", "output_dir"}
TEXT_KEYS = PATH_KEYS | {"note_title", "anki_profile"}
ALLOWED_KEYS = TEXT_KEYS | {"no_online", "review_annotation_keys"}


class ConfigError(RuntimeError):
    pass


def _path(value: str | Path, base: Path) -> Path:
    path = Path(os.path.expandvars(str(value))).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def resolve_config(
    config_path: Path | None = None,
    overrides: dict | None = None,
    *,
    require_collection: bool = True,
) -> dict:
    """CLI values override local JSON; no Anki profile is selected implicitly."""
    path = (config_path or DEFAULT_CONFIG).expanduser().resolve()
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise ConfigError(f"Cannot read configuration: {path}: {exc}") from exc
    elif config_path is not None:
        raise ConfigError("Configuration not found. Copy config.example.json to config.local.json and edit it locally.")
    if not isinstance(settings, dict):
        raise ConfigError("Configuration must be a JSON object.")
    unknown = settings.keys() - ALLOWED_KEYS
    if unknown:
        raise ConfigError(f"Unknown configuration keys: {', '.join(sorted(unknown))}")
    for key in TEXT_KEYS & settings.keys():
        if not isinstance(settings[key], str):
            raise ConfigError(f"{key} must be a string.")
    if "no_online" in settings and not isinstance(settings["no_online"], bool):
        raise ConfigError("no_online must be true or false.")
    review_keys = settings.get("review_annotation_keys", [])
    if not isinstance(review_keys, list) or any(
        not isinstance(key, str) or not key.isascii() or not key.isalnum() for key in review_keys
    ):
        raise ConfigError("review_annotation_keys must be a list of annotation identifiers.")

    # Resolve JSON paths relative to the configuration file, never the shell cwd.
    values = {key: value for key, value in settings.items() if value != ""}
    for key in PATH_KEYS & values.keys():
        values[key] = _path(values[key], path.parent)
    explicit = {key: value for key, value in (overrides or {}).items() if value is not None and key in ALLOWED_KEYS}
    for key in PATH_KEYS & explicit.keys():
        explicit[key] = _path(explicit[key], Path.cwd())
    # A command-line profile/root intentionally overrides a stored collection.
    if ("anki_profile" in explicit or "anki_root" in explicit) and "collection" not in explicit:
        values.pop("collection", None)
    values.update(explicit)
    values.setdefault("database", DEFAULT_DATABASE)
    values.setdefault("anki_root", DEFAULT_ANKI_ROOT)
    values.setdefault("anki_packages", DEFAULT_ANKI_PACKAGES)
    values.setdefault("anki_exe", DEFAULT_ANKI_INSTALL / "Anki.exe")
    values.setdefault("output_dir", ROOT / "dist")
    values.setdefault("no_online", True)
    values["review_annotation_keys"] = [key.upper() for key in review_keys]
    if not values.get("note_title", "").strip():
        raise ConfigError("Set note_title in config.local.json or pass --note-title (exact Zotero Note title).")
    if not values.get("collection") and values.get("anki_profile"):
        profile = values["anki_profile"]
        if profile in {".", ".."} or any(char in profile for char in '/\\:'):
            raise ConfigError("anki_profile must be a profile name, not a path; use collection for a custom path.")
        values["collection"] = values["anki_root"] / profile / "collection.anki2"
    if require_collection and not values.get("collection"):
        raise ConfigError("Set anki_profile or collection in config.local.json, or pass --collection. No profile is chosen automatically.")
    for key in PATH_KEYS & values.keys():
        values[key] = Path(values[key]).resolve()
    return values


def apply_config(args: argparse.Namespace, *, require_collection: bool = True) -> None:
    values = resolve_config(args.config, vars(args), require_collection=require_collection)
    for key, value in values.items():
        setattr(args, key, value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve local settings for the Windows launcher; does not run a sync.")
    parser.add_argument("--config", type=Path)
    for key in sorted(TEXT_KEYS):
        parser.add_argument("--" + key.replace("_", "-"))
    parser.add_argument("--no-online", action="store_true", default=None)
    args = parser.parse_args()
    try:
        values = resolve_config(args.config, vars(args))
    except ConfigError as exc:
        parser.exit(2, f"Configuration error: {exc}\n")
    print(json.dumps(values, default=str, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
