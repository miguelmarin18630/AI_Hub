"""Herramientas de archivos para el agente del panel.

El modelo (vía OpenRouter) puede listar, leer, crear y editar archivos dentro
del proyecto elegido. Todo se valida para que no salga de esa carpeta y nunca
se escribe dentro de .git.
"""

from __future__ import annotations

from pathlib import Path

MAX_READ_CHARS = 20_000
MAX_WRITE_CHARS = 200_000
MAX_LIST_ENTRIES = 300

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    ".next",
    ".nuxt",
    "build",
    "dist",
    ".gradle",
    ".idea",
    ".vscode",
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Lista archivos y carpetas dentro del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Subcarpeta relativa al proyecto. Vacío o '.' para la raíz.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee un archivo de texto del proyecto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa del archivo."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o reemplaza un archivo con el contenido indicado. Úsalo para archivos nuevos o reescrituras completas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa del archivo."},
                    "content": {"type": "string", "description": "Contenido completo del archivo."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Reemplaza un fragmento de texto exacto dentro de un archivo existente. Mejor para cambios pequeños.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Ruta relativa del archivo."},
                    "old": {"type": "string", "description": "Texto exacto que ya existe."},
                    "new": {"type": "string", "description": "Texto nuevo que lo sustituye."},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
]


class ToolError(Exception):
    """Error controlado que se devuelve al modelo como resultado."""


def _inside_git(path: Path) -> bool:
    """True si la ruta está dentro de .git (sin distinguir mayúsculas: Windows es insensible)."""
    return any(part.lower() == ".git" for part in path.parts)


def _resolve(root: Path, raw: str | None) -> Path:
    root = root.resolve()
    text = str(raw or "").strip().strip('"')
    if text in ("", ".", "./"):
        return root
    target = (root / text).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"Ruta fuera del proyecto: {text}")
    return target


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def list_files(root: Path, path: str = "") -> tuple[str, str]:
    folder = _resolve(root, path)
    if not folder.is_dir():
        raise ToolError(f"No es una carpeta: {_relative(root, folder) or '.'}")
    lines: list[str] = []
    count = 0
    try:
        entries = sorted(folder.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
    except OSError as exc:
        raise ToolError(f"No se pudo leer la carpeta: {exc}") from None
    for entry in entries:
        if entry.name.startswith(".") and entry.name not in (".env.example",):
            continue
        if entry.is_dir() and entry.name in SKIP_DIRS:
            continue
        count += 1
        if count > MAX_LIST_ENTRIES:
            lines.append(f"… (más de {MAX_LIST_ENTRIES} entradas, usa una subcarpeta)")
            break
        if entry.is_dir():
            lines.append(f"{entry.name}/")
        else:
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            lines.append(f"{entry.name} ({_size(size)})")
    rel = _relative(root, folder) or "."
    header = f"{rel}/" if rel != "." else "./"
    body = "\n".join(lines) if lines else "(carpeta vacía)"
    return f"{header}\n{body}", f"listar · {rel} ({count} entradas)"


def read_file(root: Path, path: str) -> tuple[str, str]:
    file = _resolve(root, path)
    if not file.is_file():
        raise ToolError(f"No existe el archivo: {_relative(root, file)}")
    try:
        size = file.stat().st_size
        with file.open("rb") as handle:
            raw = handle.read(MAX_READ_CHARS * 4 + 1)
    except OSError as exc:
        raise ToolError(f"No se pudo leer: {exc}") from None
    if b"\x00" in raw[:4000]:
        raise ToolError("El archivo parece binario y no se puede leer como texto.")
    text = raw.decode("utf-8", "replace")
    truncated = len(text) > MAX_READ_CHARS or size > len(raw)
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS]
    rel = _relative(root, file)
    note = f"\n\n[truncado a {MAX_READ_CHARS} caracteres]" if truncated else ""
    return f"Archivo {rel}:\n{text}{note}", f"leer · {rel} ({_size(size)})"


def write_file(root: Path, path: str, content: str) -> tuple[str, str]:
    file = _resolve(root, path)
    if _inside_git(file):
        raise ToolError("No se escribe dentro de .git")
    if file.is_dir():
        raise ToolError(f"Es una carpeta: {_relative(root, file)}")
    if len(content) > MAX_WRITE_CHARS:
        raise ToolError("El contenido es demasiado grande (máximo 200 000 caracteres).")
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolError(f"No se pudo escribir: {exc}") from None
    rel = _relative(root, file)
    return (
        f"Escrito {rel} ({len(content)} caracteres, {content.count(chr(10)) + 1} líneas).",
        f"escribir · {rel} ({_size(len(content.encode('utf-8')))})",
    )


