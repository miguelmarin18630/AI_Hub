"""Proveedores añadidos por el usuario: APIs compatibles con OpenAI.

Cada proveedor guarda su nombre, URL base y clave en config.json. Al conectarlo se
listan sus modelos y se reparten entre Programación (chat) e Imagen. Vídeo requiere
un adaptador propio y no se ofrece todavía.
"""

from __future__ import annotations

import re

from . import api, catalog, config

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


def _is_free_model(model_id: str) -> bool:
    """Determina si un modelo de proveedor personalizado es gratuito.

    Reglas por proveedor basadas en substrings del nombre del modelo.
    Se marcan como gratuit los modelos que los proveedores suelen ofrecer
    en sus planes free / quota diario.
    """
    low = model_id.lower()

    # --- OpenAI ---
    # La API de OpenAI no tiene nivel gratuito: todos sus modelos (gpt-3.5,
    # gpt-4o-mini, etc.) se cobran contra el saldo de la cuenta. Los nuevos
    # proyectos pueden tener créditos de prueba, pero eso no es "gratis".
    if any(sub in low for sub in ["gpt-", "o1-", "o3-", "o4-", "davinci", "text-embedding"]):
        return False

    # --- Google Gemini ---
    # Los de -flash suelen tener quota gratuito diario
    if any(sub in low for sub in ["flash", "1.5-flash"]):
        return True

    # --- DeepSeek ---
    # Los modelos -code, -coder y -distill suelen tener free tier
    if any(sub in low for sub in ["-code", "-coder", "-distill"]):
        return True

    # --- Groq ---
    # No tiene free tier para modelos de chat
    if "groq" in low:
        return False

    # --- Mistral ---
    # Los de -instruct y -small suelen ser gratuitos o tener trial
    if any(sub in low for sub in ["-instruct", "-small", "-v0.1"]):
        return True

    # --- Together AI ---
    # Por defecto pago
    return False


def records(cfg: dict) -> list[dict]:
    return [dict(item) for item in (cfg.get("custom_providers") or []) if isinstance(item, dict)]


def get(cfg: dict, pid: str) -> dict | None:
    return next((item for item in records(cfg) if item.get("id") == pid), None)


def unique_id(cfg: dict, preset_id: str) -> str:
    taken = {item["id"] for item in records(cfg)} | set(catalog.PROVIDER_BY_ID)
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
        # Determinar si es gratuito basándose en el nombre del modelo
        is_free = _is_free_model(model_id)
        # Establecer precio: si es gratis, 0; si no, indicar que hay que consultar cuenta
        price_val = 0.0 if is_free else None
        price_unit = "gratis" if is_free else "por consultar en cuenta"
        tags.append("gratis" if is_free else "de pago")
        models.append(
            catalog.Model(
                provider=pid,
                uid=model_id,
                name=model_id,
                category=category,
                free=is_free,
                price=price_val,
                unit="1M tokens" if category == "code" else "imagen",
                desc=f"Modelo de {name}. {price_unit}. Revisa tu cuenta para confirmar.",
                tags=tags,
                extra={
                    "modality": "text+image->text" if vision else "text->text",
                    "custom": True,
                    "free_model": is_free,
                    "custom_paid": not is_free,
                },
            )
        )
    if not models:
        raise api.ApiError("La API respondió, pero no encontré modelos de chat ni de imagen.")
    return models


def categories_of(models: list[catalog.Model]) -> list[str]:
    found = {catalog.tab_of(model.category) for model in models}
    return [cat for cat, _label in catalog.CATEGORIES if cat in found]