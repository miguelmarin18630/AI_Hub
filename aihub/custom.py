"""Proveedores añadidos por el usuario: APIs compatibles con OpenAI.

Cada proveedor guarda su nombre, URL base y clave en config.json. Al conectarlo se
listan sus modelos y se reparten entre Programación (chat) e Imagen. Vídeo requiere
un adaptador propio y no se ofrece todavía.
"""

from __future__ import annotations

import re

from . import api, catalog

PRESETS = [
    {"id": "openai", "name": "OpenAI", "base": "https://api.openai.com/v1", "glyph": "◎", "color": "#10a37f",
     "help": "Clave en platform.openai.com/api-keys"},
    {"id": "gemini", "name": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
     "glyph": "✦", "color": "#4285f4", "help": "Clave en aistudio.google.com/apikey"},
    {"id": "groq", "name": "Groq", "base": "https://api.groq.com/openai/v1", "glyph": "⚡", "color": "#f55036",
     "help": "Clave en console.groq.com/keys"},
    {"id": "deepseek", "name": "DeepSeek", "base": "https://api.deepseek.com/v1", "glyph": "◈", "color": "#4d6bfe",
     "help": "Clave en platform.deepseek.com/api_keys"},
    {"id": "mistral", "name": "Mistral", "base": "https://api.mistral.ai/v1", "glyph": "M", "color": "#fa520f",
     "help": "Clave en console.mistral.ai/api-keys"},
    {"id": "together", "name": "Together AI", "base": "https://api.together.xyz/v1", "glyph": "◐", "color": "#0f6fff",
     "help": "Clave en api.together.ai/settings/api-keys"},
    {"id": "custom", "name": "Personalizado", "base": "", "glyph": "◆", "color": "#9aa4b2",
     "help": "Cualquier servidor compatible con OpenAI (p. ej. LM Studio: http://localhost:1234/v1)"},
]

_NOT_CHAT = ("embed", "whisper", "tts", "moderation", "transcri", "realtime", "audio", "rerank", "guard")
_IMAGE_WORDS = ("image", "dall-e", "imagen", "flux", "gpt-image")
_VISION_WORDS = ("vision", "4o", "gpt-4.1", "gpt-5", "gemini", "-vl", "vl-", "llava", "pixtral", "claude")


def preset(preset_id: str) -> dict:
    return next((item for item in PRESETS if item["id"] == preset_id), PRESETS[-1])


def classify(model_id: str) -> str | None:
    low = model_id.lower()
    if any(word in low for word in _NOT_CHAT):
        return None
    if any(word in low for word in _IMAGE_WORDS):
        return "image"
    return "code"


def is_vision(model_id: str) -> bool:
    low = model_id.lower()
    return any(word in low for word in _VISION_WORDS)


_OPENAI_PRICES = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "o1": (15.00, 60.00),
    "o1-mini": (1.10, 4.40),
    "o1-preview": (15.00, 60.00),
    "o3": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
}


def _openai_price(model_id: str) -> tuple[float | None, float | None]:
    """Precio de referencia (USD por 1M tokens). Gana la clave más larga:
    «gpt-4o-mini» debe usar su tarifa y no la de «gpt-4o»."""
    low = model_id.lower()
    for key in sorted(_OPENAI_PRICES, key=len, reverse=True):
        if key in low:
            return _OPENAI_PRICES[key]
    return None, None


def records(cfg: dict) -> list[dict]:
    return [dict(item) for item in (cfg.get("custom_providers") or []) if isinstance(item, dict)]


def get(cfg: dict, pid: str) -> dict | None:
    return next((item for item in records(cfg) if item.get("id") == pid), None)


def unique_id(cfg: dict, preset_id: str) -> str:
    base_ids = {item["id"] for item in catalog.PROVIDERS if not item.get("custom")}
    taken = base_ids | {item["id"] for item in records(cfg)}
    candidate, number = preset_id, 2
    while candidate in taken:
        candidate = f"{preset_id}-{number}"
        number += 1
    return candidate


