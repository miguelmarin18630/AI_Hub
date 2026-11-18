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

## 4. Arranque automático (opcional)

Para que el servidor arranque con Windows, crea una tarea en el Programador de
tareas que ejecute `python -m aihub.web run` en `C:\Proyectos\AI_HUB` al
iniciar sesión. El túnel de Cloudflare puede arrancarse igual con
`cloudflared tunnel run aihub`.

## 5. Seguridad

- Las claves se guardan por usuario en el servidor, no en el navegador.
- El servidor escucha solo en `127.0.0.1`; el túnel de Cloudflare es el único
  acceso externo.
- Las contraseñas se guardan con PBKDF2-HMAC-SHA256.
- La app aplica un límite de intentos de inicio de sesión por IP.
- No publiques el servidor directamente en internet sin HTTPS y sin contraseña.

## 6. Copias de seguridad

Copia la carpeta `%APPDATA%\AIHub\web` (cuentas, claves, proyectos y consumo).
Restaurarla en otra máquina deja todo igual.
