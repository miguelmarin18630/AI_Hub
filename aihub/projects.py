"""Proyectos: carpetas de trabajo dentro de la carpeta de proyectos.

La app pregunta al arrancar en qué proyecto trabajar. Cada proyecto es una
subcarpeta de ``projects_root`` (por defecto C:\\Proyectos); también se puede
elegir la propia carpeta raíz o cualquier otra con el botón «Otro…».
"""

from __future__ import annotations

import time
from pathlib import Path

from . import config

# Marcadores para adivinar de qué tipo es cada proyecto.
MARKERS = (
    (".git", "git"),
    ("package.json", "web"),
    ("index.html", "web"),
    ("build.gradle", "Android"),
    ("build.gradle.kts", "Android"),
    ("AndroidManifest.xml", "Android"),
    ("pubspec.yaml", "Flutter"),
    ("pyproject.toml", "Python"),
    ("requirements.txt", "Python"),
)


def root(cfg: dict | None = None) -> Path:
    cfg = cfg if cfg is not None else config.load_config()
    raw = str(cfg.get("projects_root") or "").strip()
    return Path(raw) if raw else Path(config._default_projects_root())


def _relative_day(stamp: float) -> str:
    try:
        moment = time.localtime(stamp)
    except (OSError, OverflowError, ValueError):
        return ""
    today = time.localtime()
    if (moment.tm_year, moment.tm_yday) == (today.tm_year, today.tm_yday):
        return "hoy"
    yesterday = time.localtime(time.time() - 86400)
    if (moment.tm_year, moment.tm_yday) == (yesterday.tm_year, yesterday.tm_yday):
        return "ayer"
    return f"{moment.tm_mday:02d}/{moment.tm_mon:02d}/{moment.tm_year}"


def describe(path: Path, is_root: bool = False) -> dict:
    """Datos ligeros de una carpeta: tipo, nº de elementos y fecha."""
    try:
        entries = list(path.iterdir())
    except OSError:
        entries = []

    kinds: list[str] = []
    for marker, label in MARKERS:
        if label in kinds:
            continue
        try:
            if (path / marker).exists():
                kinds.append(label)
        except OSError:
            pass

    try:
        stamp = path.stat().st_mtime
    except OSError:
        stamp = 0.0

    visible = [item for item in entries if not item.name.startswith(".")]
    return {
        "name": path.name or str(path),
        "path": path,
        "root": is_root,
        "kinds": kinds,
        "count": len(visible),
        "mtime": stamp,
    }


def detail_text(project: dict) -> str:
    bits = list(project["kinds"])
    count = project["count"]
    bits.append(f"{count} elemento" if count == 1 else f"{count} elementos")
    moment = _relative_day(project["mtime"])
    if moment:
        bits.append(moment)
    if project.get("root"):
        bits.append("raíz")
    return " · ".join(bits)


def list_projects(cfg: dict | None = None) -> list[dict]:
    cfg = cfg if cfg is not None else config.load_config()
    base = root(cfg)
    projects: list[dict] = []
    if base.is_dir():
        projects.append(describe(base, is_root=True))
        try:
            children = sorted(base.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            children = []
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            projects.append(describe(child))
    return projects


def with_current(projects: list[dict], current: Path) -> list[dict]:
    """Añade el proyecto actual si está fuera de la carpeta de proyectos."""
    if any(item["path"] == current for item in projects):
        return projects
    extra = describe(current)
    extra["outside"] = True
    return [extra] + projects if current.is_dir() else projects


def create(base: Path, name: str) -> Path:
    """Crea (si falta) la carpeta del proyecto y la devuelve."""
    clean = " ".join(str(name).split()).strip().strip("\\/")
    if not clean:
        raise ValueError("Escribe un nombre para el proyecto.")
    bad = set('<>:"|?*')
    if any(char in bad for char in clean):
        raise ValueError('El nombre no puede llevar < > : " | ? *')
    target = base / clean
    target.mkdir(parents=True, exist_ok=True)
    return target
