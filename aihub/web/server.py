"""Servidor HTTP de AI Hub para uso familiar en el navegador.

No usa dependencias externas: ``http.server`` + HTML/CSS/JS. Cada petición
autenticada activa la carpeta de datos de su usuario, de modo que las claves,
los modelos personalizados, el consumo y los proyectos nunca se mezclan.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from aihub import __version__, agent, api, catalog, config, custom, local, projects, usage

from . import users

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BODY = 4 * 1024 * 1024
MAX_HISTORY = 40
TOOL_ROUNDS = 7

_login_attempts: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _base_providers() -> list[dict]:
    return [dict(item) for item in catalog.PROVIDERS if not item.get("custom")]


def _provider_list(cfg: dict) -> list[dict]:
    providers = _base_providers()
    providers.extend(custom.provider_entry(item) for item in custom.records(cfg))
    return providers


def _model_payload(model: catalog.Model, provider: dict | None) -> dict:
    data = asdict(model)
    data.update(
        {
            "price_text": model.price_text(),
            "price_detail": model.price_detail(),
            "context_text": model.context_text(),
            "info_text": model.info_text(),
            "effective_price": model.effective_price,
            "provider_name": (provider or {}).get("name", model.provider),
            "provider_color": (provider or {}).get("color", "#8b93a7"),
            "provider_glyph": (provider or {}).get("glyph", "◆"),
        }
    )
    return data


def _all_models(cfg: dict) -> tuple[list[dict], list[dict]]:
    providers = _provider_list(cfg)
    by_id = {item["id"]: item for item in providers}
    models: list[dict] = []
    for provider in providers:
        cached, stamp = catalog.cached_models(provider["id"])
        for model in cached:
            item = _model_payload(model, by_id.get(model.provider) or provider)
            item["cached_at"] = stamp
            models.append(item)
    return providers, models


def _project_root(cfg: dict) -> Path:
    return projects.root(cfg).resolve()


def _safe_project(cfg: dict, name: str | None) -> Path:
    root = _project_root(cfg)
    raw = str(name or "").strip()
    if raw in ("", "__root__"):
        return root
    target = (root / raw).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Proyecto no válido.")
    if not target.is_dir():
        raise ValueError("Ese proyecto no existe.")
    return target


def _safe_in(base: Path, relative: str | None) -> Path:
    base = base.resolve()
    target = (base / str(relative or "")).resolve()
    if not target.is_relative_to(base):
        raise ValueError("Ruta fuera del proyecto.")
    return target


def _projects_payload(cfg: dict) -> list[dict]:
    active = str(cfg.get("workdir") or "")
    out: list[dict] = []
    for item in projects.list_projects(cfg):
        is_root = bool(item.get("root"))
        out.append(
            {
                "id": "__root__" if is_root else item["name"],
                "name": "Todos los proyectos" if is_root else item["name"],
                "kinds": item["kinds"],
                "count": item["count"],
                "mtime": item["mtime"],
                "root": is_root,
                "active": (str(item["path"]) == active) if not is_root else active == str(item["path"]),
            }
        )
    return out


def _settings_payload(cfg: dict) -> dict:
    key = config.openrouter_key(cfg, allow_env=False)
    return {
        "openrouter_set": bool(key),
        "openrouter_hint": (key[-4:] if key else ""),
        "custom_providers": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "base": item.get("base"),
                "glyph": item.get("glyph"),
                "color": item.get("color"),
                "categories": item.get("categories") or ["code"],
                "key_set": bool(item.get("key")),
            }
            for item in custom.records(cfg)
        ],
        "presets": custom.PRESETS,
        "output_root": str(cfg.get("output_root") or ""),
    }


def _origin_ok(handler: BaseHTTPRequestHandler) -> bool:
    origin = handler.headers.get("Origin")
    if not origin:
        return True
    host = handler.headers.get("Host") or ""
    return urllib.parse.urlparse(origin).netloc == host


def _is_secure(handler: BaseHTTPRequestHandler) -> bool:
    return (
        (handler.headers.get("X-Forwarded-Proto") or "").lower() == "https"
        or handler.headers.get("CF-Visitor", "").find('"https"') >= 0
    )


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _login_lock:
        stamps = [stamp for stamp in _login_attempts.get(ip, []) if now - stamp < 600]
        _login_attempts[ip] = stamps
        return len(stamps) >= 15


def _note_failure(ip: str) -> None:
    with _login_lock:
        _login_attempts.setdefault(ip, []).append(time.time())


def _clear_failures(ip: str) -> None:
    with _login_lock:
        _login_attempts.pop(ip, None)


class Handler(BaseHTTPRequestHandler):
    server_version = f"AIHub/{__version__}"
    protocol_version = "HTTP/1.1"

    # -- utilidades ---------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} · {fmt % args}")

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
            "font-src 'self'; frame-ancestors 'none'",
        )

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            pass

    def _error(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            raise ValueError("La petición es demasiado grande.")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Se esperaba un objeto JSON.")
        return data

    def _cookie(self, name: str) -> str:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value
        return ""

    def _current_user(self) -> dict | None:
        token = self._cookie(users.cookie_name())
        user_id = users.read_session(token)
        if not user_id:
            config.set_app_dir(None)
            return None
        user = users.get_user(user_id)
        if not user:
            config.set_app_dir(None)
            return None
        users.activate(user_id)
        return user

    def _require_user(self) -> dict | None:
        user = self._current_user()
        if not user:
            self._error(401, "Inicia sesión para continuar.")
            return None
        return user

    def _require_admin(self) -> dict | None:
        user = self._require_user()
        if user and user.get("role") != "admin":
            self._error(403, "Solo el administrador puede hacer esto.")
            return None
        return user

    def _client_ip(self) -> str:
        return (
            self.headers.get("CF-Connecting-IP")
            or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or self.client_address[0]
        )

    # -- HTTP ---------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._serve_file(STATIC_DIR / "index.html")
                return
            if path.startswith("/static/"):
                self._serve_static(path[len("/static/") :])
                return
            if path == "/favicon.ico":
                self._serve_file(STATIC_DIR / "favicon.svg", "image/svg+xml")
                return
            if path == "/api/state":
                self._send_json(
                    {
                        "setup_required": not users.has_users(),
                        "version": __version__,
                    }
                )
                return
            if path == "/api/me":
                user = self._require_user()
                if user:
                    self._send_json({"user": users.public(user)})
                return
            if path == "/api/catalog":
                if not self._require_user():
                    return
                cfg = config.load_config()
                providers, models = _all_models(cfg)
                self._send_json(
                    {
                        "providers": providers,
                        "models": models,
                        "projects": _projects_payload(cfg),
                        "settings": _settings_payload(cfg),
                        "favorites": cfg.get("favorite_models") or [],
                        "version": __version__,
                    }
                )
                return
            if path == "/api/projects":
                if not self._require_user():
                    return
                cfg = config.load_config()
                self._send_json({"projects": _projects_payload(cfg)})
                return
            if path == "/api/files":
                if not self._require_user():
                    return
                cfg = config.load_config()
                project = (query.get("project") or [""])[0]
                rel = (query.get("path") or [""])[0]
                root = _safe_project(cfg, project)
                target = _safe_in(root, rel)
                if not target.is_dir():
                    raise ValueError("La carpeta no existe.")
                entries = []
                for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    if item.name.startswith(".") or (item.is_dir() and item.name in agent.SKIP_DIRS):
                        continue
                    try:
                        size = item.stat().st_size if item.is_file() else 0
                    except OSError:
                        size = 0
                    entries.append(
                        {
                            "name": item.name,
                            "dir": item.is_dir(),
                            "size": size,
                            "path": str((Path(rel) / item.name).as_posix()) if rel else item.name,
                        }
                    )
                self._send_json({"path": rel, "entries": entries[:400]})
                return
            if path == "/api/file":
                if not self._require_user():
                    return
                cfg = config.load_config()
                project = (query.get("project") or [""])[0]
                rel = (query.get("path") or [""])[0]
                root = _safe_project(cfg, project)
                text, log = agent.read_file(root, rel)
                self._send_json({"path": rel, "text": text, "log": log})
                return
            if path == "/api/usage":
                if not self._require_user():
                    return
                provider = (query.get("provider") or [""])[0]
                uid = (query.get("uid") or [""])[0]
                stats = usage.get(provider, uid)
                self._send_json(
                    {"text": usage.describe(stats), "today": stats.get("today") or {}, "total": stats}
                )
                return
            if path == "/api/settings":
                if not self._require_user():
                    return
                self._send_json(_settings_payload(config.load_config()))
                return
            if path == "/api/admin/users":
                if not self._require_admin():
                    return
                self._send_json({"users": users.list_users()})
                return
            if path == "/api/media":
                if not self._require_user():
                    return
                uid = users.read_session(self._cookie(users.cookie_name()))
                rel = (query.get("path") or [""])[0]
                base = users.user_dir(uid or "")
                target = _safe_in(base, rel)
                if not target.is_file():
                    self._error(404, "Archivo no encontrado.")
                    return
                self._serve_file(target)
                return
            self._error(404, "No encontrado.")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, f"Error interno: {exc}")

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            if not _origin_ok(self):
                self._error(403, "Origen no permitido.")
                return
            if path == "/api/setup":
                self._setup()
                return
            if path == "/api/login":
                self._login()
                return
            if path == "/api/logout":
                self._logout()
                return
            if path == "/api/refresh":
                self._refresh()
                return
            if path == "/api/chat":
                self._chat()
                return
            if path == "/api/project/select":
                self._select_project()
                return
            if path == "/api/project/create":
                self._create_project()
                return
            if path == "/api/settings":
                self._save_settings()
                return
            if path == "/api/custom/add":
                self._add_custom()
                return
            if path == "/api/custom/update":
                self._update_custom()
                return
            if path == "/api/custom/delete":
                self._delete_custom()
                return
            if path == "/api/account/password":
                self._change_password()
                return
            if path == "/api/admin/users":
                self._admin_create()
                return
            if path == "/api/admin/users/password":
                self._admin_password()
                return
            if path == "/api/admin/users/delete":
                self._admin_delete()
                return
            if path == "/api/image":
                self._image()
                return
            if path == "/api/video":
                self._video()
                return
            if path == "/api/favorites":
                self._favorites()
                return
            if path == "/api/check":
                self._check()
                return
            self._error(404, "No encontrado.")
        except ValueError as exc:
            self._error(400, str(exc))
        except api.ApiError as exc:
            self._error(502, str(exc))
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._error(500, f"Error interno: {exc}")

    def do_DELETE(self) -> None:
        self._error(405, "Método no permitido.")

    # -- autenticación ------------------------------------------------------

    def _setup(self) -> None:
        if users.has_users():
            self._error(403, "La instalación ya está configurada.")
            return
        data = self._body()
        user = users.create_user(
            str(data.get("name") or "admin"), str(data.get("password") or ""), "admin"
        )
        self.send_response(200)
        body = json.dumps({"user": user}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", users.cookie_header(user["id"], _is_secure(self)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _login(self) -> None:
        ip = self._client_ip()
        if _rate_limited(ip):
            self._error(429, "Demasiados intentos. Espera unos minutos.")
            return
        data = self._body()
        user = users.verify(str(data.get("name") or ""), str(data.get("password") or ""))
        if not user:
            _note_failure(ip)
            self._error(401, "Usuario o contraseña incorrectos.")
            return
        _clear_failures(ip)
        self.send_response(200)
        body = json.dumps({"user": user}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", users.cookie_header(user["id"], _is_secure(self)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _change_password(self) -> None:
        user = self._require_user()
        if not user:
            return
        data = self._body()
        if not users.verify(user["id"], str(data.get("current") or "")):
            self._error(403, "La contraseña actual no es correcta.")
            return
        users.set_password(user["id"], str(data.get("new") or ""))
        self._send_json({"ok": True})

    def _logout(self) -> None:
        config.set_app_dir(None)
        self.send_response(200)
        body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", users.clear_cookie_header(_is_secure(self)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    # -- catálogo -----------------------------------------------------------

    def _refresh(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        wanted = data.get("providers")
        if not isinstance(wanted, list) or not wanted:
            wanted = None
        base_ids = [item["id"] for item in _base_providers()]
        custom_records = custom.records(cfg)
        targets = set(wanted) if wanted else set(base_ids) | {item["id"] for item in custom_records}

        errors: dict[str, str] = {}
        result: dict[str, dict] = {}
        base_targets = [pid for pid in base_ids if pid in targets]
        if base_targets:
            try:
                result.update(
                    catalog.refresh_all(
                        cfg,
                        providers=base_targets,
                        image_prices=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                errors["__general__"] = str(exc)
                traceback.print_exc()

        for record in custom_records:
            pid = record.get("id")
            if pid not in targets:
                continue
            try:
                models = custom.fetch(record)
                catalog.store_models(pid, models)
                result[pid] = {"models": models, "error": None}
            except Exception as exc:  # noqa: BLE001
                errors[pid] = str(exc)
                result.setdefault(pid, {"models": [], "error": str(exc)})

        providers, models = _all_models(cfg)
        self._send_json(
            {
                "providers": providers,
                "models": models,
                "errors": errors,
                "updated": list(result.keys()),
            }
        )

    def _check(self) -> None:
        if not self._require_user():
            return
        cfg = config.load_config()
        key = config.openrouter_key(cfg, allow_env=False)
        if not key:
            self._error(400, "No hay clave de OpenRouter guardada.")
            return
        self._send_json(api.check_openrouter(key))

    # -- chat ---------------------------------------------------------------

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        self.close_connection = True

    def _sse(self, event: dict) -> None:
        try:
            payload = json.dumps(event, ensure_ascii=False)
            self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            pass

    def _chat(self) -> None:
        user = self._require_user()
        if not user:
            return
        data = self._body()
        provider_id = str(data.get("provider") or "")
        uid = str(data.get("uid") or "")
        category = str(data.get("category") or "code")
        project_name = str(data.get("project") or "")
        use_tools = bool(data.get("use_tools"))
        raw_messages = data.get("messages") or []
        if category != "code":
            self._error(400, "Ese modelo no es de chat.")
            return

        cfg = config.load_config()
        providers = {item["id"]: item for item in _provider_list(cfg)}
        info = providers.get(provider_id)
        if not info:
            self._error(400, "Proveedor desconocido.")
            return
        messages: list[dict] = []
        for item in raw_messages[-MAX_HISTORY:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = item.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
                continue
            messages.append({"role": role, "content": content[:120000]})
        if not messages or messages[-1]["role"] != "user":
            self._error(400, "Falta el mensaje del usuario.")
            return

        root: Path | None = None
        if project_name:
            try:
                root = _safe_project(cfg, project_name)
            except ValueError as exc:
                self._error(400, str(exc))
                return
            if not root.is_dir():
                root = None

        if root and use_tools:
            messages = [{"role": "system", "content": agent.system_prompt(root)}] + messages

        started = time.time()
        self._sse_start()
        self._sse({"type": "start", "model": uid, "provider": provider_id})
        usage_total: dict = {}
        try:
            if provider_id in ("opencode", "claude"):
                self._chat_cli(provider_id, uid, messages, root, cfg, usage_total)
            elif provider_id == "ollama":
                if root and use_tools:
                    self._chat_tools_ollama(uid, messages, root, usage_total)
                else:
                    stats = api.stream_ollama_chat(
                        uid,
                        messages,
                        on_delta=lambda text: self._sse({"type": "delta", "text": text}),
                    )
                    usage_total.update(stats or {})
            else:
                if provider_id == "openrouter":
                    key = config.openrouter_key(cfg, allow_env=False)
                    base = api.BASE
                else:
                    record = custom.get(cfg, provider_id) or {}
                    key = str(record.get("key") or "")
                    base = str(record.get("base") or "")
                if not key:
                    raise api.ApiError(
                        "Falta la clave de este proveedor. Añádela en Ajustes."
                    )
                if root and use_tools:
                    self._chat_tools_openai(key, uid, base, messages, root, usage_total)
                else:
                    stats = api.stream_openrouter_chat(
                        key,
                        uid,
                        messages,
                        on_delta=lambda text: self._sse({"type": "delta", "text": text}),
                        base=base,
                    )
                    usage_total.update(stats or {})

            self._record_usage(provider_id, uid, usage_total)
            stats = usage.get(provider_id, uid)
            self._sse(
                {
                    "type": "done",
                    "elapsed": round(time.time() - started, 1),
                    "usage": usage_total,
                    "usage_text": usage.describe(stats),
                }
            )
        except api.ApiError as exc:
            self._sse({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._sse({"type": "error", "message": f"Error inesperado: {exc}"})

    def _record_usage(self, provider: str, uid: str, totals: dict) -> None:
        if not totals:
            return
        try:
            usage.record(
                provider,
                uid,
                prompt=int(totals.get("prompt_tokens") or totals.get("input_tokens") or 0),
                completion=int(totals.get("completion_tokens") or totals.get("output_tokens") or 0),
                cost=float(totals.get("cost") or 0.0),
            )
        except Exception:
            traceback.print_exc()

    def _tool_event(self, name: str, args: dict, status: str = "run", detail: str = "") -> None:
        self._sse(
            {
                "type": "tool",
                "status": status,
                "name": name,
                "detail": detail or agent.describe(name, args),
            }
        )

    def _run_tool(self, name: str, args: dict, root: Path) -> str:
        self._tool_event(name, args)
        try:
            result, log = agent.execute(name, args, root)
            self._tool_event(name, args, "done", log)
            return result
        except Exception as exc:  # noqa: BLE001
            self._tool_event(name, args, "error", str(exc))
            return f"Error: {exc}"

    def _chat_tools_openai(
        self, key: str, uid: str, base: str, messages: list[dict], root: Path, totals: dict
    ) -> None:
        msgs = list(messages)
        for _ in range(TOOL_ROUNDS):
            response = api.chat_tools(key, uid, msgs, agent.TOOLS, base=base)
            self._add_usage(totals, response.get("usage") or {})
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                text = message.get("content") or ""
                if text:
                    self._sse({"type": "delta", "text": text})
                return
            msgs.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": calls,
                }
            )
            for call in calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}
                result = self._run_tool(name, args, root)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"call_{name}",
                        "name": name,
                        "content": result,
                    }
                )
        self._sse({"type": "delta", "text": "\n\n(Se alcanzó el límite de pasos con herramientas.)"})

    def _chat_tools_ollama(self, uid: str, messages: list[dict], root: Path, totals: dict) -> None:
        msgs = list(messages)
        for _ in range(TOOL_ROUNDS):
            response = api.chat_ollama_tools(uid, msgs, agent.TOOLS)
            self._add_usage(totals, response.get("usage") or {})
            choice = (response.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            calls = message.get("tool_calls") or []
            if not calls:
                text = message.get("content") or ""
                if text:
                    self._sse({"type": "delta", "text": text})
                return
            msgs.append(
                {
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": calls,
                }
            )
            for call in calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                raw_args = fn.get("arguments") or {}
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except (json.JSONDecodeError, TypeError, ValueError):
                    args = {}
                result = self._run_tool(name, args, root)
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id") or f"call_{name}",
                        "name": name,
                        "content": result,
                    }
                )
        self._sse({"type": "delta", "text": "\n\n(Se alcanzó el límite de pasos con herramientas.)"})

    def _add_usage(self, totals: dict, data: dict) -> None:
        for key, names in (
            ("prompt_tokens", ("prompt_tokens", "input_tokens")),
            ("completion_tokens", ("completion_tokens", "output_tokens")),
            ("cost", ("cost",)),
        ):
            value = next((data.get(name) for name in names if data.get(name) is not None), None)
            if value is None:
                continue
            try:
                totals[key] = float(totals.get(key, 0)) + float(value)
            except (TypeError, ValueError):
                pass

    def _chat_cli(
        self,
        provider: str,
        uid: str,
        messages: list[dict],
        root: Path | None,
        cfg: dict,
        totals: dict,
    ) -> None:
        if not local.installed(provider):
            raise api.ApiError(
                f"{provider} no está instalado en el servidor. Usa OpenRouter, Ollama o un proveedor propio."
            )
        workdir = str(root or projects.root(cfg))
        prompt = "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)
        code = local.run_prompt(
            provider,
            uid,
            prompt,
            workdir,
            on_line=lambda line: self._sse({"type": "delta", "text": line + "\n"}),
        )
        if code not in (0, None):
            self._sse({"type": "delta", "text": f"\n(El proceso terminó con código {code}.)"})

    # -- proyectos ----------------------------------------------------------

    def _select_project(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        name = str(data.get("name") or "")
        cfg = config.load_config()
        if not name:
            config.update_config(workdir="")
            self._send_json({"ok": True, "workdir": ""})
            return
        target = _safe_project(cfg, name)
        config.update_config(workdir=str(target))
        self._send_json({"ok": True, "workdir": str(target), "name": target.name})

    def _create_project(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        name = str(data.get("name") or "")
        target = projects.create(_project_root(cfg), name)
        config.update_config(workdir=str(target))
        self._send_json(
            {"ok": True, "workdir": str(target), "name": target.name, "projects": _projects_payload(config.load_config())}
        )

    # -- ajustes y proveedores ---------------------------------------------

    def _favorites(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        favorites = list(cfg.get("favorite_models") or [])
        key = str(data.get("provider")) + ":" + str(data.get("uid"))
        favorite = bool(data.get("favorite"))
        if favorite:
            if key not in favorites:
                favorites.append(key)
        else:
            favorites = [item for item in favorites if item != key]
        config.update_config(favorite_models=favorites)
        self._send_json({"ok": True, "favorites": favorites})

    def _save_settings(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        changes: dict = {}
        if "openrouter_api_key" in data:
            key = str(data.get("openrouter_api_key") or "").strip()
            changes["openrouter_api_key"] = "" if key == "__clear__" else key
        if "auto_refresh" in data:
            changes["auto_refresh"] = bool(data.get("auto_refresh"))
        if data.get("clear_usage"):
            changes["usage"] = {}
        if changes:
            config.update_config(**changes)
        self._send_json(_settings_payload(config.load_config()))

    def _add_custom(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        preset_id = str(data.get("preset") or "custom")
        preset = custom.preset(preset_id)
        name = str(data.get("name") or preset["name"]).strip()
        base = str(data.get("base") or preset["base"]).strip().rstrip("/")
        key = str(data.get("key") or "").strip()
        categories = data.get("categories") or ["code"]
        if not isinstance(categories, list):
            categories = ["code"]
        categories = [item for item in categories if item in ("code", "media")] or ["code"]
        if not re.match(r"^https?://", base):
            raise ValueError("La URL debe empezar por http:// o https://")
        pid = custom.unique_id(cfg, preset_id)
        record = {
            "id": pid,
            "name": name or preset["name"],
            "base": base,
            "key": key,
            "glyph": preset.get("glyph", "◆"),
            "color": preset.get("color", "#9aa4b2"),
            "categories": categories,
        }
        records = custom.records(cfg)
        records.append(record)
        config.update_config(custom_providers=records)
        error = ""
        try:
            models = custom.fetch(record)
            catalog.store_models(pid, models)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        self._send_json({"ok": True, "provider": record, "error": error})

    def _update_custom(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        pid = str(data.get("id") or "")
        cfg = config.load_config()
        records = custom.records(cfg)
        record = next((item for item in records if item.get("id") == pid), None)
        if record is None:
            raise ValueError("Ese proveedor no existe.")
        if "name" in data and str(data.get("name") or "").strip():
            record["name"] = str(data["name"]).strip()
        if "base" in data and str(data.get("base") or "").strip():
            base = str(data["base"]).strip().rstrip("/")
            if not re.match(r"^https?://", base):
                raise ValueError("La URL debe empezar por http:// o https://")
            record["base"] = base
        if "key" in data and str(data.get("key") or "").strip() not in ("", "__keep__"):
            record["key"] = str(data["key"]).strip()
        if "categories" in data:
            categories = data.get("categories") or []
            if not isinstance(categories, list):
                categories = ["code"]
            categories = [item for item in categories if item in ("code", "media")] or ["code"]
            record["categories"] = categories
        config.update_config(custom_providers=records)
        error = ""
        try:
            models = custom.fetch(record)
            catalog.store_models(pid, models)
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        self._send_json({"ok": True, "provider": record, "error": error})

    def _delete_custom(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        pid = str(data.get("id") or "")
        cfg = config.load_config()
        records = [item for item in custom.records(cfg) if item.get("id") != pid]
        if len(records) == len(custom.records(cfg)):
            raise ValueError("Ese proveedor no existe.")
        config.update_config(custom_providers=records)
        try:
            catalog.store_models(pid, [])
        except Exception:
            pass
        self._send_json({"ok": True})

    # -- administración -----------------------------------------------------

    def _admin_create(self) -> None:
        if not self._require_admin():
            return
        data = self._body()
        user = users.create_user(
            str(data.get("name") or ""),
            str(data.get("password") or ""),
            "admin" if data.get("role") == "admin" else "user",
        )
        self._send_json({"ok": True, "user": user})

    def _admin_password(self) -> None:
        if not self._require_admin():
            return
        data = self._body()
        users.set_password(str(data.get("id") or ""), str(data.get("password") or ""))
        self._send_json({"ok": True})

    def _admin_delete(self) -> None:
        user = self._require_admin()
        if not user:
            return
        data = self._body()
        users.delete_user(str(data.get("id") or ""), user["id"])
        self._send_json({"ok": True})

    # -- imagen y vídeo -----------------------------------------------------

    def _image(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        provider = str(data.get("provider") or "openrouter")
        uid = str(data.get("uid") or "")
        prompt = str(data.get("prompt") or "").strip()
        aspect = str(data.get("aspect_ratio") or "").strip() or None
        if not prompt:
            raise ValueError("Escribe qué imagen quieres generar.")
        out_dir = config.image_dir(cfg)
        if provider == "openrouter":
            key = config.openrouter_key(cfg, allow_env=False)
            if not key:
                raise api.ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
            path, cost, _media = api.generate_image(key, uid, prompt, out_dir, aspect_ratio=aspect)
        else:
            record = custom.get(cfg, provider) or {}
            key = str(record.get("key") or "")
            base = str(record.get("base") or "")
            if not key or not base:
                raise api.ApiError("Falta la clave o la URL de ese proveedor.")
            path, cost, _media = api.generate_image_openai(base, key, uid, prompt, out_dir)
        try:
            usage.record(provider, uid, images=1, cost=cost or 0.0)
        except Exception:
            pass
        rel = path.resolve().relative_to(users.user_dir(self._cookie_user_id()).resolve())
        self._send_json(
            {
                "ok": True,
                "url": f"/api/media?path={urllib.parse.quote(rel.as_posix())}",
                "cost": cost,
                "name": path.name,
            }
        )

    def _video(self) -> None:
        if not self._require_user():
            return
        data = self._body()
        cfg = config.load_config()
        uid = str(data.get("uid") or "")
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Escribe qué vídeo quieres generar.")
        key = config.openrouter_key(cfg, allow_env=False)
        if not key:
            raise api.ApiError("Falta la clave de OpenRouter. Configúrala en Ajustes.")
        duration = data.get("duration")
        try:
            duration = int(duration) if duration not in (None, "") else None
        except (TypeError, ValueError):
            duration = None
        path = api.generate_video(
            key,
            uid,
            prompt,
            config.video_dir(cfg),
            duration=duration,
            resolution=str(data.get("resolution") or "") or None,
            aspect_ratio=str(data.get("aspect_ratio") or "") or None,
        )
        try:
            usage.record("openrouter", uid, videos=1)
        except Exception:
            pass
        rel = path.resolve().relative_to(users.user_dir(self._cookie_user_id()).resolve())
        self._send_json(
            {
                "ok": True,
                "url": f"/api/media?path={urllib.parse.quote(rel.as_posix())}",
                "name": path.name,
            }
        )

    def _cookie_user_id(self) -> str:
        return users.read_session(self._cookie(users.cookie_name())) or ""

    # -- archivos estáticos -------------------------------------------------

    def _serve_static(self, relative: str) -> None:
        clean = relative.replace("\\", "/").lstrip("/")
        if ".." in clean.split("/"):
            self._error(404, "No encontrado.")
            return
        target = STATIC_DIR / clean
        if not target.is_file():
            self._error(404, "No encontrado.")
            return
        self._serve_file(target)

    def _serve_file(self, path: Path, content_type: str | None = None) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            self._error(404, "No encontrado.")
            return
        ctype = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        try:
            is_static = path.resolve().relative_to(STATIC_DIR.resolve())
        except ValueError:
            is_static = None
        cache = "no-store" if is_static is not None else "private, max-age=3600"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self._security_headers()
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, OSError):
            pass


class AIHubHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    users.web_dir().mkdir(parents=True, exist_ok=True)
    server = AIHubHTTPServer((host, port), Handler)
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print(f"AI Hub web {__version__} · http://{shown}:{port}")
    if not users.has_users():
        print("Primera vez: abre la URL y crea la cuenta de administrador.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrando AI Hub web…")
    finally:
        server.server_close()
