# Manual de Continuación — AI Hub

> **Qué es este documento.** Es el **modelo de trabajo** para continuar el proyecto:
> cómo actualizar archivos, verificar, cambiar de versión y subir a GitHub.
> **No es un registro de cambios.** No se anota aquí cada modificación; el historial
> vive en los commits de Git. Este archivo solo cambia si cambia *el proceso*.

Ubicación fija: `C:\Proyectos\AI_HUB\MANUAL_CONTINUACION.md`

---

## 1. Resumen del proyecto

**AI Hub** es una app de escritorio (Windows/macOS) en español para ver y usar
modelos de IA: muestra qué modelos son gratis y cuáles son los más baratos, y
permite chatear con memoria de conversación, editar archivos de la carpeta de
trabajo, generar imágenes/vídeo y abrir el terminal con el modelo cargado.

- **Entrada:** `AIHub.pyw` + paquete `aihub/`
- **Versión web:** `python -m aihub.web run` (multiusuario, sin dependencias)
- **Proveedores:** OpenCode, Claude Code, Ollama, OpenRouter (+ proveedores
  personalizados compatibles con OpenAI: OpenAI, Gemini, Groq, DeepSeek, Mistral,
  Together AI, LM Studio…).
- **Categorías:** Programación (chat) e Imagen y vídeo.

## 2. Restricciones técnicas (no romper)

- **Python 3.10+ / Tkinter, solo biblioteca estándar.** No añadir dependencias de
  `pip`.
- **Interfaz y mensajes en español.**
- Nada de bloquear el hilo de la UI: el trabajo de red va en hilos y se comunica
  por la cola (`self.q`).
- **Contexto de conversación:** los mensajes se construyen con `aihub/chat.py`
  (`build_messages`, `build_cli_prompt`). No enviar `self.history` en bruto ni
  duplicar el mensaje del usuario. El recorte se hace por turnos completos,
  conserva las instrucciones del sistema y nunca parte una llamada a
  herramientas. El límite se obtiene con `chat.context_limit_for(model)`.
- La configuración del usuario vive en `%APPDATA%\AIHub\` (`config.json`,
  `cache.json`), **fuera** del repositorio. Nunca commitear claves.
- Si existen cuentas web (`%APPDATA%\AIHub\web\users.json`), el escritorio pide
  login y trabaja en la carpeta de esa cuenta
  (`%APPDATA%\AIHub\web\users\<id>\`). Así comparte claves, proyectos e historial
  con la web. Si no hay cuentas, funciona en modo local con `%APPDATA%\AIHub\`.
  La primera vez que una cuenta vacía inicia sesión en el escritorio, hereda la
  configuración local (claves, proveedores propios, proyectos y favoritos).

  > **Nota:** el login de escritorio está **desactivado por ahora** (versión
  > provisional). La app usa la configuración local hasta reactivarlo.

## 3. Estructura de archivos

| Archivo | Responsabilidad |
| --- | --- |
| `AIHub.pyw` | Punto de entrada; `--smoke`, `--selftest` |
| `aihub/__init__.py` | **Versión** (`__version__`) |
| `aihub/ui.py` | Ventana, paneles, chat, selector de modelos, diálogos |
| `aihub/catalog.py` | Modelos, catálogos, precios, refresco, OpenCode/Claude/Ollama |
| `aihub/custom.py` | Proveedores personalizados compatibles con OpenAI |
| `aihub/api.py` | Llamadas HTTP y traducción de errores |
| `aihub/chat.py` | Contexto de la conversación: sistema, historial, recorte y tokens |
| `aihub/agent.py` | Bucle de agente con herramientas (leer/escribir archivos) |
| `aihub/config.py` | Lectura/escritura de `config.json`; carpeta activa por usuario |
| `aihub/local.py` | Detección de CLIs, Ollama, procesos |
| `aihub/projects.py` | Proyectos y archivos |
| `aihub/usage.py` | Consumo diario y total por modelo |
| `aihub/web/server.py` | Servidor HTTP/SSE de la versión web |
| `aihub/web/users.py` | Cuentas, login, sesiones y carpetas por usuario |
| `aihub/web/static/` | HTML, CSS y JavaScript de la web |
| `README.md` | Documentación para el usuario final |
| `WEB.md` | Publicación de la web (Cloudflare Tunnel) |
| `LEEME-MAC.md` | Instrucciones específicas de macOS |

---

## 4. Modelo de trabajo (paso a paso)

### 4.1 Antes de empezar
1. Lee este manual y `README.md`.
2. Localiza el archivo responsable del cambio (tabla de la sección 3).
3. Comprueba que la app **no** está a medias de otra tarea.

### 4.2 Actualizar archivos
- Haz **ediciones dirigidas** sobre el archivo correcto; mantén el estilo, los
  nombres y los patrones existentes.
- Textos de UI en español, con el mismo tono que el resto.
- Si tocas una función compartida, revisa sus llamadas (por ejemplo `price_text`
  lo usan todos los proveedores).
- No reescribas archivos enteros si basta un cambio local.

### 4.3 Verificar (obligatorio)
```powershell
# 1) Compila los módulos tocados
C:\Python314\python.exe -m py_compile C:\Proyectos\AI_HUB\aihub\ui.py
C:\Python314\python.exe -m py_compile C:\Proyectos\AI_HUB\aihub\chat.py