def provider_entry(record: dict) -> dict:
    return {
        "id": record["id"],
        "name": record["name"],
        "sub": record.get("base", ""),
        "glyph": record.get("glyph", "◆"),
        "color": record.get("color", "#9aa4b2"),
        "custom": True,
        "categories": list(record.get("categories") or ["code"]),
    }


def register(cfg: dict) -> None:
    """Refleja los proveedores añadidos en el catálogo de la app."""
    catalog.PROVIDERS[:] = [item for item in catalog.PROVIDERS if not item.get("custom")]
    catalog.PROVIDERS.extend(provider_entry(item) for item in records(cfg))
    catalog.PROVIDER_BY_ID.clear()
    catalog.PROVIDER_BY_ID.update({item["id"]: item for item in catalog.PROVIDERS})


def _is_free_model(model_id: str) -> bool:
    """Heurística para marcar modelos gratuitos de proveedores OpenAI-compatibles.

    Un modelo se considera gratis si su id contiene algún marcador típico de
    nivel gratuito. En caso de duda se marca como de pago (no se promete
    gratuidad falsa).
    """
    text = str(model_id or "").lower()
    if "free" in text or ":free" in text:
        return True
    # DeepSeek: niveles gratuitos de código/destilación.
    if "distill" in text or "coder" in text or text.endswith("-code") or "-code-" in text:
        return True
    # Mistral: variantes instruct/small de prueba.
    if "instruct" in text or "-small" in text or "v0.1" in text:
        return True
    # Google Gemini: flash tiene cuota gratuita.
    if "flash" in text:
        return True
    return False


def fetch(record: dict, timeout: int = 30) -> list[catalog.Model]:
    """Lista los modelos del proveedor y los convierte en modelos del catálogo."""
    base = str(record.get("base") or "").strip().rstrip("/")
    if not re.match(r"^https?://", base):
        raise api.ApiError("La URL debe empezar por http:// o https://")
    data = api.request_json(f"{base}/models", None, record.get("key") or "", timeout).get("data") or []
    pid = record["id"]
    name = record.get("name", pid)
    models: list[catalog.Model] = []
    for item in data:
        model_id = str(item.get("id") or "").strip()
        category = classify(model_id) if model_id else None
        if category is None:
            continue
        vision = is_vision(model_id) and category == "code"
        tags = ["herramientas"] if category == "code" else ["imagen"]
        if vision:
            tags.append("visión")
        is_free = _is_free_model(model_id)
        is_openai = "api.openai.com" in base.lower()
        pin, pout = (_openai_price(model_id) if is_openai else (None, None))
        if is_openai and (pin is not None or pout is not None):
            tags.append("de pago")
            custom_paid = False
        else:
            custom_paid = not is_free
            if not is_free:
                tags.append("de pago")
        if is_free:
            tags.append("gratis")
        price_val = 0.0 if is_free else None
        price_unit = "gratis" if is_free else "por consultar en cuenta"
        models.append(
            catalog.Model(
                provider=pid,
                uid=model_id,
                name=model_id,
                category=category,
                free=is_free,
                p_in=pin,
                p_out=pout,
                price=price_val,
                unit="1M tokens" if category == "code" else "imagen",
                desc=f"Modelo de {name}. {price_unit}. Revisa tu cuenta para confirmar.",
                tags=tags,
                extra={
                    "modality": "text+image->text" if vision else "text->text",
                    "custom": True,
                    "free_model": is_free,
                    "custom_paid": custom_paid,
                },
            )
        )
    if not models:
        raise api.ApiError("La API respondió, pero no encontré modelos de chat ni de imagen.")
    return models


def categories_of(models: list[catalog.Model]) -> list[str]:
    found = {catalog.tab_of(model.category) for model in models}
    return [cat for cat, _label in catalog.CATEGORIES if cat in found]