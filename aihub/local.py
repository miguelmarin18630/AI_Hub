"""Integración con las herramientas locales: OpenCode, Claude Code y Ollama."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Callable

from . import api

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


@lru_cache(maxsize=16)
def which(tool: str) -> str:
    return shutil.which(tool) or ""


@lru_cache(maxsize=16)
def version(tool: str) -> str:
    """Versión corta del CLI (para el diagnóstico de acceso)."""
    exe = which(tool)
    if not exe:
        return ""
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=6,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0][:60] if text else ""
    except Exception:  # noqa: BLE001
        return ""


def installed(tool: str) -> bool:
    return bool(which(tool))


def status() -> dict:
    running = api.ollama_running()
    models = ollama_models_installed() if running else []
    return {
        "opencode": installed("opencode"),
        "claude": installed("claude"),
        "ollama": installed("ollama"),
        "ollama_running": running,
        "ollama_models": len(models),
        "opencode_version": version("opencode"),
        "claude_version": version("claude"),
    }


def start_ollama(timeout: float = 8.0) -> bool:
    """Arranca 'ollama serve' en segundo plano si está instalado."""
    exe = which("ollama")
    if not exe:
        return False
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        subprocess.Popen([exe, "serve"], creationflags=CREATE_NO_WINDOW, **kwargs)
    else:
        subprocess.Popen([exe, "serve"], start_new_session=True, **kwargs)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if api.ollama_running():
            return True
        time.sleep(0.3)
    return api.ollama_running()


def command_argv(provider: str, model: str) -> list[str]:
    if provider == "opencode":
        return [which("opencode") or "opencode", "-m", model]
    if provider == "claude":
        return [which("claude") or "claude", "--model", model]
    if provider == "ollama":
        return [which("ollama") or "ollama", "run", model]
    return []


def command_text(provider: str, model: str) -> str:
    argv = command_argv(provider, model)
    if not argv:
        return ""
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _open_in_terminal(argv: list[str], workdir: str) -> None:
    """Abre una terminal nueva ejecutando argv en workdir (Windows, macOS o Linux)."""
    if os.name == "nt":
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        args = [comspec, "/c", "start", "", "/D", workdir, "cmd.exe", "/k", *argv]
        subprocess.Popen(args, cwd=workdir, creationflags=CREATE_NO_WINDOW, close_fds=True)
        return

    if sys.platform == "darwin":
        folder = Path(tempfile.mkdtemp(prefix="aihub-term-"))
        script = folder / "AI Hub.command"
        script.write_text(
            f"#!/bin/bash\ncd {shlex.quote(workdir)}\n{shlex.join(argv)}\n",
            encoding="utf-8",
        )
        script.chmod(0o755)
        subprocess.Popen(["open", str(script)])
        return

    for name, extra in (
        ("x-terminal-emulator", ["-e"]),
        ("gnome-terminal", ["--"]),
        ("konsole", ["-e"]),
        ("xfce4-terminal", ["-e"]),
        ("xterm", ["-e"]),
    ):
        exe = shutil.which(name)
        if exe:
            subprocess.Popen([exe, *extra, *argv], cwd=workdir)
            return
    raise RuntimeError("No se encontró un terminal (prueba a instalar xterm).")


def launch(provider: str, model: str, workdir: str) -> None:
    """Abre una terminal nueva con el modelo ya seleccionado."""
    argv = command_argv(provider, model)
    if not argv:
        raise RuntimeError(f"{provider} no tiene comando de terminal.")
    workdir = workdir if Path(workdir).is_dir() else str(Path.home())
    _open_in_terminal(argv, workdir)


def pull(model: str, workdir: str | None = None) -> None:
    """Descarga un modelo de Ollama en una terminal visible."""
    exe = which("ollama") or "ollama"
    _open_in_terminal([exe, "pull", model], workdir or str(Path.home()))


def _popen_cli(argv: list[str], workdir: str) -> subprocess.Popen:
    env = dict(os.environ)
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CLICOLOR", "0")
    options = dict(
        cwd=workdir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )
    if os.name == "nt":
        return subprocess.Popen(
            subprocess.list2cmdline(argv), shell=True, creationflags=CREATE_NO_WINDOW, **options
        )
    return subprocess.Popen(argv, **options)


def run_prompt(
    provider: str,
    model: str,
    prompt: str,
    workdir: str,
    on_line: Callable[[str], None],
    cancel: Callable[[], bool] = lambda: False,
    register: Callable[[subprocess.Popen | None], None] | None = None,
) -> int:
    """Ejecuta una consulta con el CLI local y va entregando líneas de salida."""
    workdir = workdir if Path(workdir).is_dir() else str(Path.home())
    if provider == "opencode":
        argv = [which("opencode") or "opencode", "run", "-m", model]
    elif provider == "claude":
        argv = [which("claude") or "claude", "-p", "--model", model, "--permission-mode", "acceptEdits"]
    else:
        raise RuntimeError(f"Proveedor sin CLI: {provider}")

    proc = _popen_cli(argv, workdir)
    if register:
        register(proc)
    try:
        try:
            proc.stdin.write(prompt)
            if not prompt.endswith("\n"):
                proc.stdin.write("\n")
            proc.stdin.close()
        except Exception:
            pass
        produced = False
        if proc.stdout is not None:
            for raw in proc.stdout:
                if cancel():
                    proc.terminate()
                    break
                line = strip_ansi(raw.rstrip("\r\n"))
                if line.strip():
                    produced = True
                on_line(line)
        code = proc.wait(timeout=900)
    except Exception:
        proc.kill()
        raise
    finally:
        if register:
            register(None)

    # Claude Code puede ignorar stdin en algunas versiones: reintentar como argumento.
    if provider == "claude" and code == 0 and not produced and prompt.strip():
        argv = [which("claude") or "claude", "-p", prompt.strip(), "--model", model, "--permission-mode", "acceptEdits"]
        proc = _popen_cli(argv, workdir)
        if register:
            register(proc)
        try:
            if proc.stdout is not None:
                for raw in proc.stdout:
                    if cancel():
                        proc.terminate()
                        break
                    on_line(strip_ansi(raw.rstrip("\r\n")))
            code = proc.wait(timeout=900)
        finally:
            if register:
                register(None)
    return code


def ollama_models_installed() -> list[str]:
    try:
        return [str(item.get("name") or item.get("model") or "") for item in api.ollama_tags()]
    except Exception:
        return []


def open_path(path: str | Path) -> None:
    path = Path(path)
    if os.name == "nt":
        if path.is_dir():
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif path.exists():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path.parent))  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        if path.is_file():
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["open", str(path if path.exists() else path.parent)])
        return
    subprocess.Popen(["xdg-open", str(path if path.exists() else path.parent)])


def open_url(url: str) -> None:
    import webbrowser

    webbrowser.open(url)


def python_launch_command(script: Path) -> str:
    """Comando para abrir la app sin consola (pythonw en Windows)."""
    if os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else Path(sys.executable)
    else:
        exe = Path(sys.executable)
    return f'"{exe}" "{script}"'
