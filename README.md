# AI Hub

Una sola ventana de Windows para ver **qué modelos de IA puedes usar gratis y cuáles son los más
baratos**, ordenados por precio, en cuatro proveedores: **OpenCode**, **Claude Code**, **Ollama** y
**OpenRouter** (más los proveedores compatibles con OpenAI que añadas tú). También sirve para usarlos:
chatear con memoria de conversación, editar archivos, generar imágenes o vídeos y abrir el terminal
con el modelo ya cargado.

Hecho con Python y Tkinter (solo biblioteca estándar): no hay que instalar dependencias con `pip`.

La **versión** se muestra siempre en la cabecera y en la barra de estado (por ejemplo, `v1.5.0`).

---

## Cómo se abre

| Forma | Qué hace |
| --- | --- |
| Doble clic en **`Iniciar AI Hub.vbs`** | Abre la app sin ventana de consola. Es la forma recomendada. |
| Doble clic en **`AIHub.pyw`** | Igual, si tienes `.pyw` asociado a Python. |
| Doble clic en **`run.bat`** | Abre la app mostrando la consola, útil si algo falla. |
| **`Crear acceso directo.bat`** | Crea el acceso directo «AI Hub» en el escritorio, con su icono. |

Si has creado cuentas en la versión web, al abrir el escritorio aparece una
ventana de **inicio de sesión**: entra con la misma cuenta y compartirás claves,
proyectos, favoritos e historial con la web. La primera vez, una cuenta vacía
hereda la configuración que ya tenías en el equipo.

> **Nota:** el login de escritorio está **desactivado por ahora** (versión
> provisional). La app de escritorio usa directamente tu configuración local
> (`%APPDATA%\AIHub\config.json`) hasta que la versión definitiva reactive la
> sincronización con la web.

Requisitos: **Windows 10/11 o macOS** y **Python 3.10 o superior** con Tk (viene por defecto).
Para macOS hay instrucciones específicas en `LEEME-MAC.md` y el lanzador `Iniciar_AI_Hub.command`.

Opcional, para aprovechar cada proveedor:

