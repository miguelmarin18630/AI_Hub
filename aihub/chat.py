"""Cómo funciona una IA con las consultas y respuestas.

Una IA no recuerda nada por sí sola: en cada petición hay que enviarle el
**contexto** completo de la conversación. Este módulo centraliza esa lógica
para que todos los proveedores se comporten igual:

1. El mensaje del usuario se añade al historial.
2. Se construye el contexto: instrucciones del sistema + turnos anteriores +
   el mensaje nuevo.
3. Si el contexto supera la **ventana del modelo**, se recortan los turnos más
   antiguos completos (nunca la mitad de una llamada a herramientas).
4. El modelo responde y su respuesta se añade al historial.
5. El historial se guarda en disco y se recupera al volver a abrir la app.

La medición de tokens es una aproximación (≈4 caracteres por token). No
necesita ser exacta: sirve para no desbordar la ventana del modelo.
"""

from __future__ import annotations

from dataclasses import dataclass

# Ventana de contexto que se usa cuando el catálogo no la conoce.
DEFAULT_CONTEXT = 32_768
# Los modelos locales suelen configurarse con 4K/8K; 8K es un límite seguro.
OLLAMA_CONTEXT = 8_192
# Espacio reservado para la respuesta que va a escribir el modelo.
RESERVE_TOKENS = 1_024
# Límite aproximado del historial que se pasa a los CLI (OpenCode / Claude Code).
CLI_CONTEXT = 12_000

DEFAULT_SYSTEM_PROMPT = (
    "Eres AI Hub, un asistente de IA útil, directo y honesto. "
    "Responde en el idioma del usuario (por defecto, en español). "
    "Ten en cuenta los mensajes anteriores de la conversación: mantén el hilo, "
    "no vuelvas a preguntar lo que el usuario ya explicó y usa el contexto disponible. "
    "Si no sabes algo o necesitas un dato que no tienes, dilo en lugar de inventarlo. "
    "Cuando escribas código, usa bloques de código y explica solo lo necesario."
)

# Texto compartido por la app (diálogo «Cómo funciona») y la documentación.
EXPLAIN_STEPS = (
    (
        "1. Escribes una consulta",
        "La app la añade al historial como un mensaje de usuario. El historial es la "
        "memoria de la conversación: sin él, cada pregunta empezaría de cero.",
    ),
    (
        "2. Se construye el contexto",
        "Antes de llamar al modelo se envía: las instrucciones del sistema (cómo debe "
        "responder), los turnos anteriores y tu mensaje nuevo. Así la segunda pregunta "
        "puede apoyarse en la primera respuesta.",
    ),
    (
        "3. Se respeta la ventana del modelo",
        "Cada modelo admite un máximo de tokens. Si la conversación crece demasiado, "
        "la app recorta los turnos más antiguos y conserva los recientes. El indicador "
        "«Contexto» de la cabecera muestra cuánto se está usando.",
    ),
    (
        "4. El modelo responde",
        "La respuesta llega en streaming y se guarda como mensaje del asistente. En los "
        "modelos con herramientas, también se guardan las lecturas y escrituras de "
        "archivos para que el siguiente turno sepa qué se hizo.",
    ),
    (
        "5. La conversación continúa",
        "Cambiar de modelo o de proveedor no borra el hilo: el contexto se envía al "
        "modelo nuevo. «Nuevo chat» sí empieza una conversación limpia. Al cerrar la "
        "app, el historial queda en conversations.json y se recupera al abrirla.",
    ),
)


@dataclass
class ContextInfo:
    """Resumen del contexto de una conversación."""

    tokens: int
    sent_tokens: int
    limit: int
    turns: int
    messages: int
    sent: int
    dropped: int
    truncated: bool = False

    @property
    def percent(self) -> float:
        if self.limit <= 0:
            return 0.0
        return min(1.0, self.tokens / self.limit)

    @property
    def level(self) -> str:
        """Semáforo para la interfaz: ok, aviso o límite."""
        if self.percent >= 0.85:
            return "high"
        if self.percent >= 0.6:
            return "medium"
        return "ok"


