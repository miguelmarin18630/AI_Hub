"""AI Hub · punto de entrada.

Uso:
    pythonw AIHub.pyw          abre la aplicación
    python AIHub.pyw --selftest   prueba catálogos y APIs sin interfaz
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def selftest() -> int:
    from aihub import api, catalog, config, local

    print("AI Hub · autocomprobación")
    print("-" * 60)
    cfg = config.load_config()
    print(f"Config: {config.CONFIG_PATH}")
    print(f"Trabajo: {cfg['workdir']}")
    print(f"Salida: {cfg['output_root']}")
    print(f"OpenRouter key: {'sí' if config.openrouter_key(cfg) else 'no'}")
    print(f"Herramientas: {local.status()}")
    access = api.check_openrouter(config.openrouter_key(cfg))
    if access.get("ok"):
        bits = ["clave válida"]
        if isinstance(access.get("free_remaining"), int):
            bits.append(f"{access['free_remaining']} peticiones gratis hoy")
        if isinstance(access.get("remaining"), (int, float)):
            bits.append(f"límite de la clave ${access['remaining']:g}")
        print("Acceso OpenRouter:", " · ".join(bits))
    else:
        print(f"Acceso OpenRouter: {access.get('reason')} · {access.get('message')}")
    print()

    started = time.time()
    result = catalog.refresh_all(
        cfg,
        progress=lambda message: print("  ·", message),
        image_prices=True,
    )
    print(f"\nCatálogos actualizados en {time.time() - started:.1f} s\n")

    for provider in ("opencode", "claude", "ollama", "openrouter"):
        payload = result.get(provider) or {}
        models = payload.get("models") or []
        if not models:
            print(f"{provider:12} SIN MODELOS  {payload.get('error') or ''}")
            continue
        counts = {cat_id: len([m for m in models if m.category == cat_id]) for cat_id, _label in catalog.CATEGORIES}
        free = len([m for m in models if m.free])
        print(f"{provider:12} {len(models):4} modelos · gratis {free:3} · {counts}")
        if payload.get("error"):
            print(f"{'':12} aviso: {payload['error']}")
        for category in ("code", "image", "video"):
            subset = catalog.sort_models([m for m in models if m.category == category], "price")
            if not subset:
                continue
            print(f"  {category}:")
            for model in subset[:4]:
                print(f"    {model.price_text():28} {model.name[:42]:44} {model.uid}")
        print()

    prices = api.image_endpoint_prices(["google/gemini-nano-banana-2.1", "black-forest-labs/flux-3-image-klein"])
    print("Precios de imagen de prueba:", prices)
    print("\nAutocomprobación completada.")
    return 0


def smoke() -> int:
    from aihub.ui import MainWindow

    app = MainWindow()
    app.update()
    app.after(1800, app.destroy)
    app.mainloop()
    print("GUI smoke test OK")
    return 0


def commands() -> int:
    from aihub import config, local

    cfg = config.load_config()
    print("Comandos de terminal:")
    print(" ", local.command_text("opencode", "opencode/big-pickle"))
    print(" ", local.command_text("claude", "sonnet"))
    print(" ", local.command_text("ollama", "qwen2.5-coder:1.5b"))
    print("Trabajo:", cfg["workdir"])
    return 0


def _report_crash() -> None:
    """Muestra el error de arranque en vez de fallar en silencio con pythonw."""

    import ctypes
    import traceback

    from aihub import config

    text = traceback.format_exc()
    where = ""
    try:
        target = config.APP_DIR / "error.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        where = str(target)
    except Exception:
        pass
    lines = [line for line in text.strip().splitlines() if line.strip()]
    message = "AI Hub no pudo abrirse.\n\n" + (lines[-1][:400] if lines else "Error desconocido")
    if where:
        message += "\n\nDetalle guardado en:\n" + where
    try:
        ctypes.windll.user32.MessageBoxW(None, message, "AI Hub", 0x10)
    except Exception:
        print(message)


def main() -> int:
    args = set(sys.argv[1:])
    if "--selftest" in args:
        return selftest()
    if "--smoke" in args:
        return smoke()
    if "--commands" in args:
        return commands()

    from aihub.ui import run

    try:
        run()
    except Exception:
        _report_crash()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
