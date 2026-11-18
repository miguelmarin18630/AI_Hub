# AI Hub

Una sola ventana de Windows para ver **qué modelos de IA puedes usar gratis y cuáles son los más
baratos**, ordenados por precio, en cuatro proveedores: **OpenCode**, **Claude Code**, **Ollama** y
**OpenRouter**. También sirve para usarlos: abrir el terminal con el modelo ya cargado, descargar
modelos de Ollama, chatear y generar imágenes o vídeos.

Hecho con Python y Tkinter (solo biblioteca estándar): no hay que instalar dependencias con `pip`.

---

## Cómo se abre

| Forma | Qué hace |
| --- | --- |
| Doble clic en **`Iniciar AI Hub.vbs`** | Abre la app sin ventana de consola. Es la forma recomendada. |
| Doble clic en **`AIHub.pyw`** | Igual, si tienes `.pyw` asociado a Python. |
| Doble clic en **`run.bat`** | Abre la app mostrando la consola, útil si algo falla. |
| **`Crear acceso directo.bat`** | Crea el acceso directo «AI Hub» en el escritorio, con su icono. |

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

1. **Proyecto**: al abrir la app se elige la carpeta de trabajo (o `Ctrl+P`).
2. **Proveedor**: OpenCode, Claude Code, Ollama u OpenRouter, en la columna izquierda.
3. **Modelo**: en la lista. Para modificar archivos, el modelo debe admitir herramientas.
4. **Descripción**: escribe lo que necesitas y pulsa Enter. El modelo lee y modifica los archivos del
   proyecto y lo resume en la conversación.

La pantalla de inicio de cada chat muestra el estado de estos cuatro pasos. Sin proyecto o con un
modelo sin herramientas, la app no envía la consulta y te indica qué falta.

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
2. **Conversación** (centro, la parte principal) → cabecera con el modelo activo y su acceso a
   archivos, el hilo de mensajes y el **compositor**: escribe y pulsa **Enter** para enviar
   (**Shift+Enter** para salto de línea). «Nuevo chat» empieza una conversación limpia.
3. **Modelo y archivos** (derecha) → precio, descripción, acciones (terminal, copiar comando/ID) y la
   lista de archivos del proyecto. Doble clic en un archivo lo abre; «Modificados en este chat» indica
   lo que el modelo ha cambiado.

Filtros y orden: buscador, desplegable **Todos / Gratis / De pago** y orden **Precio ↑, Precio ↓,
Nombre, Contexto ↓**. Los modelos **gratuitos van siempre primero** y, dentro de ellos, ordenados por
**relevancia** (contexto, herramientas, visión, razonamiento, tamaño y familia), no alfabéticamente.

---

## macOS

Abre la app con el lanzador **`Iniciar_AI_Hub.command`** (doble clic, o arrástralo al Dock). Si
Terminal te pide permisos, acéptalos.

Requisitos: Python 3.10+ con Tkinter (`brew install python-tk`). Los proyectos se detectan en
`~/Proyectos` y la configuración se guarda en `~/Library/Application Support/AIHub`.
Más detalles en **`LEEME-MAC.md`**.

## Proyecto de trabajo

Al abrir la app pregunta **en qué proyecto vas a trabajar**. Cada proyecto es una carpeta dentro de
`C:\Proyectos`; ahí se ejecutan las consolas de OpenCode, Claude Code y Ollama y las consultas.

- Se elige con doble clic o con **Trabajar aquí**. La última elección queda marcada.
- **Sin proyecto** → para **imágenes y fotos** (y chat o vídeo) sin atar nada a una carpeta. Las
  imágenes siguen guardándose en `Imágenes\AI Hub`. Si en ese modo intentas usar OpenCode, Claude
  Code o Ollama, la app te pedirá un proyecto.
- **Nueva carpeta…** crea un proyecto nuevo dentro de `C:\Proyectos`.
- **Otro…** permite elegir cualquier carpeta del equipo.
- Para cambiarlo sin cerrar la app: botón **Proyecto · nombre** del encabezado o `Ctrl+P`.

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
  lista (OpenAI, Google Gemini, Groq, DeepSeek, Mistral, Together AI) o **Personalizado** para cualquier
  servidor compatible con OpenAI (p. ej. LM Studio con `http://localhost:1234/v1`).
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
  trabajo con el modelo ya seleccionado. Enviar un mensaje ejecuta el CLI en segundo plano, dentro del
  proyecto, y va escribiendo la respuesta en la conversación. El CLI lee y escribe archivos por sí mismo
  (Claude Code se ejecuta con `--permission-mode acceptEdits` para poder editar sin preguntar).
