# AI Hub · app de escritorio para elegir modelos de IA gratis y baratos.

Requisitos: **Python 3.10+** (con Tkinter) y conexión a internet.

## macOS

1. Instala Python si no lo tienes: `https://www.python.org/downloads/macos/` (o `brew install python-tk`).
2. Abre esta carpeta en Terminal y ejecuta:
   ```bash
   python3 -m compileall aihub
   python3 AIHub.pyw --selftest     # comprueba catálogos y APIs
   ./Iniciar_AI_Hub.command         # abre la app
   ```
3. Para tenerla siempre a mano, arrastra **`Iniciar_AI_Hub.command`** al Dock, o crea un
   alias: `Cmd+clic en el archivo → Crear alias`. También puedes generar un `.app` de verdad:

   ```bash
   python3 tools/make_mac_app.py
   open "dist/AI Hub.app"
   ```

   El `.app` lanza `python3 AIHub.pyw` desde la carpeta del proyecto.

Los proyectos se detectan en `~/Proyectos`. La configuración se guarda en
`~/Library/Application Support/AIHub`.

## Windows

- Doble clic en **`Iniciar AI Hub.vbs`** (o en el acceso directo del escritorio).
- **`run.bat`** abre la app mostrando la consola (útil para ver errores).
- **`Crear acceso directo.bat`** crea el acceso directo con su icono.

## Comprobaciones

```bash
python3 AIHub.pyw --selftest     # macOS/Linux
python  AIHub.pyw --selftest     # Windows
```

## Uso rápido

1. Elige proveedor y categoría; los modelos **gratis** salen primero.
2. Elige el modelo en la lista.
3. Escribe la consulta en el compositor y pulsa **Enter** (o `Ctrl+Enter`). `Shift+Enter` añade una línea.
   La conversación **recuerda los turnos anteriores**; el indicador «Contexto» de la cabecera muestra
   cuántos turnos y tokens aproximados se usan. «Nuevo chat» empieza de cero.
4. Para **leer y escribir archivos**, abre una carpeta con «abrir carpeta» (panel derecho) y activa
   «Leer y escribir archivos» bajo el compositor. Conversar, generar imágenes o vídeos no necesita
   carpeta.

La clave de OpenRouter se guarda en la app o en la variable `OPENROUTER_API_KEY`.