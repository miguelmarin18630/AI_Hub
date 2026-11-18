"""Arranque de la versión web.

Uso:
    python -m aihub.web run [--host 127.0.0.1] [--port 8765] [--open]
    python -m aihub.web add-user NOMBRE [--admin]
    python -m aihub.web reset-password NOMBRE
    python -m aihub.web list-users
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import users
from .server import run as run_server


def _input_password(label: str = "Contraseña: ") -> str:
    return getpass.getpass(label).strip()


def cmd_run(args: argparse.Namespace) -> int:
    if args.open:
        import webbrowser

        host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
        webbrowser.open(f"http://{host}:{args.port}/")
    run_server(args.host, args.port)
    return 0


def cmd_add_user(args: argparse.Namespace) -> int:
    password = args.password or _input_password("Contraseña (mínimo 8 caracteres): ")
    if len(password) < 8:
        print("La contraseña debe tener al menos 8 caracteres.")
        return 2
    try:
        user = users.create_user(args.name, password, "admin" if args.admin else "user")
    except ValueError as exc:
        print(f"No se pudo crear el usuario: {exc}")
        return 2
    print(f"Usuario creado: {user['id']} ({user['name']}) · rol {user['role']}")
    return 0


def cmd_reset_password(args: argparse.Namespace) -> int:
    user = users.get_user(args.name)
    if user is None:
        print("Usuario no encontrado.")
        return 2
    password = args.password or _input_password(f"Nueva contraseña para {user['id']}: ")
    try:
        users.set_password(user["id"], password)
    except ValueError as exc:
        print(str(exc))
        return 2
    print("Contraseña actualizada.")
    return 0


def cmd_list_users(_args: argparse.Namespace) -> int:
    items = users.list_users()
    if not items:
        print("Todavía no hay usuarios.")
        return 0
    for item in items:
        print(f"{item['id']:24} {item['name']:28} {item['role']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m aihub.web", description="AI Hub web")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Arranca el servidor web")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8765)
    run.add_argument("--open", action="store_true")
    run.set_defaults(func=cmd_run)

    add = sub.add_parser("add-user", help="Crea una cuenta")
    add.add_argument("name")
    add.add_argument("--admin", action="store_true")
    add.add_argument("--password", default="")
    add.set_defaults(func=cmd_add_user)

    reset = sub.add_parser("reset-password", help="Cambia la contraseña de una cuenta")
    reset.add_argument("name")
    reset.add_argument("--password", default="")
    reset.set_defaults(func=cmd_reset_password)

    listing = sub.add_parser("list-users", help="Lista las cuentas")
    listing.set_defaults(func=cmd_list_users)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
