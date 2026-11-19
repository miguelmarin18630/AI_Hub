"""Interfaz gráfica de AI Hub (Tkinter)."""

from __future__ import annotations

import base64
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, agent, api, catalog, config, custom, local, projects, usage

# Login de escritorio (compartir datos con la versión web) — desactivado hasta
# tener la versión definitiva. Para reactivarlo, pon True.
DESKTOP_LOGIN_ENABLED = False

# ---------------------------------------------------------------------------
# Paleta y tipografía
# ---------------------------------------------------------------------------

BG = "#0b0d12"
PANEL = "#13161f"
PANEL_2 = "#1a1f2a"
PANEL_3 = "#222836"
INPUT = "#0e1219"
BORDER = "#252c3b"
TEXT = "#e9ecf4"
MUTED = "#8b93a7"
DIM = "#5f687c"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#8f73ff"
ACCENT_SOFT = "#2a2350"
GREEN = "#43d9a3"
AMBER = "#f2b84b"
RED = "#ff6b6b"
CYAN = "#4ec9b0"

FONT = "Segoe UI"
MONO = "Consolas"

IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

MAX_TEXT_CHARS = 60_000
# Porcentaje de «ollama pull», p. ej. "pulling 8934d96d3f08...  45% ▕██▏"
PULL_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
TOOL_RESULT_LIMIT = 12_000  # caracteres de cada resultado de herramienta que ve el modelo


def _file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def _attachment_kind(path: Path) -> str:
    return "image" if path.suffix.lower() in IMAGE_TYPES else "text"


def _read_text_file(path: Path) -> tuple[str, bool]:
    # Solo se lee lo que se va a enviar (UTF-8: como mucho 4 bytes por carácter),
    # para no cargar en memoria archivos de cientos de MB.
    limit = MAX_TEXT_CHARS * 4
    with path.open("rb") as handle:
        raw = handle.read(limit + 1)
    text = raw[:limit].decode("utf-8", "replace")
    if len(raw) > limit or len(text) > MAX_TEXT_CHARS:
        return text[:MAX_TEXT_CHARS], True
    return text, False


def _supports_images(model) -> bool:
    """Los modelos con visión aceptan imágenes adjuntas."""
    if model.provider in ("opencode", "claude"):
        return False
    if model.provider == "ollama":
        return any("visi" in str(tag).lower() for tag in model.tags)
    modality = str(model.extra.get("modality") or "")
    return "image" in modality.split("->")[0]


def _supports_tools(model) -> bool:
    """¿El modelo anuncia función calling (herramientas)?"""
    return "herramientas" in model.tags


def _pick_fonts(root: tk.Misc) -> None:
    global MONO, FONT
    try:
        families = set(tkfont.families(root))
    except Exception:
        return
    for name in ("Segoe UI", "SF Pro Text", "Helvetica Neue", "Helvetica", "DejaVu Sans", "Arial"):
        if name in families:
            FONT = name
            break
    for name in (
        "Cascadia Mono",
        "Cascadia Code",
        "Consolas",
        "SF Mono",
        "Menlo",
        "DejaVu Sans Mono",
        "Courier New",
    ):
        if name in families:
            MONO = name
            break


def _setup_style(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "TCombobox",
        fieldbackground=PANEL_2,
        background=PANEL_2,
        foreground=TEXT,
        arrowcolor=MUTED,
        bordercolor=BORDER,
        lightcolor=PANEL_2,
        darkcolor=PANEL_2,
        insertcolor=TEXT,
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PANEL_2)],
        foreground=[("readonly", TEXT)],
        selectbackground=[("readonly", PANEL_2)],
        selectforeground=[("readonly", TEXT)],
        bordercolor=[("focus", ACCENT)],
    )
    style.configure(
        "AIH.Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        borderwidth=0,
        rowheight=32,
        font=(FONT, 10),
    )
    style.map(
        "AIH.Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure(
        "AIH.Treeview.Heading",
        background=PANEL_2,
        foreground=DIM,
        relief="flat",
        borderwidth=0,
        font=(FONT, 9, "bold"),
        padding=(8, 8),
    )
    style.map(
        "AIH.Treeview.Heading",
        background=[("active", PANEL_3)],
        foreground=[("active", MUTED)],
    )
    style.configure(
        "AIH.Vertical.TScrollbar",
        background=PANEL_3,
        troughcolor=PANEL,
        bordercolor=PANEL,
        arrowcolor=MUTED,
        darkcolor=PANEL_3,
        lightcolor=PANEL_3,
        width=10,
    )
    style.map("AIH.Vertical.TScrollbar", background=[("active", "#2f3748")])
    style.configure(
        "AIH.Horizontal.TScrollbar",
        background=PANEL_3,
        troughcolor=PANEL,
        bordercolor=PANEL,
        arrowcolor=MUTED,
        darkcolor=PANEL_3,
        lightcolor=PANEL_3,
        width=12,
    )
    style.map("AIH.Horizontal.TScrollbar", background=[("active", "#2f3748")])


# ---------------------------------------------------------------------------
# Utilidades de widgets
# ---------------------------------------------------------------------------

def _button(
    parent: tk.Misc,
    text: str,
    command,
    kind: str = "ghost",
    height: int = 34,
    font_size: int = 10,
    bold: bool = False,
) -> tk.Button:
    palettes = {
        "primary": (ACCENT, "#ffffff", ACCENT_HOVER, "#ffffff"),
        "ghost": (PANEL_2, TEXT, PANEL_3, TEXT),
        "soft": (ACCENT_SOFT, "#cdc2ff", "#342b63", "#e2dbff"),
        "link": (PANEL, ACCENT, PANEL, ACCENT_HOVER),
        "danger": (PANEL, RED, PANEL, "#ff8f8f"),
    }
    bg, fg, hover_bg, hover_fg = palettes.get(kind, palettes["ghost"])
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=hover_bg,
        activeforeground=hover_fg,
        disabledforeground=DIM,
        relief="flat",
        bd=0,
        highlightthickness=0,
        cursor="hand2",
        font=(FONT, font_size, "bold" if bold else "normal"),
        padx=10,
        pady=7 if height >= 32 else (5 if height >= 28 else 2),
    )
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover_bg, fg=hover_fg) if str(btn["state"]) != "disabled" else None)
    btn.bind("<Leave>", lambda _e: btn.configure(bg=bg, fg=fg) if str(btn["state"]) != "disabled" else None)
    btn._normal_bg = bg  # type: ignore[attr-defined]
    btn._normal_fg = fg  # type: ignore[attr-defined]
    return btn


def _set_enabled(btn: tk.Button, enabled: bool) -> None:
    btn.configure(state="normal" if enabled else "disabled")
    if enabled:
        btn.configure(bg=getattr(btn, "_normal_bg", PANEL_2), fg=getattr(btn, "_normal_fg", TEXT))
    else:
        btn.configure(bg=PANEL_2, fg=DIM)


def _bind_recursive(widget: tk.Misc, callback) -> None:
    widget.bind("<Button-1>", lambda _e: callback())
    for child in widget.winfo_children():
        _bind_recursive(child, callback)