def replace_in_file(root: Path, path: str, old: str, new: str) -> tuple[str, str]:
    file = _resolve(root, path)
    if _inside_git(file):
        raise ToolError("No se escribe dentro de .git")
    if not file.is_file():
        raise ToolError(f"No existe el archivo: {_relative(root, file)}")
    if not old:
        raise ToolError("El texto a sustituir está vacío.")
    # newline="" conserva los finales de línea originales (CRLF en Windows). Si el
    # archivo usa CRLF en todas sus líneas, se trabaja en LF y se restauran al escribir;
    # así el modelo puede dar fragmentos con \n y no se reescribe todo el archivo.
    try:
        with file.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"No se pudo leer el archivo: {exc}") from None
    crlf = "\r\n" in text and text.count("\r\n") == text.count("\n")
    if crlf:
        text = text.replace("\r\n", "\n")
        old = old.replace("\r\n", "\n")
        new = new.replace("\r\n", "\n")
    count = text.count(old)
    if count == 0:
        raise ToolError("No se encontró el texto indicado en el archivo.")
    updated = text.replace(old, new)
    if crlf:
        updated = updated.replace("\n", "\r\n")
    try:
        file.write_text(updated, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolError(f"No se pudo escribir: {exc}") from None
    rel = _relative(root, file)
    return (
        f"Actualizado {rel}: {count} sustitución(es).",
        f"editar · {rel} ({count} cambio{'s' if count != 1 else ''})",
    )


def execute(name: str, args: dict, root: Path) -> tuple[str, str]:
    """Ejecuta una herramienta y devuelve (resultado para el modelo, línea de registro)."""
    if name == "list_files":
        return list_files(root, str(args.get("path") or ""))
    if name == "read_file":
        return read_file(root, str(args.get("path") or ""))
    if name == "write_file":
        return write_file(root, str(args.get("path") or ""), str(args.get("content") or ""))
    if name == "replace_in_file":
        return replace_in_file(
            root,
            str(args.get("path") or ""),
            str(args.get("old") or ""),
            str(args.get("new") or ""),
        )
    raise ToolError(f"Herramienta desconocida: {name}")


def list_entries(root: Path, limit: int = 200) -> list[tuple[str, bool]]:
    """Entradas de primer nivel del proyecto para el panel lateral: (nombre, es_carpeta)."""
    try:
        entries = list(root.iterdir())
    except OSError:
        return []
    visible: list[tuple[str, bool]] = []
    for entry in entries:
        if entry.name.startswith("."):
            continue
        is_dir = entry.is_dir()
        if is_dir and entry.name in SKIP_DIRS:
            continue
        visible.append((entry.name, is_dir))
    visible.sort(key=lambda item: (not item[1], item[0].lower()))
    return visible[:limit]


def parse_text_call(text: str) -> tuple[str, dict] | None:
    """Reconoce una llamada a herramienta escrita como texto.

    Algunos modelos locales pequeños (p. ej. qwen2.5-coder:1.5b) anuncian
    soporte de herramientas pero las escriben en el mensaje, a veces dentro de
    un bloque ```json. Devuelve (nombre, argumentos) si es una llamada válida.
    """
    import json

    raw = (text or "").strip()
    if not raw or ("{" not in raw):
        return None
    start = raw.find("{")
    depth = 0
    end = -1
    in_string = False
    escape = False
    for index in range(start, len(raw)):
        char = raw[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end <= start:
        return None
    try:
        data = json.loads(raw[start:end])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name") or data.get("tool") or data.get("function") or data.get("action")
    if isinstance(name, dict):
        name = name.get("name")
    if not isinstance(name, str) or name not in {tool["function"]["name"] for tool in TOOLS}:
        return None
    args = data.get("arguments")
    if args is None:
        args = data.get("parameters")
    if args is None:
        args = data.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(args, (dict, type(None))):
        return None
    return name, dict(args or {})


def describe(name: str, args: dict) -> str:
    """Texto corto para el registro de la interfaz."""
    path = str(args.get("path") or "").strip() or "."
    if name == "list_files":
        return path
    if name == "read_file":
        return path
    if name == "write_file":
        content = str(args.get("content") or "")
        return f"{path} ({_size(len(content.encode('utf-8')))})"
    if name == "replace_in_file":
        return path
    return path


def system_prompt(root: Path) -> str:
    return (
        "Eres un asistente de programación que trabaja dentro del proyecto ubicado en "
        f"{root}.\n"
        "Puedes listar, leer, crear y modificar archivos con las herramientas disponibles. "
        "Trabaja únicamente dentro de esa carpeta y no escribas en .git.\n"
        "Reglas: lee un archivo antes de editarlo; para cambios pequeños usa "
        "replace_in_file y para archivos nuevos o reescrituras completas usa write_file; "
        "no inventes el contenido de archivos que no has leído. "
        "Responde en el mismo idioma que el usuario. Al terminar, resume qué archivos "
        "has cambiado y qué has hecho."
    )
