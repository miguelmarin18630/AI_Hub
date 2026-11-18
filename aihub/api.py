"""Clientes HTTP: OpenRouter, Ollama y utilidades de red.

Solo usa la biblioteca estándar de Python (urllib).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

BASE = "https://openrouter.ai/api/v1"
OLLAMA = "http://127.0.0.1:11434"
UA = "AIHub/1.0 (Windows; +https://openrouter.ai)"


class ApiError(Exception):
    """Error de red o de la API con mensaje legible."""


def _headers(key: str | None = None) -> dict:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://localhost/ai-hub",
        "X-Title": "AI Hub",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", "replace")
    except Exception:
        body = ""
    message = body.strip()
    try:
        parsed = json.loads(body)
        err = parsed.get("error")
        if isinstance(err, dict):
            message = err.get("message") or message
        elif isinstance(err, str):
            message = err
        elif parsed.get("message"):
            message = parsed["message"]
    except Exception:
        pass
    # Muchos proveedores usan 429 para dos cosas distintas: límite de ritmo
    # (rate limit) o falta de saldo/créditos. Distinguirlas evita mensajes
    # confusos como "espera unos segundos" cuando en realidad no hay crédito.
    low = str(message or "").lower()
    no_credits = any(
        word in low
        for word in (
            "no credits remaining",
            "no credit",
            "insufficient quota",
            "insufficient_quota",
            "exceeded your current quota",
            "quota exceeded",
            "credit balance is too low",
            "billing",
            "add credits",
            "payment required",
        )
    )
    if exc.code in (402, 429) and no_credits:
        return (
            "Tu cuenta de este proveedor no tiene saldo/créditos. "
            "Añade crédito en su panel de facturación o elige otro modelo. "
            f"(HTTP {exc.code}: {str(message)[:240]})"
        )
    hints = {
        401: "Clave no válida o revocada: revísala en Ajustes.",
        402: "Sin saldo para este modelo. Añade crédito o usa uno gratis.",
        429: "Demasiadas peticiones seguidas: espera unos segundos y reintenta.",
    }
    if exc.code in hints:
        return f"{hints[exc.code]} (HTTP {exc.code}: {str(message)[:180]})"
    return f"HTTP {exc.code}: {str(message)[:500]}"


def check_openrouter(key: str, timeout: int = 20) -> dict:
    """Comprueba si la clave de OpenRouter es válida y cuánto queda disponible."""
    if not key:
        return {"ok": False, "reason": "missing", "message": "Falta la clave de OpenRouter."}
    try:
        data = request_json(f"{BASE}/key", None, key, timeout)
    except ApiError as exc:
        return {"ok": False, "reason": "invalid", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "error", "message": str(exc)}
    info = data.get("data") or {}
    free = info.get("free_model_daily_requests") or {}
    result = {
        "ok": True,
        "reason": "ok",
        "message": "",
        "label": str(info.get("label") or ""),
        "limit": info.get("limit"),
        "remaining": info.get("limit_remaining"),
        "free_used": free.get("used"),
        "free_limit": free.get("limit"),
        "free_remaining": free.get("remaining"),
    }
    try:
        credits = request_json(f"{BASE}/credits", None, key, timeout)
        payload = credits.get("data") or {}
        total = payload.get("total_credits")
        used = payload.get("total_usage")
        if total is not None and used is not None:
            result["credits"] = round(float(total) - float(used), 4)
            result["total_usage"] = round(float(used), 4)
    except Exception:  # noqa: BLE001 - el saldo es informativo
        pass
    return result


def request_json(
    url: str,
    payload: dict | None = None,
    key: str | None = None,
    timeout: int = 60,
    method: str | None = None,
) -> dict:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(key), method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise ApiError(_error_message(exc)) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError(f"Sin conexión: {reason}") from None
    except TimeoutError:
        raise ApiError("La petición ha tardado demasiado (timeout).") from None


# ---------------------------------------------------------------------------
# Catálogos
# ---------------------------------------------------------------------------

def openrouter_models_text() -> list[dict]:
    data = request_json(f"{BASE}/models", timeout=45).get("data", [])
    return data if isinstance(data, list) else []


def openrouter_models_image() -> list[dict]:
    data = request_json(f"{BASE}/images/models", timeout=45).get("data", [])
    return data if isinstance(data, list) else []


def openrouter_models_video() -> list[dict]:
    data = request_json(f"{BASE}/videos/models", timeout=45).get("data", [])
    return data if isinstance(data, list) else []


def opencode_models_meta() -> dict[str, dict]:
    """Catálogo de OpenCode Zen con precios reales (por 1M de tokens)."""
    req = urllib.request.Request(
        "https://opencode.ai/inference/v1/models",
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
    except Exception:
        return {}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {}
    catalog: dict[str, dict] = {}
    for item in items:
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        cost = ((item.get("cost") or {}).get("text") or {})
        p_in = ((cost.get("input") or {}).get("price"))
        p_out = ((cost.get("output") or {}).get("price"))
        try:
            p_in = float(p_in) if p_in is not None else None
            p_out = float(p_out) if p_out is not None else None
        except (TypeError, ValueError):
            p_in = p_out = None
        catalog[mid] = {
            "name": item.get("name") or mid,
            "desc": item.get("description") or "",
            "context": (item.get("limit") or {}).get("context"),
            "p_in": p_in,
            "p_out": p_out,
            "free": p_out == 0 and p_in == 0,
            "reasoning": bool(((item.get("capabilities") or {}).get("reasoning") or {}).get("supported")),
            "tools": bool(((item.get("capabilities") or {}).get("tools") or {}).get("supported")),
            "modalities": item.get("modalities") or {},
        }
    return catalog


def image_endpoint_prices(model_ids: Iterable[str], workers: int = 10) -> dict[str, dict]:
    """Precio mínimo por imagen de cada modelo (consulta los endpoints)."""
    result: dict[str, dict] = {}
    ids = list(model_ids)

    def one(model_id: str) -> None:
        try:
            quoted = urllib.parse.quote(model_id, safe="/:@.")
            data = request_json(
                f"{BASE}/images/models/{quoted}/endpoints", timeout=25
            )
            best: tuple[float, str] | None = None
            for endpoint in data.get("endpoints") or []:
                for line in endpoint.get("pricing") or []:
                    if line.get("billable") not in ("output_image", "output_image_edit"):
                        continue
                    try:
                        cost = float(line.get("cost_usd") or 0)
                    except (TypeError, ValueError):
                        continue
                    if cost <= 0:
                        continue
                    unit = str(line.get("unit") or "image")
                    if best is None or cost < best[0]:
                        best = (cost, unit)
            if best:
                result[model_id] = {"price": best[0], "unit": best[1]}
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, ids))
    return result


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------

def ollama_tags(timeout: float = 2.5) -> list[dict]:
    try:
        data = request_json(f"{OLLAMA}/api/tags", timeout=timeout)
    except ApiError:
        return []
    models = data.get("models") or []
    return models if isinstance(models, list) else []


def ollama_running(timeout: float = 1.5) -> bool:
    try:
        request_json(f"{OLLAMA}/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def stream_ollama_chat(
    model: str,
    messages: list[dict],
    on_delta: Callable[[str], None],
    cancel: Callable[[], bool] = lambda: False,
    timeout: int = 900,
) -> str:
    payload = {"model": model, "messages": messages, "stream": True}
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
        method="POST",
    )
    parts: list[str] = []
    stats: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw in response:
                if cancel():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    raise ApiError(str(obj["error"]))
                delta = (obj.get("message") or {}).get("content") or ""
                if delta:
                    parts.append(delta)
                    on_delta(delta)
                if obj.get("done"):
                    stats = {
                        "prompt_tokens": obj.get("prompt_eval_count") or 0,
                        "completion_tokens": obj.get("eval_count") or 0,
                        "eval_duration": (obj.get("eval_duration") or 0) / 1e9,
                    }
                    break
    except urllib.error.HTTPError as exc:
        raise ApiError(_error_message(exc)) from None
    except urllib.error.URLError as exc:
        raise ApiError(
            "No se puede conectar con Ollama. Abre la app de Ollama o ejecuta "
            "'ollama serve'."
        ) from None
    return stats


def ollama_capabilities(model: str, timeout: float = 3.0) -> list[str] | None:
    """Capacidades que anuncia Ollama para un modelo (p. ej. 'tools'). None si no se sabe."""
    try:
        data = request_json(f"{OLLAMA}/api/show", {"model": model}, timeout=timeout)
    except ApiError:
        return None
    caps = data.get("capabilities")
    return [str(item) for item in caps] if isinstance(caps, list) else None


def _ollama_outgoing(messages: list[dict]) -> list[dict]:
    """Convierte el historial al formato de Ollama (los argumentos van como objeto, no como texto)."""
    out: list[dict] = []
    for message in messages:
        item = dict(message)
        item["content"] = item.get("content") or ""
        calls = item.get("tool_calls")
        if calls:
            fixed = []
            for call in calls:
                fn = dict(call.get("function") or {})
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        fn["arguments"] = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        fn["arguments"] = {}
                fixed.append({"function": fn})
            item["tool_calls"] = fixed
        out.append(item)
    return out


def chat_ollama_tools(
    model: str,
    messages: list[dict],
    tools: list[dict],
    timeout: int = 600,
) -> dict:
    """Chat con herramientas en Ollama. Devuelve la misma forma que OpenAI (choices/usage)."""
    payload = {
        "model": model,
        "messages": _ollama_outgoing(messages),
        "tools": tools,
        "stream": False,
    }
    data = request_json(f"{OLLAMA}/api/chat", payload, timeout=timeout)
    message = data.get("message") or {}
    calls: list[dict] = []
    for index, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments") or {}
        calls.append(
            {
                "id": f"call_{index}",
                "type": "function",
                "function": {
                    "name": str(fn.get("name") or ""),
                    "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                },
            }
        )
    out_message: dict = {"role": "assistant", "content": message.get("content") or ""}
    if calls:
        out_message["tool_calls"] = calls
    usage = {
        "prompt_tokens": data.get("prompt_eval_count") or 0,
        "completion_tokens": data.get("eval_count") or 0,
        "eval_duration": (data.get("eval_duration") or 0) / 1e9,
    }
    return {"choices": [{"message": out_message}], "usage": usage}


# ---------------------------------------------------------------------------
# OpenRouter: chat, imagen y vídeo
# ---------------------------------------------------------------------------

def _extract_text(delta: dict) -> str:
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                out.append(str(part.get("text") or ""))
        return "".join(out)
    return ""


def chat_tools(
    key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
    timeout: int = 300,
    base: str = BASE,
) -> dict:
    """Una petición de chat sin streaming, con herramientas (function calling)."""
    if not key:
        raise ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
    }
    return request_json(f"{base.rstrip('/')}/chat/completions", payload, key, timeout)


def stream_openrouter_chat(
    key: str,
    model: str,
    messages: list[dict],
    on_delta: Callable[[str], None],
    cancel: Callable[[], bool] = lambda: False,
    timeout: int = 900,
    base: str = BASE,
) -> dict:
    if not key:
        raise ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
    payload = {"model": model, "messages": messages, "stream": True}
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(key),
        method="POST",
    )
    usage: dict = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            for raw in response:
                if cancel():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if obj.get("error"):
                    err = obj["error"]
                    raise ApiError(str(err.get("message") if isinstance(err, dict) else err))
                if obj.get("usage"):
                    usage = obj["usage"]
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = _extract_text(delta)
                if text:
                    on_delta(text)
    except urllib.error.HTTPError as exc:
        raise ApiError(_error_message(exc)) from None
    except urllib.error.URLError as exc:
        raise ApiError(f"Sin conexión con OpenRouter: {exc.reason}") from None
    return usage


_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "image/gif": "gif",
}


def _slug(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return clean[-60:] or "modelo"


def generate_image(
    key: str,
    model: str,
    prompt: str,
    out_dir: Path,
    aspect_ratio: str | None = None,
    timeout: int = 600,
) -> tuple[Path, float | None, str]:
    if not key:
        raise ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
    payload: dict = {"model": model, "prompt": prompt, "n": 1}
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    data = request_json(f"{BASE}/images", payload, key, timeout)
    items = data.get("data") or []
    if not items:
        raise ApiError("La API no devolvió ninguna imagen.")
    item = items[0]
    encoded = item.get("b64_json")
    if not encoded:
        raise ApiError("Respuesta de imagen sin datos (b64_json).")
    media = str(item.get("media_type") or "image/png")
    ext = _EXT.get(media, "png")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{_slug(model)}.{ext}"
    path.write_bytes(base64.b64decode(encoded))
    cost = (data.get("usage") or {}).get("cost")
    try:
        cost = float(cost) if cost is not None else None
    except (TypeError, ValueError):
        cost = None
    return path, cost, media


def generate_image_openai(
    base: str,
    key: str,
    model: str,
    prompt: str,
    out_dir: Path,
    timeout: int = 600,
) -> tuple[Path, None, str]:
    """Imagen con el formato de OpenAI (/images/generations), usado por proveedores compatibles."""
    if not key:
        raise ApiError("Falta la clave del proveedor. Configúrala al añadirlo.")
    data = request_json(
        f"{base.rstrip('/')}/images/generations",
        {"model": model, "prompt": prompt, "n": 1},
        key,
        timeout,
    )
    items = data.get("data") or []
    if not items:
        raise ApiError("La API no devolvió ninguna imagen.")
    item = items[0]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{_slug(model)}.png"
    if item.get("b64_json"):
        path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        download_url(str(item["url"]), path, None, timeout)
    else:
        raise ApiError("Respuesta de imagen sin datos.")
    return path, None, "image/png"


def generate_video(
    key: str,
    model: str,
    prompt: str,
    out_dir: Path,
    duration: int | float | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    on_status: Callable[[str], None] = lambda _s: None,
    cancel: Callable[[], bool] = lambda: False,
    timeout: int = 1800,
) -> Path:
    if not key:
        raise ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
    payload: dict = {"model": model, "prompt": prompt}
    if duration:
        payload["duration"] = duration
    if resolution:
        payload["resolution"] = resolution
    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    job = request_json(f"{BASE}/videos", payload, key, 120)
    job_id = job.get("id")
    if not job_id:
        raise ApiError(f"La API no devolvió un id de trabajo: {job}")
    poll_url = job.get("polling_url")
    if poll_url and str(poll_url).startswith("/"):
        poll_url = "https://openrouter.ai" + str(poll_url)
    status = job
    on_status(str(status.get("status") or "pending"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = str(status.get("status") or "")
        if state == "completed":
            break
        if state in ("failed", "cancelled", "expired"):
            raise ApiError(f"El vídeo terminó en estado '{state}': {status.get('error') or ''}")
        if cancel():
            raise ApiError("Generación de vídeo cancelada.")
        if not poll_url:
            raise ApiError("La API no devolvió polling_url.")
        time.sleep(4)
        status = request_json(str(poll_url), None, key, 90, method="GET")
        on_status(str(status.get("status") or ""))
    else:
        raise ApiError("Tiempo de espera agotado generando el vídeo.")

    if str(status.get("status")) != "completed":
        raise ApiError("El vídeo no se completó.")

    url = f"{BASE}/videos/{urllib.parse.quote(str(job_id), safe='')}/content?index=0"
    req = urllib.request.Request(url, headers=_headers(key))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{stamp}-{_slug(model)}.mp4"
    try:
        with urllib.request.urlopen(req, timeout=900) as response, path.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 256)
    except urllib.error.HTTPError as exc:
        raise ApiError(_error_message(exc)) from None
    except urllib.error.URLError as exc:
        raise ApiError(f"No se pudo descargar el vídeo: {exc.reason}") from None
    return path


def video_prices(skus: dict | None) -> tuple[float | None, str]:
    """Estimación de coste por segundo a partir de pricing_skus."""
    if not isinstance(skus, dict):
        return None, ""
    candidates: list[tuple[int, float]] = []
    for name, raw in skus.items():
        key = str(name).lower()
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        if "second" not in key and "duration" not in key:
            continue
        if "cents" in key:
            value /= 100.0
        preference = 9
        for rank, tag in enumerate(("480p", "720p", "1080p", "768p", "360p", "2k", "4k")):
            if tag in key:
                preference = rank
                break
        if "long_" in key or "reference" in key:
            preference += 10
        candidates.append((preference, value))
    if not candidates:
        return None, ""
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1], "s"


def download_url(url: str, dest: Path, key: str | None = None, timeout: int = 600) -> Path:
    req = urllib.request.Request(url, headers=_headers(key))
    with urllib.request.urlopen(req, timeout=timeout) as response, dest.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 256)
    return dest
