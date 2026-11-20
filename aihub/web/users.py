"""Cuentas y sesiones de la versión web multiusuario.

Cada cuenta tiene su propia carpeta dentro de ``%APPDATA%\\AIHub\\web\\users``
con su configuración, claves, caché de modelos y proyectos. Las contraseñas se
guardan con PBKDF2-HMAC-SHA256 y las sesiones se firman con HMAC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from aihub import config

_ITERATIONS = 260_000
_COOKIE = "aihub_session"
_SESSION_DAYS = 30
_lock = threading.RLock()


def web_dir() -> Path:
    env = os.environ.get("AIHUB_WEB_DIR")
    return Path(env) if env else config.APP_DIR / "web"


def users_file() -> Path:
    return web_dir() / "users.json"


def secret_file() -> Path:
    return web_dir() / "secret.key"


def _read_users() -> list[dict]:
    try:
        raw = json.loads(users_file().read_text(encoding="utf-8"))
    except Exception:
        return []
    items = raw.get("users") if isinstance(raw, dict) else raw
    return [dict(item) for item in (items or []) if isinstance(item, dict)]


def _write_users(users: list[dict]) -> None:
    base = web_dir()
    base.mkdir(parents=True, exist_ok=True)
    tmp = users_file().with_suffix(".tmp")
    tmp.write_text(json.dumps({"users": users}, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(users_file())


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:32] or "usuario"


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS).hex()


def public(user: dict, detailed: bool = False) -> dict:
    data = {
        "id": user.get("id"),
        "name": user.get("name"),
        "role": user.get("role", "user"),
        "created": user.get("created"),
        "desktop": bool(data_dir(user)),
    }
    if detailed:
        data["data_dir"] = str(data_dir(user) or "")
    return data


def list_users(detailed: bool = False) -> list[dict]:
    return [public(item, detailed=detailed) for item in _read_users()]


def get_user(user_id: str) -> dict | None:
    return next((item for item in _read_users() if item.get("id") == user_id), None)


def has_users() -> bool:
    return bool(_read_users())


def create_user(name: str, password: str, role: str = "user") -> dict:
    name = " ".join(str(name or "").split()).strip()
    if len(name) < 2:
        raise ValueError("El nombre debe tener al menos 2 caracteres.")
    if len(password or "") < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    role = "admin" if role == "admin" else "user"
    with _lock:
        users = _read_users()
        taken = {item.get("id") for item in users}
        base = slugify(name)
        user_id, number = base, 2
        while user_id in taken:
            user_id = f"{base}-{number}"
            number += 1
        salt = secrets.token_bytes(16)
        user = {
            "id": user_id,
            "name": name,
            "role": role,
            "salt": salt.hex(),
            "hash": _hash(password, salt),
            "iterations": _ITERATIONS,
            "created": int(time.time()),
        }
        users.append(user)
        _write_users(users)
        ensure_user_env(user_id)
        return public(user)


def verify(name: str, password: str) -> dict | None:
    """Busca por id o por nombre (sin distinguir mayúsculas) y comprueba la clave."""
    wanted = str(name or "").strip().lower()
    for user in _read_users():
        if str(user.get("id", "")).lower() != wanted and str(user.get("name", "")).lower() != wanted:
            continue
        try:
            salt = bytes.fromhex(str(user.get("salt") or ""))
        except ValueError:
            return None
        expected = str(user.get("hash") or "")
        actual = _hash(password or "", salt)
        if hmac.compare_digest(expected, actual):
            return public(user)
        return None
    return None


def set_password(user_id: str, password: str) -> None:
    if len(password or "") < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres.")
    with _lock:
        users = _read_users()
        user = next((item for item in users if item.get("id") == user_id), None)
        if user is None:
            raise ValueError("Ese usuario no existe.")
        salt = secrets.token_bytes(16)
        user["salt"] = salt.hex()
        user["hash"] = _hash(password, salt)
        user["iterations"] = _ITERATIONS
        _write_users(users)


def delete_user(user_id: str, requester: str) -> None:
    with _lock:
        users = _read_users()
        target = next((item for item in users if item.get("id") == user_id), None)
        if target is None:
            raise ValueError("Ese usuario no existe.")
        if user_id == requester:
            raise ValueError("No puedes borrar tu propia cuenta.")
        admins = [item for item in users if item.get("role") == "admin"]
        if target.get("role") == "admin" and len(admins) <= 1:
            raise ValueError("Debe quedar al menos un administrador.")
        users = [item for item in users if item.get("id") != user_id]
        _write_users(users)


def user_dir(user_id: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", str(user_id or "")):
        raise ValueError("Identificador de usuario no válido.")
    return web_dir() / "users" / user_id


def data_dir(user: dict | None) -> Path | None:
    """Carpeta de datos compartida (por ejemplo, la de la app de escritorio)."""
    raw = str((user or {}).get("data_dir") or "").strip()
    return Path(raw).expanduser() if raw else None


def effective_dir(user_id: str) -> Path:
    """Carpeta real de datos del usuario: la vinculada o la suya de la web."""
    user = get_user(user_id)
    linked = data_dir(user)
    return linked if linked is not None else user_dir(user_id)


def _initial_config(base: Path) -> dict:
    cfg = dict(config.DEFAULTS)
    cfg.update(
        {
            "openrouter_api_key": "",
            "workdir": "",
            "projects_root": str(base / "proyectos"),
            "output_root": str(base / "salida"),
            "custom_providers": [],
            "usage": {},
            "last_provider": "openrouter",
            "last_category": "code",
            "last_models": {},
        }
    )
    return cfg


def ensure_user_env(user_id: str) -> Path:
    """Crea la carpeta personal y una configuración inicial aislada.

    Si la cuenta está vinculada a otra carpeta (la del escritorio), se usa esa
    carpeta tal cual: así comparte claves, proyectos e historial con la app de
    escritorio. Nunca se pisan ficheros que ya existan.
    """
    user = get_user(user_id)
    linked = data_dir(user)
    if linked is not None:
        base = linked
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(f"No se puede usar la carpeta {base}: {exc}") from exc
    else:
        base = user_dir(user_id)
        (base / "proyectos").mkdir(parents=True, exist_ok=True)
        (base / "salida").mkdir(parents=True, exist_ok=True)

    cfg_file = base / "config.json"
    if not cfg_file.exists():
        config.set_app_dir(base)
        try:
            config.save_config(_initial_config(base))
        finally:
            config.set_app_dir(None)
    return base


def set_data_dir(user_id: str, raw: str) -> str:
    """Vincula la cuenta a una carpeta de datos o la devuelve a la suya.

    ``raw`` vacío desvincula. El valor especial ``__desktop__`` enlaza con la
    carpeta de la app de escritorio (``%APPDATA%\\AIHub``). Cualquier otra cosa
    debe ser una ruta absoluta a una carpeta existente.
    """
    with _lock:
        users = _read_users()
        user = next((item for item in users if item.get("id") == user_id), None)
        if user is None:
            raise ValueError("Ese usuario no existe.")
        value = str(raw or "").strip()
        if value in ("", "__none__"):
            user.pop("data_dir", None)
        else:
            if value == "__desktop__":
                target = config.APP_DIR
            else:
                target = Path(value).expanduser()
                if not target.is_absolute():
                    raise ValueError("Escribe una ruta absoluta, por ejemplo C:\\Proyectos.")
                target = target.resolve()
                if not target.is_dir():
                    raise ValueError("Esa carpeta no existe.")
            user["data_dir"] = str(target)
        _write_users(users)
        return str(data_dir(user) or "")


def activate(user_id: str) -> Path:
    """Activa la carpeta del usuario en este hilo y devuelve su ruta."""
    base = ensure_user_env(user_id)
    config.set_app_dir(base)
    return base


def _secret() -> bytes:
    path = secret_file()
    try:
        if path.exists():
            return path.read_bytes()
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_bytes(48)
    path.write_bytes(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def make_session(user_id: str) -> str:
    expires = int(time.time()) + _SESSION_DAYS * 86400
    payload = f"{user_id}.{expires}"
    signature = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_session(token: str) -> str | None:
    parts = str(token or "").split(".")
    if len(parts) != 3:
        return None
    user_id, raw_exp, signature = parts
    payload = f"{user_id}.{raw_exp}"
    expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        if int(raw_exp) < time.time():
            return None
    except ValueError:
        return None
    return user_id if get_user(user_id) else None


def cookie_header(user_id: str, secure: bool) -> str:
    token = make_session(user_id)
    bits = [
        f"{_COOKIE}={token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Lax",
        f"Max-Age={_SESSION_DAYS * 86400}",
    ]
    if secure:
        bits.append("Secure")
    return "; ".join(bits)


def clear_cookie_header(secure: bool) -> str:
    bits = [f"{_COOKIE}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        bits.append("Secure")
    return "; ".join(bits)


def cookie_name() -> str:
    return _COOKIE
