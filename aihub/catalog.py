"""Catálogo de modelos: normalización, precios, caché y actualización."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import __version__, api, config, local

CACHE_VERSION = 4

PROVIDERS = [
    {
        "id": "ollama",
        "name": "Ollama",
        "sub": "Local, 100 % gratis",
        "glyph": "⬢",
        "color": "#4ec9b0",
        "categories": ["code"],
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "sub": "Agente de código en terminal",
        "glyph": "◇",
        "color": "#8b7bff",
        "categories": ["code"],
    },
    {
        "id": "claude",
        "name": "Claude Code",
        "sub": "Anthropic, en terminal",
        "glyph": "✳",
        "color": "#e89b5a",
        "categories": ["code"],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "sub": "Texto, imagen y vídeo por API",
        "glyph": "↗",
        "color": "#f2b84b",
        "categories": ["code", "media"],
    },
]

PROVIDER_BY_ID = {item["id"]: item for item in PROVIDERS}
CATEGORIES = [("code", "Programación"), ("media", "Imagen y vídeo")]
CATEGORY_LABELS = {"code": "Programación", "image": "Imagen", "video": "Vídeo", "media": "Imagen y vídeo"}
_TAB_OF = {"code": "code", "image": "media", "video": "media", "media": "media"}


def tab_of(category: str) -> str:
    """Pestaña a la que pertenece una categoría de modelo (imagen y vídeo comparten pestaña)."""
    return _TAB_OF.get(category, category)

CLAUDE_ALIASES = [
    ("haiku", "Claude Haiku 5.5", "anthropic/claude-haiku-5.5", 0.10, 0.50,
     "El más rápido y barato de Anthropic. Ideal para tareas sencillas y ediciones rápidas."),
    ("sonnet", "Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5", 2.00, 10.00,
     "Equilibrio entre calidad y precio. El modelo recomendado para programar con Claude Code."),
    ("opus", "Claude Opus 5.5", "anthropic/claude-opus-5.5", 4.00, 20.00,
     "El más capaz para código complejo, aunque cuesta el doble que Sonnet."),
    ("fable", "Claude Fable 5.2", "anthropic/claude-fable-5.2", 8.00, 40.00,
     "Modelo premium de la familia Mythos. Solo para trabajos que necesiten lo máximo."),
]

OLLAMA_CURATED = [
    ("qwen2.5-coder:1.5b", "Programación · ultrarrápido, 1 GB", "Ideal para autocompletar y preguntas rápidas en un portátil."),
    ("qwen2.5-coder:7b", "Programación · equilibrio, 4,7 GB", "Muy bueno en código para su tamaño; cabe en 8 GB de RAM."),
    ("qwen3-coder:30b", "Programación · potente, ~19 GB", "Nivel avanzado si tienes una GPU con suficiente VRAM."),
    ("deepseek-coder-v2:16b", "Programación · 8,9 GB", "Fuerte en lenguajes de programación y refactorización."),
    ("llama3.2:3b", "General · ligero, 2 GB", "Rápido para chat general y tareas de texto."),
    ("gemma3:4b", "General · multimodal, 3,3 GB", "Acepta imágenes y texto; buena relación tamaño/calidad."),
    ("phi4:14b", "Razonamiento · 9,1 GB", "Buen razonamiento matemático y técnico en local."),
    ("mistral:7b", "General · 4,4 GB", "Clásico fiable para tareas generales."),
    ("codellama:7b", "Programación · 3,8 GB", "Especializado en código, ligero y veterano."),
    ("starcoder2:7b", "Programación · 4 GB", "Entrenado con código; bueno para completar funciones."),
    ("llava:7b", "Visión · 4,7 GB", "Analiza imágenes (no genera): describe, extrae texto, responde preguntas."),
    ("llama3.2-vision:11b", "Visión · 7,9 GB", "Analiza imágenes y documentos con buena calidad."),
    ("qwen2.5vl:7b", "Visión · 6 GB", "Visión y OCR potentes, también para capturas de pantalla."),
    ("moondream:latest", "Visión · 1,7 GB", "Visión muy ligera para describir imágenes rápido."),
]

_IMAGE_UNIT = {"image": "imagen", "megapixel": "MP", "token": "1M tokens"}


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    if value == 0:
        return "0"
    if value < 0.0001:
        return f"{value:.6f}".rstrip("0").rstrip(".")
    if value < 0.01:
        return f"{value:.4f}".rstrip("0").rstrip(".")
    if value < 1:
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{value:.2f}".rstrip("0").rstrip(".") if value < 10 else f"{value:.2f}".rstrip("0").rstrip(".")


def fmt_context(tokens: int | None) -> str:
    if not tokens:
        return "—"
    if tokens >= 1_000_000:
        value = tokens / 1_000_000
        return f"{value:.1f}".rstrip("0").rstrip(".") + "M"
    if tokens >= 1000:
        return f"{round(tokens / 1000)}K"
    return str(tokens)


def human_size(num_bytes: int | float | None) -> str:
    if not num_bytes:
        return ""
    gb = float(num_bytes) / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f} GB".replace(".", ",")
    return f"{gb * 1024:.0f} MB"


@dataclass
class Model:
    provider: str
    uid: str
    name: str
    category: str
    free: bool = False
    p_in: float | None = None
    p_out: float | None = None
    price: float | None = None
    unit: str = "1M tokens"
    context: int | None = None
    desc: str = ""
    tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    # -- presentación -------------------------------------------------------
    @property
    def effective_price(self) -> float | None:
        if self.category == "code":
            if self.p_out:
                return self.p_out
            if self.p_in:
                return self.p_in
            if self.free:
                return 0.0
            return self.price
        return self.price

    def price_text(self) -> str:
        if self.free:
            return "Gratis"
        if self.extra.get("custom_paid"):
            return "de pago"
        if self.extra.get("variable_price"):
            return "variable"
        if self.category == "code":
            has_in = self.p_in is not None
            has_out = self.p_out is not None
            if has_in and has_out:
                if not self.p_in and not self.p_out:
                    return "por petición"
                return f"${fmt_usd(self.p_in)} / ${fmt_usd(self.p_out)}"
            if self.effective_price is not None:
                return f"${fmt_usd(self.effective_price)}"
            return "—"
        if self.price is None:
            if self.extra.get("token_price"):
                return "por tokens"
            return "—"
        if self.unit == "imagen":
            return f"${fmt_usd(self.price)} / imagen"
        if self.unit == "s":
            return f"${fmt_usd(self.price)} / s"
        if self.unit == "MP":
            return f"${fmt_usd(self.price)} / MP"
        return f"${fmt_usd(self.price)}"

    def price_detail(self) -> str:
        if self.provider == "ollama":
            return "Local y gratis · usa tu propio hardware"
        if self.free:
            return "Gratis · 0 $ por millón de tokens"
        if self.category == "code":
            if self.extra.get("variable_price"):
                return "Precio variable: el router elige el modelo y cobra el de ese modelo"
            if self.p_in is None and self.p_out is None:
                return "Precio no disponible en el catálogo local"
            if not self.p_in and not self.p_out:
                per_request = self.extra.get("per_request")
                if per_request:
                    return f"Se cobra por petición: ${fmt_usd(float(per_request))} cada una"
                return "Se cobra por petición, no por token"
            return f"Entrada ${fmt_usd(self.p_in)} · Salida ${fmt_usd(self.p_out)} por 1M tokens"
        if self.category == "image":
            if self.price is None:
                token_price = self.extra.get("token_price")
                if token_price:
                    return (
                        f"${fmt_usd(token_price)} por token de imagen · "
                        "el coste real depende de la resolución"
                    )
                return "Precio por imagen aún sin calcular"
            if self.unit == "MP":
                return f"${fmt_usd(self.price)} por megapíxel generado"
            return f"${fmt_usd(self.price)} por imagen generada"
        if self.category == "video":
            if self.price is None:
                return "Precio por segundo no disponible (se factura por tokens)"
            seconds = self.extra.get("sample_duration") or 4
            estimate = self.price * seconds
            return (
                f"≈ ${fmt_usd(self.price)} por segundo · "
                f"{seconds}s ≈ ${fmt_usd(estimate)}"
            )
        return ""

    def context_text(self) -> str:
        return fmt_context(self.context)

    def info_text(self) -> str:
        bits: list[str] = []
        if self.provider == "opencode":
            gateway = {
                "openrouter": "OpenRouter",
                "console-openrouter": "Console",
                "opencode": "Zen",
                "google": "Google",
                "groq": "Groq",
            }.get(str(self.extra.get("gateway") or ""), "")
            if gateway:
                bits.append(gateway)
        if self.provider == "ollama":
            if self.extra.get("installed"):
                bits.append("Instalado")
                size = human_size(self.extra.get("size"))
                if size:
                    bits[-1] += f" · {size}"
            else:
                bits.append("Descargable")
        if self.category == "code" and self.context:
            bits.append(f"{self.context_text()} ctx")
        if self.category == "image":
            ratios = self.extra.get("aspect_ratios") or []
            if ratios:
                bits.append(" · ".join(ratios[:3]))
        if self.category == "video":
            res = self.extra.get("resolutions") or []
            durations = self.extra.get("durations") or []
            if res:
                order = ["360p", "480p", "540p", "720p", "1080p", "1440p", "2K", "4K"]
                best = max(res, key=lambda item: order.index(item) if item in order else -1)
                bits.append(best)
            if durations:
                bits.append(f"{max(durations)}s")
        if self.provider == "claude":
            bits.append(f"alias: {self.extra.get('alias', self.uid)}")
        if not bits:
            bits.append(self.unit)
        return " · ".join(bits)

    def is_installed(self) -> bool:
        return bool(self.extra.get("installed"))


# ---------------------------------------------------------------------------
# Caché
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache_data: dict[str, dict] = {}


def _empty_cache() -> dict:
    return {"version": CACHE_VERSION, "app_version": __version__, "providers": {}, "image_prices": {}}


def _read_cache() -> dict:
    try:
        raw = json.loads(config.cache_path().read_text(encoding="utf-8"))
        if (
            isinstance(raw, dict)
            and raw.get("version") == CACHE_VERSION
            and raw.get("app_version") == __version__
        ):
            raw.setdefault("providers", {})
            raw.setdefault("image_prices", {})
            return raw
    except Exception:
        pass
    return _empty_cache()


def cache() -> dict:
    key = str(config.cache_path())
    with _cache_lock:
        if key not in _cache_data:
            _cache_data[key] = _read_cache()
        return _cache_data[key]


def _write_cache(data: dict) -> None:
    try:
        config.app_dir().mkdir(parents=True, exist_ok=True)
        tmp = config.cache_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(config.cache_path())
    except Exception:
        pass


def store_models(provider: str, models: list[Model]) -> None:
    data = cache()
    data["providers"][provider] = {
        "ts": time.time(),
        "models": [asdict(model) for model in models],
    }
    _write_cache(data)


def cached_models(provider: str) -> tuple[list[Model], float | None]:
    entry = cache()["providers"].get(provider) or {}
    raw = entry.get("models") or []
    models: list[Model] = []
    for item in raw:
        try:
            item.setdefault("extra", {})
            item["tags"] = list(item.get("tags") or [])
            models.append(Model(**item))
        except Exception:
            continue
    return models, entry.get("ts")


def cached_image_prices() -> tuple[dict, float | None]:
    entry = cache().get("image_prices") or {}
    return entry.get("data") or {}, entry.get("ts")


def store_image_prices(data: dict) -> None:
    cache()["image_prices"] = {"ts": time.time(), "data": data}
    _write_cache(cache())


def cached_video_meta(provider: str) -> list[Model]:
    models, _ = cached_models(provider)
    return models


# ---------------------------------------------------------------------------
# Construcción de catálogos
# ---------------------------------------------------------------------------

def _clean_desc(text: str | None, limit: int = 420) -> str:
    if not text:
        return ""
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text))
    value = re.sub(r"[*_`#>]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > limit:
        value = value[:limit].rstrip() + "…"
    return value


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_name(name: str, uid: str) -> str:
    """Quita prefijos de proveedor redundantes: "Recraft: Recraft V4" -> "Recraft V4"."""
    name = " ".join(name.split())
    if ": " not in name:
        return name
    prefix, rest = name.split(": ", 1)
    norm = lambda text: "".join(ch for ch in text.lower() if ch.isalnum())  # noqa: E731
    prefix_key = norm(prefix)
    if len(prefix_key) >= 3 and norm(rest).startswith(prefix_key):
        return rest
    return name


def build_openrouter_text(raw: list[dict]) -> list[Model]:
    models: list[Model] = []
    for item in raw:
        uid = str(item.get("id") or "").strip()
        if not uid or uid.endswith(":batch"):
            continue
        arch = item.get("architecture") or {}
        outputs = arch.get("output_modalities") or ["text"]
        if any(kind in outputs for kind in ("image", "video", "audio")):
            continue
        pricing = item.get("pricing") or {}
        raw_in = _num(pricing.get("prompt"))
        raw_out = _num(pricing.get("completion"))
        per_request = _num(pricing.get("request")) or 0.0
        # OpenRouter usa -1 en modelos de precio variable (routers): no es un precio real.
        p_in = None if raw_in is None or raw_in < 0 else round(raw_in * 1_000_000, 6)
        p_out = None if raw_out is None or raw_out < 0 else round(raw_out * 1_000_000, 6)
        free = p_in == 0 and p_out == 0 and per_request <= 0
        variable = (raw_in is not None and raw_in < 0) or (raw_out is not None and raw_out < 0)
        supported = item.get("supported_parameters") or []
        inputs = arch.get("input_modalities") or ["text"]
        tags: list[str] = []
        if free:
            tags.append("gratis")
        if item.get("reasoning"):
            tags.append("razonamiento")
        if "tools" in supported:
            tags.append("herramientas")
        if "image" in inputs:
            tags.append("visión")
        if "free" in uid and uid.endswith(":free"):
            tags.append("free")
        models.append(
            Model(
                provider="openrouter",
                uid=uid,
                name=_display_name(str(item.get("name") or uid), uid),
                category="code",
                free=free,
                p_in=p_in,
                p_out=p_out,
                price=p_out if p_out else p_in,
                unit="1M tokens",
                context=item.get("context_length"),
                desc=_clean_desc(item.get("description")),
                tags=tags,
                extra={
                    "modality": arch.get("modality"),
                    "per_request": per_request,
                    "variable_price": variable,
                    "created": item.get("created"),
                },
            )
        )
    return models


def build_openrouter_images(raw: list[dict]) -> list[Model]:
    models: list[Model] = []
    for item in raw:
        uid = str(item.get("id") or "").strip()
        if not uid:
            continue
        arch = item.get("architecture") or {}
        params = item.get("supported_parameters") or {}
        ratios = (params.get("aspect_ratio") or {}).get("values") or []
        inputs = arch.get("input_modalities") or ["text"]
        tags = ["imagen"]
        if "image" in inputs:
            tags.append("edición")
        if item.get("supports_streaming"):
            tags.append("streaming")
        models.append(
            Model(
                provider="openrouter",
                uid=uid,
                name=_display_name(str(item.get("name") or uid), uid),
                category="image",
                free=False,
                context=None,
                desc=_clean_desc(item.get("description")),
                tags=tags,
                unit="imagen",
                extra={
                    "aspect_ratios": list(ratios),
                    "input_modalities": list(inputs),
                },
            )
        )
    return models


def build_openrouter_videos(raw: list[dict]) -> list[Model]:
    models: list[Model] = []
    for item in raw:
        uid = str(item.get("id") or "").strip()
        durations = [d for d in (item.get("supported_durations") or []) if isinstance(d, (int, float)) and d > 0]
        if not uid or not durations:
            continue
        price, unit = api.video_prices(item.get("pricing_skus"))
        resolutions = list(item.get("supported_resolutions") or [])
        aspects = list(item.get("supported_aspect_ratios") or [])
        sample = min(durations) if durations else 4
        tags = ["vídeo"]
        if item.get("generate_audio"):
            tags.append("con audio")
        if item.get("supported_frame_images"):
            tags.append("imagen→vídeo")
        models.append(
            Model(
                provider="openrouter",
                uid=uid,
                name=_display_name(str(item.get("name") or uid), uid),
                category="video",
                free=price == 0,
                price=price,
                unit=unit or "s",
                desc=_clean_desc(item.get("description")),
                tags=tags,
                extra={
                    "durations": durations,
                    "resolutions": resolutions,
                    "aspect_ratios": aspects,
                    "sample_duration": sample,
                    "audio": bool(item.get("generate_audio")),
                },
            )
        )
    return models


def apply_image_prices(models: list[Model], prices: dict) -> None:
    for model in models:
        info = prices.get(model.uid)
        if not info:
            continue
        price = _num(info.get("price"))
        unit = str(info.get("unit") or "image")
        if price is None or price < 0:
            continue
        if unit == "token":
            # Se factura por tokens: no es comparable con un precio por imagen.
            model.extra["token_price"] = price
            model.price = None
            model.unit = "tokens"
            continue
        model.price = price
        model.unit = _IMAGE_UNIT.get(unit, "imagen")
        model.free = model.price == 0


def build_claude(text_models: list[Model]) -> list[Model]:
    by_uid = {model.uid: model for model in text_models}
    models: list[Model] = []
    for alias, name, api_id, fallback_in, fallback_out, desc in CLAUDE_ALIASES:
        source = by_uid.get(api_id)
        p_in = source.p_in if source and source.p_in is not None else fallback_in
        p_out = source.p_out if source and source.p_out is not None else fallback_out
        models.append(
            Model(
                provider="claude",
                uid=alias,
                name=name,
                category="code",
                free=False,
                p_in=p_in,
                p_out=p_out,
                price=p_out,
                context=(source.context if source and source.context else 1_000_000),
                desc=desc,
                tags=["Anthropic", f"alias: {alias}"],
                extra={"alias": alias, "api_id": api_id, "live_price": bool(source)},
            )
        )
    return models


def _pretty_name(uid: str) -> str:
    base = uid.split(":")[0].split("/")[-1]
    base = base.replace("-", " ").replace("_", " ").strip()
    return base[:1].upper() + base[1:] if base else uid


def _opencode_error_hint(stderr: str) -> str:
    """Convierte el error crudo del CLI de OpenCode en un aviso legible.

    El CLI (compilado con bun) a veces falla al activar sus plugins npm
    (`@ai-sdk/openai-compatible`, etc.) y escupe un stack interno. Normalmente
    es transitorio: al reintentar ya funciona. Aquí lo traducimos a algo
    entendible en vez de mostrar la traza interna.
    """
    low = (stderr or "").lower()
    if "did not finish activating" in low or "serviceunavailable" in low:
        return (
            "OpenCode no terminó de activar sus plugins (suele ser temporal). "
            "Pulsa «Actualizar» para reintentar; si persiste, abre OpenCode una "
            "vez en el terminal y vuelve a intentarlo."
        )
    if "enoent" in low or "not found" in low:
        return "El comando «opencode» no respondió correctamente. Revisa la instalación de OpenCode."
    detail = _clean_desc((stderr or "").strip(), 180)
    return detail


def _parse_opencode_uids(stdout: str) -> list[str]:
    uids: list[str] = []
    for line in (stdout or "").splitlines():
        value = local.strip_ansi(line).strip()
        if value and "/" in value and " " not in value:
            uids.append(value)
    return uids


def build_opencode(text_models: list[Model], zen: dict | None = None) -> list[Model]:
    zen = zen or {}
    if not local.installed("opencode"):
        raise RuntimeError(
            "OpenCode no está instalado o no está en el PATH. "
            "Instálalo con: npm install -g opencode-ai"
        )
    # El CLI puede fallar de forma intermitente la primera vez (activación de
    # plugins npm en frío). Reintentamos un par de veces antes de rendirnos.
    uids: list[str] = []
    last_detail = ""
    for attempt in range(3):
        try:
            proc = subprocess.run(
                "opencode models",
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                creationflags=local.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("OpenCode tardó demasiado en listar los modelos.") from None
        uids = _parse_opencode_uids(proc.stdout or "")
        if uids:
            break
        last_detail = _opencode_error_hint((proc.stderr or "").strip())
        if attempt < 2:
            time.sleep(1.5)
    if not uids:
        raise RuntimeError(
            "No se pudieron leer los modelos de OpenCode."
            + (f" {last_detail}" if last_detail else "")
        )

    by_uid = {model.uid: model for model in text_models}
    by_name = {model.name: model for model in text_models}
    gateway_names = {
        "openrouter": "OpenRouter",
        "console-openrouter": "OpenRouter",
        "opencode": "OpenCode Zen",
        "google": "Google",
        "groq": "Groq",
        "ollama": "Ollama",
    }
    models: list[Model] = []
    seen: set[str] = set()
    for uid in uids:
        if uid in seen:
            continue
        seen.add(uid)
        base = uid
        for prefix in ("openrouter/", "console-openrouter/"):
            if base.startswith(prefix):
                base = base[len(prefix):]
                break
        source = by_uid.get(base) or by_uid.get(uid)
        gateway = uid.split("/", 1)[0]
        zen_id = uid.split("/", 1)[1] if gateway == "opencode" and "/" in uid else ""
        zen_info = zen.get(zen_id) if zen_id else None
        free = bool(re.search(r"(?::free|-free)$", uid))
        tags = [gateway_names.get(gateway, gateway)]
        if free:
            tags.append("gratis")
        if zen_info:
            name = str(zen_info.get("name") or _pretty_name(base))
            p_in = zen_info.get("p_in")
            p_out = zen_info.get("p_out")
            context = zen_info.get("context")
            desc = _clean_desc(zen_info.get("desc")) or "Modelo servido por OpenCode Zen."
            if zen_info.get("free"):
                free = True
                tags.append("gratis")
            if zen_info.get("reasoning"):
                tags.append("razonamiento")
            if zen_info.get("tools"):
                tags.append("herramientas")
        elif source:
            name = source.name
            p_in, p_out = source.p_in, source.p_out
            context = source.context
            desc = source.desc
            if source.free:
                free = True
            tags.extend(tag for tag in source.tags if tag not in tags)
        else:
            name = _pretty_name(base)
            p_in = p_out = None
            context = None
            desc = "Modelo disponible en OpenCode."
        if free:
            p_in = p_out = 0.0
        models.append(
            Model(
                provider="opencode",
                uid=uid,
                name=name,
                category="code",
                free=free,
                p_in=p_in,
                p_out=p_out,
                price=(p_out if p_out is not None else p_in),
                context=context,
                desc=desc,
                tags=tags,
                extra={"gateway": gateway, "base": base},
            )
        )
    return models


def build_ollama(tags: list[dict]) -> list[Model]:
    installed: dict[str, dict] = {}
    for item in tags:
        name = str(item.get("name") or item.get("model") or "").strip()
        if name:
            installed[name] = item
    curated = {name: (label, desc) for name, label, desc in OLLAMA_CURATED}
    models: list[Model] = []

    for name, item in installed.items():
        label, desc = curated.get(name, ("", ""))
        models.append(
            Model(
                provider="ollama",
                uid=name,
                name=name,
                category="code",
                free=True,
                p_in=0.0,
                p_out=0.0,
                price=0.0,
                unit="local",
                desc=desc or "Modelo instalado en local con Ollama. Gratis e ilimitado.",
                tags=["local", "instalado"] + ([label] if label else []),
                extra={
                    "installed": True,
                    "size": item.get("size"),
                    "modified": item.get("modified_at"),
                },
            )
        )

    for name, label, desc in OLLAMA_CURATED:
        if name in installed:
            continue
        models.append(
            Model(
                provider="ollama",
                uid=name,
                name=name,
                category="code",
                free=True,
                p_in=0.0,
                p_out=0.0,
                price=0.0,
                unit="local",
                desc=f"{desc} Se descarga una vez y funciona sin conexión.",
                tags=["local", "descargable"],
                extra={"installed": False},
            )
        )
    return models


# ---------------------------------------------------------------------------
# Actualización completa
# ---------------------------------------------------------------------------

def refresh_all(
    cfg: dict,
    providers: list[str] | None = None,
    progress=lambda _message: None,
    image_prices: bool = False,
) -> dict:
    """Actualiza los catálogos indicados. Devuelve {provider: {models, error}}."""
    wanted = set(providers or ["ollama", "opencode", "claude", "openrouter"])
    result: dict[str, dict] = {}

    text_raw: list[dict] = []
    text_models: list[Model] = []
    if wanted & {"openrouter", "claude", "opencode"}:
        progress("Descargando catálogo de OpenRouter…")
        text_raw = api.openrouter_models_text()
        text_models = build_openrouter_text(text_raw)
        if not text_models:
            raise RuntimeError("OpenRouter devolvió un catálogo vacío.")

    if "openrouter" in wanted:
        progress("Descargando modelos de imagen y vídeo…")
        images: list[Model] = []
        videos: list[Model] = []
        try:
            images = build_openrouter_images(api.openrouter_models_image())
        except Exception as exc:
            result.setdefault("openrouter", {"models": [], "error": str(exc)})
        try:
            videos = build_openrouter_videos(api.openrouter_models_video())
        except Exception as exc:
            result.setdefault("openrouter", {"models": [], "error": str(exc)})

        if image_prices or not cached_image_prices()[0]:
            progress("Calculando precios por imagen…")
            prices = api.image_endpoint_prices([model.uid for model in images])
            if prices:
                apply_image_prices(images, prices)
                store_image_prices(prices)
        else:
            apply_image_prices(images, cached_image_prices()[0])

        models = text_models + images + videos
        store_models("openrouter", models)
        result["openrouter"] = {
            "models": models,
            "error": (result.get("openrouter") or {}).get("error"),
        }

    if "claude" in wanted:
        progress("Actualizando Claude Code…")
        models = build_claude(text_models)
        store_models("claude", models)
        result["claude"] = {"models": models, "error": None}

    if "opencode" in wanted:
        progress("Leyendo modelos de OpenCode…")
        try:
            zen = api.opencode_models_meta()
            models = build_opencode(text_models, zen)
            store_models("opencode", models)
            result["opencode"] = {"models": models, "error": None}
        except Exception as exc:
            old, _ = cached_models("opencode")
            result["opencode"] = {"models": old, "error": str(exc)}

    if "ollama" in wanted:
        progress("Consultando Ollama local…")
        models = build_ollama(api.ollama_tags())
        store_models("ollama", models)
        result["ollama"] = {"models": models, "error": None}

    return result


_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z])")

TOP_FAMILIES = (
    "deepseek",
    "qwen",
    "glm",
    "kimi",
    "minimax",
    "llama",
    "mistral",
    "mixtral",
    "gemma",
    "gpt",
    "gemini",
    "claude",
    "phi",
    "nemotron",
    "seed",
    "hunyuan",
    "ernie",
    "ling",
    "command",
    "grok",
)

ROUTER_WORDS = ("router", "auto", "fusion", "switchyard", "free models")


def relevance_score(model: Model) -> float:
    """Puntuación aproximada para ordenar los modelos gratuitos (mayor = más útil).

    Suma contexto, capacidades (herramientas, visión, razonamiento), tamaño de
    parámetros, familia conocida y antigüedad. No es una medida objetiva: sirve
    para que primero salgan los gratuitos que suelen dar mejor resultado.
    """
    score = 0.0

    context = model.context or 0
    if context:
        score += min(context / 200_000, 1.0) * 35

    tags = set(model.tags)
    if "herramientas" in tags:
        score += 12
    if "visión" in tags:
        score += 8
    if "razonamiento" in tags:
        score += 6

    text = f"{model.name} {model.uid}".lower()
    sizes = [float(match) for match in _SIZE_RE.findall(text)]
    if sizes:
        size = max(sizes)
        score += min(size / 70.0, 1.0) * 16
        if size < 3:
            score -= 6

    if any(family in text for family in TOP_FAMILIES):
        score += 10

    if any(word in text for word in ROUTER_WORDS):
        score -= 18

    created = model.extra.get("created")
    try:
        created = float(created)
    except (TypeError, ValueError):
        created = 0.0
    if created:
        age_days = max(0.0, (time.time() - created) / 86_400)
        score += max(0.0, 1.0 - age_days / 400.0) * 8

    return round(score, 2)


def sort_models(models: list[Model], mode: str = "price") -> list[Model]:
    """Ordena: primero los gratuitos por relevancia y luego los de pago más baratos."""
    ordered = list(models)

    if mode == "name":
        ordered.sort(key=lambda model: (model.name.lower(), model.uid))
        return ordered

    if mode == "context":
        ordered.sort(key=lambda model: (-(model.context or 0), model.name.lower()))
        return ordered

    def desc_key(model: Model):
        price = model.effective_price
        if model.free:
            return (3, -relevance_score(model), 0.0, model.name.lower())
        if price is None:
            return (2, 0.0, 0.0, model.name.lower())
        return (1, -price, 0.0, model.name.lower())

    if mode == "price_desc":
        ordered.sort(key=desc_key)
        return ordered

    def asc_key(model: Model):
        if model.provider == "ollama":
            return (0, 0.0 if model.is_installed() else 1.0, -relevance_score(model), model.name.lower())
        if model.free:
            return (0, -relevance_score(model), 0.0, model.name.lower())
        price = model.effective_price
        if price is None:
            return (2, 0.0, 0.0, model.name.lower())
        return (1, price, 0.0, model.name.lower())

    ordered.sort(key=asc_key)
    return ordered


def filter_models(
    models: list[Model],
    query: str = "",
    price_filter: str = "Todos",
) -> list[Model]:
    query = (query or "").strip().lower()
    output: list[Model] = []
    for model in models:
        if price_filter == "Gratis" and not model.free:
            continue
        if price_filter == "De pago" and model.free:
            continue
        if query:
            haystack = f"{model.name} {model.uid} {model.desc} {' '.join(model.tags)}".lower()
            if query not in haystack:
                continue
        output.append(model)
    return output


def cache_age_text(ts: float | None) -> str:
    if not ts:
        return "sin datos"
    seconds = max(0, int(time.time() - ts))
    if seconds < 60:
        return "ahora mismo"
    if seconds < 3600:
        return f"hace {seconds // 60} min"
    if seconds < 86400:
        return f"hace {seconds // 3600} h"
    return f"hace {seconds // 86400} d"
