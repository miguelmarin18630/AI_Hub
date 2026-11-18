"""Configuración persistente de AI Hub.

Se guarda en la carpeta de datos del usuario (config.json y cache.json):
Windows %APPDATA%\\AIHub · macOS ~/Library/Application Support/AIHub.
"""

from __future__ import annotations

import contextvars
import json
import os
import sys
from pathlib import Path

from . import __version__

APP_NAME = "AI Hub"
APP_VERSION = __version__


def _app_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AIHub"
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        return Path(base) / "AIHub" if base else Path.home() / "AppData" / "Roaming" / "AIHub"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "AIHub"


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.json"
CACHE_PATH = APP_DIR / "cache.json"

# Carpeta de datos activa. La app de escritorio usa APP_DIR; el servidor web
# cambia esta variable por la carpeta de cada usuario antes de atender su
# petición, de modo que claves, caché y consumo quedan aislados por cuenta.
_ACTIVE_DIR: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "aihub_app_dir", default=None
)


def set_app_dir(path: str | Path | None) -> None:
    """Activa una carpeta de datos (por usuario) o vuelve a la de escritorio."""
    _ACTIVE_DIR.set(Path(path) if path else None)


def app_dir() -> Path:
    return _ACTIVE_DIR.get() or APP_DIR


def config_path() -> Path:
    return app_dir() / "config.json"


def cache_path() -> Path:
    return app_dir() / "cache.json"


def _default_workdir() -> str:
    home = str(Path.home())
    candidates = ["C:\\Proyectos", str(Path.home() / "Proyectos"), home] if os.name == "nt" else [
        str(Path.home() / "Proyectos"),
        home,
    ]
    for candidate in candidates:
        if Path(candidate).is_dir():
            return candidate
    return home


def _default_projects_root() -> str:
    for candidate in (
        str(Path.home() / "Proyectos"),
        "C:\\Proyectos" if os.name == "nt" else "",
    ):
        if candidate and Path(candidate).is_dir():
            return candidate
    return _default_workdir()


def _default_output_root() -> str:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return str(home / "Pictures" / "AI Hub")


DEFAULTS = {
    "openrouter_api_key": "",
    "workdir": _default_workdir(),
    "projects_root": _default_projects_root(),
    "output_root": _default_output_root(),
    "auto_refresh": True,
    "last_provider": "opencode",
    "last_category": "code",
    "last_models": {},
}


def ensure_dirs() -> None:
    app_dir().mkdir(parents=True, exist_ok=True)
    try:
        Path(load_config()["output_root"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def load_config() -> dict:
    data = dict(DEFAULTS)
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            data.update(raw)
    except Exception:
        pass
    if not data.get("output_root"):
        data["output_root"] = _default_output_root()
    return data


def save_config(cfg: dict) -> None:
    base = app_dir()
    base.mkdir(parents=True, exist_ok=True)
    tmp = config_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config_path())


def update_config(**changes) -> dict:
    """Guarda solo las claves indicadas, sin pisar cambios hechos fuera de la app."""
    data = load_config()
    data.update(changes)
    save_config(data)
    return data


def openrouter_key(cfg: dict | None = None, allow_env: bool = True) -> str:
    """Clave de OpenRouter: la guardada en Ajustes o, si no hay, la del sistema.

    En la versión web se usa ``allow_env=False`` para que cada cuenta use solo su
    propia clave y no se comparta la variable de entorno del servidor.
    """
    cfg = cfg if cfg is not None else load_config()
    stored = str(cfg.get("openrouter_api_key") or "").strip()
    if stored:
        return stored
    if not allow_env:
        return ""
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def image_dir(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else load_config()
    path = Path(cfg["output_root"]) / "imagenes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def video_dir(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else load_config()
    path = Path(cfg["output_root"]) / "videos"
    path.mkdir(parents=True, exist_ok=True)
    return path