def _as_text(value: object) -> str:
    """Extrae el texto de un contenido (cadena o lista multimodal)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return "" if value is None else str(value)


def estimate_tokens(value: object) -> int:
    """Estimación rápida de tokens: ~4 caracteres por token y 800 por imagen."""
    if isinstance(value, list):
        tokens = estimate_tokens(_as_text(value))
        images = sum(
            1
            for item in value
            if isinstance(item, dict) and item.get("type") in ("image_url", "image")
        )
        return tokens + images * 800
    text = _as_text(value)
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def message_tokens(message: dict) -> int:
    """Tokens estimados de un mensaje, incluido su envoltorio."""
    if not isinstance(message, dict):
        return 0
    tokens = 4 + estimate_tokens(message.get("content"))
    images = message.get("images")
    if isinstance(images, list):
        tokens += len(images) * 800
    return tokens


def history_tokens(history: list[dict]) -> int:
    return sum(message_tokens(item) for item in history or [] if isinstance(item, dict))


def turn_count(history: list[dict]) -> int:
    return sum(1 for item in history or [] if isinstance(item, dict) and item.get("role") == "user")


def context_limit_for(model) -> int:
    """Ventana de contexto del modelo, con un valor seguro si no se conoce."""
    try:
        value = int(getattr(model, "context", 0) or 0)
    except (TypeError, ValueError):
        value = 0
    if value > 0:
        return value
    if getattr(model, "provider", "") == "ollama":
        return OLLAMA_CONTEXT
    return DEFAULT_CONTEXT


def fmt_tokens(value: int) -> str:
    """Formato corto en español: 950, 8K, 12,5K, 1M."""
    value = max(0, int(value or 0))
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".", ",")
    if value >= 10_000:
        return f"{round(value / 1000)}K"
    if value >= 1_000:
        return f"{value / 1000:.1f}K".replace(".", ",")
    return str(value)


def conversation_info(history: list[dict], limit: int) -> ContextInfo:
    """Resumen para la cabecera: tamaño actual del hilo y su límite."""
    messages = [item for item in (history or []) if isinstance(item, dict)]
    tokens = history_tokens(messages)
    return ContextInfo(
        tokens=tokens,
        sent_tokens=tokens,
        limit=max(1, int(limit or DEFAULT_CONTEXT)),
        turns=turn_count(messages),
        messages=len(messages),
        sent=len(messages),
        dropped=0,
    )


def _normalized(history: list[dict]) -> list[dict]:
    """Copia los mensajes válidos; no modifica el historial original."""
    clean: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")
        if role not in ("user", "assistant", "tool", "system"):
            continue
        message = dict(item)
        content = message.get("content")
        if isinstance(content, list):
            message["content"] = [dict(part) for part in content if isinstance(part, dict)]
        clean.append(message)
    return clean


def _truncate_last_user(messages: list[dict], budget: int) -> bool:
    """Recorta el último mensaje si él solo no cabe en la ventana."""
    if not messages:
        return False
    last = messages[-1]
    if last.get("role") != "user":
        return False
    content = last.get("content")
    if not isinstance(content, str):
        return False
    excess = history_tokens(messages) - budget
    if excess <= 0:
        return False
    keep = max(500, len(content) - excess * 4)
    if keep >= len(content):
        return False
    marker = "\n\n[… recortado por espacio de contexto]"
    last["content"] = content[:keep] + marker
    return True


def build_messages(
    history: list[dict],
    *,
    limit: int = DEFAULT_CONTEXT,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    reserve: int = RESERVE_TOKENS,
) -> tuple[list[dict], ContextInfo]:
    """Construye el contexto que se envía al modelo.

    Devuelve ``(mensajes, info)``. Los turnos se recortan siempre por bloques
    que empiezan en un mensaje de usuario, para no romper las llamadas a
    herramientas de un turno anterior.
    """
    clean = _normalized(history)
    limit = max(1_024, int(limit or DEFAULT_CONTEXT))
    system = {"role": "system", "content": system_prompt} if system_prompt else None
    system_tokens = estimate_tokens(system_prompt) if system_prompt else 0
    budget = max(512, limit - max(0, reserve) - system_tokens)

    total_tokens = history_tokens(clean)
    turns = turn_count(clean)

    boundaries = [index for index, item in enumerate(clean) if item.get("role") == "user"]
    selected: list[dict] = []
    if boundaries:
        for start in boundaries:
            candidate = clean[start:]
            if history_tokens(candidate) <= budget:
                selected = candidate
                break
        if not selected:
            selected = clean[boundaries[-1]:]

    truncated = _truncate_last_user(selected, budget)
    sent_tokens = history_tokens(selected)
    messages = ([system] if system else []) + selected
    info = ContextInfo(
        tokens=total_tokens,
        sent_tokens=sent_tokens,
        limit=limit,
        turns=turns,
        messages=len(clean),
        sent=len(selected),
        dropped=max(0, len(clean) - len(selected)),
        truncated=truncated,
    )
    return messages, info


def context_note(info: ContextInfo) -> str:
    """Aviso breve cuando hubo que recortar el contexto."""
    if info.dropped <= 0 and not info.truncated:
        return ""
    bits = [f"Contexto: se envían los últimos {info.sent} mensajes"]
    if info.truncated:
        bits.append("y se recortó la consulta")
    return " · ".join(bits) + f" (~{fmt_tokens(info.sent_tokens)} de {fmt_tokens(info.limit)} tokens)."


def build_cli_prompt(
    history: list[dict],
    prompt: str,
    *,
    limit: int = CLI_CONTEXT,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """Convierte el historial en texto para los CLI (OpenCode / Claude Code)."""
    clean = _normalized(history)
    # El CLI recibe el prompt actual aparte: el historial previo es el contexto.
    if clean and clean[-1].get("role") == "user":
        clean = clean[:-1]
    if not clean:
        return prompt

    budget = max(512, limit - estimate_tokens(prompt) - 256)
    boundaries = [index for index, item in enumerate(clean) if item.get("role") == "user"]
    selected: list[dict] = []
    for start in boundaries:
        candidate = clean[start:]
        if history_tokens(candidate) <= budget:
            selected = candidate
            break
    if not selected and boundaries:
        selected = clean[boundaries[-1]:]

    lines: list[str] = []
    for item in selected:
        role = item.get("role")
        content = _as_text(item.get("content")).strip()
        if not content:
            continue
        name = "Usuario" if role == "user" else "Asistente"
        lines.append(f"{name}: {content}")
    if not lines:
        return prompt
    preamble = system_prompt.strip()
    body = "\n\n".join(lines)
    return (
        f"{preamble}\n\n"
        "Contexto de la conversación anterior:\n\n"
        f"{body}\n\n"
        "Nueva consulta del usuario:\n\n"
        f"{prompt}"
    )


def explain_text() -> str:
    return "\n\n".join(f"{title}\n{body}" for title, body in EXPLAIN_STEPS)