- `opencode` → [opencode.ai](https://opencode.ai)
- `claude` → Claude Code
- `ollama` → [ollama.com](https://ollama.com) (con el servidor en marcha: `ollama serve`)

La app detecta sola cuáles están instalados y lo indica en cada tarjeta del panel izquierdo.

---

## Qué muestra

La app funciona como un proveedor de IA, con este flujo:

1. **Proveedor**: OpenCode, Claude Code, Ollama u OpenRouter, en la columna izquierda.
2. **Modelo**: en la lista. Para modificar archivos, el modelo debe admitir herramientas.
3. **Consulta**: escribe lo que necesitas y pulsa Enter. El modelo responde en el panel central y
   la app **conserva el hilo**: la siguiente consulta se envía con las respuestas anteriores.
4. **Contexto**: la cabecera de la conversación muestra cuántos turnos lleva y cuántos tokens
   aproximados se están usando del límite del modelo. El botón **Cómo funciona** explica el proceso.

La pantalla de inicio de cada chat muestra el estado del proveedor, del modelo y de la conversación.
No hace falta elegir un proyecto para conversar: la carpeta de trabajo es opcional y solo se usa
cuando el modelo va a leer o escribir archivos.

Al arrancar, la app **comprueba el acceso a los cuatro proveedores**: si OpenCode o Claude Code no
están instalados, si Ollama no responde, o si falta la clave de OpenRouter, abre el diálogo
**Acceso a los proveedores** con el botón necesario (descargar, arrancar el servidor o añadir la
clave). El chip «4/4 proveedores listos» de la cabecera abre ese mismo diálogo cuando quieras. Si la
cuenta de OpenRouter no tiene saldo, la app lo indica: el chat gratis sigue funcionando, pero las
imágenes y los vídeos avisan antes de intentarlo.

La pantalla funciona como el espacio de chat de un proveedor de IA. Tiene tres columnas:

1. **Proveedor y modelos** (izquierda, estrecha) → elige la pestaña (*Programación* o *Imagen y vídeo*);
   cada pestaña muestra solo los proveedores que tienen modelos en ella. Después elige el proveedor y el
   modelo de la lista. La lista muestra
   **primero los gratuitos** y después los de pago **de menor a mayor precio**. Con «Precio ↓» se
   invierte el orden. La columna tiene **ancho fijo** y las tarjetas de proveedor tienen **scroll**, así
   que añadir proveedores no reduce la conversación; el botón **◀** la pliega a una franja lateral y
   **▶** la vuelve a mostrar.
2. **Conversación** (centro, la parte principal) → cabecera con el modelo activo, su acceso a
   archivos y el **indicador de contexto** (turnos y tokens usados). Incluye **Historial**,
   **Cómo funciona** y **Nuevo chat**. El hilo de mensajes se conserva entre consultas y al cambiar de
   modelo; el **compositor** envía con **Enter** (**Shift+Enter** para salto de línea). «Nuevo chat»
   empieza una conversación limpia.
3. **Modelo y archivos** (derecha) → precio, descripción, acciones (terminal, copiar comando/ID), la
   carpeta de trabajo y la lista de archivos. Doble clic en un archivo lo abre; «Modificados en este
   chat» indica lo que el modelo ha cambiado.

Filtros y orden: buscador, desplegable **Todos / Gratis / De pago** y orden **Precio ↑, Precio ↓,
Nombre, Contexto ↓**. Los modelos **gratuitos van siempre primero** y, dentro de ellos, ordenados por
**relevancia** (contexto, herramientas, visión, razonamiento, tamaño y familia), no alfabéticamente.

---

## Cómo funciona la conversación (contexto)

Una IA no recuerda nada entre peticiones: la memoria se la da la app enviando el historial. AI Hub lo
hace igual en todos los proveedores:

1. **Tu consulta se guarda** en el historial como mensaje de usuario.
2. **Se construye el contexto**: instrucciones del sistema (responder en español, no inventar, usar el
   hilo) + turnos anteriores + tu mensaje nuevo.
3. **Se respeta la ventana del modelo**. Si el hilo crece demasiado, se recortan los turnos más
   antiguos completos; nunca se parte una llamada a herramientas por la mitad. El indicador
   **Contexto** de la cabecera muestra los turnos y los tokens aproximados usados.
4. **La respuesta se añade al historial** como mensaje del asistente. En los modelos con herramientas
   también se guardan las lecturas/escrituras de archivos del turno.
5. **El hilo se conserva** al cambiar de modelo o proveedor (el contexto se envía al modelo nuevo) y
   al cerrar y reabrir la app. Solo **Nuevo chat** empieza de cero. El historial completo está en
   **Historial**.

Los tokens son una **estimación** (≈4 caracteres por token y ~800 por imagen); sirven para no
desbordar el límite, no para facturar. El gasto real lo marca la cuenta del proveedor.

---

## macOS

Abre la app con el lanzador **`Iniciar_AI_Hub.command`** (doble clic, o arrástralo al Dock). Si
Terminal te pide permisos, acéptalos.

Requisitos: Python 3.10+ con Tkinter (`brew install python-tk`). Los proyectos se detectan en
`~/Proyectos` y la configuración se guarda en `~/Library/Application Support/AIHub`.
Más detalles en **`LEEME-MAC.md`**.

## Versión web (navegador, multiusuario)

Además de la app de escritorio hay una versión web que se abre en el navegador y
permite que **varias personas** (por ejemplo, tu familia) usen AI Hub cada una
con su cuenta, sus claves, sus modelos y sus proyectos:

- Lanzador: **`Iniciar_Web.vbs`** (o `python -m aihub.web run`).
- Abre http://127.0.0.1:8765 y crea la primera cuenta de administrador.
- El administrador crea cuentas en **Ajustes → Usuarios de la familia**.
- Para publicarla en tu dominio (marinweb.org) con Cloudflare Tunnel, sigue
  **`WEB.md`**.

La web es la misma app que el escritorio: lo único que cambia es el inicio de
sesión. En **Ajustes → Mi cuenta** puedes pulsar **Vincular con el escritorio**
para que tu cuenta use `%APPDATA%\AIHub` y veas en el navegador el mismo
historial, favoritos, clave de OpenRouter y carpetas que en el escritorio. Las
demás cuentas familiares siguen separadas. No uses la misma conversación en los
dos sitios a la vez: ambos guardan en `conversations.json` y prevalece el último
guardado.

En el móvil la barra superior se reduce a **Modelos** y al menú **⋯** (Historial,
Detalles, Ayuda, Ajustes y cuenta); los paneles se abren como cajones laterales y
los modales ocupan la pantalla.

La versión web conserva las mismas funciones: catálogo de modelos, chat con
herramientas sobre tus archivos, generación de imágenes y vídeos, consumo por
modelo y ajustes. OpenCode y Claude Code usan los CLI instalados en el servidor.

## Carpeta de trabajo (opcional)

La app **ya no pregunta por un proyecto al abrir**. Recuerda la última carpeta usada y la muestra en
el panel derecho («ARCHIVOS DE LA CARPETA»).

- **Conversar, generar imágenes o vídeos no necesita carpeta**. Puedes empezar directamente.
- Para que un modelo **lea o escriba archivos**, abre una carpeta con **abrir carpeta** (panel derecho)
  y deja activada la casilla «Leer y escribir archivos» del compositor.
- La carpeta elegida se guarda en la configuración y se recupera al volver a abrir la app.
- OpenCode y Claude Code necesitan una carpeta para trabajar: si no hay ninguna, la app la pide al
  enviar la primera consulta.
- Las imágenes y los vídeos se guardan en `Imágenes\AI Hub` (se puede cambiar en Ajustes).

### Cómo se calculan los precios

- Los catálogos se descargan **en vivo**: OpenRouter (`/models`, `/images/models`, `/videos/models` y
  precios por endpoint), OpenCode (`opencode models` + precios reales de OpenCode Zen) y Ollama
  (`/api/tags` más una lista curada de la biblioteca). Claude Code toma sus alias (`fable`, `opus`,
  `sonnet`, `haiku`) y les pone los precios actuales de Anthropic.
- **Gratis** = 0 $ por token (o `:free` / `-free` / Zen a 0), y en Ollama todo es gratis porque corre
  en tu equipo. Los gratuitos se ordenan por relevancia; el pago, de menor a mayor precio.
- En programación se muestran **entrada / salida por 1M de tokens**.
- En imagen, **precio por imagen** o **por megapíxel**. Si el modelo cobra por tokens de imagen se
  indica «por tokens» y se coloca al final para no engañar con un precio falso.
- En vídeo, **precio por segundo** y una estimación de lo que costará el clip.
- Imagen y vídeo comparten la pestaña **Imagen y vídeo**. Por defecto solo existen en **OpenRouter** y en
  los proveedores que tú añadas (si ofrecen modelos de imagen). El vídeo necesita OpenRouter.

### Añadir proveedores propios

- Botón **«＋ Añadir proveedor»** (bajo las tarjetas, o en el diálogo de acceso). Eliges un servicio de la
  lista (OpenAI, Google Gemini, Groq, DeepSeek, Mistral, Together AI, Perplexity, Fireworks AI, xAI,
  Cerebras, SambaNova, Hugging Face, Novita AI, SiliconFlow, Hyperbolic, Cohere, Alibaba/Qwen, Moonshot,
  MiniMax) o **Personalizado** para cualquier servidor compatible con OpenAI (p. ej. LM Studio con
  `http://localhost:1234/v1`).
- Pide la clave de API, comprueba la conexión y lee los modelos. Los de chat aparecen en **Programación**;
  los de imagen, en **Imagen y vídeo**. La clave se guarda solo en tu equipo.
- Desde el mismo diálogo puedes **quitar** un proveedor (borra su clave guardada).
- La app no puede leer el saldo ni la cuota de estos proveedores: revísalos en su cuenta.
- Limitación: el vídeo no tiene una API estándar, así que los proveedores añadidos solo ofrecen chat e imagen.

---

## Qué puedes hacer con un modelo

- **Adjuntar archivo** (junto a CONSULTA / PROMPT) para preguntar sobre un archivo:
  - **Texto o código** (`.txt`, `.md`, `.py`, `.json`, `.csv`, `.html`, …): se envía como bloque
    adjunto, hasta 60 000 caracteres.
  - **Imágenes** (`.png`, `.jpg`, `.webp`, `.gif`, hasta 8 MB): se envían al modelo si tiene visión
    (OpenRouter u Ollama).
  - Solo un archivo a la vez; se quita con **quitar**. En Imagen/Vídeo el botón se oculta porque no
    se usa.
- **OpenCode / Claude Code** → «Abrir terminal con este modelo» lanza una consola en la carpeta de
  trabajo con el modelo ya seleccionado. Enviar un mensaje ejecuta el CLI en segundo plano, dentro de la
  carpeta, y va escribiendo la respuesta en la conversación. El CLI lee y escribe archivos por sí mismo
  (Claude Code se ejecuta con `--permission-mode acceptEdits` para poder editar sin preguntar).
- **Ollama** → chat en el panel; si el modelo aún no está descargado, el botón de la ficha lo
  descarga en una consola aparte. Si el modelo declara soporte de herramientas, también lee y escribe
  archivos de la carpeta; si no, responde en modo solo chat y lo indica.
- **OpenRouter** → chat con streaming dentro de la app (guarda el hilo de la conversación) y
  generación de **imágenes** y **vídeos**. Las imágenes se guardan en
  `Imágenes\AI Hub\imagenes` y los vídeos en `Imágenes\AI Hub\videos` (se puede cambiar en Ajustes).
  Antes de gastar en un vídeo, la app pide confirmación y muestra el coste estimado.
  Para imágenes y fotos **no hace falta carpeta**.
- **Leer y escribir archivos** → con una carpeta abierta, OpenRouter (modelos con herramientas) y
  Ollama (modelos con soporte de herramientas) pueden **listar, leer, crear y editar archivos** de esa
  carpeta. La casilla «Leer y escribir archivos», bajo el compositor, activa o desactiva este acceso.
  Cada acción aparece en la conversación (`⚙ read_file …`, `⚙ write_file …`), el resumen final indica
  los archivos modificados y el panel derecho los lista. Todo queda limitado a la carpeta elegida
  y nunca se escribe dentro de `.git`.
  - Si un modelo de Ollama no admite herramientas, la app responde en modo solo chat y lo indica.
  - Si un modelo de OpenRouter no admite herramientas, la casilla aparece desactivada.
  - Sin carpeta abierta no hay archivos que leer: usa «abrir carpeta» en el panel derecho.

### Clave de OpenRouter

Solo hace falta para OpenRouter (chat, imagen y vídeo). Consíguela en
<https://openrouter.ai/keys> y pégala en **Ajustes**. Si no hay ninguna guardada, se usa la variable
de entorno `OPENROUTER_API_KEY`. La clave de Ajustes tiene prioridad.

Se guarda en `%APPDATA%\AIHub\config.json`, en tu equipo. La app nunca la muestra en pantalla salvo
que pulses «ver».

---

## Atajos

| Atajo | Acción |
| --- | --- |
| `Ctrl+F` | Ir al buscador |
| `F5` | Actualizar catálogos |
| `Enter` en el compositor | Enviar la consulta (`Shift+Enter` = nueva línea; `Ctrl+Enter` también envía) |
| Doble clic / `Enter` en la lista | Usar el modelo (acción principal) |
| `Esc` | Cerrar Ajustes |

---

## Datos y caché

- Configuración: `%APPDATA%\AIHub\config.json`
- Catálogos en caché: `%APPDATA%\AIHub\cache.json` (se regeneran con el botón **Actualizar** o `F5`)
- Historial de conversaciones: `%APPDATA%\AIHub\conversations.json` (hasta 30 conversaciones; la
  conversación actual se recupera al abrir la app). En la web, cada cuenta usa
  `%APPDATA%\AIHub\web\users\<usuario>\` y su propio `conversations.json`, salvo que se vincule
  al escritorio: entonces comparte el historial de `%APPDATA%\AIHub`.
- La app abre al instante con la caché y actualiza en segundo plano si «Actualizar el catálogo al
  abrir la app» está marcado.

## Si algo no aparece

- **La app no abre**: ejecuta `run.bat` para ver el error en consola. Si el fallo
  ocurre al arrancar sin consola, el detalle queda en `%APPDATA%\AIHub\error.log`.
  Si se queda una ventana colgada, cierra `pythonw.exe` desde el Administrador de
  tareas y vuelve a abrir.
- **Pide iniciar sesión**: (actualmente desactivado). Si se reactiva, usa la misma
  cuenta que en la web (la contraseña se creó allí); cerrar el diálogo cierra
  la app.
- **Falta un proveedor**: pulsa el chip «N/4 proveedores» de la cabecera (o el aviso que aparece al
  arrancar) para ver qué falta y resolverlo con un clic: descargar el CLI, arrancar Ollama o añadir la
  clave de OpenRouter.
- **No sigue el hilo de la conversación**: comprueba que no has pulsado «Nuevo chat»; el indicador
  **Contexto** de la cabecera debe mostrar más de 0 turnos. Si el modelo es local con una ventana
  pequeña, la app recorta los turnos más antiguos para no desbordarla (lo indica en la conversación).
- **No hay modelos**: pulsa **Actualizar** (hace falta conexión). Si falla, revisa la barra de estado.
- **Ollama sin modelos**: abre Ollama o ejecuta `ollama serve`; luego **Actualizar**.
- **OpenRouter no responde**: comprueba la clave en Ajustes o la variable `OPENROUTER_API_KEY`.
- **OpenCode/Claude no instalados**: la app lo indica en la tarjeta; el resto sigue funcionando.
- Comprobación rápida sin interfaz:

  ```bat
  python AIHub.pyw --selftest
  ```

  Descarga los catálogos y muestra cuántos modelos hay, cuántos son gratis y los más baratos de cada
  categoría.

---

## Arquitectura

La app vive en `C:\Proyectos\AI_HUB` (los proyectos se guardan dentro de `C:\Proyectos`).

```
C:\Proyectos\AI_HUB\
├─ AIHub.pyw                  punto de entrada (--selftest, --smoke, --commands)
├─ Iniciar AI Hub.vbs         lanzador sin consola
├─ Iniciar_Web.vbs            lanzador de la versión web sin consola
├─ run.bat                    lanzador con consola (para ver errores)
├─ Iniciar_Web.bat            lanzador web con consola
├─ Crear acceso directo.bat   crea el acceso directo del escritorio
├─ crear_acceso_directo.ps1   lógica del acceso directo
├─ assets/AIHub.ico           icono
├─ aihub/
│  ├─ config.py               rutas y configuración (%APPDATA%\AIHub)
│  ├─ api.py                  OpenRouter, Ollama y precios de OpenCode Zen
│  ├─ chat.py                 contexto de la conversación (memoria, turnos y tokens)
│  ├─ local.py                detección y ejecución de opencode / claude / ollama
│  ├─ catalog.py              modelos, precios, orden y caché
│  ├─ projects.py             lista y creación de proyectos (C:\Proyectos)
│  ├─ ui.py                   interfaz Tkinter (escritorio)
│  └─ web/                    versión web multiusuario (servidor + frontend)
│     ├─ users.py             cuentas, sesiones y carpetas por usuario
│     ├─ server.py            API HTTP y SSE
│     └─ static/              HTML, CSS y JavaScript
└─ tools/make_icon.py         regenera el icono
   LEEME-MAC.md                instrucciones para macOS
   Iniciar_AI_Hub.command      lanzador para macOS/Linux
   Iniciar_Web.command         lanzador web para macOS/Linux
   WEB.md                      publicar la versión web en marinweb.org
```

El agente usa `aihub/agent.py` (listar, leer, escribir y reemplazar dentro de la carpeta de trabajo).
El contexto de la conversación se centraliza en `aihub/chat.py`: instrucciones del sistema, historial,
recorte por ventana y estimación de tokens. Cualquier proveedor nuevo debe usarlo en vez de enviar el
historial en bruto.

Los precios son informativos y pueden cambiar: la app los lee de las APIs públicas cada vez que
actualizas. El gasto real lo marca tu cuenta de OpenRouter.

---

## Licencia

© 2026 Miguel Marín. Todos los derechos reservados. AI Hub es software propietario: no se permite
su copia, distribución, modificación ni uso comercial sin autorización escrita. El código está
publicado para consulta; no se concede licencia para reutilizarlo. Ver `LICENSE`.