- **Ollama** → chat en el panel; si el modelo aún no está descargado, el botón de la ficha lo
  descarga en una consola aparte. Si el modelo declara soporte de herramientas, también lee y escribe
  archivos del proyecto; si no, responde en modo solo chat y lo indica.
- **OpenRouter** → chat con streaming dentro de la app (guarda el hilo de la conversación) y
  generación de **imágenes** y **vídeos**. Las imágenes se guardan en
  `Imágenes\AI Hub\imagenes` y los vídeos en `Imágenes\AI Hub\videos` (se puede cambiar en Ajustes).
  Antes de gastar en un vídeo, la app pide confirmación y muestra el coste estimado.
  Para imágenes y fotos **no hace falta proyecto**: elige «Sin proyecto» al abrir.
- **Leer y escribir archivos** → con un proyecto elegido, OpenRouter (modelos con herramientas) y
  Ollama (modelos con soporte de herramientas) pueden **listar, leer, crear y editar archivos** del
  proyecto. La casilla «Leer y escribir archivos», bajo el compositor, activa o desactiva este acceso.
  Cada acción aparece en la conversación (`⚙ read_file …`, `⚙ write_file …`), el resumen final indica
  los archivos modificados y el panel derecho los lista. Todo queda limitado a la carpeta del proyecto
  y nunca se escribe dentro de `.git`.
  - Si un modelo de Ollama no admite herramientas, la app responde en modo solo chat y lo indica.
  - Si un modelo de OpenRouter no admite herramientas, la casilla aparece desactivada.
  - Sin proyecto no hay archivos que leer: elige uno con `Ctrl+P`.

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
| `Ctrl+P` | Cambiar de proyecto |
| `F5` | Actualizar catálogos |
| `Enter` en el compositor | Enviar la consulta (`Shift+Enter` = nueva línea; `Ctrl+Enter` también envía) |
| Doble clic / `Enter` en la lista | Usar el modelo (acción principal) |
| `Esc` | Cerrar Ajustes |

---

## Datos y caché

- Configuración: `%APPDATA%\AIHub\config.json`
- Catálogos en caché: `%APPDATA%\AIHub\cache.json` (se regeneran con el botón **Actualizar** o `F5`)
- La app abre al instante con la caché y actualiza en segundo plano si «Actualizar el catálogo al
  abrir la app» está marcado.

## Si algo no aparece

- **Falta un proveedor**: pulsa el chip «N/4 proveedores» de la cabecera (o el aviso que aparece al
  arrancar) para ver qué falta y resolverlo con un clic: descargar el CLI, arrancar Ollama o añadir la
  clave de OpenRouter.
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
├─ run.bat                    lanzador con consola (para ver errores)
├─ Crear acceso directo.bat   crea el acceso directo del escritorio
├─ crear_acceso_directo.ps1   lógica del acceso directo
├─ assets/AIHub.ico           icono
├─ aihub/
│  ├─ config.py               rutas y configuración (%APPDATA%\AIHub)
│  ├─ api.py                  OpenRouter, Ollama y precios de OpenCode Zen
│  ├─ local.py                detección y ejecución de opencode / claude / ollama
│  ├─ catalog.py              modelos, precios, orden y caché
│  ├─ projects.py             lista y creación de proyectos (C:\Proyectos)
│  └─ ui.py                   interfaz Tkinter
└─ tools/make_icon.py         regenera el icono
   LEEME-MAC.md                instrucciones para macOS
   Iniciar_AI_Hub.command      lanzador para macOS/Linux
```

El agente usa `aihub/agent.py` (listar, leer, escribir y reemplazar dentro del proyecto).

Los precios son informativos y pueden cambiar: la app los lee de las APIs públicas cada vez que
actualizas. El gasto real lo marca tu cuenta de OpenRouter.