def _sep(parent: tk.Misc, color: str = BORDER) -> tk.Frame:
    frame = tk.Frame(parent, bg=color, height=1)
    return frame


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class MainWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        _pick_fonts(self)
        _setup_style(self)

        self.logged_user = None
        try:
            from aihub.web import users as web_users
            if web_users.has_users() and "--smoke" not in sys.argv and DESKTOP_LOGIN_ENABLED:
                legacy_cfg = config.load_config()
                user = self._prompt_login()
                if user is None:
                    self.destroy()
                    return
                self.logged_user = user
                web_users.activate(user["id"])
                self._seed_account_config(legacy_cfg)
        except Exception:
            pass
        self.cfg = config.load_config()
        config.ensure_dirs()
        custom.register(self.cfg)
        self.favorites = set(self.cfg.get("favorite_models") or [])

        self.q: queue.Queue = queue.Queue()
        self.refreshing = False
        self.busy = False
        self.cancel_event = threading.Event()
        self.proc = None
        self.last_path: Path | None = None
        self.touched_files: list[str] = []
        self.attachment: Path | None = None
        self.preview_photo = None
        self.history: list[dict] = []
        self.conversations: list[dict] = []
        self.current_conversation_id: str | None = None
        self._loaded_conversation: dict | None = None
        self.history_key: tuple[str, str] | None = None
        self._pending_history = False
        self.statuses: dict = {}
        self.access: dict = {}
        self._access_prompted = False
        self.catalogs: dict[str, list[catalog.Model]] = {}
        self.catalog_errors: dict[str, str] = {}
        self.visible: list[catalog.Model] = []
        self.selected: catalog.Model | None = None
        self._search_placeholder = "Buscar modelo, id o etiqueta…"
        self._placeholder_active = True

        self.provider = self.cfg.get("last_provider") or "opencode"
        self.category = catalog.tab_of(self.cfg.get("last_category") or "code")
        if self.provider not in catalog.PROVIDER_BY_ID:
            self.provider = "opencode"
        if self.category not in ("code", "media"):
            self.category = "code"

        self.title(f"AI Hub v{__version__} · chat con modelos de IA")
        width = min(1440, self.winfo_screenwidth() - 60)
        height = min(880, self.winfo_screenheight() - 90)
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 2 - 10)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(1040, 640)
        self.after(80, self._maximize)
        self.configure(bg=BG)

        self._make_icon()
        self._build_header()
        self._build_body()
        self._build_statusbar()
        self._load_cache_into_memory()
        self._ensure_visible_category()
        self._update_statuses_ui()
        self._render_all()
        self._restore_conversation_model()
        self._load_conversation_state()
        self._render_loaded_conversation()

        self.after(60, self._drain_queue)
        self.after(120, self._dark_titlebar)
        self.after(200, self._startup)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.report_callback_exception = self._report_callback_error
        self.bind("<Control-f>", lambda _e: self._focus_search())
        self.bind("<F5>", lambda _e: self._refresh_clicked())

    # -- construcción -------------------------------------------------------

    def _make_icon(self) -> None:
        icon = tk.PhotoImage(width=64, height=64)
        icon.put(ACCENT, to=(0, 0, 64, 64))
        icon.put("#ffffff", to=(28, 12, 36, 52))
        icon.put("#ffffff", to=(12, 28, 52, 36))
        icon.put(ACCENT, to=(30, 26, 34, 38))
        icon.put(ACCENT, to=(26, 30, 38, 34))
        self.iconphoto(True, icon)
        self._icon_ref = icon
        ico = Path(__file__).resolve().parent.parent / "assets" / "AIHub.ico"
        if ico.exists() and os.name == "nt":
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=PANEL, height=68)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        header.columnconfigure(1, weight=1)
        # Franja de acento superior: identifica la app de un vistazo.
        tk.Frame(header, bg=ACCENT, height=3).place(relx=0, rely=0, relwidth=1, height=3)

        brand = tk.Frame(header, bg=PANEL)
        brand.grid(row=0, column=0, sticky="w", padx=(22, 8), pady=(10, 8))

        logo = tk.Canvas(brand, width=40, height=40, bg=PANEL, highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        logo.create_rectangle(0, 0, 40, 40, fill=ACCENT, outline="")
        logo.create_rectangle(17, 7, 23, 33, fill="#ffffff", outline="")
        logo.create_rectangle(7, 17, 33, 23, fill="#ffffff", outline="")

        text = tk.Frame(brand, bg=PANEL)
        text.pack(side="left")
        title_row = tk.Frame(text, bg=PANEL)
        title_row.pack(anchor="w")
        tk.Label(title_row, text="AI Hub", bg=PANEL, fg=TEXT, font=(FONT, 15, "bold")).pack(side="left")
        # Versión visible y siempre presente: se ve en la cabecera y en la barra de estado.
        self.version_badge = tk.Label(
            title_row, text=f"v{__version__}", bg=ACCENT_SOFT, fg="#cdc2ff",
            font=(FONT, 8, "bold"), padx=7, pady=1,
        )
        self.version_badge.pack(side="left", padx=(10, 0), pady=(4, 0))
        tk.Label(
            text, text="Chat y catálogo de modelos de IA", bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w",
        ).pack(anchor="w")

        right = tk.Frame(header, bg=PANEL)
        right.grid(row=0, column=2, sticky="e", padx=(0, 22))

        self.header_chip = tk.Label(
            right,
            text="·  detectando…",
            bg=PANEL_2,
            fg=MUTED,
            font=(FONT, 9),
            padx=10,
            pady=5,
            cursor="hand2",
        )
        self.header_chip.pack(side="left", padx=(0, 12))
        self.header_chip.bind("<Button-1>", lambda _e: self._open_access_dialog())
        self.header_chip.bind(
            "<Enter>", lambda _e: self.header_chip.configure(fg=TEXT)
        )
        self.header_chip.bind(
            "<Leave>", lambda _e: self._paint_header_chip()
        )

        tk.Frame(right, bg=BORDER, width=1, height=26).pack(side="left", padx=(0, 12))

        self.btn_refresh = _button(right, "⟳  Actualizar", self._refresh_clicked, kind="ghost", height=34)
        self.btn_refresh.pack(side="left", padx=(0, 8))

        self.btn_settings = _button(right, "⚙  Ajustes", self._open_settings, kind="primary", height=34, bold=True)
        self.btn_settings.pack(side="left")
        if getattr(self, "logged_user", None):
            user_chip = tk.Label(right, text=f"👤 {self.logged_user['name']}", bg=PANEL_2, fg=TEXT, font=(FONT, 9), padx=10, pady=5)
            user_chip.pack(side="left", padx=(8, 0))

        self._update_project_button()

        tk.Frame(header, bg=BORDER, height=1).place(relx=0, rely=1, anchor="sw", relwidth=1, height=1)

    def _build_body(self) -> None:
        body = tk.Frame(self, bg=BG)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, minsize=520, weight=1)
        body.columnconfigure(2, minsize=270, weight=0)
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._body = body

        # Columna izquierda de ancho fijo: al añadir proveedores no crece ni
        # empuja a la conversación. `grid_propagate(False)` impide que el
        # contenido (tarjetas, nombres largos) dicte el ancho de la columna.
        self.sidebar_width = 400
        self.sidebar_collapsed = False
        self.sidebar_holder = tk.Frame(body, bg=BG, width=self.sidebar_width)
        self.sidebar_holder.grid(row=0, column=0, sticky="nsew")
        self.sidebar_holder.grid_propagate(False)
        self.sidebar_holder.rowconfigure(0, weight=1)
        self.sidebar_holder.columnconfigure(0, weight=1)

        # Rail estrecho que queda visible cuando la columna está plegada.
        self.sidebar_rail = tk.Frame(body, bg=BG, width=38, cursor="hand2")
        self.sidebar_rail.grid(row=0, column=0, sticky="ns")
        self.sidebar_rail.grid_propagate(False)
        self.sidebar_rail.pack_propagate(False)
        rail_open = tk.Label(
            self.sidebar_rail,
            text="▶",
            bg=PANEL,
            fg=ACCENT,
            font=(FONT, 10, "bold"),
            cursor="hand2",
        )
        rail_open.pack(fill="x", pady=(14, 8))
        rail_label = tk.Label(
            self.sidebar_rail,
            text="\n".join("MODELOS"),
            bg=BG,
            fg=DIM,
            font=(FONT, 8, "bold"),
            cursor="hand2",
        )
        rail_label.pack()
        _bind_recursive(self.sidebar_rail, lambda: self._toggle_sidebar(False))
        self.sidebar_rail.grid_remove()

        self._build_sidebar(self.sidebar_holder)  # proveedor y catálogo de modelos
        self._build_center(body)   # conversación: el panel principal
        self._build_detail(body)   # ficha del modelo, acciones y archivos

    def _toggle_sidebar(self, collapse: bool | None = None) -> None:
        """Pliega o despliega la columna de proveedores y modelos."""
        if collapse is None:
            collapse = not self.sidebar_collapsed
        self.sidebar_collapsed = bool(collapse)
        if self.sidebar_collapsed:
            self.sidebar_holder.grid_remove()
            self.sidebar_rail.grid()
        else:
            self.sidebar_rail.grid_remove()
            self.sidebar_holder.grid()

    def _build_sidebar(self, parent: tk.Misc) -> None:
        side = tk.Frame(parent, bg=BG, padx=12, pady=12)
        side.grid(row=0, column=0, sticky="nsew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        side.columnconfigure(0, weight=1)
        side.rowconfigure(5, weight=1)

        head = tk.Frame(side, bg=BG)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="PROVEEDORES", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        collapse = tk.Label(
            head,
            text="◀",
            bg=BG,
            fg=DIM,
            font=(FONT, 9, "bold"),
            cursor="hand2",
            padx=4,
        )
        collapse.grid(row=0, column=1, sticky="e")
        collapse.bind("<Button-1>", lambda _e: self._toggle_sidebar(True))
        collapse.bind("<Enter>", lambda _e: collapse.configure(fg=TEXT))
        collapse.bind("<Leave>", lambda _e: collapse.configure(fg=DIM))

        # Tarjetas de proveedor en una zona desplazable con altura limitada:
        # añadir proveedores hace scroll, no crece la columna.
        cards_wrap = tk.Frame(side, bg=BG, height=140)
        cards_wrap.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        cards_wrap.grid_propagate(False)
        cards_wrap.columnconfigure(0, weight=1)
        cards_wrap.rowconfigure(0, weight=1)
        self.cards_wrap = cards_wrap

        self.cards_canvas = tk.Canvas(
            cards_wrap, bg=BG, highlightthickness=0, bd=0, height=140
        )
        self.cards_canvas.grid(row=0, column=0, sticky="nsew")
        self.cards_scroll = ttk.Scrollbar(
            cards_wrap,
            orient="vertical",
            command=self.cards_canvas.yview,
            style="AIH.Vertical.TScrollbar",
        )
        self.cards_canvas.configure(yscrollcommand=self.cards_scroll.set)

        grid = tk.Frame(self.cards_canvas, bg=BG)
        grid.columnconfigure(0, weight=1)
        self.cards_window = self.cards_canvas.create_window((0, 0), window=grid, anchor="nw")
        self.cards_canvas.bind("<Configure>", self._on_cards_canvas_configure)
        grid.bind("<Configure>", lambda _e: self._sync_cards_size())

        self.card_grid = grid
        self._render_provider_cards()

        # Categorías
        cat_row = tk.Frame(side, bg=BG)
        cat_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.cat_buttons: dict[str, tk.Button] = {}
        for cat_id, label in catalog.CATEGORIES:
            btn = tk.Button(
                cat_row,
                text=label,
                command=lambda cid=cat_id: self._select_category(cid),
                bg=PANEL_2,
                fg=MUTED,
                activebackground=PANEL_2,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                highlightthickness=0,
                cursor="hand2",
                font=(FONT, 9, "bold"),
                padx=10,
                pady=5,
            )
            btn.pack(side="left", padx=(0, 5))
            self.cat_buttons[cat_id] = btn

        # Buscador y filtros
        toolbar = tk.Frame(side, bg=BG)
        toolbar.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        toolbar.columnconfigure(1, weight=1)

        search_box = tk.Frame(toolbar, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
        search_box.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        tk.Label(search_box, text="⌕", bg=INPUT, fg=DIM, font=(FONT, 12)).pack(side="left", padx=(8, 2))
        self.search_var = tk.StringVar()
        self.search_entry = tk.Entry(
            search_box,
            textvariable=self.search_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(FONT, 9),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(2, 8), pady=7)
        self.search_entry.insert(0, self._search_placeholder)
        self.search_entry.configure(fg=DIM)
        self.search_entry.bind("<FocusIn>", self._search_focus_in)
        self.search_entry.bind("<FocusOut>", self._search_focus_out)
        self.search_entry.bind("<KeyPress>", self._search_key)
        self.search_var.trace_add("write", lambda *_: self._on_search_change())

        self.filter_var = tk.StringVar(value="Todos")
        self.filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=["Todos", "Gratis", "De pago", "Favoritos"],
            state="readonly",
            width=9,
            font=(FONT, 9),
        )
        self.filter_box.grid(row=1, column=0, sticky="ew", padx=(0, 4))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self._render_list())

        self.sort_var = tk.StringVar(value="Precio ↑")
        self.sort_box = ttk.Combobox(
            toolbar,
            textvariable=self.sort_var,
            values=["Precio ↑", "Precio ↓", "Nombre", "Contexto ↓"],
            state="readonly",
            width=11,
            font=(FONT, 9),
        )
        self.sort_box.grid(row=1, column=1, sticky="ew", padx=(4, 0))
        self.sort_box.bind("<<ComboboxSelected>>", lambda _e: self._render_list())

        self.model_box = ttk.Combobox(toolbar, state="readonly", font=(FONT, 9))
        self.model_box.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.model_box.bind("<<ComboboxSelected>>", self._on_model_box_select)

        # Título de sección de la tabla, con el número de modelos a la derecha
        models_head = tk.Frame(side, bg=BG)
        models_head.grid(row=4, column=0, sticky="ew", pady=(0, 6))
        models_head.columnconfigure(0, weight=1)
        tk.Label(models_head, text="MODELOS", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=0, column=0, sticky="w")
        self.count_label = tk.Label(models_head, text="", bg=BG, fg=MUTED, font=(FONT, 8, "bold"), anchor="e")
        self.count_label.grid(row=0, column=1, sticky="e")

        # Tabla de modelos
        table_frame = tk.Frame(side, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        table_frame.grid(row=5, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.table_frame = table_frame

        self.tree = ttk.Treeview(
            table_frame,
            columns=("name", "price"),
            show="headings",
            style="AIH.Treeview",
            selectmode="browse",
        )
        self.tree.heading("name", text="MODELO", anchor="w")
        self.tree.heading("price", text="PRECIO (USD / 1M)", anchor="e")
        self.tree.column("name", width=320, minwidth=200, stretch=False)
        self.tree.column("price", width=170, minwidth=120, stretch=False, anchor="e")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.tag_configure("free", foreground=GREEN)
        self.tree.tag_configure("paid", foreground=TEXT)
        self.tree.tag_configure("unknown", foreground=MUTED)
        self.tree.tag_configure("local", foreground=CYAN)

        scroll = ttk.Scrollbar(
            table_frame, orient="vertical", command=self.tree.yview, style="AIH.Vertical.TScrollbar"
        )
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        hscroll = ttk.Scrollbar(
            table_frame, orient="horizontal", command=self.tree.xview, style="AIH.Horizontal.TScrollbar"
        )
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=hscroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", lambda _e: self._primary_action())
        self.tree.bind("<Return>", lambda _e: self._primary_action())

        self.empty_box = tk.Frame(table_frame, bg=PANEL)
        self.empty_label = tk.Label(
            self.empty_box,
            text="",
            bg=PANEL,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=280,
            justify="center",
        )
        self.empty_label.pack()
        self.empty_actions = tk.Frame(self.empty_box, bg=PANEL)
        self.empty_actions.pack(pady=(10, 0))

        legend = tk.Frame(side, bg=BG)
        legend.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        legend.columnconfigure(0, weight=1)
        self.legend_label = tk.Label(
            legend,
            text="Gratis primero · doble clic para usar",
            bg=BG,
            fg=DIM,
            font=(FONT, 8),
            anchor="w",
        )
        self.legend_label.grid(row=0, column=0, sticky="w")

    def _render_provider_cards(self) -> None:
        grid = self.card_grid
        for child in grid.winfo_children():
            child.destroy()
        self.cards = {}
        self.card_status = {}
        self.card_status_dot = {}
        self.card_widgets = {}

        providers = [item for item in catalog.PROVIDERS if self.category in item.get("categories", [])]
        for index, provider in enumerate(providers):
            card = tk.Frame(
                grid,
                bg=PANEL,
                highlightbackground=BORDER,
                highlightthickness=1,
                cursor="hand2",
                padx=10,
                pady=6,
            )
            card.grid(row=index, column=0, sticky="ew", pady=(0, 4))
            card.columnconfigure(1, weight=1)

            glyph = tk.Label(
                card, text=provider["glyph"], bg=PANEL, fg=provider["color"], font=(FONT, 15, "bold")
            )
            glyph.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 8))
            name = tk.Label(card, text=provider["name"], bg=PANEL, fg=TEXT, font=(FONT, 10, "bold"), anchor="w")
            name.grid(row=0, column=1, sticky="w")

            status_row = tk.Frame(card, bg=PANEL)
            status_row.grid(row=1, column=1, sticky="w")
            dot = tk.Label(status_row, text="*", bg=PANEL, fg=DIM, font=(FONT, 7))
            dot.pack(side="left", padx=(0, 4))
            status = tk.Label(status_row, text="...", bg=PANEL, fg=MUTED, font=(FONT, 8), anchor="w")
            status.pack(side="left")

            self.cards[provider["id"]] = card
            self.card_status[provider["id"]] = status
            self.card_status_dot[provider["id"]] = dot
            self.card_widgets[provider["id"]] = [card, glyph, name, status_row, dot, status]
            _bind_recursive(card, lambda pid=provider["id"]: self._select_provider(pid))

        add = tk.Frame(
            grid, bg=BG, highlightbackground=BORDER, highlightthickness=1, cursor="hand2", padx=10, pady=5
        )
        add.grid(row=len(providers), column=0, sticky="ew", pady=(0, 4))
        tk.Label(add, text="+  Añadir proveedor", bg=BG, fg=ACCENT, font=(FONT, 9, "bold")).pack(anchor="w")
        _bind_recursive(add, self._open_add_provider)
        self._update_cards()
        self.after_idle(self._sync_cards_size)


    def _on_cards_canvas_configure(self, event) -> None:
        if getattr(self, "cards_canvas", None) is None:
            return
        self.cards_canvas.itemconfigure(self.cards_window, width=event.width)
        self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all") or (0, 0, 0, 0))

    def _sync_cards_size(self) -> None:
        if getattr(self, "cards_canvas", None) is None:
            return
        grid = getattr(self, "card_grid", None)
        wrap = getattr(self, "cards_wrap", None)
        if grid is None or wrap is None:
            return
        try:
            needed = grid.winfo_reqheight()
        except tk.TclError:
            return
        if needed <= 0:
            return
        limit = 140  # proveedores ocupan menos; a partir de aquí, scroll
        target = max(58, min(needed, limit))
        try:
            current = int(float(wrap.cget("height")))
        except (TypeError, ValueError, tk.TclError):
            current = -1
        if current != target:
            wrap.configure(height=target)
            self.cards_canvas.configure(height=target)
        self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all") or (0, 0, 0, 0))
        if needed > limit:
            self.cards_scroll.grid(row=0, column=1, sticky="ns")
        else:
            self.cards_scroll.grid_remove()

    def _build_center(self, parent: tk.Misc) -> None:
        """Panel principal: conversación con el modelo y compositor de entrada."""
        center = tk.Frame(parent, bg=BG, padx=4, pady=12)
        center.grid(row=0, column=1, sticky="nsew")
        center.rowconfigure(1, weight=1)
        center.rowconfigure(3, minsize=150)
        center.columnconfigure(0, weight=1)

        # Cabecera de la conversación
        head = tk.Frame(center, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=18, pady=12)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        tk.Frame(head, bg=ACCENT, width=3).place(x=0, y=0, relheight=1)
        titles = tk.Frame(head, bg=PANEL)
        titles.grid(row=0, column=0, sticky="ew")
        self.conv_title = tk.Label(
            titles, text="Elige un modelo", bg=PANEL, fg=TEXT, font=(FONT, 13, "bold"), anchor="w"
        )
        self.conv_title.pack(anchor="w")
        self.conv_sub = tk.Label(titles, text="", bg=PANEL, fg=MUTED, font=(FONT, 9), anchor="w")
        self.conv_sub.pack(anchor="w")
        btns = tk.Frame(head, bg=PANEL)
        btns.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.btn_clear = _button(
            btns, "＋  Nuevo chat", lambda: self._new_chat(reset_prompt=True), kind="ghost", height=32, font_size=9
        )
        self.btn_clear.pack(side="right")
        self.btn_history = _button(
            btns, "Historial", self._open_history, kind="ghost", height=32, font_size=9
        )
        self.btn_history.pack(side="right", padx=(0, 6))

        # Conversación (la salida)
        conv = tk.Frame(center, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
        conv.grid(row=1, column=0, sticky="nsew", pady=(10, 10))
        conv.rowconfigure(0, weight=1)
        conv.columnconfigure(0, weight=1)

        self.output = tk.Text(
            conv,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            wrap="word",
            font=(FONT, 10),
            padx=22,
            pady=14,
            spacing1=2,
            spacing3=2,
            state="disabled",
            cursor="arrow",
        )
        self.output.grid(row=0, column=0, sticky="nsew")
        out_scroll = ttk.Scrollbar(
            conv, orient="vertical", command=self.output.yview, style="AIH.Vertical.TScrollbar"
        )
        out_scroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=out_scroll.set)
        self.output.bind("<Control-c>", self._copy_output)
        self.output.bind("<Control-C>", self._copy_output)
        self.output.bind("<Control-a>", self._select_all_output)
        self.output.tag_configure("label_user", foreground=MUTED, font=(FONT, 8, "bold"), spacing1=14, spacing3=3)
        self.output.tag_configure(
            "user", background=PANEL_3, foreground=TEXT, lmargin1=70, lmargin2=70, rmargin=10,
            spacing1=3, spacing3=3,
        )
        self.output.tag_configure("user_meta", foreground=CYAN, font=(FONT, 8), lmargin1=70)
        self.output.tag_configure("label_model", foreground=ACCENT, font=(FONT, 8, "bold"), spacing1=16, spacing3=3)
        self.output.tag_configure("head", foreground=TEXT, font=(FONT, 12, "bold"), spacing3=4)
        self.output.tag_configure("prompt", foreground=ACCENT, font=(FONT, 9, "bold"))
        self.output.tag_configure("cmd", foreground="#c8d1e6", font=(MONO, 9))
        self.output.tag_configure("dim", foreground=DIM, font=(FONT, 9))
        self.output.tag_configure("ok", foreground=GREEN, font=(FONT, 8, "bold"), spacing1=8)
        self.output.tag_configure("err", foreground=RED)
        self.output.tag_configure("tool", foreground=AMBER, font=(MONO, 9))

        self.preview = tk.Label(center, bg=BG, bd=0, highlightthickness=0)
        self.preview.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self.preview.grid_remove()

        # Compositor (la entrada)
        comp = tk.Frame(center, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=10)
        comp.grid(row=3, column=0, sticky="ew")
        comp.columnconfigure(0, weight=1)

        self.attach_bar = tk.Frame(comp, bg=PANEL)
        self.attach_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.attach_bar.columnconfigure(0, weight=1)
        self.attach_label = tk.Label(self.attach_bar, text="", bg=PANEL, fg=CYAN, font=(FONT, 8), anchor="w")
        self.attach_label.grid(row=0, column=0, sticky="w")
        self.btn_unattach = _button(
            self.attach_bar, "quitar", self._clear_attachment, kind="link", height=0, font_size=8
        )
        self.btn_unattach.grid(row=0, column=1, sticky="e")
        self.attach_bar.grid_remove()

        self.prompt = tk.Text(
            comp,
            height=4,
            width=1,
            bg=INPUT,
            fg=DIM,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            wrap="word",
            font=(FONT, 10),
            padx=10,
            pady=8,
        )
        self.prompt.grid(row=1, column=0, sticky="ew")
        self._prompt_placeholder = "Escribe tu consulta…"
        self._prompt_placeholder_active = True
        self.prompt.insert("1.0", self._prompt_placeholder)
        self.prompt.bind("<FocusIn>", self._prompt_focus_in)
        self.prompt.bind("<KeyPress>", self._prompt_key)
        self.prompt.bind("<Return>", self._on_prompt_enter)
        self.prompt.bind("<Control-Return>", lambda _e: (self._send(), "break")[1])

        bottom = tk.Frame(comp, bg=PANEL)
        bottom.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        bottom.columnconfigure(0, weight=0)
        bottom.columnconfigure(1, weight=1)

        self.btn_attach = _button(bottom, "Adjuntar…", self._pick_attachment, kind="ghost", height=30, font_size=9)
        self.btn_attach.grid(row=1, column=0, sticky="w")

        self.tools_var = tk.BooleanVar(value=True)
        self.tools_check = tk.Checkbutton(
            bottom,
            text="Leer y escribir archivos",
            variable=self.tools_var,
            command=self._on_tools_toggle,
            bg=PANEL,
            fg=TEXT,
            activebackground=PANEL,
            activeforeground=TEXT,
            selectcolor=PANEL_3,
            disabledforeground=DIM,
            font=(FONT, 9),
            bd=0,
            highlightthickness=0,
            anchor="w",
            cursor="hand2",
        )
        self.tools_check.grid(row=1, column=1, sticky="w", padx=(12, 0))

        self.send_hint = tk.Label(
            bottom, text="", bg=PANEL, fg=DIM, font=(FONT, 8), anchor="w", justify="left"
        )
        self.send_hint.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))

        self.btn_stop = _button(bottom, "Detener", self._stop, kind="danger", height=32, font_size=9)
        self.btn_stop.grid(row=1, column=2, sticky="e", padx=(0, 8))
        self.btn_send = _button(bottom, "Enviar  ▸", self._send, kind="primary", height=32, bold=True)
        self.btn_send.grid(row=1, column=3, sticky="e")

        _set_enabled(self.btn_send, False)
        _set_enabled(self.btn_stop, False)

    def _build_detail(self, parent: tk.Misc) -> None:
        wrap = tk.Frame(parent, bg=BG, pady=12)
        wrap.grid(row=0, column=2, sticky="nsew", padx=(4, 12))
        wrap.columnconfigure(0, weight=1)
        wrap.rowconfigure(1, weight=1)

        # Ficha del modelo
        info = tk.Frame(wrap, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=12)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(0, weight=1)

        chips = tk.Frame(info, bg=PANEL)
        chips.grid(row=0, column=0, sticky="w")
        self.chip_cat = tk.Label(chips, text="", bg=PANEL_3, fg=MUTED, font=(FONT, 8, "bold"), padx=7, pady=2)
        self.chip_cat.pack(side="left", padx=(0, 5))
        self.chip_provider = tk.Label(chips, text="", bg=PANEL_3, fg=MUTED, font=(FONT, 8, "bold"), padx=7, pady=2)
        self.chip_provider.pack(side="left", padx=(0, 5))
        self.chip_free = tk.Label(chips, text="", bg=PANEL_3, fg=GREEN, font=(FONT, 8, "bold"), padx=7, pady=2)
        self.chip_free.pack(side="left")

        self.detail_name = tk.Label(
            info, text="Selecciona un modelo", bg=PANEL, fg=TEXT, font=(FONT, 12, "bold"),
            wraplength=230, justify="left", anchor="w",
        )
        self.detail_name.grid(row=1, column=0, sticky="ew", pady=(8, 2))

        id_row = tk.Frame(info, bg=PANEL)
        id_row.grid(row=2, column=0, sticky="ew")
        self._id_row = id_row
        id_row.columnconfigure(0, weight=1)
        self.detail_id = tk.Label(
            id_row, text="", bg=PANEL, fg=DIM, font=(MONO, 8), wraplength=190, justify="left", anchor="w"
        )
        self.detail_id.grid(row=0, column=0, sticky="w")
        self.btn_copy_id = _button(id_row, "copiar", self._copy_id, kind="link", height=0, font_size=8)
        self.btn_copy_id.grid(row=0, column=1, sticky="e")
        self.btn_favorite = _button(id_row, "☆ Favorito", self._toggle_favorite, kind="link", height=0, font_size=8)
        self.btn_favorite.grid(row=0, column=2, sticky="e", padx=(6, 0))

        self.detail_price = tk.Label(info, text="", bg=PANEL, fg=ACCENT, font=(FONT, 12, "bold"), anchor="w")
        self.detail_price.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.detail_price_sub = tk.Label(
            info, text="", bg=PANEL, fg=MUTED, font=(FONT, 8), wraplength=230, justify="left", anchor="w"
        )
        self.detail_price_sub.grid(row=4, column=0, sticky="ew", pady=(1, 4))
        self.detail_desc = tk.Label(
            info, text="", bg=PANEL, fg=MUTED, font=(FONT, 9), wraplength=230,
            justify="left", anchor="nw", height=2,
        )
        self.detail_desc.grid(row=5, column=0, sticky="ew", pady=(0, 8))

        self.usage_box = tk.Frame(info, bg=PANEL_3, padx=10, pady=8)
        self.usage_box.grid(row=6, column=0, sticky="ew", pady=(0, 8))
        self.usage_box.columnconfigure(0, weight=1)
        tk.Label(self.usage_box, text="CONSUMO", bg=PANEL_3, fg=DIM, font=(FONT, 7, "bold"), anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.usage_model = tk.Label(
            self.usage_box, text="", bg=PANEL_3, fg=TEXT, font=(FONT, 8), anchor="w", justify="left", wraplength=220
        )
        self.usage_model.grid(row=1, column=0, sticky="ew", pady=(2, 4))
        self.usage_quota = tk.Label(
            self.usage_box, text="", bg=PANEL_3, fg=MUTED, font=(FONT, 8), anchor="w", justify="left", wraplength=220
        )
        self.usage_quota.grid(row=2, column=0, sticky="ew")

        actions = tk.Frame(info, bg=PANEL)
        actions.grid(row=7, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.btn_primary = _button(actions, "Usar modelo", self._primary_action, kind="primary", height=32, bold=True)
        self.btn_primary.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        self.btn_secondary = _button(actions, "Copiar comando", self._secondary_action, kind="ghost", height=28, font_size=9)
        self.btn_secondary.grid(row=1, column=0, sticky="ew", padx=(0, 3))
        self.btn_third = _button(actions, "Copiar ID", self._third_action, kind="ghost", height=28, font_size=9)
        self.btn_third.grid(row=1, column=1, sticky="ew", padx=(3, 0))

        # Archivos del proyecto
        files = tk.Frame(wrap, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=12)
        files.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        files.columnconfigure(0, weight=1)
        files.rowconfigure(2, weight=1)

        head = tk.Frame(files, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew")
        head.columnconfigure(0, weight=1)
        tk.Label(head, text="ARCHIVOS DEL PROYECTO", bg=PANEL, fg=DIM, font=(FONT, 8, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.btn_open_folder = _button(head, "abrir carpeta", self._open_project_folder, kind="link", height=0, font_size=8)
        self.btn_open_folder.grid(row=0, column=1, sticky="e")
        self.files_title = tk.Label(files, text="", bg=PANEL, fg=TEXT, font=(FONT, 9, "bold"), anchor="w")
        self.files_title.grid(row=1, column=0, sticky="ew", pady=(4, 6))

        list_frame = tk.Frame(files, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.files_list = tk.Listbox(
            list_frame,
            bg=INPUT,
            fg=TEXT,
            selectbackground=ACCENT_SOFT,
            selectforeground="#ffffff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            activestyle="none",
            font=(MONO, 9),
        )
        self.files_list.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        files_scroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.files_list.yview, style="AIH.Vertical.TScrollbar"
        )
        files_scroll.grid(row=0, column=1, sticky="ns")
        self.files_list.configure(yscrollcommand=files_scroll.set)
        self.files_list.bind("<Double-1>", lambda _e: self._open_selected_file())
        self.files_list.bind("<Return>", lambda _e: self._open_selected_file())
        self._files_paths: list[Path] = []

        self.touched_label = tk.Label(
            files, text="", bg=PANEL, fg=GREEN, font=(FONT, 8), anchor="w", justify="left", wraplength=230
        )
        self.touched_label.grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self.btn_open_file = _button(files, "Abrir último resultado", self._open_last_file, kind="link", height=0, font_size=8)
        self.btn_open_file.grid(row=4, column=0, sticky="w", pady=(4, 0))

        def _resize(event) -> None:
            width = max(200, event.width - 36)
            for widget in (
                self.detail_name, self.detail_price_sub, self.detail_desc, self.touched_label,
                self.usage_model, self.usage_quota,
            ):
                widget.configure(wraplength=width)
            self.detail_id.configure(wraplength=max(150, width - 50))

        info.bind("<Configure>", _resize)

        _set_enabled(self.btn_primary, False)
        _set_enabled(self.btn_secondary, False)
        _set_enabled(self.btn_third, False)
        _set_enabled(self.btn_open_file, False)

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, height=30)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(0, weight=1)
        tk.Frame(self, bg=BORDER, height=1).grid(row=2, column=0, sticky="new")
        self.status_left = tk.Label(
            bar, text="Listo", bg=PANEL, fg=MUTED, font=(FONT, 8), anchor="w"
        )
        self.status_left.grid(row=0, column=0, sticky="w", padx=16, pady=4)

        right = tk.Frame(bar, bg=PANEL)
        right.grid(row=0, column=1, sticky="e", padx=16)
        self.status_right = tk.Label(right, text="", bg=PANEL, fg=DIM, font=(FONT, 8), anchor="e")
        self.status_right.pack(side="left", padx=(0, 10))
        self.version_label = tk.Label(
            right, text=f"AI Hub v{__version__}", bg=ACCENT_SOFT, fg="#cdc2ff",
            font=(FONT, 8, "bold"), padx=7, pady=1,
        )
        self.version_label.pack(side="left")

    # -- estado inicial -----------------------------------------------------

    def _startup(self) -> None:
        self._detect_statuses()
        self._update_cache_label()
        if self.cfg.get("auto_refresh", True):
            self._refresh(None, manual=False)
        else:
            self._update_statuses_ui()

    def _all_provider_ids(self) -> list[str]:
        return [item["id"] for item in catalog.PROVIDERS]

    def _is_api(self, pid: str) -> bool:
        """Proveedores que se usan por API con clave: OpenRouter y los añadidos por el usuario."""
        return pid == "openrouter" or bool(catalog.PROVIDER_BY_ID.get(pid, {}).get("custom"))

    def _api_endpoint(self, pid: str) -> tuple[str, str]:
        """(URL base, clave) del proveedor por API."""
        if pid == "openrouter":
            return api.BASE, config.openrouter_key(self.cfg)
        record = custom.get(self.cfg, pid) or {}
        return str(record.get("base") or ""), str(record.get("key") or "")

    def _providers_for(self, category: str) -> list[str]:
        return [item["id"] for item in catalog.PROVIDERS if category in item.get("categories", [])]

    def _load_cache_into_memory(self) -> None:
        for provider in self._all_provider_ids():
            models, _ts = catalog.cached_models(provider)
            if models:
                self.catalogs[provider] = models

    def _detect_statuses(self) -> None:
        def work() -> None:
            statuses = local.status()
            access = api.check_openrouter(config.openrouter_key(self.cfg))
            self.q.put(("access", statuses, access))

        threading.Thread(target=work, daemon=True).start()

    def _ensure_visible_category(self) -> None:
        """Si la categoría guardada no tiene modelos aquí, abre la primera que sí tenga."""
        models = self.catalogs.get(self.provider) or []
        if not models or any(catalog.tab_of(m.category) == self.category for m in models):
            return
        for cat_id, _label in catalog.CATEGORIES:
            if any(catalog.tab_of(m.category) == cat_id for m in models):
                self.category = cat_id
                return

    def _maximize(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

    def _dark_titlebar(self) -> None:
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    # -- refresco -----------------------------------------------------------

    def _refresh_clicked(self) -> None:
        self._refresh(None, manual=True)

    def _refresh(self, providers: list[str] | None, manual: bool = True) -> None:
        if self.refreshing:
            return
        self.refreshing = True
        self.btn_refresh.configure(text="⟳  Actualizando…")
        _set_enabled(self.btn_refresh, False)
        self.status_left.configure(text="Actualizando catálogos…")

        selected_uid = (self.selected.provider, self.selected.uid) if self.selected else None
        include_images = manual and (providers is None or "openrouter" in (providers or []))

        def work() -> None:
            try:
                result = catalog.refresh_all(
                    self.cfg,
                    providers=providers,
                    progress=lambda message: self.q.put(("status", message)),
                    image_prices=include_images,
                )
                for record in custom.records(self.cfg):
                    if providers is not None and record["id"] not in providers:
                        continue
                    result[record["id"]] = self._fetch_custom(record)
                self.q.put(("refresh_done", result, None, selected_uid))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("refresh_done", {}, str(exc), selected_uid))

        threading.Thread(target=work, daemon=True).start()

    def _fetch_custom(self, record: dict) -> dict:
        """Descarga los modelos de un proveedor añadido. Si falla, conserva la caché."""
        pid = record["id"]
        try:
            models = custom.fetch(record)
            catalog.store_models(pid, models)
            return {"models": models, "error": None}
        except Exception as exc:  # noqa: BLE001
            old, _ts = catalog.cached_models(pid)
            return {"models": old, "error": str(exc)}

    def _apply_refresh(self, result: dict, error: str | None, selected_uid) -> None:
        self.refreshing = False
        self.btn_refresh.configure(text="⟳  Actualizar")
        _set_enabled(self.btn_refresh, True)
        if error:
            self._out(f"\n⚠ No se pudo actualizar: {error}\n", "err")
            self.status_left.configure(text=f"Error al actualizar: {error[:120]}")
        else:
            self.catalog_errors = {}
            selected_provider = self.selected.provider if self.selected else None
            for provider, payload in result.items():
                models = payload.get("models") or []
                if models:
                    self.catalogs[provider] = models
                if payload.get("error"):
                    self.catalog_errors[provider] = str(payload["error"])
                    # Solo lo escribimos en la conversación si es el proveedor
                    # que estás usando; el resto se indica en su tarjeta y en la
                    # cabecera, para no ensuciar el panel del modelo actual.
                    if provider == selected_provider:
                        self._out(f"\n⚠ Catálogo de {provider}: {payload['error']}\n", "err")
            self.status_left.configure(text="Catálogo actualizado")

        self._render_all()
        if selected_uid:
            for index, model in enumerate(self.visible):
                if (model.provider, model.uid) == selected_uid:
                    self.tree.selection_set(self.tree.get_children()[index])
                    break
        self._update_cache_label()
        self._update_statuses_ui()

    # -- render -------------------------------------------------------------

    def _render_all(self, cards: bool = True) -> None:
        if cards:
            self._render_provider_cards()
        else:
            self._update_cards()
        self._render_categories()
        self._update_cards()
        self._render_list()
        self._update_detail()

    def _render_categories(self) -> None:
        models = self.catalogs.get(self.provider, [])
        for cat_id, label in catalog.CATEGORIES:
            count = sum(1 for model in models if catalog.tab_of(model.category) == cat_id)
            active = cat_id == self.category
            btn = self.cat_buttons[cat_id]
            btn.configure(
                text=f"{label}  {count}",
                bg=ACCENT if active else PANEL_2,
                fg="#ffffff" if active else MUTED,
                activebackground=ACCENT if active else PANEL_3,
            )

    def _select_provider(self, provider: str) -> None:
        if provider == self.provider:
            return
        self.provider = provider
        self.cfg["last_provider"] = provider
        config.update_config(last_provider=provider)
        self.selected = None
        self._render_all(cards=False)
        if provider == "openrouter" and self.category == "media":
            self._ensure_image_prices()

    def _select_category(self, category: str) -> None:
        if category == self.category:
            return
        self.category = category
        self.cfg["last_category"] = category
        config.update_config(last_category=category)
        self.selected = None
        supported = self._providers_for(category)
        if supported and self.provider not in supported:
            self.provider = supported[0]
            self.cfg["last_provider"] = self.provider
            config.update_config(last_provider=self.provider)
        self._render_provider_cards()
        self._render_categories()
        self._render_list()
        self._update_detail()
        if self.provider == "openrouter" and category == "media":
            self._ensure_image_prices()

    def _models_for_view(self) -> list[catalog.Model]:
        query = "" if self._placeholder_active else self.search_var.get()
        if self.filter_var.get() == "Favoritos":
            models = []
            for models_list in self.catalogs.values():
                for model in (models_list or []):
                    if catalog.tab_of(model.category) == self.category and f"{model.provider}:{model.uid}" in self.favorites:
                        models.append(model)
            return catalog.filter_models(models, query, "Todos")
        models = [
            model for model in self.catalogs.get(self.provider, []) if catalog.tab_of(model.category) == self.category
        ]
        return catalog.filter_models(models, query, self.filter_var.get())

    def _sort_mode(self) -> str:
        return {
            "Precio ↑": "price",
            "Precio ↓": "price_desc",
            "Nombre": "name",
            "Contexto ↓": "context",
        }.get(self.sort_var.get(), "price")

    def _on_model_box_select(self, _event=None) -> None:
        if not hasattr(self, "model_box"):
            return
        index = self.model_box.current()
        if 0 <= index < len(self.visible):
            model = self.visible[index]
            if self.selected is None or (self.selected.uid, self.selected.provider) != (model.uid, model.provider):
                self.selected = model
                self._update_detail()

    def _render_list(self) -> None:
        previous = self.selected
        models = self._models_for_view()
        self.visible = catalog.sort_models(models, self._sort_mode())

        for item in self.tree.get_children():
            self.tree.delete(item)

        heading = "PRECIO (USD / 1M)" if self.category == "code" else "PRECIO"
        self.tree.heading("price", text=heading, anchor="e")
        self.legend_label.configure(
            text={
                "price": "Gratis primero, por relevancia · doble clic para usar",
                "price_desc": "Los más caros primero · doble clic para usar el modelo",
                "name": "Orden alfabético · doble clic para usar el modelo",
                "context": "Mayor contexto primero · doble clic para usar el modelo",
            }.get(self._sort_mode(), "Doble clic para usar el modelo")
        )

        for model in self.visible:
            if model.provider == "ollama":
                tag = "local"
            elif model.free:
                tag = "free"
            elif model.effective_price is None:
                tag = "unknown"
            else:
                tag = "paid"
            self.tree.insert(
                "",
                "end",
                values=(model.name, model.price_text()),
                tags=(tag,),
            )

        total = len(
            [m for m in self.catalogs.get(self.provider, []) if catalog.tab_of(m.category) == self.category]
        )
        self.count_label.configure(text=f"{len(self.visible)} de {total} modelos")
        self._update_empty_state(total)
        if hasattr(self, "model_box"):
            self.model_box["values"] = [model.name for model in self.visible]
            if self.selected is not None:
                for index, model in enumerate(self.visible):
                    if (model.uid, model.provider) == (self.selected.uid, self.selected.provider):
                        self.model_box.current(index)
                        break

        if not self.visible:
            self.selected = None
            self._update_detail()
            return

        first = self.tree.get_children()[0]
        current = self.tree.selection()
        wanted = None
        if previous and previous.provider == self.provider:
            for index, model in enumerate(self.visible):
                if model.uid == previous.uid:
                    wanted = self.tree.get_children()[index]
                    break
        if wanted:
            target = wanted
        elif current:
            target = current[0]
        else:
            target = first
        self.tree.selection_set(target)
        self.tree.focus(target)
        self.tree.see(target)
        self._on_tree_select()

    def _update_empty_state(self, total: int) -> None:
        if self.visible:
            self.empty_box.place_forget()
            return

        for child in self.empty_actions.winfo_children():
            child.destroy()

        provider_name = catalog.PROVIDER_BY_ID[self.provider]["name"]
        category_name = dict(catalog.CATEGORIES).get(self.category, self.category).lower()
        query = "" if self._placeholder_active else self.search_entry.get().strip()
        price_filter = self.filter_var.get()
        actions: list[tuple[str, object]] = []

        messages = {
            ("opencode", "media"): "OpenCode no genera imágenes ni vídeo.\nSelecciona OpenRouter para usar FLUX, Veo, Kling y más.",
            ("claude", "media"): "Claude Code es solo código y texto.\nPara imagen y vídeo usa OpenRouter.",
            ("ollama", "media"): "Ollama no genera imágenes ni vídeo.\nPara crear contenido usa OpenRouter. Los modelos de visión están en Programación.",
        }

        if total == 0:
            if self.refreshing:
                text = "Actualizando el catálogo…\nSuele tardar unos segundos."
            else:
                text = messages.get(
                    (self.provider, self.category),
                    "No hay modelos en esta categoría.\nPulsa «Actualizar» para descargar el catálogo.",
                )
                if not self.catalogs.get(self.provider):
                    actions.append(("Descargar catálogo", self._refresh_clicked))
            if not self.refreshing and self.provider == "openrouter" and not config.openrouter_key(self.cfg):
                text = "Configura tu clave de OpenRouter en Ajustes\npara usar la API y ver todos los modelos."
            if self.provider == "openrouter" and self.category == "media" and self.refreshing:
                text = "Actualizando modelos de imagen y vídeo…\nLa primera vez tarda unos segundos."
        elif query and price_filter != "Todos":
            text = f'Ningún modelo coincide con «{query}» y el filtro «{price_filter}».'
            actions.append(("Quitar búsqueda y filtro", self._clear_filters))
        elif query:
            text = f'Ningún modelo coincide con «{query}».\nPrueba con otra palabra.'
            actions.append(("Borrar búsqueda", self._clear_filters))
        elif price_filter == "Gratis":
            text = (
                f"{provider_name} no tiene modelos gratis en {category_name}.\n"
                f"Hay {total} modelos, pero todos son de pago."
            )
            actions.append(("Ver todos", self._clear_filters))
            if self.provider != "opencode" and self.category == "code":
                actions.append(("Gratis de OpenCode", self._show_opencode_free))
        elif price_filter == "De pago":
            text = f"En {category_name.lower()}, todos los modelos de {provider_name} son gratuitos."
            actions.append(("Ver todos", self._clear_filters))
        else:
            text = "No hay modelos que mostrar."

        self.empty_label.configure(text=text)
        for label, command in actions:
            _button(
                self.empty_actions,
                label,
                command,
                kind="primary" if command == self._clear_filters else "ghost",
                height=30,
                font_size=9,
            ).pack(side="left", padx=(0, 6))
        self.empty_box.place(relx=0.5, rely=0.5, anchor="center")

    def _clear_filters(self) -> None:
        self.filter_var.set("Todos")
        self._placeholder_active = True
        self.search_var.set("")
        self.search_entry.delete(0, "end")
        self.search_entry.insert(0, self._search_placeholder)
        self.search_entry.configure(fg=DIM)
        self._render_list()

    def _show_opencode_free(self) -> None:
        self.filter_var.set("Gratis")
        self._select_provider("opencode")
        self._select_category("code")
        self._render_list()

    def _on_tree_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        index = self.tree.index(selection[0])
        if 0 <= index < len(self.visible):
            model = self.visible[index]
            self.selected = model
            self._update_detail()

    def _on_search_change(self) -> None:
        if self._placeholder_active:
            return
        self._render_list()

    def _search_focus_in(self, _event=None) -> None:
        if self._placeholder_active:
            self.search_entry.icursor("end")

    def _search_key(self, event):
        """El texto de ayuda desaparece al empezar a escribir, no al enfocar."""
        if not self._placeholder_active:
            return None
        if event.keysym in (
            "Left",
            "Right",
            "Home",
            "End",
            "Up",
            "Down",
            "Tab",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Caps_Lock",
        ):
            return None
        self._placeholder_active = False
        self.search_entry.delete(0, "end")
        self.search_entry.configure(fg=TEXT)
        if event.char and event.char.isprintable():
            self.search_var.set(event.char)
            self.search_entry.icursor("end")
            return "break"
        return None

    def _search_focus_out(self, _event=None) -> None:
        if not self._placeholder_active and not self.search_entry.get().strip():
            self._placeholder_active = True
            self.search_entry.delete(0, "end")
            self.search_entry.insert(0, self._search_placeholder)
            self.search_entry.configure(fg=DIM)

    def _focus_search(self) -> None:
        self._search_focus_in()
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        self.search_entry.icursor("end")

    # -- detalle ------------------------------------------------------------

    def _file_access(self, model) -> tuple[str, str]:
        """Cómo accede el modelo a los archivos del proyecto.

        Devuelve (modo, texto): modo "agent" (herramientas de AI Hub), "cli"
        (el propio CLI de OpenCode/Claude Code opera en el proyecto) u "off".
        """
        if model is None or model.category != "code":
            return "off", ""
        if model.provider in ("opencode", "claude"):
            return "cli", "archivos vía " + ("OpenCode" if model.provider == "opencode" else "Claude Code")
        if model.provider == "ollama":
            if self._current_project() is None:
                return "off", "sin proyecto: elige uno (Ctrl+P) para leer y escribir archivos"
            if not self.tools_var.get():
                return "off", "acceso a archivos desactivado"
            return "agent", "archivos del proyecto (modelo local)"
        if self._current_project() is None:
            return "off", "sin proyecto: elige uno (Ctrl+P) para leer y escribir archivos"
        if not _supports_tools(model):
            return "off", "este modelo no admite herramientas de archivos"
        if not self.tools_var.get():
            return "off", "acceso a archivos desactivado"
        return "agent", "lee y escribe archivos del proyecto"

    def _tools_active(self, model: catalog.Model | None) -> bool:
        return self._file_access(model)[0] == "agent"

    def _on_tools_toggle(self) -> None:
        self._refresh_tools_hint()
        self._update_conversation_header()

    def _refresh_tools_hint(self) -> None:
        """Interruptor de archivos bajo el compositor, según proveedor, modelo y proyecto."""
        check = getattr(self, "tools_check", None)
        model = self.selected
        if check is None:
            return
        if model is None or model.category != "code":
            check.grid_remove()
            return
        check.grid()
        mode, _reason = self._file_access(model)
        if mode == "cli":
            self.tools_var.set(True)
            check.configure(text="Archivos vía CLI", state="disabled")
            return
        check.configure(text="Leer y escribir archivos")
        can_toggle = self._current_project() is not None and (
            model.provider != "openrouter" or _supports_tools(model)
        )
        check.configure(state="normal" if can_toggle else "disabled")

    def _update_conversation_header(self) -> None:
        model = self.selected
        if model is None:
            self.conv_title.configure(text="Elige un modelo")
            self.conv_sub.configure(text="Proveedor y modelo en la columna izquierda")
            return
        provider = catalog.PROVIDER_BY_ID[model.provider]["name"]
        category = catalog.CATEGORY_LABELS.get(model.category, model.category)
        bits = [provider, category]
        if model.category == "code":
            _mode, reason = self._file_access(model)
            if reason:
                bits.append(reason)
        self.conv_title.configure(text=model.name)
        self.conv_sub.configure(text=" · ".join(bits))

    def _update_detail(self) -> None:
        model = self.selected
        self._refresh_tools_hint()
        self._update_conversation_header()
        if not model:
            self.chip_cat.configure(text="SIN SELECCIÓN")
            self.chip_provider.configure(text="")
            self.chip_free.configure(text="")
            self.detail_name.configure(text="Elige un modelo de la lista", fg=TEXT)
            self.detail_id.configure(text="")
            self.detail_price.configure(text="")
            self.detail_price_sub.configure(text="")
            self.detail_desc.configure(text="")
            self.btn_copy_id.grid_remove()
            self.btn_favorite.grid_remove()
            self.btn_primary.configure(text="Usar modelo")
            self.btn_secondary.configure(text="Copiar comando")
            self.btn_third.configure(text="Copiar ID")
            _set_enabled(self.btn_primary, False)
            _set_enabled(self.btn_secondary, False)
            _set_enabled(self.btn_third, False)
            self.btn_attach.grid_remove()
            self.attach_bar.grid_remove()
            self.btn_send.configure(text="Enviar  ▸")
            self.send_hint.configure(text="Elige un proveedor y un modelo para empezar")
            self._update_usage_label()
            _set_enabled(self.btn_send, False)
            _set_enabled(self.btn_open_file, self.last_path is not None)
            return

        self.btn_copy_id.grid()
        self.btn_favorite.grid()
        if self.selected is not None and f"{self.selected.provider}:{self.selected.uid}" in self.favorites:
            self.btn_favorite.configure(text="★ Favorito")
        else:
            self.btn_favorite.configure(text="☆ Favorito")
        self.detail_name.configure(fg=TEXT)

        provider_name = catalog.PROVIDER_BY_ID[model.provider]["name"]
        self.chip_cat.configure(text=catalog.CATEGORY_LABELS.get(model.category, model.category).upper())
        self.chip_provider.configure(text=provider_name.upper())
        if model.free:
            self.chip_free.configure(text="GRATIS", fg=GREEN)
        elif model.effective_price is None:
            self.chip_free.configure(text="PRECIO N/D", fg=MUTED)
        else:
            self.chip_free.configure(text="DE PAGO", fg=AMBER)

        self.detail_name.configure(text=model.name)
        self.detail_id.configure(text=model.uid)
        self.detail_price.configure(
            text=model.price_text(),
            fg=GREEN if model.free else (ACCENT if model.effective_price is not None else MUTED),
        )
        self.detail_price_sub.configure(text=model.price_detail())
        desc = model.desc or "Sin descripción disponible."
        width = int(self.detail_desc.cget("wraplength") or 230)
        limit = max(60, int(width / 6.4) * 2)
        if len(desc) > limit:
            desc = desc[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
        self.detail_desc.configure(text=desc)

        if model.provider in ("opencode", "claude"):
            self.btn_primary.configure(text="Abrir terminal")
            self.btn_secondary.configure(text="Copiar comando")
            self.btn_third.configure(text="Copiar ID")
        elif model.provider == "ollama":
            if model.is_installed():
                self.btn_primary.configure(text="Abrir chat en terminal")
            else:
                self.btn_primary.configure(text="Descargar modelo")
            self.btn_secondary.configure(text="Copiar comando")
            self.btn_third.configure(text="Ver en Ollama")
        else:
            if model.category == "code":
                self.btn_primary.configure(text="Escribir al modelo")
            elif model.category == "image":
                self.btn_primary.configure(text="Preparar imagen")
            else:
                self.btn_primary.configure(text="Preparar vídeo")
            self.btn_secondary.configure(text="Ver en OpenRouter")
            self.btn_third.configure(text="Copiar ID")

        _set_enabled(self.btn_primary, True)
        _set_enabled(self.btn_secondary, True)
        _set_enabled(self.btn_third, True)
        _set_enabled(self.btn_send, not self.busy)
        _set_enabled(self.btn_open_file, self.last_path is not None)

        if model.category == "image":
            self.btn_send.configure(text="Generar imagen  ▸")
            hint = "Describe la imagen. Ctrl+Enter genera. No hace falta proyecto."
        elif model.category == "video":
            self.btn_send.configure(text="Generar vídeo  ▸")
            hint = "Describe el vídeo. Se cobra por segundo y se avisa antes."
        elif model.provider == "ollama" and not model.is_installed():
            self.btn_send.configure(text="Enviar  ▸")
            hint = "Primero descarga el modelo (botón de la ficha)."
        else:
            self.btn_send.configure(text="Enviar  ▸")
            if self._current_project() is None:
                hint = "Paso 1: elige el proyecto (Ctrl+P) antes de describir la tarea"
            else:
                hint = "Paso 4: describe lo que necesitas · Enter envía · Shift+Enter nueva línea"
        self.send_hint.configure(text=hint)

        if model.category == "code":
            self.btn_attach.grid()
            self._update_attachment_ui()
        else:
            self.btn_attach.grid_remove()
            self.attach_bar.grid_remove()

        self._update_usage_label()
        self._refresh_files()

    def _provider_quota_lines(self, provider: str) -> list[str]:
        """Cuota gratuita y saldo del proveedor, según lo que la app puede consultar."""
        if catalog.PROVIDER_BY_ID.get(provider, {}).get("custom"):
            name = catalog.PROVIDER_BY_ID[provider]["name"]
            return [f"{name} · la app no puede leer tu saldo ni tu cuota: revísalos en la cuenta de {name}."]
        if provider == "openrouter":
            info = self.access.get("openrouter") or {}
            if not config.openrouter_key(self.cfg):
                return ["OpenRouter · falta la clave: añádela en Ajustes para ver tu cuota."]
            if not info.get("ok"):
                return ["OpenRouter · no se pudo consultar la cuota ahora (revisa la clave)."]
            lines = []
            free_used, free_limit = info.get("free_used"), info.get("free_limit")
            if isinstance(free_limit, int):
                lines.append(
                    f"Gratis hoy: {free_used or 0} de {free_limit} peticiones "
                    "(cuenta compartida por todos los modelos :free)."
                )
            credits = info.get("credits")
            if isinstance(credits, (int, float)):
                total = info.get("total_usage")
                spent = f" · gastado ${total:.2f}" if isinstance(total, (int, float)) else ""
                if credits > 0:
                    lines.append(f"Saldo: ${credits:.2f}{spent}.")
                else:
                    lines.append(f"Saldo: $0.00{spent}. Sin saldo, imagen y vídeo fallan.")
            return lines
        if provider == "ollama":
            return ["Ollama · local: gratis e ilimitado, no consume cuota."]
        if provider == "opencode":
            return [
                "OpenCode · la app no puede leer tu cuota de OpenCode. "
                "Los modelos de pago se cobran en tu cuenta de OpenCode."
            ]
        return ["Claude Code · el consumo depende de tu plan de Claude; la app no lo puede leer."]

    def _update_usage_label(self) -> None:
        box = getattr(self, "usage_model", None)
        if box is None:
            return
        model = self.selected
        if model is None:
            box.configure(text="Elige un modelo para ver su consumo.")
            self.usage_quota.configure(text="")
            return
        box.configure(text=usage.describe(usage.get(model.provider, model.uid)))
        self.usage_quota.configure(text="\n".join(self._provider_quota_lines(model.provider)))

    def _refresh_files(self) -> None:
        """Lista el primer nivel del proyecto en el panel derecho."""
        listing = getattr(self, "files_list", None)
        if listing is None:
            return
        listing.delete(0, "end")
        self._files_paths = []
        root = self._current_project()
        if root is None or not root.is_dir():
            self.files_title.configure(text="Sin proyecto")
            listing.insert("end", "  Elige un proyecto (Ctrl+P)")
            listing.configure(fg=DIM)
            self._refresh_touched()
            return
        listing.configure(fg=TEXT)
        self.files_title.configure(text=root.name or str(root))
        for name, is_dir in agent.list_entries(root):
            listing.insert("end", ("▸ " + name + "/") if is_dir else ("  " + name))
            self._files_paths.append(root / name)
        if not self._files_paths:
            listing.insert("end", "  (carpeta vacía)")
        self._refresh_touched()

    def _refresh_touched(self) -> None:
        names = list(getattr(self, "touched_files", []) or [])
        if names:
            self.touched_label.configure(text="Modificados en este chat: " + ", ".join(names))
        else:
            self.touched_label.configure(text="")

    def _open_selected_file(self) -> None:
        selection = self.files_list.curselection()
        if not selection or selection[0] >= len(self._files_paths):
            return
        path = self._files_paths[selection[0]]
        if path.exists():
            local.open_path(path)

    def _open_project_folder(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title="Elegir carpeta para los archivos")
        if not chosen:
            return
        self.cfg["workdir"] = chosen
        try:
            config.update_config(workdir=chosen)
        except Exception:
            pass
        self._refresh_files()
        self._set_status(f"Carpeta: {Path(chosen).name}")

    def _on_prompt_enter(self, event):
        """Enter envía (estilo chat); Shift+Enter inserta un salto de línea."""
        if event.state & 0x0001:
            return None
        self._send()
        return "break"

    def _reset_prompt(self) -> None:
        """Deja el compositor limpio con su texto de ayuda tras enviar."""
        self.prompt.delete("1.0", "end")
        self.prompt.configure(fg=DIM)
        self.prompt.insert("1.0", self._prompt_placeholder)
        self._prompt_placeholder_active = True

    def _prompt_focus_in(self, _event=None) -> None:
        if getattr(self, "_prompt_placeholder_active", False):
            self.prompt.delete("1.0", "end")
            self.prompt.configure(fg=TEXT)
            self._prompt_placeholder_active = False

    def _prompt_key(self, event):
        """El texto de ayuda desaparece al escribir, no al enfocar."""
        if not getattr(self, "_prompt_placeholder_active", False):
            return None
        # No borrar el marcador de posición con atajos de portapapeles o
        # navegación: deja que Tk los procese normalmente.
        if event.state & 0x4 or event.state & 0x8:  # Control o Alt
            if event.keysym.lower() in ("v", "x", "a"):
                self.prompt.delete("1.0", "end")
                self.prompt.configure(fg=TEXT)
                self._prompt_placeholder_active = False
            return None
        if event.keysym in (
            "Left", "Right", "Home", "End", "Up", "Down", "Tab",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
            "BackSpace", "Delete",
        ):
            return None
        self.prompt.delete("1.0", "end")
        self.prompt.configure(fg=TEXT)
        self._prompt_placeholder_active = False
        if event.char and event.char.isprintable():
            self.prompt.insert("1.0", event.char)
            return "break"
        return None

    # -- acciones -----------------------------------------------------------

    def _primary_action(self) -> None:
        model = self.selected
        if not model:
            return
        if model.provider in ("opencode", "claude"):
            self._launch_terminal(model)
        elif model.provider == "ollama":
            if model.is_installed():
                self._launch_terminal(model)
            else:
                self._download_ollama(model)
        else:
            self.prompt.focus_set()

    def _secondary_action(self) -> None:
        model = self.selected
        if not model:
            return
        if model.provider == "openrouter":
            url = f"https://openrouter.ai/{model.uid}"
            if model.category == "image":
                url += "?output_modalities=image"
            local.open_url(url)
            self._set_status(f"Abriendo {url}")
        else:
            self._copy_text(local.command_text(model.provider, model.uid))
            self._set_status("Comando copiado al portapapeles")

    def _third_action(self) -> None:
        model = self.selected
        if not model:
            return
        if model.provider == "ollama" and not model.is_installed():
            local.open_url(f"https://ollama.com/library/{model.uid.split(':')[0]}")
            return
        self._copy_id()

    def _copy_id(self) -> None:
        if self.selected:
            self._copy_text(self.selected.uid)
            self._set_status("ID copiado")

    def _copy_text(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)

    def _launch_terminal(self, model: catalog.Model) -> None:
        if model.provider in ("opencode", "claude") and not self._require_cli(model.provider):
            return
        if model.provider == "ollama" and not self._require_ollama():
            return
        if self._needs_project():
            return
        try:
            local.launch(model.provider, model.uid, self.cfg["workdir"])
            self._out(f"$ {local.command_text(model.provider, model.uid)}\n", "prompt")
            self._set_status("Terminal abierta con el modelo seleccionado")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("No se pudo abrir la terminal", str(exc), parent=self)

    def _download_ollama(self, model: catalog.Model) -> None:
        if not self._require_ollama():
            return
        # Ventana de progreso
        prog = tk.Toplevel(self)
        prog.title("Descargando modelo · Ollama")
        prog.configure(bg=BG)
        prog.transient(self)
        prog.grab_set()
        prog.resizable(False, True)
        width, height = 420, 140
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        prog.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

        info = tk.Frame(prog, bg=BG, padx=20, pady=20)
        info.pack(fill="both", expand=True)
        tk.Label(info, text=f"Descargando «{model.name}»", bg=BG, fg=TEXT, font=(FONT, 10, "bold")).pack(anchor="w")
        tk.Label(info, text=f"Modelo: {model.uid}", bg=BG, fg=MUTED, font=(FONT, 9)).pack(anchor="w", pady=(6, 0))

        bar = ttk.Progressbar(info, orient="horizontal", length=380, mode="determinate")
        bar.pack(pady=(12, 0))
        bar["maximum"] = 100
        bar["value"] = 0

        status = tk.Label(info, text="0 %", bg=BG, fg=MUTED, font=(FONT, 9))
        status.pack()

        def close_and_finish(success: bool, message: str) -> None:
            try:
                prog.destroy()
            except tk.TclError:
                pass
            self._set_status(message)
            if success:
                self._launch_terminal(model)

        # El hilo de descarga no toca widgets de Tk: solo deja mensajes en esta
        # cola y el sondeo (en el hilo principal) actualiza la ventana.
        progress: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                exe = local.which("ollama") or "ollama"
                env = dict(os.environ)
                env.setdefault("NO_COLOR", "1")
                env.setdefault("CLICOLOR", "0")
                # Sin proyecto el workdir está vacío: usa la carpeta personal.
                workdir = str(self.cfg.get("workdir") or "")
                if not Path(workdir).is_dir():
                    workdir = str(Path.home())
                proc = subprocess.Popen(
                    [exe, "pull", model.uid],
                    cwd=workdir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=local.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                for line in proc.stdout:
                    progress.put(("line", line))
                    # Solo se toma un número seguido de % (p. ej. "45%"); sin el símbolo,
                    # los dígitos de los hashes de capa se leerían como progreso.
                    match = PULL_PERCENT_RE.search(line)
                    if match:
                        progress.put(("pct", max(0.0, min(100.0, float(match.group(1))))))
                code = proc.wait()
                if code == 0:
                    progress.put(("done", True, f"Modelo «{model.name}» descargado"))
                else:
                    progress.put(("done", False, f"No se pudo descargar «{model.name}» (código {code})"))
            except Exception as exc:  # noqa: BLE001
                progress.put(("done", False, f"No se pudo descargar: {exc}"))

        def poll() -> None:
            try:
                if not prog.winfo_exists():
                    return
            except tk.TclError:
                return
            while True:
                try:
                    item = progress.get_nowait()
                except queue.Empty:
                    break
                if item[0] == "pct":
                    bar["value"] = item[1]
                    status.config(text=f"{int(item[1])} %")
                elif item[0] == "line":
                    if not self.busy:
                        self._out(item[1], "prompt")
                elif item[0] == "done":
                    close_and_finish(item[1], item[2])
                    return
            prog.after(100, poll)

        threading.Thread(target=work, daemon=True).start()
        prog.after(100, poll)

    def _open_last_file(self) -> None:
        if self.last_path and self.last_path.exists():
            local.open_path(self.last_path)

    # -- adjuntos -----------------------------------------------------------

    def _pick_attachment(self) -> None:
        path = filedialog.askopenfilename(
            title="Adjuntar archivo a la consulta",
            parent=self,
            filetypes=[
                ("Texto y código", "*.txt *.md *.py *.js *.ts *.tsx *.jsx *.json *.csv *.html *.css *.sql *.log *.yml *.yaml *.xml *.ini *.toml *.cfg *.java *.kt *.c *.h *.cpp *.hpp *.cs *.go *.rs *.rb *.php *.sh *.bat *.ps1"),
                ("Imágenes", "*.png *.jpg *.jpeg *.webp *.gif"),
                ("Todos los archivos", "*.*"),
            ],
        )
        if not path:
            return
        chosen = Path(path)
        try:
            size = chosen.stat().st_size
        except OSError:
            messagebox.showwarning("No se pudo leer", f"No se encuentra el archivo:\n{chosen}", parent=self)
            return
        if _attachment_kind(chosen) == "image" and size > MAX_IMAGE_BYTES:
            messagebox.showwarning(
                "Imagen demasiado grande",
                "El máximo para adjuntar una imagen son 8 MB.",
                parent=self,
            )
            return
        if _attachment_kind(chosen) == "text" and size > 8 * 1024 * 1024:
            if not messagebox.askyesno(
                "Archivo muy grande",
                "Solo se enviarán los primeros 60 000 caracteres.\n¿Continuar?",
                parent=self,
            ):
                return
        self.attachment = chosen
        self._update_attachment_ui()
        self._set_status(f"Adjunto listo: {chosen.name}")

    def _clear_attachment(self) -> None:
        self.attachment = None
        self._update_attachment_ui()
        self._set_status("Adjunto quitado")

    def _update_attachment_ui(self) -> None:
        path = self.attachment
        if path is None or not path.exists():
            self.attachment = None
            self.attach_bar.grid_remove()
            return
        try:
            size = _file_size(path.stat().st_size)
        except OSError:
            size = ""
        bits = [path.name]
        if size:
            bits.append(size)
        bits.append("imagen" if _attachment_kind(path) == "image" else "texto")
        self.attach_label.configure(text="Adjunto: " + " · ".join(bits))
        self.attach_bar.grid()

    def _attachment_payload(self, model: catalog.Model) -> tuple[str, str | None]:
        """Devuelve (texto extra para el prompt, imagen en base64)."""
        path = self.attachment
        if path is None:
            return "", None
        if not path.exists():
            raise ValueError(f"El archivo adjunto ya no existe:\n{path}")
        if _attachment_kind(path) == "image":
            if not _supports_images(model):
                raise ValueError(f"{model.name} no acepta imágenes: elige un modelo con visión.")
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise ValueError(f"No se pudo leer la imagen: {exc}") from None
            if len(raw) > MAX_IMAGE_BYTES:
                raise ValueError("La imagen supera los 8 MB.")
            return "", base64.b64encode(raw).decode("ascii")
        try:
            text, truncated = _read_text_file(path)
        except OSError as exc:
            raise ValueError(f"No se pudo leer el archivo: {exc}") from None
        note = "\n[archivo truncado a los primeros 60 000 caracteres]" if truncated else ""
        block = f"\n\n--- Archivo adjunto: {path.name} ---\n```\n{text}\n```{note}"
        return block, None

    def _offer_vision_switch(self, model: catalog.Model) -> None:
        """Si el modelo no ve imágenes, ofrece cambiar a uno con visión sin perder la consulta."""
        candidates = [
            m
            for models in self.catalogs.values()
            for m in models
            if m.category == "code" and _supports_images(m) and (m.provider != "ollama" or m.is_installed())
        ]
        candidates.sort(key=lambda m: (not m.free, m.provider != "openrouter", m.name.lower()))
        if not candidates:
            messagebox.showinfo(
                "Sin modelo con visión",
                f"{model.name} no acepta imágenes.\n\n"
                "Para analizar una imagen usa un modelo de OpenRouter con visión, "
                "o instala uno de visión en Ollama (por ejemplo: ollama pull llama3.2-vision).",
                parent=self,
            )
            return
        best = candidates[0]
        price = "gratis" if best.free else "de pago"
        if not messagebox.askyesno(
            "Este modelo no ve imágenes",
            f"{model.name} no acepta imágenes.\n\n"
            f"¿Cambiar a «{best.name}» ({price}, con visión) y enviar tu consulta con la imagen?\n\n"
            "Tu texto y la imagen adjunta se conservan.",
            parent=self,
        ):
            return
        attachment = self.attachment
        self._select_provider(best.provider)
        self._select_category("code")
        if best not in self.visible:
            self.attachment = attachment
            self._update_attachment_ui()
            self._set_status("Elige el modelo con visión en la lista y pulsa Enviar")
            return
        index = self.visible.index(best)
        self.tree.selection_set(self.tree.get_children()[index])
        self._on_tree_select()
        self.attachment = attachment
        self._update_attachment_ui()
        self._set_status(f"Modelo cambiado a {best.name}. Pulsa Enviar para analizar la imagen.")

    # -- envío --------------------------------------------------------------

    def _send(self) -> None:
        model = self.selected
        if not model or self.busy:
            return
        if getattr(self, "_prompt_placeholder_active", False):
            prompt = ""
        else:
            prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            self.prompt.focus_set()
            self._set_status("Escribe una consulta o un prompt")
            return
        if model.provider == "openrouter" and not self._require_openrouter():
            return

        if model.provider == "openrouter" and model.category in ("image", "video"):
            credits = (self.access.get("openrouter") or {}).get("credits")
            if isinstance(credits, (int, float)) and credits <= 0:
                if messagebox.askyesno(
                    "Sin saldo en OpenRouter",
                    "Tu cuenta de OpenRouter no tiene saldo.\n\n"
                    f"«{model.name}» se cobra de ese saldo, así que la generación fallará (error 402).\n\n"
                    "El chat con modelos gratis sigue funcionando.\n\n"
                    "¿Quieres abrir la página para añadir créditos?",
                    parent=self,
                ):
                    local.open_url("https://openrouter.ai/settings/credits")
                return

        if model.category == "code" and self._flow_blocked(model):
            return

        extra_text, image_b64 = "", None
        if (
            model.category == "code"
            and self.attachment is not None
            and _attachment_kind(self.attachment) == "image"
            and not _supports_images(model)
        ):
            self._offer_vision_switch(model)
            return
        if model.category == "code" and self.attachment is not None:
            try:
                extra_text, image_b64 = self._attachment_payload(model)
            except (OSError, ValueError) as exc:
                messagebox.showwarning("Archivo adjunto", str(exc), parent=self)
                return

        if model.category == "video":
            durations = model.extra.get("durations") or [4]
            duration = 4 if 4 in durations else min(durations)
            estimate = ""
            if model.price:
                estimate = f"\n\nCoste estimado: {duration}s × ${catalog.fmt_usd(model.price)}/s ≈ ${model.price * duration:.2f}"
            if not messagebox.askyesno(
                "Generar vídeo",
                f"Modelo: {model.name}\nDuración: {duration}s\n\nSe enviará a OpenRouter y se cobrará de tu saldo.{estimate}",
                parent=self,
            ):
                return

        self.cancel_event.clear()
        self._set_busy(True)
        if model.category == "code":
            self._send_chat(model, prompt, extra_text, image_b64)
        elif model.category == "image":
            self._send_image(model, prompt)
        else:
            self._send_video(model, prompt)

    def _send_chat(
        self,
        model: catalog.Model,
        prompt: str,
        extra_text: str = "",
        image_b64: str | None = None,
    ) -> None:
        attachment = self.attachment
        project = self._current_project()
        mode, _reason = self._file_access(model)
        stamp = time.strftime("%H:%M")

        self._out(f"\nTú · {stamp}\n", "label_user")
        self._out(f"{prompt}\n", "user")
        if attachment is not None:
            self._out(f"adjunto: {attachment.name}\n", "user_meta")
        if mode == "agent" and project is not None:
            self._out(f"acceso a archivos: {project.name}\n", "user_meta")
        self._out(f"\n{model.name} · {stamp}\n", "label_model")
        self._reset_prompt()

        if model.provider in ("opencode", "claude"):
            if not self._require_cli(model.provider):
                self._finish_error(f"{model.provider} no está instalado.")
                return
            self._out(f"$ {local.command_text(model.provider, model.uid)}\n", "cmd")
            thread = threading.Thread(
                target=self._cli_worker, args=(model, prompt + extra_text), daemon=True
            )
            thread.start()
            return

        if model.provider == "ollama" and not self._require_ollama():
            self._finish_error("Ollama no está en marcha.")
            return

        key = (model.provider, model.uid)
        # El historial se mantiene al cambiar de modelo o proveedor: solo se
        # reinicia con «Nuevo chat». Así se puede seguir la conversación.
        self.history_key = key
        note = ""
        if image_b64 is not None and attachment is not None:
            note = f"\n[imagen adjunta: {attachment.name}]"
        self.history.append({"role": "user", "content": prompt + extra_text + note})
        self._pending_history = True

        if mode == "agent" and image_b64 is None:
            thread = threading.Thread(target=self._agent_worker, args=(model, prompt), daemon=True)
        elif model.provider != "ollama":
            thread = threading.Thread(
                target=self._openrouter_worker, args=(model, prompt, image_b64), daemon=True
            )
        else:
            thread = threading.Thread(
                target=self._ollama_worker, args=(model, prompt, image_b64), daemon=True
            )
        thread.start()

    def _openrouter_worker(
        self, model: catalog.Model, prompt: str, image_b64: str | None = None
    ) -> None:
        started = time.time()
        collected: list[str] = []

        def on_delta(text: str) -> None:
            collected.append(text)
            self.q.put(("delta", text))

        messages = list(self.history)
        if image_b64 and self.attachment is not None:
            mime = IMAGE_TYPES.get(self.attachment.suffix.lower(), "image/png")
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                    },
                ],
            }

        base, key = self._api_endpoint(model.provider)
        try:
            usage = api.stream_openrouter_chat(
                key,
                model.uid,
                messages,
                on_delta,
                self.cancel_event.is_set,
                base=base,
            )
            self.q.put(("chat_done", "".join(collected), usage, time.time() - started, (model.provider, model.uid)))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("error", str(exc)))

    def _agent_worker(self, model: catalog.Model, prompt: str) -> None:
        """Conversa con el modelo y ejecuta sus herramientas de archivo dentro del proyecto.

        Funciona con OpenRouter (function calling) y con Ollama (tools nativas).
        Guarda en el historial toda la traza (llamadas y resultados) para que el
        modelo recuerde lo que hizo en turnos posteriores.
        """
        started = time.time()
        root = self._current_project()
        base, key = self._api_endpoint(model.provider) if self._is_api(model.provider) else ("", "")
        touched: list[str] = []
        base_history = list(self.history)
        new_start = 1 + len(base_history)

        def emit(text: str, tag: str = "dim") -> None:
            self.q.put(("line", text, tag))

        if root is None:
            if model.provider == "ollama":
                self._ollama_worker(model, prompt, None)
            else:
                self._openrouter_worker(model, prompt, None)
            return

        if model.provider == "ollama":
            caps = api.ollama_capabilities(model.uid)
            if caps is not None and "tools" not in caps:
                emit(f"{model.name} no admite herramientas: respondo sin acceso a archivos.", "err")
                self._ollama_worker(model, prompt, None)
                return

        messages: list[dict] = [{"role": "system", "content": agent.system_prompt(root)}] + base_history
        usage_total: dict = {}

        def record(usage: dict) -> None:
            for field_name in ("prompt_tokens", "completion_tokens"):
                usage_total[field_name] = usage_total.get(field_name, 0) + int(usage.get(field_name) or 0)
            if usage.get("cost"):
                usage_total["cost"] = usage_total.get("cost", 0.0) + float(usage["cost"])
            if usage.get("eval_duration"):
                usage_total["eval_duration"] = usage_total.get("eval_duration", 0.0) + float(usage["eval_duration"])

        def finish(text: str) -> None:
            transcript = messages[new_start:] if text else []
            self.q.put(
                (
                    "agent_done",
                    text,
                    dict(usage_total),
                    time.time() - started,
                    (model.provider, model.uid),
                    list(touched),
                    transcript,
                )
            )

        def chat_once() -> dict:
            if model.provider == "ollama":
                return api.chat_ollama_tools(model.uid, messages, agent.TOOLS)
            return api.chat_tools(key, model.uid, messages, agent.TOOLS, base=base)

        last_call: list = [None, 0]

        def repeated(name: str, args: dict) -> bool:
            """Evita bucles infinitos cuando el modelo repite la misma orden."""
            try:
                signature = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            except (TypeError, ValueError):
                signature = (name, repr(args))
            if signature == last_call[0]:
                last_call[1] += 1
            else:
                last_call[0], last_call[1] = signature, 1
            return last_call[1] >= 2

        try:
            for _step in range(12):
                if self.cancel_event.is_set():
                    finish("")
                    return
                try:
                    data = chat_once()
                except api.ApiError as exc:
                    text = str(exc).lower()
                    if model.provider == "ollama" and "tools" in text and ("support" in text or "admite" in text):
                        emit(f"{model.name} no admite herramientas: respondo sin acceso a archivos.", "err")
                        self._ollama_worker(model, prompt, None)
                        return
                    raise

                record(data.get("usage") or {})
                choice = (data.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                calls = message.get("tool_calls") or []

                if not calls:
                    reply = str(message.get("content") or "").strip()
                    parsed = agent.parse_text_call(reply) if reply else None
                    if parsed is not None:
                        name, args = parsed
                        if repeated(name, args):
                            emit(
                                f"El modelo repite «{name}» sin avanzar. Prueba con un modelo más grande "
                                "o desactiva «Leer y escribir archivos».",
                                "err",
                            )
                            finish("")
                            return
                        messages.append({"role": "assistant", "content": reply})
                        emit(f"⚙ {name} {agent.describe(name, args)}  (escrito como texto)", "tool")
                        try:
                            result, log = agent.execute(name, args, root)
                        except Exception as exc:  # noqa: BLE001
                            result, log = f"Error: {exc}", ""
                        if log:
                            emit(f"   {log}", "dim")
                        path = str(args.get("path") or "").strip()
                        if name in ("write_file", "replace_in_file") and path and not result.startswith("Error"):
                            if path not in touched:
                                touched.append(path)
                        messages.append(
                            {"role": "tool", "name": name, "content": result[:TOOL_RESULT_LIMIT]}
                        )
                        continue
                    messages.append({"role": "assistant", "content": reply})
                    if reply:
                        emit(reply, "normal")
                    finish(reply)
                    return

                messages.append(message)
                preview = str(message.get("content") or "").strip()
                if preview:
                    emit(preview, "dim")

                for call in calls:
                    if self.cancel_event.is_set():
                        finish("")
                        return
                    function = call.get("function") or {}
                    name = str(function.get("name") or "")
                    raw_args = function.get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        args = {}
                    if repeated(name, args):
                        emit(
                            f"El modelo repite «{name}» sin avanzar. Prueba con un modelo más grande "
                            "o desactiva «Leer y escribir archivos».",
                            "err",
                        )
                        finish("")
                        return
                    try:
                        result, log = agent.execute(name, args, root)
                    except Exception as exc:  # noqa: BLE001 - se devuelve al modelo como error
                        result, log = f"Error: {exc}", ""
                    emit(f"⚙ {name} {agent.describe(name, args)}", "tool")
                    if log:
                        emit(f"   {log}", "dim")
                    path = str(args.get("path") or "").strip()
                    if name in ("write_file", "replace_in_file") and path and not result.startswith("Error"):
                        if path not in touched:
                            touched.append(path)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id"),
                            "name": name,
                            "content": result[:TOOL_RESULT_LIMIT],
                        }
                    )

            emit("Se alcanzó el límite de pasos con herramientas.", "err")
            finish("")
        except Exception as exc:  # noqa: BLE001
            self.q.put(("error", str(exc)))

    def _ollama_worker(self, model: catalog.Model, prompt: str, image_b64: str | None = None) -> None:
        started = time.time()
        collected: list[str] = []

        def on_delta(text: str) -> None:
            collected.append(text)
            self.q.put(("delta", text))

        messages = [dict(item) for item in self.history]
        if image_b64:
            messages[-1]["images"] = [image_b64]

        try:
            usage = api.stream_ollama_chat(model.uid, messages, on_delta, self.cancel_event.is_set)
            self.q.put(("chat_done", "".join(collected), usage, time.time() - started, (model.provider, model.uid)))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("error", str(exc)))

    def _cli_worker(self, model: catalog.Model, prompt: str) -> None:
        started = time.time()
        collected: list[str] = []

        def on_line(line: str) -> None:
            collected.append(line)
            self.q.put(("line", line))

        def register(proc) -> None:
            self.proc = proc

        # Mantener el contexto de la conversación: se envía el historial previo
        # (sin el mensaje actual, que ya está al final) al CLI.
        prior = [m for m in self.history if m.get("role") in ("user", "assistant")]
        # Excluye el último mensaje de usuario (el prompt actual) para no duplicarlo.
        if prior and prior[-1].get("role") == "user":
            prior = prior[:-1]
        history_text = ""
        for m in prior:
            role = "Usuario" if m.get("role") == "user" else "Asistente"
            history_text += f"{role}: {str(m.get('content') or '').strip()}\n\n"
        full_prompt = (history_text + prompt) if history_text else prompt

        try:
            local.run_prompt(
                model.provider,
                model.uid,
                full_prompt,
                self.cfg["workdir"],
                on_line,
                self.cancel_event.is_set,
                register,
            )
            reply = "\n".join(collected).strip()
            self.q.put(("chat_done", reply, {}, time.time() - started, (model.provider, model.uid)))
        except Exception as exc:  # noqa: BLE001
            self.q.put(("error", str(exc)))

    def _send_image(self, model: catalog.Model, prompt: str) -> None:
        self._out(f"\nTú · {time.strftime('%H:%M')}\n", "label_user")
        self._out(f"{prompt}\n", "user")
        self._out(f"\n{model.name} · generando… (puede tardar 10-60 s)\n", "label_model")
        self._reset_prompt()
        base, key = self._api_endpoint(model.provider)
        out_dir = config.image_dir(self.cfg)
        ratios = model.extra.get("aspect_ratios") or []
        aspect = next((r for r in ("1:1", "16:9", "9:16", "4:3") if r in ratios), None)

        def work() -> None:
            started = time.time()
            try:
                if model.provider == "openrouter":
                    path, cost, media = api.generate_image(key, model.uid, prompt, out_dir, aspect)
                else:
                    path, cost, media = api.generate_image_openai(base, key, model.uid, prompt, out_dir)
                self.q.put(("image", str(path), cost, time.time() - started, (model.provider, model.uid)))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _send_video(self, model: catalog.Model, prompt: str) -> None:
        self._out(f"\nTú · {time.strftime('%H:%M')}\n", "label_user")
        self._out(f"{prompt}\n", "user")
        self._out(f"\n{model.name} · vídeo en cola\n", "label_model")
        self._reset_prompt()
        durations = model.extra.get("durations") or [4]
        duration = 4 if 4 in durations else min(durations)
        resolutions = model.extra.get("resolutions") or []
        resolution = next((r for r in ("720p", "1080p", "480p") if r in resolutions), resolutions[0] if resolutions else None)
        aspects = model.extra.get("aspect_ratios") or []
        aspect = next((a for a in ("16:9", "9:16", "1:1") if a in aspects), aspects[0] if aspects else None)
        self._out(f"Enviando trabajo ({duration}s, {resolution or 'auto'}, {aspect or 'auto'})…\n", "dim")
        key = config.openrouter_key(self.cfg)
        out_dir = config.video_dir(self.cfg)

        def work() -> None:
            started = time.time()
            try:
                path = api.generate_video(
                    key,
                    model.uid,
                    prompt,
                    out_dir,
                    duration=duration,
                    resolution=resolution,
                    aspect_ratio=aspect,
                    on_status=lambda status: self.q.put(("status", f"Vídeo: {status}")),
                    cancel=self.cancel_event.is_set,
                )
                self.q.put(("video", str(path), time.time() - started, (model.provider, model.uid)))
            except Exception as exc:  # noqa: BLE001
                self.q.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _finish_error(self, message: str) -> None:
        if self._pending_history and self.history and self.history[-1].get("role") == "user":
            self.history.pop()
            self._pending_history = False
        self._out(f"✕ {message}\n", "err")
        self._set_busy(False)
        self._set_status(message[:150])
        try:
            self._save_current_conversation()
            self._save_conversation_state(include_current=True)
        except Exception:
            pass

    def _stop(self) -> None:
        self.cancel_event.set()
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        self._out("\n· cancelando…\n", "dim")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        _set_enabled(self.btn_send, not busy and self.selected is not None)
        if not busy:
            try:
                self.prompt.focus_set()
            except tk.TclError:
                pass
        _set_enabled(self.btn_primary, not busy and self.selected is not None)
        _set_enabled(self.btn_stop, busy)
        self.btn_send.configure(text="Trabajando…" if busy else self._send_label())
        if busy:
            self._set_status("Trabajando…")
        else:
            self._set_status("Listo")

    def _send_label(self) -> str:
        if not self.selected:
            return "Enviar consulta"
        if self.selected.category == "image":
            return "Generar imagen"
        if self.selected.category == "video":
            return "Generar vídeo"
        return "Enviar consulta"

    # -- cola de eventos ----------------------------------------------------

    def _drain_queue(self) -> None:
        try:
            while True:
                message = self.q.get_nowait()
                try:
                    self._handle_message(message)
                except Exception as exc:  # noqa: BLE001
                    self._out(f"\n⚠ Error interno: {exc}\n", "err")
        except queue.Empty:
            pass
        self.after(70, self._drain_queue)

    def _handle_message(self, message) -> None:
        kind = message[0]
        if kind == "status":
            self._set_status(str(message[1]))
        elif kind == "statuses":
            self.statuses = message[1] or {}
            self._update_statuses_ui()
        elif kind == "access":
            self.statuses = message[1] or {}
            self.access = {"openrouter": message[2] or {}}
            self._update_statuses_ui()
            self._refresh_access_dialog()
            self._update_usage_label()
            self._schedule_access_prompt()
        elif kind == "refresh_done":
            self._apply_refresh(message[1], message[2], message[3])
        elif kind == "delta":
            self._out(str(message[1]))
        elif kind == "line":
            tag = message[2] if len(message) > 2 else "normal"
            self._out(str(message[1]) + "\n", tag)
        elif kind == "chat_done":
            self._on_chat_done(message[1], message[2], message[3], message[4] if len(message) > 4 else None)
        elif kind == "agent_done":
            self._on_agent_done(
                message[1],
                message[2],
                message[3],
                message[4] if len(message) > 4 else None,
                message[5] if len(message) > 5 else [],
                message[6] if len(message) > 6 else None,
            )
        elif kind == "image":
            self._on_image(message[1], message[2], message[3], message[4] if len(message) > 4 else None)
        elif kind == "video":
            self._on_video(message[1], message[2], message[3] if len(message) > 3 else None)
        elif kind == "error":
            self._finish_error(str(message[1]))
        elif kind == "image_prices":
            self._render_list()
            self._update_detail()

    def _usage_suffix(self, usage: dict, elapsed: float) -> str:
        extra = f" · {elapsed:.1f} s"
        if usage:
            prompt_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
            completion_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
            cost = usage.get("cost")
            if prompt_tokens or completion_tokens:
                extra += f" · {prompt_tokens or 0}↑ {completion_tokens or 0}↓ tokens"
            eval_s = usage.get("eval_duration") or 0
            if eval_s and completion_tokens:
                extra += f" · {completion_tokens / eval_s:.1f} tok/s"
            if cost:
                extra += f" · ${cost:.4f}"
        return extra

    def _commit_history(self, key, reply: str, transcript: list[dict] | None) -> None:
        """Guarda en el historial la respuesta (o la traza completa de herramientas)."""
        if key is None or self.history_key != key:
            self._pending_history = False
            return
        if transcript:
            self.history.extend(transcript)
        elif reply:
            self.history.append({"role": "assistant", "content": reply})
        elif self._pending_history and self.history and self.history[-1].get("role") == "user":
            self.history.pop()
        self._pending_history = False
        self._save_conversation_state(include_current=True)

    def _conversation_path(self) -> Path:
        return config.app_dir() / "conversations.json"

    def _load_conversation_state(self) -> None:
        path = self._conversation_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        items = data.get("items") if isinstance(data, dict) else None
        self.conversations = [dict(item) for item in (items or []) if isinstance(item, dict)]
        current = data.get("current") if isinstance(data, dict) else None
        if isinstance(current, dict) and current.get("messages"):
            self.history = [dict(m) for m in current["messages"] if isinstance(m, dict)]
            model = current.get("model")
            if isinstance(model, str) and ":" in model:
                provider, uid = model.split(":", 1)
                self.history_key = (provider, uid)
            self.current_conversation_id = current.get("id")
            self._loaded_conversation = current
        else:
            self._loaded_conversation = None

    def _save_current_conversation(self) -> None:
        if not self.history:
            return
        record = self._conversation_record()
        if record is None:
            return
        # Sustituye si ya existía (mismo id) o añade.
        items = [item for item in self.conversations if item.get("id") != record["id"]]
        items.insert(0, record)
        self.conversations = items[:30]
        self.current_conversation_id = record["id"]

    def _conversation_record(self) -> dict | None:
        if not self.history:
            return None
        first_user = next((str(m.get("content") or "") for m in self.history if m.get("role") == "user"), "")
        title = first_user.strip().replace("\\n", " ")
        if len(title) > 60:
            title = title[:57] + "…"
        if not title:
            title = "Chat sin título"
        model = None
        if self.history_key:
            model = f"{self.history_key[0]}:{self.history_key[1]}"
        elif self.selected is not None:
            model = f"{self.selected.provider}:{self.selected.uid}"
        return {
            "id": self.current_conversation_id or str(int(time.time() * 1000)),
            "title": title,
            "model": model,
            "messages": [dict(m) for m in self.history],
            "updated": time.time(),
        }

    def _save_conversation_state(self, include_current: bool = True) -> None:
        current = None
        if include_current and self.history:
            current = self._conversation_record()
            if current is not None:
                self.current_conversation_id = current["id"]
        data = {"items": self.conversations, "current": current}
        try:
            path = self._conversation_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _render_loaded_conversation(self) -> None:
        current = getattr(self, "_loaded_conversation", None)
        if not current or not current.get("messages"):
            return
        self._clear_output()
        stamp = time.strftime("%H:%M")
        for message in current["messages"]:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user":
                self._out(f"\\nTú · {stamp}\\n", "label_user")
                self._out(f"{content}\\n", "user")
            else:
                name = self.selected.name if self.selected is not None else "Asistente"
                self._out(f"\\n{name} · {stamp}\\n", "label_model")
                self._out(f"{content}\\n", "normal")
        self._out("\\n(Conversación recuperada)\\n", "dim")
        self._loaded_conversation = None

    def _restore_conversation_model(self) -> None:
        current = None
        try:
            data = json.loads(self._conversation_path().read_text(encoding="utf-8"))
            current = data.get("current") if isinstance(data, dict) else None
        except Exception:
            current = None
        if not isinstance(current, dict) or not current.get("model"):
            return
        model_id = str(current["model"])
        if ":" not in model_id:
            return
        provider, uid = model_id.split(":", 1)
        model = None
        for item in (self.catalogs.get(self.category) or self.visible or []):
            if item.provider == provider and item.uid == uid:
                model = item
                break
        if model is None:
            # Buscar en todos los catálogos cargados.
            for models in self.catalogs.values():
                for item in models or []:
                    if item.provider == provider and item.uid == uid:
                        model = item
                        break
                if model is not None:
                    break
        if model is not None:
            self.selected = model
            self.history_key = (provider, uid)
            self._update_detail()
            self._ensure_visible_category()

    def _toggle_favorite(self) -> None:
        model = self.selected
        if model is None:
            return
        key = f"{model.provider}:{model.uid}"
        if key in self.favorites:
            self.favorites.discard(key)
        else:
            self.favorites.add(key)
        self.cfg["favorite_models"] = sorted(self.favorites)
        config.update_config(favorite_models=self.cfg["favorite_models"])
        self._update_detail()
        self._render_list()

    def _record_usage(self, key, *, cost: float = 0.0, images: int = 0, videos: int = 0, usage_data: dict | None = None) -> None:
        """Suma el uso de una respuesta al consumo guardado del modelo."""
        if not key:
            return
        provider, uid = key
        data = usage_data or {}
        usage.record(
            provider,
            uid,
            prompt=int(data.get("prompt_tokens") or data.get("input_tokens") or 0),
            completion=int(data.get("completion_tokens") or data.get("output_tokens") or 0),
            cost=float(cost or data.get("cost") or 0.0),
            images=images,
            videos=videos,
        )
        self._update_usage_label()

    def _open_history(self) -> None:
        if self.busy:
            self._set_status("Espera a que termine la respuesta actual")
            return
        self._save_current_conversation()
        self._save_conversation_state(include_current=True)
        items = [dict(item) for item in self.conversations]
        current = None
        try:
            data = json.loads(self._conversation_path().read_text(encoding="utf-8"))
            current = data.get("current") if isinstance(data, dict) else None
        except Exception:
            current = None
        if isinstance(current, dict) and current.get("messages"):
            items = [current] + [item for item in items if item.get("id") != current.get("id")]

        win = tk.Toplevel(self)
        win.title("Historial de conversaciones")
        win.configure(bg=BG)
        win.geometry("560x440")
        win.transient(self)

        tk.Label(win, text="Conversaciones guardadas", bg=BG, fg=TEXT, font=(FONT, 11, "bold")).pack(
            anchor="w", padx=14, pady=(12, 6)
        )
        frame = tk.Frame(win, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        listbox = tk.Listbox(
            frame, bg=PANEL, fg=TEXT, selectbackground=ACCENT_SOFT, selectforeground=TEXT,
            relief="flat", bd=0, highlightthickness=0, font=(FONT, 9),
        )
        listbox.pack(fill="both", expand=True, padx=6, pady=6)
        for item in items:
            title = str(item.get("title") or "Chat sin título")
            model = str(item.get("model") or "")
            listbox.insert("end", f"{title}  ·  {model}")

        def load_selected() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            index = selection[0]
            if 0 <= index < len(items):
                self._load_conversation_record(items[index])
                win.destroy()

        def delete_selected() -> None:
            selection = listbox.curselection()
            if not selection:
                return
            index = selection[0]
            if 0 <= index < len(items):
                target_id = items[index].get("id")
                del items[index]
                self.conversations = [item for item in self.conversations if item.get("id") != target_id]
                listbox.delete(index)
                self._save_conversation_state(include_current=True)

        actions = tk.Frame(win, bg=BG)
        actions.pack(fill="x", padx=14, pady=(0, 12))
        _button(actions, "Abrir", load_selected, kind="primary", height=30, font_size=9).pack(side="left")
        _button(actions, "Borrar", delete_selected, kind="danger", height=30, font_size=9).pack(side="left", padx=(6, 0))
        _button(actions, "Cerrar", win.destroy, kind="ghost", height=30, font_size=9).pack(side="right")
        listbox.bind("<Double-1>", lambda _e: load_selected())

    def _load_conversation_record(self, record: dict) -> None:
        if self.busy:
            return
        self._save_current_conversation()
        self.history = [dict(m) for m in (record.get("messages") or []) if isinstance(m, dict)]
        model = record.get("model")
        if isinstance(model, str) and ":" in model:
            provider, uid = model.split(":", 1)
            self.history_key = (provider, uid)
        else:
            self.history_key = None
        self.current_conversation_id = record.get("id")
        self._clear_output()
        stamp = time.strftime("%H:%M")
        for message in self.history:
            role = message.get("role")
            content = str(message.get("content") or "")
            if role == "user":
                self._out(f"\\nTú · {stamp}\\n", "label_user")
                self._out(f"{content}\\n", "user")
            else:
                name = self.selected.name if self.selected is not None else "Asistente"
                self._out(f"\\n{name} · {stamp}\\n", "label_model")
                self._out(f"{content}\\n", "normal")
        self._out("\\n(Conversación recuperada)\\n", "dim")
        if self.history_key:
            provider, uid = self.history_key
            for models in self.catalogs.values():
                for item in (models or []):
                    if item.provider == provider and item.uid == uid:
                        self.selected = item
                        self._update_detail()
                        break
        self._save_conversation_state(include_current=True)

    def _copy_output(self, _event=None):
        try:
            text = self.output.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(text)
        return "break"

    def _select_all_output(self, _event=None):
        self.output.tag_add("sel", "1.0", "end")
        self.output.mark_set("insert", "1.0")
        self.output.see("insert")
        return "break"

    def _on_chat_done(self, reply: str, usage_data: dict, elapsed: float, key=None) -> None:
        try:
            self._record_usage(key, usage_data=usage_data)
            self._commit_history(key, reply, None)
            self._out(f"✓ Listo{self._usage_suffix(usage_data, elapsed)}\n", "ok")
            self._refresh_files()
            self.attachment = None
            self._update_attachment_ui()
        finally:
            self._set_busy(False)
            try:
                self._save_current_conversation()
                self._save_conversation_state(include_current=True)
            except Exception:
                pass

    def _on_agent_done(
        self,
        reply: str,
        usage: dict,
        elapsed: float,
        key=None,
        touched=None,
        transcript=None,
    ) -> None:
        touched = touched or []
        try:
            self._record_usage(key, usage_data=usage)
            self._commit_history(key, reply, transcript)
            for path in touched:
                if path not in self.touched_files:
                    self.touched_files.append(path)
            self._out(f"✓ Listo{self._usage_suffix(usage, elapsed)}\n", "ok")
            if touched:
                self._out("✓ Archivos modificados: " + ", ".join(touched) + "\n", "ok")
            self._refresh_files()
            self._set_status(
                f"Listo · {len(touched)} archivo(s) modificados" if touched else "Listo · sin cambios en archivos"
            )
        finally:
            self._set_busy(False)
            try:
                self._save_current_conversation()
                self._save_conversation_state(include_current=True)
            except Exception:
                pass

    def _on_image(self, path: str, cost, elapsed: float, key=None) -> None:
        try:
            self._record_usage(key, cost=cost or 0.0, images=1)
            self.last_path = Path(path)
            self._out(f"\n✓ Imagen guardada: {path}", "ok")
            if cost:
                self._out(f" · coste ${cost:.4f}", "dim")
            self._out(f" · {elapsed:.1f} s\n", "dim")
            self._show_preview(Path(path))
            _set_enabled(self.btn_open_file, True)
            self._set_status("Imagen generada")
        finally:
            self._set_busy(False)
            try:
                self._save_current_conversation()
                self._save_conversation_state(include_current=True)
            except Exception:
                pass

    def _on_video(self, path: str, elapsed: float, key=None) -> None:
        try:
            self._record_usage(key, videos=1)
            self.last_path = Path(path)
            self._out(f"\n✓ Vídeo guardado: {path} · {elapsed:.0f} s\n", "ok")
            _set_enabled(self.btn_open_file, True)
            self._set_status("Vídeo generado")
        finally:
            self._set_busy(False)
            try:
                self._save_current_conversation()
                self._save_conversation_state(include_current=True)
            except Exception:
                pass
        if messagebox.askyesno("Vídeo listo", "¿Quieres abrir el vídeo ahora?", parent=self):
            local.open_path(path)

    def _show_preview(self, path: Path) -> None:
        self._reset_preview()
        if not path.exists():
            return
        try:
            if path.suffix.lower() == ".png":
                photo = tk.PhotoImage(file=str(path))
                factor = max(1, photo.width() // 330)
                if factor > 1:
                    photo = photo.subsample(factor, factor)
            else:
                try:
                    from PIL import Image, ImageTk  # type: ignore

                    image = Image.open(path)
                    image.thumbnail((330, 220))
                    photo = ImageTk.PhotoImage(image)
                except Exception:
                    self._out("(vista previa no disponible para este formato)\n", "dim")
                    return
            self.preview.configure(image=photo, text="")
            self.preview.image = photo  # type: ignore[attr-defined]
            self.preview_photo = photo
            self.preview.grid()
        except Exception:
            self._out("(no se pudo mostrar la vista previa)\n", "dim")

    def _reset_preview(self) -> None:
        self.preview.configure(image="", text="")
        self.preview.image = None  # type: ignore[attr-defined]
        self.preview_photo = None
        self.preview.grid_remove()

    # -- salida / estado ----------------------------------------------------

    def _out(self, text: str, tag: str = "") -> None:
        self.output.configure(state="normal")
        if tag:
            self.output.insert("end", text, tag)
        else:
            self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _new_chat(self, reset_prompt: bool = False) -> None:
        if self.busy:
            self._set_status("Espera a que termine la respuesta actual")
            return
        self._save_current_conversation()
        self.history = []
        self.history_key = None
        self._pending_history = False
        self.current_conversation_id = None
        self.touched_files = []
        self.attachment = None
        self._update_attachment_ui()
        self._reset_preview()
        if reset_prompt:
            self._reset_prompt()
        self._clear_output()
        self._refresh_touched()
        self._set_status("Chat nuevo")
        self._save_conversation_state(include_current=False)

    def _clear_output(self) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        self._welcome()

    def _welcome(self) -> None:
        """Pantalla de inicio de la conversación: guía los pasos del flujo."""
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")
        model = self.selected
        self._out("Flujo de trabajo\n", "head")
        for index, (done, title, detail) in enumerate(self._flow_steps(), start=1):
            mark = "✓" if done else "○"
            self._out(f" {mark}  {index}. {title}: ", "ok" if done else "dim")
            self._out(f"{detail}\n", "normal" if done else "dim")
        if model is None:
            self._out("\nElige un proveedor y un modelo en la columna izquierda para empezar.\n", "dim")
            return
        if model.category == "code":
            mode, _reason = self._file_access(model)
            if mode == "agent":
                note = "Describe lo que necesitas: el modelo leerá y modificará los archivos del proyecto."
            elif mode == "cli":
                note = "Describe lo que necesitas: el CLI leerá y modificará los archivos del proyecto."
            else:
                note = "Atención: la casilla de archivos está desactivada; el modelo solo responderá."
            self._out(f"\n{note}\n", "dim")
        elif model.category == "image":
            self._out("\nDescribe la imagen y pulsa Generar.\n", "dim")
        else:
            self._out("\nDescribe el vídeo; se avisa del coste antes de generarlo.\n", "dim")

    def _set_status(self, text: str) -> None:
        self.status_left.configure(text=text[:200])
    def _update_cache_label(self) -> None:
        _, ts = catalog.cached_models(self.provider)
        self.status_right.configure(text=f"Datos: {catalog.cache_age_text(ts)}")

    def _provider_ready(self, pid: str) -> bool:
        if catalog.PROVIDER_BY_ID.get(pid, {}).get("custom"):
            return bool(self.catalogs.get(pid))
        if pid == "openrouter":
            return bool((self.access.get("openrouter") or {}).get("ok"))
        if pid == "ollama":
            return bool(self.statuses.get("ollama_running"))
        return bool(self.statuses.get(pid))

    def _paint_header_chip(self) -> None:
        ids = self._all_provider_ids()
        total = len(ids)
        ready = sum(1 for pid in ids if self._provider_ready(pid))
        if ready == total:
            self.header_chip.configure(text=f"●  {total}/{total} proveedores listos", fg=GREEN)
            return
        if not self.statuses and not self.access:
            self.header_chip.configure(text="●  Comprobando proveedores…", fg=AMBER)
            return
        text = f"●  {ready}/{total} proveedores · revisar"
        self.header_chip.configure(text=text, fg=AMBER if ready else RED)

    def _on_provider_box_select(self, _event=None) -> None:
        name = self.provider_box.get()
        pid = self._provider_name_to_id.get(name)
        if pid and pid != self.provider:
            self._select_provider(pid)

    def _update_cards(self) -> None:
        openrouter = self.access.get("openrouter") or {}
        for provider in catalog.PROVIDERS:
            pid = provider["id"]
            dot = self.card_status_dot.get(pid)
            label = self.card_status.get(pid)

            if provider.get("custom"):
                count = len(self.catalogs.get(pid, []))
                if count:
                    text = f"Conectado · {count} modelos"
                    color = GREEN
                else:
                    text = "Sin modelos: revisa la clave"
                    color = AMBER
            elif pid == "openrouter":
                if openrouter.get("ok"):
                    credits = openrouter.get("credits")
                    if isinstance(credits, (int, float)):
                        text = "Clave válida · con saldo" if credits > 0 else "Clave válida · sin saldo"
                    else:
                        text = "Clave válida"
                    color = GREEN if not isinstance(credits, (int, float)) or credits > 0 else AMBER
                elif openrouter.get("reason") == "invalid":
                    text = "Clave no válida"
                    color = RED
                elif openrouter.get("reason") == "error":
                    text = "Sin conexión"
                    color = RED
                elif config.openrouter_key(self.cfg, allow_env=False):
                    text = "Comprobando…"
                    color = AMBER
                else:
                    text = "Falta la clave"
                    color = AMBER
            elif pid == "ollama":
                running = self.statuses.get("ollama_running")
                exists = self.statuses.get("ollama")
                if exists and running:
                    text = "Servidor activo"
                    color = GREEN
                elif exists:
                    text = "Servidor apagado"
                    color = AMBER
                else:
                    text = "No instalado"
                    color = RED
            else:
                exists = self.statuses.get(pid)
                if self.catalog_errors.get(pid):
                    text = "No se pudieron leer los modelos · Actualizar"
                    color = AMBER
                else:
                    text = "Instalado" if exists else "No instalado"
                    color = GREEN if exists else RED

            if dot is not None:
                dot.configure(fg=color)
            if label is not None:
                label.configure(text=text)
            if pid == self.provider and getattr(self, "provider_status", None) is not None:
                self.provider_status.configure(text=text, fg=color)

        self._paint_header_chip()

        for pid, card in getattr(self, "cards", {}).items():
            active = pid == self.provider
            bg = PANEL_2 if active else PANEL
            card.configure(bg=bg, highlightbackground=ACCENT if active else BORDER)
            for widget in self.card_widgets.get(pid, []):
                try:
                    widget.configure(bg=bg)
                except Exception:
                    pass

    def _update_statuses_ui(self) -> None:
        self._update_cards()
        self._update_cache_label()

    # -- acceso a los proveedores -------------------------------------------

    def _provider_status_text(self, pid: str) -> str:
        count = len(self.catalogs.get(pid, []))
        if catalog.PROVIDER_BY_ID.get(pid, {}).get("custom"):
            if not count:
                return "Conectado, pero sin modelos: revisa la clave o la URL."
            tabs = {catalog.tab_of(m.category) for m in self.catalogs.get(pid, [])}
            parts = []
            if "code" in tabs:
                parts.append(f"{sum(1 for m in self.catalogs[pid] if m.category == 'code')} de programación")
            if "media" in tabs:
                parts.append(f"{sum(1 for m in self.catalogs[pid] if m.category != 'code')} de imagen")
            return "Conectado · " + " · ".join(parts)
        if pid == "openrouter":
            info = self.access.get("openrouter") or {}
            if info.get("ok"):
                bits = ["Clave válida"]
                free = info.get("free_remaining")
                if isinstance(free, int):
                    bits.append(f"{free} gratis hoy")
                credits = info.get("credits")
                if isinstance(credits, (int, float)):
                    if credits > 0:
                        bits.append(f"saldo ${credits:.2f}")
                    else:
                        bits.append("sin saldo: imágenes y vídeos fallarán")
                return " · ".join(bits)
            if info.get("reason") == "invalid":
                return "La clave guardada no es válida o ha caducado."
            if info.get("reason") == "error":
                return "No se pudo conectar con OpenRouter para comprobar la clave."
            if config.openrouter_key(self.cfg):
                return "Comprobando la clave…"
            return "No hay clave guardada. Consíguela gratis en openrouter.ai/keys."
        if pid == "ollama":
            running = self.statuses.get("ollama_running")
            exists = self.statuses.get("ollama")
            models = self.statuses.get("ollama_models") or 0
            if not exists:
                return "No está instalado en este equipo."
            if running:
                if models == 1:
                    return "Servidor activo · 1 modelo instalado"
                if models:
                    return f"Servidor activo · {models} modelos instalados"
                return "Servidor activo · sin modelos"
            return "Instalado, pero el servidor no responde (ollama serve)."
        exists = self.statuses.get(pid)
        version = self.statuses.get(f"{pid}_version") or ""
        if exists:
            bits = ["Instalado"]
            if version:
                bits.append(version)
            if count:
                bits.append(f"{count} modelos")
            return " · ".join(bits)
        return "No está instalado en este equipo."

    def _schedule_access_prompt(self) -> None:
        """Abre una sola vez el diálogo de acceso si falta lo imprescindible."""

        def check() -> None:
            if getattr(self, "_access_prompted", False):
                return
            if self.grab_current() is not None:
                self.after(800, check)
                return
            info = self.access.get("openrouter") or {}
            missing_key = info.get("reason") in ("missing", "invalid")
            ready = sum(1 for pid in self._all_provider_ids() if self._provider_ready(pid))
            if not missing_key and ready > 0:
                return
            self._access_prompted = True
            self._open_access_dialog()

        self.after(1100, check)

    def _open_access_dialog(self) -> None:
        current = getattr(self, "access_win", None)
        if current is not None:
            try:
                if current.winfo_exists():
                    current.deiconify()
                    current.lift()
                    current.focus_force()
                    return
            except tk.TclError:
                pass
        win = tk.Toplevel(self)
        win.title("Acceso a los proveedores · AI Hub")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.resizable(False, True)

        width = 700
        height = min(self.winfo_screenheight() - 60, 185 + 80 * len(catalog.PROVIDERS))
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

        container = tk.Frame(win, bg=BG, padx=24, pady=20)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        tk.Label(
            container, text="Acceso a los proveedores", bg=BG, fg=TEXT, font=(FONT, 16, "bold")
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            container,
            text="Comprueba qué puedes usar ahora y configura lo que falte.",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))

        canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview, style="AIH.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=2, column=0, sticky="nsew")
        scrollbar.grid(row=2, column=1, sticky="ns")
        container.columnconfigure(1, weight=0)
        rows = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=rows, anchor="nw")
        rows.columnconfigure(0, weight=1)

        def _on_rows_configure(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        rows.bind("<Configure>", _on_rows_configure)

        def _on_wheel(event) -> None:
            canvas.yview_scroll(int(-event.delta / 120), "units")

        canvas.bind("<MouseWheel>", _on_wheel)
        rows.bind("<MouseWheel>", _on_wheel)

        footer = tk.Frame(container, bg=BG)
        footer.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        _button(footer, "Volver a comprobar", self._detect_statuses, kind="ghost", height=32, font_size=9).pack(
            side="left"
        )
        _button(footer, "＋ Añadir proveedor", self._open_add_provider, kind="ghost", height=32, font_size=9).pack(
            side="left", padx=(8, 0)
        )
        _button(footer, "Cerrar", win.destroy, kind="primary", height=32, bold=True).pack(side="right")

        win.bind("<Escape>", lambda _e: win.destroy())
        self.access_win = win
        self.access_rows = rows
        self._fill_access_rows()

    def _refresh_access_dialog(self) -> None:
        win = getattr(self, "access_win", None)
        if win is not None and win.winfo_exists():
            self._fill_access_rows()

    def _provider_color(self, pid: str) -> str:
        if not self._provider_ready(pid):
            return AMBER
        if pid == "openrouter":
            credits = (self.access.get("openrouter") or {}).get("credits")
            if isinstance(credits, (int, float)) and credits <= 0:
                return AMBER
        return GREEN

    def _fill_access_rows(self) -> None:
        rows = getattr(self, "access_rows", None)
        if rows is None or not rows.winfo_exists():
            return
        for child in rows.winfo_children():
            child.destroy()

        for index, provider in enumerate(catalog.PROVIDERS):
            pid = provider["id"]
            ready = self._provider_ready(pid)
            row = tk.Frame(rows, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=14, pady=12)
            row.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            row.columnconfigure(1, weight=1)

            dot = tk.Label(row, text="●", bg=PANEL, fg=self._provider_color(pid), font=(FONT, 11))
            dot.grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, 10))

            tk.Label(
                row, text=provider["name"], bg=PANEL, fg=TEXT, font=(FONT, 11, "bold"), anchor="w"
            ).grid(row=0, column=1, sticky="w")
            tk.Label(
                row,
                text=self._provider_status_text(pid),
                bg=PANEL,
                fg=MUTED if ready else AMBER,
                font=(FONT, 9),
                anchor="w",
                wraplength=390,
                justify="left",
            ).grid(row=1, column=1, sticky="w", pady=(2, 0))

            label, command, primary = self._provider_action(pid)
            _button(row, label, command, kind="primary" if primary else "ghost", height=30, font_size=9).grid(
                row=0, column=2, rowspan=2, sticky="e"
            )
            if catalog.PROVIDER_BY_ID.get(pid, {}).get("custom"):
                _button(
                    row, "Editar", lambda pid=pid: self._open_edit_provider(pid),
                    kind="ghost", height=28, font_size=9,
                ).grid(row=0, column=3, rowspan=2, sticky="e", padx=(6, 0))

    def _provider_action(self, pid: str) -> tuple[str, object, bool]:
        if catalog.PROVIDER_BY_ID.get(pid, {}).get("custom"):
            return "Probar", lambda pid=pid: self._refresh([pid], manual=True), not self._provider_ready(pid)
        if pid == "openrouter":
            info = self.access.get("openrouter") or {}
            if info.get("ok"):
                return "Comprobar", self._detect_statuses, False
            if config.openrouter_key(self.cfg):
                return "Revisar clave", self._edit_openrouter_key, True
            return "Añadir clave", self._edit_openrouter_key, True
        if pid == "ollama":
            if not self.statuses.get("ollama"):
                return "Descargar", lambda: local.open_url("https://ollama.com/download"), True
            if not self.statuses.get("ollama_running"):
                return "Iniciar servidor", self._start_ollama, True
            return "Comprobar", self._detect_statuses, False
        if not self.statuses.get(pid):
            url = (
                "https://opencode.ai"
                if pid == "opencode"
                else "https://claude.com/claude-code"
            )
            return "Descargar", lambda url=url: local.open_url(url), True
        return "Comprobar", self._detect_statuses, False

    # -- proveedores añadidos por el usuario ----------------------------------

    def _open_edit_provider(self, pid: str) -> None:
        record = custom.get(self.cfg, pid)
        if record is None:
            messagebox.showerror("Editar proveedor", "Ese proveedor no existe.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title(f"Editar {record.get('name', pid)} · AI Hub")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.resizable(False, True)
        width, height = 520, min(self.winfo_screenheight() - 60, 440)
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        win.bind("<Escape>", lambda _e: win.destroy())

        container = tk.Frame(win, bg=BG, padx=24, pady=18)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        tk.Label(container, text="Editar proveedor", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(container, text="Deja la clave vacía para no cambiarla.", bg=BG, fg=MUTED, font=(FONT, 9)).grid(
            row=1, column=0, sticky="w", pady=(2, 12)
        )

        def field(row: int, title: str, var: tk.StringVar, show: str = "") -> tk.Entry:
            tk.Label(container, text=title, bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=row * 2, column=0, sticky="w")
            frame = tk.Frame(container, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
            frame.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(3, 8))
            entry = tk.Entry(
                frame, textvariable=var, show=show, bg=INPUT, fg=TEXT, insertbackground=TEXT,
                relief="flat", bd=0, highlightthickness=0, font=(MONO, 9),
            )
            entry.pack(fill="x", padx=8, pady=7)
            return entry

        name_var = tk.StringVar(value=str(record.get("name") or ""))
        base_var = tk.StringVar(value=str(record.get("base") or ""))
        key_var = tk.StringVar(value="")
        field(2, "NOMBRE", name_var)
        field(3, "URL BASE", base_var)
        field(4, "NUEVA CLAVE (opcional)", key_var, show="•")

        cat_frame = tk.Frame(container, bg=BG)
        cat_frame.grid(row=10, column=0, sticky="w", pady=(4, 8))
        code_var = tk.BooleanVar(value="code" in (record.get("categories") or []))
        media_var = tk.BooleanVar(value="media" in (record.get("categories") or []))
        tk.Checkbutton(cat_frame, text="Programación", variable=code_var, bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG).pack(side="left")
        tk.Checkbutton(cat_frame, text="Imagen y vídeo", variable=media_var, bg=BG, fg=TEXT, selectcolor=PANEL, activebackground=BG).pack(side="left", padx=(12, 0))

        status = tk.Label(container, text="", bg=BG, fg=MUTED, font=(FONT, 8), wraplength=480, justify="left", anchor="w")
        status.grid(row=11, column=0, sticky="ew", pady=(0, 8))

        buttons = tk.Frame(container, bg=BG)
        buttons.grid(row=12, column=0, sticky="ew")
        save_btn = _button(buttons, "Guardar y leer modelos", lambda: save(), kind="primary", height=34, bold=True)
        save_btn.pack(side="right")
        _button(buttons, "Cerrar", win.destroy, kind="ghost", height=34).pack(side="right", padx=(0, 8))

        def save() -> None:
            name = name_var.get().strip() or str(record.get("name") or pid)
            base = base_var.get().strip().rstrip("/")
            key = key_var.get().strip()
            if not base:
                status.configure(text="Escribe la URL base.", fg=RED)
                return
            if not re.match(r"^https?://", base):
                status.configure(text="La URL debe empezar por http:// o https://", fg=RED)
                return
            cats = []
            if code_var.get():
                cats.append("code")
            if media_var.get():
                cats.append("media")
            if not cats:
                cats = ["code"]

            records = custom.records(self.cfg)
            target = next((r for r in records if r.get("id") == pid), None)
            if target is None:
                status.configure(text="Proveedor no encontrado.", fg=RED)
                return
            target["name"] = name
            target["base"] = base
            if key:
                target["key"] = key
            target["categories"] = cats

            self.cfg["custom_providers"] = records
            config.update_config(custom_providers=records)
            custom.register(self.cfg)

            status.configure(text="Guardando y leyendo los modelos…", fg=AMBER)
            save_btn.configure(state="disabled")
            result: dict = {}

            def work() -> None:
                try:
                    result["models"] = custom.fetch(target)
                except Exception as exc:  # noqa: BLE001
                    result["error"] = str(exc)

            threading.Thread(target=work, daemon=True).start()

            def poll() -> None:
                try:
                    if not win.winfo_exists():
                        return
                except tk.TclError:
                    return
                if "models" in result:
                    models = result["models"]
                    catalog.store_models(pid, models)
                    target["categories"] = custom.categories_of(models) or cats
                    records2 = [r for r in custom.records(self.cfg) if r.get("id") != pid] + [target]
                    self.cfg["custom_providers"] = records2
                    config.update_config(custom_providers=records2)
                    custom.register(self.cfg)
                    self._refresh([pid], manual=True)
                    status.configure(text="Proveedor actualizado.", fg=GREEN)
                    save_btn.configure(state="normal")
                    return
                if "error" in result:
                    status.configure(text=result["error"][:300], fg=RED)
                    save_btn.configure(state="normal")
                    return
                win.after(200, poll)

            win.after(200, poll)


    def _open_add_provider(self) -> None:
        current = getattr(self, "add_win", None)
        if current is not None:
            try:
                if current.winfo_exists():
                    current.lift()
                    current.focus_force()
                    return
            except tk.TclError:
                pass

        win = tk.Toplevel(self)
        self.add_win = win
        win.title("Añadir proveedor · AI Hub")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.resizable(False, True)
        width, height = 640, min(self.winfo_screenheight() - 60, 640)
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        win.bind("<Escape>", lambda _e: win.destroy())

        container = tk.Frame(win, bg=BG, padx=24, pady=18)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        tk.Label(container, text="Añadir proveedor", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        tk.Label(
            container,
            text="Conecta tu cuenta. Sus modelos aparecen en la pestaña que les corresponda.",
            bg=BG, fg=MUTED, font=(FONT, 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        presets = {item["name"]: item for item in custom.PRESETS}
        tk.Label(container, text="PROVEEDOR", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=2, column=0, sticky="w")
        preset_var = tk.StringVar(value=custom.PRESETS[0]["name"])
        box = ttk.Combobox(container, values=list(presets), state="readonly", textvariable=preset_var, font=(FONT, 9))
        box.grid(row=3, column=0, sticky="ew", pady=(4, 2))
        help_label = tk.Label(container, text="", bg=BG, fg=DIM, font=(FONT, 8), wraplength=580, justify="left", anchor="w")
        help_label.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        def field(row: int, title: str, var: tk.StringVar, show: str = "") -> tk.Entry:
            tk.Label(container, text=title, bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=row * 2 + 0, column=0, sticky="w")
            frame = tk.Frame(container, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
            frame.grid(row=row * 2 + 1, column=0, sticky="ew", pady=(3, 8))
            entry = tk.Entry(
                frame, textvariable=var, show=show, bg=INPUT, fg=TEXT, insertbackground=TEXT,
                relief="flat", bd=0, highlightthickness=0, font=(MONO, 9),
            )
            entry.pack(fill="x", padx=8, pady=7)
            return entry

        name_var = tk.StringVar(value=custom.PRESETS[0]["name"])
        base_var = tk.StringVar(value=custom.PRESETS[0]["base"])
        key_var = tk.StringVar(value="")
        field(3, "NOMBRE (cómo aparecerá)", name_var)
        field(4, "URL BASE", base_var)
        field(5, "CLAVE DE API", key_var, show="•")

        status = tk.Label(container, text="", bg=BG, fg=MUTED, font=(FONT, 8), wraplength=580, justify="left", anchor="w")
        status.grid(row=12, column=0, sticky="ew", pady=(0, 8))

        def apply_preset(_event=None) -> None:
            item = presets[preset_var.get()]
            name_var.set("" if item["id"] == "custom" else item["name"])
            base_var.set(item["base"])
            help_label.configure(text=item["help"])
            status.configure(text="")

        box.bind("<<ComboboxSelected>>", apply_preset)
        apply_preset()

        buttons = tk.Frame(container, bg=BG)
        buttons.grid(row=13, column=0, sticky="ew")
        connect_btn = _button(buttons, "Conectar", lambda: connect(), kind="primary", height=34, bold=True)
        connect_btn.pack(side="right")
        _button(buttons, "Cerrar", win.destroy, kind="ghost", height=34).pack(side="right", padx=(0, 8))

        tk.Label(container, text="PROVEEDORES CONECTADOS", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(
            row=14, column=0, sticky="w", pady=(18, 6)
        )
        listing = tk.Frame(container, bg=BG)
        listing.grid(row=15, column=0, sticky="ew")
        listing.columnconfigure(0, weight=1)

        def fill_listing() -> None:
            for child in listing.winfo_children():
                child.destroy()
            records = custom.records(self.cfg)
            if not records:
                tk.Label(listing, text="Todavía no has añadido ninguno.", bg=BG, fg=DIM, font=(FONT, 9)).pack(anchor="w")
                return
            for index, record in enumerate(records):
                row = tk.Frame(listing, bg=PANEL, highlightbackground=BORDER, highlightthickness=1, padx=12, pady=8)
                row.grid(row=index, column=0, sticky="ew", pady=(0, 6))
                row.columnconfigure(0, weight=1)
                tk.Label(row, text=record["name"], bg=PANEL, fg=TEXT, font=(FONT, 10, "bold"), anchor="w").grid(
                    row=0, column=0, sticky="w"
                )
                tk.Label(
                    row, text=self._provider_status_text(record["id"]), bg=PANEL, fg=MUTED, font=(FONT, 8),
                    anchor="w", justify="left", wraplength=460,
                ).grid(row=1, column=0, sticky="w")
                _button(
                    row, "Quitar", lambda pid=record["id"]: remove(pid), kind="ghost", height=28, font_size=9
                ).grid(row=0, column=1, rowspan=2, sticky="e")

        def remove(pid: str) -> None:
            self._remove_custom(pid, parent=win)
            fill_listing()

        def connect() -> None:
            item = presets[preset_var.get()]
            name = name_var.get().strip() or item["name"]
            base = base_var.get().strip().rstrip("/")
            key = key_var.get().strip()
            if not base:
                status.configure(text="Escribe la URL base del servicio.", fg=RED)
                return
            if not key:
                status.configure(text="Escribe la clave de API.", fg=RED)
                return
            record = {
                "id": custom.unique_id(self.cfg, item["id"]),
                "name": name,
                "preset": item["id"],
                "base": base,
                "key": key,
                "glyph": item["glyph"],
                "color": item["color"],
            }
            status.configure(text="Conectando y leyendo los modelos…", fg=AMBER)
            connect_btn.configure(state="disabled")
            result: dict = {}

            def work() -> None:
                try:
                    result["models"] = custom.fetch(record)
                except Exception as exc:  # noqa: BLE001
                    result["error"] = str(exc)

            threading.Thread(target=work, daemon=True).start()

            def poll() -> None:
                try:
                    if not win.winfo_exists():
                        return
                except tk.TclError:
                    return
                if "models" in result:
                    self._finish_connect(win, record, result["models"])
                    return
                if "error" in result:
                    status.configure(text=result["error"][:300], fg=RED)
                    connect_btn.configure(state="normal")
                    return
                win.after(200, poll)

            win.after(200, poll)

        fill_listing()

    def _finish_connect(self, win: tk.Toplevel, record: dict, models: list) -> None:
        record["categories"] = custom.categories_of(models)
        records = [item for item in custom.records(self.cfg) if item["id"] != record["id"]] + [record]
        self.cfg["custom_providers"] = records
        config.update_config(custom_providers=records)
        custom.register(self.cfg)
        catalog.store_models(record["id"], models)
        self.catalogs[record["id"]] = models
        try:
            win.destroy()
        except tk.TclError:
            pass
        target = self.category if self.category in record["categories"] else record["categories"][0]
        self._select_category(target)
        self._select_provider(record["id"])
        self._render_all()
        self._update_statuses_ui()
        self._refresh_access_dialog()
        counts = []
        if "code" in record["categories"]:
            counts.append(f"{sum(1 for m in models if m.category == 'code')} de programación")
        if "media" in record["categories"]:
            counts.append(f"{sum(1 for m in models if m.category != 'code')} de imagen")
        self._set_status(f"{record['name']} conectado: " + " · ".join(counts))

    def _remove_custom(self, pid: str, parent: tk.Misc | None = None) -> None:
        name = catalog.PROVIDER_BY_ID.get(pid, {}).get("name", pid)
        if not messagebox.askyesno(
            "Quitar proveedor",
            f"¿Quitar {name}? Se borrará la clave guardada en este equipo.",
            parent=parent or self,
        ):
            return
        records = [item for item in custom.records(self.cfg) if item["id"] != pid]
        self.cfg["custom_providers"] = records
        config.update_config(custom_providers=records)
        custom.register(self.cfg)
        self.catalogs.pop(pid, None)
        catalog.store_models(pid, [])
        # Un modelo de ese proveedor seleccionado dejaría de tener proveedor válido.
        if self.selected is not None and self.selected.provider == pid:
            self.selected = None
        if self.provider == pid:
            supported = self._providers_for(self.category) or ["opencode"]
            self._select_provider(supported[0])
        self._render_all()
        self._update_statuses_ui()
        self._refresh_access_dialog()
        self._set_status(f"{name} quitado")

    def _edit_openrouter_key(self) -> None:
        win = getattr(self, "access_win", None)
        if win is not None and win.winfo_exists():
            win.destroy()
        self.after(120, self._open_settings)

    def _start_ollama(self) -> None:
        self._set_status("Arrancando el servidor de Ollama…")

        def work() -> None:
            started = local.start_ollama()
            self.q.put(("status", "Ollama en marcha" if started else "No se pudo arrancar Ollama"))
            self._detect_statuses()

        threading.Thread(target=work, daemon=True).start()

    def _require_openrouter(self) -> bool:
        """True si hay clave válida; si no, pide lo necesario."""
        info = self.access.get("openrouter") or {}
        if info.get("ok"):
            return True
        if not info and config.openrouter_key(self.cfg):
            return True  # todavía sin comprobar: dejamos que la API responda
        if not config.openrouter_key(self.cfg):
            win = tk.Toplevel(self)
            win.title("Falta la clave de OpenRouter")
            win.configure(bg=BG)
            win.transient(self)
            win.grab_set()
            win.resizable(False, False)
            frame = tk.Frame(win, bg=BG, padx=26, pady=22)
            frame.pack(fill="both", expand=True)
            tk.Label(
                frame, text="Falta la clave de OpenRouter", bg=BG, fg=TEXT, font=(FONT, 14, "bold")
            ).pack(anchor="w")
            tk.Label(
                frame,
                text="OpenRouter es necesario para chatear, generar imágenes y vídeos.\n"
                "La clave es gratuita y se crea en openrouter.ai/keys.",
                bg=BG,
                fg=MUTED,
                font=(FONT, 9),
                wraplength=430,
                justify="left",
            ).pack(anchor="w", pady=(8, 14))
            buttons = tk.Frame(frame, bg=BG)
            buttons.pack(anchor="e")
            _button(
                buttons,
                "Crear clave ↗",
                lambda: local.open_url("https://openrouter.ai/keys"),
                kind="ghost",
                height=32,
            ).pack(side="left", padx=(0, 8))
            _button(buttons, "Añadir a Ajustes", self._edit_openrouter_key, kind="primary", height=32, bold=True).pack(
                side="left"
            )
            win.bind("<Escape>", lambda _e: win.destroy())
            self._center_on_parent(win, 520, 230)
            return False
        messagebox.showerror(
            "No se puede usar OpenRouter",
            info.get("message") or "La clave no es válida. Revísala en Ajustes.",
            parent=self,
        )
        return False

    def _require_ollama(self) -> bool:
        if self.statuses.get("ollama_running"):
            return True
        if not self.statuses.get("ollama"):
            messagebox.showinfo(
                "Falta Ollama",
                "Ollama no está instalado en este equipo.\n\nDescárgalo en ollama.com/download.",
                parent=self,
            )
            local.open_url("https://ollama.com/download")
            return False
        if messagebox.askyesno(
            "Ollama no responde",
            "Ollama está instalado pero el servidor no está en marcha.\n\n¿Quieres arrancarlo ahora?",
            parent=self,
        ):
            self._start_ollama()
        return False

    def _require_cli(self, provider: str) -> bool:
        if local.installed(provider):
            return True
        name = "OpenCode" if provider == "opencode" else "Claude Code"
        url = "https://opencode.ai" if provider == "opencode" else "https://claude.com/claude-code"
        if messagebox.askyesno(
            f"Falta {name}",
            f"{name} no está instalado en este equipo.\n\n¿Quieres abrir su página de descarga?",
            parent=self,
        ):
            local.open_url(url)
        return False

    def _center_on_parent(self, win: tk.Toplevel, width: int, height: int) -> None:
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    # -- precios de imagen --------------------------------------------------

    def _ensure_image_prices(self) -> None:
        models = [m for m in self.catalogs.get("openrouter", []) if m.category == "image"]
        if not models:
            return
        prices, ts = catalog.cached_image_prices()
        if ts and time.time() - ts < 7 * 86400:
            return
        if self.refreshing:
            return
        ids = [m.uid for m in models]

        def work() -> None:
            self.q.put(("status", "Calculando precios de imagen…"))
            fresh = api.image_endpoint_prices(ids)
            if fresh:
                catalog.store_image_prices(fresh)
                catalog.apply_image_prices(models, fresh)
                catalog.store_models("openrouter", self.catalogs.get("openrouter", []))
                self.q.put(("image_prices", None))

        threading.Thread(target=work, daemon=True).start()

    # -- proyecto de trabajo -------------------------------------------------

    def _current_project(self) -> Path | None:
        raw = str(self.cfg.get("workdir") or "").strip()
        return Path(raw) if raw else None

    def _update_project_button(self) -> None:
        return

    def _set_project(self, path: Path) -> None:
        path = Path(path)
        if not path.is_dir():
            messagebox.showwarning(
                "Proyecto no encontrado",
                f"La carpeta ya no existe:\n{path}",
                parent=self,
            )
            return
        self.cfg["workdir"] = str(path)
        config.update_config(workdir=str(path))
        self._update_project_button()
        self._refresh_files()
        self._update_detail()
        if not self.busy and not self.history:
            self._clear_output()
        self._set_status(f"Proyecto de trabajo: {path}")

    def _set_no_project(self) -> None:
        self.cfg["workdir"] = ""
        config.update_config(workdir="")
        self._update_project_button()
        self._refresh_files()
        self._update_detail()
        if not self.busy and not self.history:
            self._clear_output()
        self._set_status("Sin proyecto: chat, imágenes y vídeos. Sin archivos del proyecto.")

    def _flow_blocked(self, model: catalog.Model) -> bool:
        """Pide el proyecto si la acción lo necesita (CLI o herramientas de archivos)."""
        project = self._current_project()
        if model.provider in ("opencode", "claude") and project is None:
            self._set_status("Paso 1: elige el proyecto donde trabajar")
            self._open_project_picker()
            return True
        if (
            self._is_api(model.provider)
            and self.tools_var.get()
            and _supports_tools(model)
            and project is None
        ):
            answer = messagebox.askyesno(
                "Falta el proyecto",
                "Has activado «Leer y escribir archivos», pero no hay proyecto elegido.\n\n"
                "¿Quieres elegir uno ahora?\n\n"
                "Si prefieres solo conversar, pulsa «No» y la app desactivará el acceso a archivos.",
                parent=self,
            )
            if answer:
                self._open_project_picker()
            else:
                self.tools_var.set(False)
                self._refresh_tools_hint()
                self._update_conversation_header()
            return True
        return False

    def _flow_steps(self) -> list[tuple[bool, str, str]]:
        """Estado de los cuatro pasos del flujo: (hecho, título, detalle)."""
        project = self._current_project()
        model = self.selected
        steps = [
            (project is not None, "Proyecto", project.name if project else "elige uno con Ctrl+P"),
            (model is not None, "Proveedor", catalog.PROVIDER_BY_ID[model.provider]["name"] if model else "elige en la columna izquierda"),
            (model is not None, "Modelo", model.name if model else "elige en la lista"),
            (bool(self.history), "Describe lo que necesitas", "escribe abajo y pulsa Enter"),
        ]
        return steps

    def _needs_project(self) -> bool:
        """Avisa si la acción requiere un proyecto y no hay ninguno elegido."""
        if self._current_project() is not None:
            return False
        messagebox.showinfo(
            "Elige un proyecto",
            "OpenCode, Claude Code y Ollama trabajan dentro de un proyecto.\n\n"
            "Elige «Sin proyecto» solo si vas a generar imágenes, vídeos o chatear con OpenRouter.",
            parent=self,
        )
        self._open_project_picker()
        return True

    def _open_project_picker(self, startup: bool = False) -> None:
        win = tk.Toplevel(self)
        win.title("Proyecto de trabajo · AI Hub")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.resizable(False, True)

        width = 660
        listing_count = 1 + len(projects.list_projects(self.cfg))
        height = max(420, min(580, 300 + listing_count * 34))
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

        container = tk.Frame(win, bg=BG, padx=24, pady=20)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        tk.Label(
            container, text="¿En qué proyecto trabajamos?", bg=BG, fg=TEXT, font=(FONT, 16, "bold")
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            container,
            text="Las consolas (OpenCode, Claude Code, Ollama) y las consultas se ejecutan dentro de esta carpeta. "
            "Para imágenes y fotos no hace falta proyecto: elige «Sin proyecto».",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
            wraplength=580,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(3, 14))

        root = projects.root(self.cfg)
        tree_frame = tk.Frame(container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        tree_frame.grid(row=3, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        tree = ttk.Treeview(
            tree_frame,
            columns=("name", "meta"),
            show="headings",
            style="AIH.Treeview",
            selectmode="browse",
        )
        tree.heading("name", text="PROYECTO", anchor="w")
        tree.heading("meta", text="DETALLE", anchor="w")
        tree.column("name", width=220, minwidth=160, stretch=True)
        tree.column("meta", width=360, minwidth=220, stretch=True)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            tree_frame, orient="vertical", command=tree.yview, style="AIH.Vertical.TScrollbar"
        )
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)
        tree.tag_configure("root", foreground=CYAN)
        tree.tag_configure("none", foreground=AMBER)

        path_label = tk.Label(
            container, text="", bg=BG, fg=DIM, font=(MONO, 8), anchor="w", wraplength=580, justify="left"
        )
        path_label.grid(row=4, column=0, sticky="ew", pady=(6, 0))

        rows: list[dict] = []

        def fill(select: Path | None = None) -> None:
            rows.clear()
            for item in tree.get_children():
                tree.delete(item)
            current = self._current_project()
            listing = projects.list_projects(self.cfg)
            if current is not None:
                listing = projects.with_current(listing, current)
            rows.append({"name": "Sin proyecto", "path": None, "none": True})
            rows.extend(listing)
            target = None
            for index, item in enumerate(rows):
                if item.get("none"):
                    tree.insert(
                        "",
                        "end",
                        iid=str(index),
                        values=("Sin proyecto", "Solo imágenes, fotos y vídeos · sin carpeta"),
                        tags=("none",),
                    )
                    if select is None and current is None:
                        target = str(index)
                    continue
                tags = ("root",) if item.get("root") else ()
                tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(item["name"], projects.detail_text(item)),
                    tags=tags,
                )
                if select is not None:
                    if item["path"] == select:
                        target = str(index)
                elif current is not None and item["path"] == current:
                    target = str(index)
            if target is None:
                target = "0"
            tree.selection_set(target)
            tree.focus(target)
            tree.see(target)
            show_path()

        def selected_row() -> dict | None:
            selection = tree.selection()
            if not selection:
                return None
            try:
                return rows[int(selection[0])]
            except (IndexError, ValueError):
                return None

        def show_path(_event=None) -> None:
            row = selected_row()
            if not row:
                path_label.configure(text=str(root))
            elif row.get("none"):
                folder = config.image_dir(self.cfg)
                path_label.configure(
                    text=f"Sin proyecto · las imágenes y vídeos se guardan en {folder.parent}"
                )
            else:
                path_label.configure(text=str(row["path"]))

        def confirm(_event=None) -> None:
            row = selected_row()
            if not row:
                return
            if row.get("none"):
                self._set_no_project()
            else:
                self._set_project(row["path"])
            win.destroy()

        def new_folder() -> None:
            name = simpledialog.askstring(
                "Nuevo proyecto",
                "Nombre de la carpeta del proyecto:",
                parent=win,
            )
            if not name:
                return
            try:
                created = projects.create(root, name)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("No se pudo crear", str(exc), parent=win)
                return
            fill(created)

        def other_folder() -> None:
            chosen = filedialog.askdirectory(
                parent=win, initialdir=str(root), title="Elegir carpeta del proyecto", mustexist=True
            )
            if chosen:
                fill(Path(chosen))

        tree.bind("<<TreeviewSelect>>", show_path)
        tree.bind("<Double-1>", confirm)
        tree.bind("<Return>", confirm)

        footer = tk.Frame(container, bg=BG)
        footer.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        footer.columnconfigure(0, weight=1)

        links = tk.Frame(footer, bg=BG)
        links.grid(row=0, column=0, sticky="w")
        _button(links, "Nueva carpeta…", new_folder, kind="link", height=0, font_size=9).pack(side="left")
        _button(links, "Otro…", other_folder, kind="link", height=0, font_size=9).pack(
            side="left", padx=(14, 0)
        )

        actions = tk.Frame(footer, bg=BG)
        actions.grid(row=0, column=1, sticky="e")
        _button(actions, "Trabajar aquí", confirm, kind="primary", height=34, bold=True).pack(side="right")
        _button(actions, "Cancelar", win.destroy, kind="ghost", height=34).pack(side="right", padx=(0, 8))

        win.bind("<Escape>", lambda _e: win.destroy())
        fill()

        if startup:
            tree.focus_set()

    # -- ajustes ------------------------------------------------------------

    def _open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("Ajustes · AI Hub")
        win.configure(bg=BG)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        width, height = 600, 520
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

        container = tk.Frame(win, bg=BG, padx=26, pady=20)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)

        tk.Label(container, text="Ajustes", bg=BG, fg=TEXT, font=(FONT, 16, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            container,
            text="La clave se guarda solo en tu equipo (%APPDATA%\\AIHub).",
            bg=BG,
            fg=MUTED,
            font=(FONT, 9),
        ).grid(row=1, column=0, sticky="w", pady=(2, 16))

        tk.Label(container, text="CLAVE DE OPENROUTER", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=2, column=0, sticky="w")
        key_var = tk.StringVar(value=str(self.cfg.get("openrouter_api_key") or ""))
        key_row = tk.Frame(container, bg=INPUT, highlightbackground=BORDER, highlightthickness=1)
        key_row.grid(row=3, column=0, sticky="ew", pady=(4, 3))
        key_row.columnconfigure(0, weight=1)
        key_entry = tk.Entry(
            key_row,
            textvariable=key_var,
            show="•",
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(MONO, 9),
        )
        key_entry.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        visible = {"value": False}

        def toggle_key() -> None:
            visible["value"] = not visible["value"]
            key_entry.configure(show="" if visible["value"] else "•")
            ver_btn.configure(text="ocultar" if visible["value"] else "ver")

        link_row = tk.Frame(container, bg=BG)
        link_row.grid(row=4, column=0, sticky="ew", pady=(0, 16))
        env_key = not str(self.cfg.get("openrouter_api_key") or "").strip() and bool(
            os.environ.get("OPENROUTER_API_KEY", "").strip()
        )
        if env_key:
            link_text = "Sin clave guardada: se usa la variable OPENROUTER_API_KEY del sistema."
        else:
            link_text = "Se usa para chat, imagen y vídeo. Consíguela en openrouter.ai/keys"
        tk.Label(
            link_row,
            text=link_text,
            bg=BG,
            fg=GREEN if env_key else DIM,
            font=(FONT, 8),
            wraplength=330,
            justify="left",
        ).pack(side="left")
        _button(
            link_row, "abrir ↗", lambda: local.open_url("https://openrouter.ai/keys"), kind="link", height=0, font_size=8
        ).pack(side="right")
        ver_btn = _button(link_row, "ver", toggle_key, kind="link", height=0, font_size=8)
        ver_btn.pack(side="right", padx=(0, 10))

        tk.Label(
            container,
            text="PROYECTO DE TRABAJO (CLIs) · vacío = sin proyecto",
            bg=BG,
            fg=DIM,
            font=(FONT, 8, "bold"),
        ).grid(row=5, column=0, sticky="w")
        work_var = tk.StringVar(value=str(self.cfg.get("workdir") or ""))
        work_row = tk.Frame(container, bg=BG)
        work_row.grid(row=6, column=0, sticky="ew", pady=(4, 12))
        work_row.columnconfigure(0, weight=1)
        work_entry = tk.Entry(
            work_row,
            textvariable=work_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            font=(FONT, 9),
        )
        work_entry.grid(row=0, column=0, sticky="ew", ipady=7)
        _button(
            work_row,
            "Elegir…",
            lambda: self._choose_dir(work_var),
            kind="ghost",
            height=32,
            font_size=9,
        ).grid(row=0, column=1, padx=(6, 0))

        tk.Label(container, text="CARPETA DE SALIDA (IMÁGENES Y VÍDEOS)", bg=BG, fg=DIM, font=(FONT, 8, "bold")).grid(row=7, column=0, sticky="w")
        out_var = tk.StringVar(value=str(self.cfg.get("output_root") or ""))
        out_row = tk.Frame(container, bg=BG)
        out_row.grid(row=8, column=0, sticky="ew", pady=(4, 12))
        out_row.columnconfigure(0, weight=1)
        out_entry = tk.Entry(
            out_row,
            textvariable=out_var,
            bg=INPUT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            highlightbackground=BORDER,
            highlightthickness=1,
            font=(FONT, 9),
        )
        out_entry.grid(row=0, column=0, sticky="ew", ipady=7)
        _button(
            out_row,
            "Elegir…",
            lambda: self._choose_dir(out_var),
            kind="ghost",
            height=32,
            font_size=9,
        ).grid(row=0, column=1, padx=(6, 0))

        auto_var = tk.BooleanVar(value=bool(self.cfg.get("auto_refresh", True)))
        tk.Checkbutton(
            container,
            text="Actualizar el catálogo al abrir la app",
            variable=auto_var,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL_3,
            font=(FONT, 9),
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        ).grid(row=9, column=0, sticky="w", pady=(4, 0))

        tk.Label(
            container,
            text="Los precios son informativos y se obtienen de OpenRouter / OpenCode.\n"
            "El vídeo y la imagen se cobran en tu cuenta de OpenRouter.",
            bg=BG,
            fg=DIM,
            font=(FONT, 8),
            justify="left",
        ).grid(row=10, column=0, sticky="w", pady=(14, 0))

        buttons = tk.Frame(container, bg=BG)
        buttons.grid(row=11, column=0, sticky="ew", pady=(20, 0))
        buttons.columnconfigure(0, weight=1)

        status_label = tk.Label(
            buttons, text="", bg=BG, fg=MUTED, font=(FONT, 8), wraplength=280, justify="left", anchor="w"
        )
        status_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        right_buttons = tk.Frame(buttons, bg=BG)
        right_buttons.grid(row=0, column=1, sticky="e")

        def test_key() -> None:
            status_label.configure(text="Comprobando la clave…", fg=AMBER)
            key_value = key_var.get().strip()
            result: dict = {}

            def work() -> None:
                result["r"] = api.check_openrouter(key_value)

            threading.Thread(target=work, daemon=True).start()

            def poll() -> None:
                try:
                    if not win.winfo_exists():
                        return
                except tk.TclError:
                    return
                if "r" not in result:
                    win.after(200, poll)
                    return
                info = result["r"]
                if info.get("ok"):
                    bits = ["Clave válida"]
                    if isinstance(info.get("free_remaining"), int):
                        bits.append(f"{info['free_remaining']} peticiones gratis hoy")
                    credits = info.get("credits")
                    if isinstance(credits, (int, float)):
                        bits.append(f"saldo ${credits:.2f}" if credits > 0 else "sin saldo (solo gratis)")
                    status_label.configure(text=" · ".join(bits), fg=GREEN if not isinstance(credits, (int, float)) or credits > 0 else AMBER)
                else:
                    status_label.configure(text=str(info.get("message") or "Clave no válida")[:160], fg=RED)

            win.after(200, poll)

        _button(right_buttons, "Probar", test_key, kind="ghost", height=34).pack(side="left", padx=(0, 8))
        cancel = _button(right_buttons, "Cancelar", win.destroy, kind="ghost", height=34)
        cancel.pack(side="left", padx=(0, 8))

        def save() -> None:
            key = key_var.get().strip()
            workdir = work_var.get().strip()
            output = out_var.get().strip() or config.DEFAULTS["output_root"]
            if workdir and not Path(workdir).is_dir():
                messagebox.showwarning("Carpeta no válida", "La carpeta de trabajo no existe.", parent=win)
                return
            self.cfg["openrouter_api_key"] = key
            self.cfg["workdir"] = workdir
            self.cfg["output_root"] = output
            self.cfg["auto_refresh"] = bool(auto_var.get())
            config.update_config(
                openrouter_api_key=key,
                workdir=workdir,
                output_root=output,
                auto_refresh=bool(auto_var.get()),
            )
            Path(output).mkdir(parents=True, exist_ok=True)
            win.destroy()
            self._update_project_button()
            self._refresh_files()
            self._update_detail()
            self._update_cache_label()
            self._set_status("Ajustes guardados")
            self._detect_statuses()
            if key and len(self.catalogs.get("openrouter", [])) == 0:
                self._refresh(["openrouter"], manual=True)

        save_btn = _button(right_buttons, "Guardar", save, kind="primary", height=34, bold=True)
        save_btn.pack(side="left")

        key_entry.focus_set()
        win.bind("<Escape>", lambda _e: win.destroy())
        win.bind("<Return>", lambda _e: save())

    def _choose_dir(self, variable: tk.StringVar) -> None:
        selected = filedialog.askdirectory(parent=self)
        if selected:
            variable.set(selected)

    # -- cierre -------------------------------------------------------------

    def _seed_account_config(self, legacy: dict) -> None:
        """Si la cuenta recién activada está vacía, hereda la configuración local.

        Así al iniciar sesión por primera vez no desaparecen las claves, los
        proveedores propios ni los proyectos que ya se usaban en este equipo.
        """
        try:
            cfg = config.load_config()
            if cfg.get("openrouter_api_key") or cfg.get("custom_providers") or cfg.get("last_models"):
                return
            for key in (
                "openrouter_api_key",
                "custom_providers",
                "workdir",
                "projects_root",
                "output_root",
                "last_provider",
                "last_category",
                "last_models",
                "favorite_models",
                "auto_refresh",
                "usage",
            ):
                if key in legacy:
                    cfg[key] = legacy[key]
            config.save_config(cfg)
        except Exception:
            pass

    def _prompt_login(self):
        from aihub.web import users as web_users

        result = {"user": None}

        win = tk.Toplevel(self)
        win.title("Iniciar sesión · AI Hub")
        win.configure(bg=BG)
        win.resizable(False, False)

        width, height = 390, 310
        x = max(0, (win.winfo_screenwidth() - width) // 2)
        y = max(0, (win.winfo_screenheight() - height) // 3)
        win.geometry(f"{width}x{height}+{x}+{y}")

        def cancel() -> None:
            result["user"] = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", cancel)

        tk.Label(win, text="AI HUB", bg=BG, fg=TEXT, font=(FONT, 14, "bold")).pack(pady=(18, 2))
        tk.Label(win, text="Inicia sesión para usar tu cuenta", bg=BG, fg=MUTED, font=(FONT, 9)).pack(pady=(0, 12))

        form = tk.Frame(win, bg=BG)
        form.pack(fill="x", padx=24)

        tk.Label(form, text="Usuario", bg=BG, fg=DIM, font=(FONT, 8, "bold")).pack(anchor="w")
        name_var = tk.StringVar()
        name_entry = tk.Entry(form, textvariable=name_var, bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=(FONT, 10))
        name_entry.pack(fill="x", pady=(2, 8), ipady=4)

        tk.Label(form, text="Contraseña", bg=BG, fg=DIM, font=(FONT, 8, "bold")).pack(anchor="w")
        pass_var = tk.StringVar()
        pass_entry = tk.Entry(form, textvariable=pass_var, show="*", bg=INPUT, fg=TEXT, insertbackground=TEXT, relief="flat", bd=0, highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=(FONT, 10))
        pass_entry.pack(fill="x", pady=(2, 8), ipady=4)

        error_var = tk.StringVar()
        tk.Label(form, textvariable=error_var, bg=BG, fg=RED, font=(FONT, 8)).pack(anchor="w")

        def submit(_event=None):
            user = web_users.verify(name_var.get(), pass_var.get())
            if user:
                result["user"] = user
                win.destroy()
            else:
                error_var.set("Usuario o contraseña incorrectos.")

        tk.Button(
            form, text="Entrar", command=submit, bg=ACCENT, fg="#ffffff", relief="flat", bd=0,
            font=(FONT, 10, "bold"), cursor="hand2", pady=6,
        ).pack(fill="x", pady=(6, 0))

        name_entry.bind("<Return>", submit)
        pass_entry.bind("<Return>", submit)

        # La ventana raíz aún no está visible: sin esto, el diálogo puede
        # quedarse oculto y la aplicación parecer que no abre.
        win.update_idletasks()
        win.deiconify()
        win.lift()
        try:
            win.attributes("-topmost", True)
            win.after(800, lambda: win.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            win.wait_visibility()
            win.grab_set()
        except tk.TclError:
            pass
        win.focus_force()
        name_entry.focus_set()

        self.wait_window(win)
        return result["user"]

    def _report_callback_error(self, exc, value, tb) -> None:
        """Registra errores de callbacks de Tk en un archivo en vez de perderlos."""
        import traceback

        text = "".join(traceback.format_exception(exc, value, tb))
        try:
            target = config.app_dir() / "error.log"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        except Exception:
            pass
        if getattr(self, "_error_shown", False):
            return
        self._error_shown = True
        try:
            messagebox.showerror("AI Hub", "Se produjo un error:\n\n" + str(value)[:600])
        except Exception:
            pass

    def _on_close(self) -> None:
        try:
            for child in list(self.winfo_children()):
                if isinstance(child, tk.Toplevel):
                    try:
                        child.destroy()
                    except Exception:
                        pass
            self.cancel_event.set()
        except Exception:
            pass
        if self.proc is not None:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self._save_current_conversation()
            self._save_conversation_state(include_current=True)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            try:
                self.quit()
            except Exception:
                pass


def run() -> None:
    app = MainWindow()
    try:
        if not app.winfo_exists():
            return
    except tk.TclError:
        return
    app.mainloop()
