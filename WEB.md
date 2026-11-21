# AI Hub Web · uso familiar en el navegador

Esta versión permite que varias personas (por ejemplo, tu familia) usen AI Hub
desde el navegador, cada una con su propia cuenta, claves, modelos y proyectos.

## 1. Arrancar en tu ordenador

Doble clic en **`Iniciar_Web.vbs`** (sin consola) o ejecuta:

```powershell
cd C:\Proyectos\AI_HUB
python -m aihub.web run
```

Abre http://127.0.0.1:8765 en el navegador. La primera vez te pedirá crear la
cuenta de administrador.

## 2. Crear cuentas para la familia

El administrador entra en **Ajustes → Usuarios de la familia** y crea una cuenta
por persona (nombre, usuario y contraseña). Cada cuenta tiene su propia carpeta
en `%APPDATA%\AIHub\web\users\<usuario>` con:

- su clave de OpenRouter (y las de proveedores propios);
- sus proveedores añadidos;
- sus proyectos y archivos;
- su consumo por modelo.

## 2.1. Compartir los datos con la app de escritorio

La web y el escritorio son la misma app: lo único que cambia es la forma de
entrar. Puedes hacer que tu cuenta web trabaje directamente sobre la carpeta del
escritorio (`%APPDATA%\AIHub`) y así ver el mismo historial, los mismos
favoritos, la misma clave de OpenRouter y las mismas carpetas que en la app de
escritorio.

1. Entra en la web con tu cuenta.
2. Abre **Ajustes → Mi cuenta** y pulsa **Vincular con el escritorio**.
   El administrador también puede hacerlo desde **Usuarios de la familia →
   Datos**.
3. Recarga la página: el historial, los proyectos y los archivos serán los del
   escritorio.

La vinculación solo cambia la carpeta de datos de esa cuenta. Las demás cuentas
familiares siguen aisladas en `%APPDATA%\AIHub\web\users\<usuario>` y no ven
nada de las demás.

> **Importante:** evita usar el escritorio y la web a la vez sobre la misma
> conversación. Los dos escriben en `conversations.json`; si guardas desde ambos
> sitios, gana el último guardado. Termina una conversación en un sitio antes de
> continuarla en el otro.

## 2.2. Uso desde el móvil

La interfaz se adapta al teléfono:

- La barra superior se reduce a **Modelos** y al menú **⋯**, que reúne Historial,
  Detalles, Ayuda, Ajustes y la cuenta.
- El panel de modelos y el de detalles se abren como cajones laterales. Se
  cierran tocando fuera o al elegir un modelo.
- El historial y los ajustes ocupan la pantalla completa y se pueden desplazar.
- El compositor deja el botón **Enviar** a todo el ancho y oculta el estado
  cuando está vacío.

Desde el navegador del móvil puedes usar **Añadir a pantalla de inicio** para
abrirla como una app.

## 3. Publicar en marinweb.org (Cloudflare)

El servidor escucha en `127.0.0.1:8765`. Para exponerlo con tu dominio:

1. Instala `cloudflared` (https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
2. Inicia sesión:

   ```powershell
   cloudflared tunnel login
   ```

3. Crea el túnel:

   ```powershell
   cloudflared tunnel create aihub
   ```

4. Asocia el túnel a un subdominio (por ejemplo `aihub.marinweb.org`):

   ```powershell
   cloudflared tunnel route dns aihub aihub.marinweb.org
   ```

5. Arranca el túnel apuntando a AI Hub:

   ```powershell
   cloudflared tunnel run --url http://127.0.0.1:8765 aihub
   ```

   O con un archivo de configuración:

   ```yaml
   tunnel: <ID-DEL-TUNEL>
   credentials-file: C:\Users\<tu-usuario>\.cloudflared\<ID>.json
   ingress:
     - hostname: aihub.marinweb.org
       service: http://127.0.0.1:8765
     - service: http_status:404
   ```

   ```powershell
   cloudflared tunnel run aihub
   ```

Después, la app queda disponible en https://aihub.marinweb.org con HTTPS y la
cookie de sesión marcada como segura.

### Abrir el túnel en el día a día

Ya está creado el túnel `aihub` apuntando a `aihub.marinweb.org`. Para abrirlo:

- Doble clic en **`Iniciar_Tunel.bat`** (muestra el registro; ciérralo con Ctrl+C).
- O doble clic en **`Iniciar_Tunel.vbs`** (sin ventana; se cierra desde el
  Administrador de tareas buscando `cloudflared`).

Orden recomendado: primero **`Iniciar_Web.vbs`** (el servidor) y después el
túnel. El túnel no necesita volver a crearse ni volver a configurarse.

## 4. Arranque automático

Ya está configurado: la tarea programada **`AI Hub`** arranca al iniciar sesión
en Windows (con 15 s de margen) y lanza, sin ventanas y sin duplicar procesos:

1. El servidor web (`python -m aihub.web run`).
2. El túnel de Cloudflare (`cloudflared tunnel run aihub`).

Ambos usan el lanzador **`Arranque_AI_Hub.vbs`**, que también puedes ejecutar a
mano con doble clic. Comprueba antes si ya están en marcha, así que no crea
instancias repetidas.

- Ver el estado: `schtasks /query /tn "AI Hub" /v /fo LIST`
- Desactivar: `schtasks /change /tn "AI Hub" /disable`
- Volver a activar: `schtasks /change /tn "AI Hub" /enable`
- Quitarlo del todo: `schtasks /delete /tn "AI Hub" /f`

Para parar el túnel o el servidor: Administrador de tareas → buscar
`cloudflared` o `python` y finalizar la tarea.

## 5. Seguridad

- Las claves se guardan por usuario en el servidor, no en el navegador.
- El servidor escucha solo en `127.0.0.1`; el túnel de Cloudflare es el único
  acceso externo.
- Las contraseñas se guardan con PBKDF2-HMAC-SHA256.
- La app aplica un límite de intentos de inicio de sesión por IP.
- Solo el administrador y las cuentas vinculadas al escritorio pueden abrir
  rutas absolutas del equipo; el resto queda dentro de sus proyectos.
- No publiques el servidor directamente en internet sin HTTPS y sin contraseña.

## 6. Copias de seguridad

Copia la carpeta `%APPDATA%\AIHub\web` (cuentas, claves, proyectos y consumo).
Si tu cuenta está vinculada al escritorio, sus datos están en
`%APPDATA%\AIHub` (configuración, historial y proyectos), así que incluye también
esa carpeta en la copia.