# 2) Test rápido de la UI
C:\Python314\python.exe "C:\Proyectos\AI_HUB\AIHub.pyw" --smoke
# -> GUI smoke test OK

# 3) Autocomprobación (si tocas catálogos, proveedores o precios)
C:\Python314\python.exe "C:\Proyectos\AI_HUB\AIHub.pyw" --selftest
```

> Si tocas el contexto o el chat, prueba además **dos consultas seguidas** en la
> app reiniciada: la segunda debe recordar la primera y el indicador «Contexto»
> debe subir de turnos.

> **Importante:** los cambios de código **no** se aplican pulsando «Actualizar».
> Python no recarga módulos: hay que **cerrar y reabrir la app** para probar con
> el código nuevo. «Actualizar» solo vuelve a descargar catálogos.

**Si la app «no abre»:**
1. Ejecuta `run.bat` (abre consola y deja ver el error).
2. Al arrancar, el escritorio pide login si hay cuentas web; el diálogo se centra
   en pantalla y se trae al frente. Cerrar ese diálogo cierra la app.
3. Cualquier fallo de arranque se guarda en `%APPDATA%\AIHub\error.log` y se
   muestra en un cuadro de diálogo. Adjunta ese archivo al diagnosticar.
4. No hay bloqueo de instancia única: si una ventana no responde, ciérrala desde
   el Administrador de tareas (`pythonw.exe`) y vuelve a abrir.

### 4.4 Cambiar la versión
La versión está **solo** en `aihub/__init__.py`:
```python
__version__ = "1.0.0"
```
- Súbela con **SemVer** (`MAYOR.MENOR.PARCHE`) según la sección 5.
- La app la muestra en la barra de estado (`… · v1.0.0`), no hay que tocarla en
  la UI.

### 4.5 Documentación
- Si el cambio altera **lo que ve el usuario** (pasos, botones, requisitos,
  proveedores), actualiza `README.md`.
- Si el cambio altera **el proceso de trabajo**, actualiza este manual.
- No uses este manual como changelog.

### 4.6 Subir a GitHub
El repositorio ya está creado y conectado:

- **Remoto:** <https://github.com/miguelmarin18630/AI_Hub>
- **Rama:** `main` (sigue a `origin/main`)
- **Estado:** primer commit subido y `.gitignore` en la raíz.

En cada cambio:
```powershell
cd C:\Proyectos\AI_HUB
git status                 # revisa qué cambia y que no haya secretos
git add -A
git commit -m "tipo: resumen corto"
git push
```
Si algún día se clona en otra máquina:
```powershell
git clone https://github.com/miguelmarin18630/AI_Hub.git
```

**`.gitignore` recomendado** (crear en la raíz del repo si no existe):
```gitignore
__pycache__/
*.pyc
*.pyo
.pytest_cache/
dist/
build/
*.spec
# Nunca subir configuración local con claves
config.json
cache.json
```

> Las claves **no** están en el repo (viven en `%APPDATA%\AIHub`). Aun así,
> revisa `git status` antes de cada commit para no colar secretos ni archivos
> temporales.

**Convención de mensajes de commit** (tipo: resumen):
- `feat:` nueva funcionalidad
- `fix:` corrección de error
- `docs:` documentación
- `refactor:` reorganización sin cambiar comportamiento
- `chore:` versión, configuración, mantenimiento

---

## 5. Política de versiones (SemVer)

| Cambio | Qué subir | Ejemplo |
| --- | --- | --- |
| Corrección de fallo, sin API nueva | **PARCHE** | `1.0.0 → 1.0.1` |
| Funcionalidad nueva compatible | **MENOR** | `1.0.1 → 1.1.0` |
| Cambio incompatible (rompe config/formato) | **MAYOR** | `1.1.0 → 2.0.0` |

Reglas:
- Un commit de trabajo = como mínimo un bump de **PARCHE** si cambia el
  comportamiento.
- La versión se toca **solo** en `aihub/__init__.py`.
- El commit de versión puede ir junto al cambio o aparte (`chore: vX.Y.Z`).

---

## 6. Convenciones de código y UI

- **UI:** Tkinter, tema oscuro; textos en español; el panel central de chat es el
  más grande; la columna izquierda es estrecha.
- **Contexto visible:** la cabecera del chat muestra turnos y tokens aproximados
  usados frente al límite del modelo; al recortar se avisa en la conversación.
- **Orden de modelos:** primero los gratuitos (por relevancia), después los de
  pago de menor a mayor precio.
- **Errores:** traducirlos a mensajes claros (ver `_error_message` en `api.py`);
  no mostrar trazas internas de los CLIs salvo como detalle.
- **Clasificación gratis/pago:** `_is_free_model()` en `custom.py` decide por
  nombre de modelo. Si añades un proveedor, añade su regla ahí.
- **Archivos del proyecto:** el agente solo lee/escribe dentro de la carpeta de
  trabajo abierta.

---

## 7. Referencia rápida: gratis vs. pago

`custom._is_free_model()` marca gratuitos por patrón. Situación actual:

| Proveedor | Gratis | Notas |
| --- | --- | --- |
| OpenAI | — | API de pago (requiere saldo) |
| Google Gemini | `flash` | cuota diaria gratuita |
| DeepSeek | `-code`, `-coder`, `-distill` | nivel gratuito de código |
| Groq | — | sin nivel gratuito de chat |
| Mistral | `-instruct`, `-small`, `-v0.1` | prueba/ligero |
| Together AI | — | de pago |

Recuerda: si un modelo de pago da error 429, `api._error_message()` distingue
«sin saldo/créditos» de «límite de peticiones».

---

## 8. Checklist «definición de terminado»

Antes de dar una tarea por acabada:

- [ ] `py_compile` de los archivos tocados sin errores.
- [ ] `--smoke` → `GUI smoke test OK`.
- [ ] `--selftest` si afecta catálogos/proveedores/precios.
- [ ] Dos consultas seguidas recuerdan la anterior si tocas `chat.py` o el envío.
- [ ] Probado con la app **reiniciada** (no solo «Actualizar»).
- [ ] Versión subida en `aihub/__init__.py` si cambia el comportamiento.
- [ ] `README.md` actualizado si cambia lo que ve el usuario.
- [ ] Este manual actualizado **solo** si cambia el proceso.
- [ ] `git status` limpio de secretos/temporales; commit y `push`.

---

## 9. Limitaciones conocidas

- Los errores de un proveedor no deben ensuciar el panel del modelo en uso: se
  muestran en la tarjeta del proveedor.
- Los tokens del indicador de contexto son una estimación (≈4 caracteres/token);
  el gasto real lo marca la cuenta del proveedor.
- Los modelos locales (Ollama) usan 8K de contexto por defecto si el catálogo no
  informa de otra ventana.
- Imágenes/vídeo en OpenRouter requieren saldo; el chat gratuito sigue.
- Modelos locales sin soporte de herramientas caen a chat plano.
- `--selftest` necesita conexión a internet.
