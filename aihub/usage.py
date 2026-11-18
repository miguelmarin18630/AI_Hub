"""Consumo por modelo (total acumulado y del día actual), en config.json («usage»).

Cada modelo guarda un total histórico y un subcontador «today» que se reinicia
automáticamente al cambiar la fecha local (a medianoche).
"""

from __future__ import annotations

from datetime import date

from aihub import config

_FIELDS = ("requests", "prompt", "completion", "cost", "images", "videos")


def _key(provider: str, uid: str) -> str:
    return f"{provider}:{uid}"


def _today() -> str:
    return date.today().isoformat()


def _blank() -> dict:
    return {"requests": 0, "prompt": 0, "completion": 0, "cost": 0.0, "images": 0, "videos": 0}


def _add(
    stats: dict,
    *,
    requests: int,
    prompt: int,
    completion: int,
    cost: float,
    images: int,
    videos: int,
) -> None:
    stats["requests"] = int(stats.get("requests", 0)) + requests
    stats["prompt"] = int(stats.get("prompt", 0)) + prompt
    stats["completion"] = int(stats.get("completion", 0)) + completion
    stats["cost"] = round(float(stats.get("cost", 0.0)) + cost, 6)
    stats["images"] = int(stats.get("images", 0)) + images
    stats["videos"] = int(stats.get("videos", 0)) + videos


def _rotate(stats: dict) -> dict:
    """Garantiza «today» y lo reinicia si la fecha guardada no es la de hoy."""
    stats = dict(stats or {})
    today = _today()
    if stats.get("date") != today:
        stats["date"] = today
        stats["today"] = _blank()
    else:
        merged = _blank()
        merged.update(stats.get("today") or {})
        stats["today"] = merged
    return stats


def get(provider: str, uid: str) -> dict:
    usage = config.load_config().get("usage") or {}
    return _rotate(dict(usage.get(_key(provider, uid)) or {}))


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
    prompt = int(prompt or 0)
    completion = int(completion or 0)
    images = int(images or 0)
    videos = int(videos or 0)
    cost = float(cost or 0.0)
    requests = 1 if (prompt or completion or cost or images or videos) else 0

    data = config.load_config()
    usage = dict(data.get("usage") or {})
    key = _key(provider, uid)
    stats = _rotate(dict(usage.get(key) or {}))

    # No crear entradas vacías si la llamada no aportó consumo.
    if not requests and not stats.get("requests"):
        return

    _add(stats, requests=requests, prompt=prompt, completion=completion, cost=cost, images=images, videos=videos)
    _add(
        stats["today"],
        requests=requests,
        prompt=prompt,
        completion=completion,
        cost=cost,
        images=images,
        videos=videos,
    )
    usage[key] = stats
    config.update_config(usage=usage)


def _summary(stats: dict) -> str:
    if not stats or not stats.get("requests"):
        return ""
    bits: list[str] = []
    tokens_in = int(stats.get("prompt", 0) or 0)
    tokens_out = int(stats.get("completion", 0) or 0)
    if tokens_in or tokens_out:
        bits.append(f"{tokens_in:,}↑ {tokens_out:,}↓ tokens".replace(",", " "))
    if stats.get("images"):
        bits.append(f"{stats['images']} imagen(es)")
    if stats.get("videos"):
        bits.append(f"{stats['videos']} vídeo(s)")
    if stats.get("cost"):
        bits.append(f"${float(stats['cost']):.4f}")
    body = " · ".join(bits)
    return f"{stats['requests']} uso(s)" + (f" · {body}" if body else "")


def describe(stats: dict) -> str:
    """Texto del consumo: hoy y total acumulado desde esta app."""
    total = _summary(stats)
    if not total:
        return "Sin uso desde esta app todavía."
    today = _summary((stats or {}).get("today") or {})
    if not today:
        return f"Hoy: sin uso · Total: {total}"
    return f"Hoy: {today} · Total: {total}"
