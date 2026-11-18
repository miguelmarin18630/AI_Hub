"""Consumo acumulado por modelo, guardado en config.json (clave «usage»)."""

from __future__ import annotations

from aihub import config


def _key(provider: str, uid: str) -> str:
    return f"{provider}:{uid}"


def get(provider: str, uid: str) -> dict:
    usage = config.load_config().get("usage") or {}
    return dict(usage.get(_key(provider, uid)) or {})


def record(
    provider: str,
    uid: str,
    *,
    prompt: int = 0,
    completion: int = 0,
    cost: float = 0.0,
    images: int = 0,
    videos: int = 0,
) -> None:
    data = config.load_config()
    usage = dict(data.get("usage") or {})
    key = _key(provider, uid)
    stats = dict(usage.get(key) or {})
    stats["requests"] = int(stats.get("requests", 0)) + (1 if (prompt or completion or cost or images or videos) else 0)
    stats["prompt"] = int(stats.get("prompt", 0)) + int(prompt or 0)
    stats["completion"] = int(stats.get("completion", 0)) + int(completion or 0)
    stats["cost"] = round(float(stats.get("cost", 0.0)) + float(cost or 0.0), 6)
    stats["images"] = int(stats.get("images", 0)) + int(images or 0)
    stats["videos"] = int(stats.get("videos", 0)) + int(videos or 0)
    usage[key] = stats
    config.update_config(usage=usage)


def describe(stats: dict) -> str:
    """Texto corto del consumo de un modelo desde esta app."""
    if not stats or not stats.get("requests"):
        return "Sin uso desde esta app todavía."
    bits = [f"{stats['requests']} uso(s)"]
    tokens_in = stats.get("prompt", 0)
    tokens_out = stats.get("completion", 0)
    if tokens_in or tokens_out:
        bits.append(f"{tokens_in:,}↑ {tokens_out:,}↓ tokens".replace(",", " "))
    if stats.get("images"):
        bits.append(f"{stats['images']} imagen(es)")
    if stats.get("videos"):
        bits.append(f"{stats['videos']} vídeo(s)")
    if stats.get("cost"):
        bits.append(f"${stats['cost']:.4f}")
    return "Tu consumo: " + " · ".join(bits)
