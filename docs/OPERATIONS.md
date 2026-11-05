# Operación en Rocky Linux 9

Servicio de sistema que corre con el usuario de la persona, endurecido para que no pueda modificar los proyectos aunque el código falle. Sin puertos abiertos: el acceso remoto a la webapp va por Tailscale.

## 1. Instalación

```bash
sudo dnf install -y python3.11 python3.11-devel git pango   # pango: WeasyPrint
sudo dnf install -y epel-release && sudo dnf install -y rclone   # o binario oficial de rclone
sudo mkdir -p /opt/daily-digest /etc/daily-digest
sudo chown "$USER": /opt/daily-digest
git clone <repo> /opt/daily-digest/src
python3.11 -m venv /opt/daily-digest/venv
/opt/daily-digest/venv/bin/pip install /opt/daily-digest/src
sudo cp /opt/daily-digest/src/config.example.yaml /etc/daily-digest/config.yaml   # editar
sudo install -m 600 -o root -g root /dev/null /etc/daily-digest/secrets.env       # QWEN_API_KEY=… NAN_API_KEY=… SMTP_PASSWORD=…
/opt/daily-digest/venv/bin/digest --config /etc/daily-digest/config.yaml doctor
```

`kanvas` debe estar en el `PATH` del usuario (`uv tool install kanvas-board`) o configurado en `kanvas.cli`.

## 2. Unidades systemd

Todas en `deploy/systemd/`, instaladas en `/etc/systemd/system/`. Sustituir `USER` y las rutas de la vault.

### Bloque común de endurecimiento (incluido en cada `.service`)

```ini
User=USER
Group=USER
Environment=GIT_OPTIONAL_LOCKS=0
ProtectSystem=strict
ProtectHome=read-only
StateDirectory=daily-digest
RuntimeDirectory=daily-digest
ReadWritePaths=/home/USER/Obsidian/Vault/Digest /home/USER/Obsidian/Vault/Revisiones /home/USER/Obsidian/Vault/Briefs /home/USER/.config/rclone
NoNewPrivileges=yes
PrivateTmp=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LoadCredential=secrets.env:/etc/daily-digest/secrets.env
```

`ProtectHome=read-only` hace de solo lectura todo `/home` salvo las rutas de `ReadWritePaths`: la vault (solo sus carpetas del digest) y la configuración de rclone (renueva el token OAuth). `StateDirectory` crea `/var/lib/daily-digest` con el propietario correcto. La aplicación lee los secretos de `$CREDENTIALS_DIRECTORY/secrets.env`.

### `digest-worker.service`

```ini
[Unit]
Description=daily-digest worker (cola de trabajos)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/opt/daily-digest/venv/bin/digest --config /etc/daily-digest/config.yaml worker
Restart=on-failure
RestartSec=15
MemoryMax=2G
CPUQuota=200%
# + bloque común

[Install]
WantedBy=multi-user.target
```

### `digest-web.service`

```ini
[Unit]
Description=daily-digest webapp
After=network.target

[Service]
Type=simple
ExecStart=/opt/daily-digest/venv/bin/digest --config /etc/daily-digest/config.yaml web
Restart=on-failure
RestartSec=5
MemoryMax=512M
# + bloque común

[Install]
WantedBy=multi-user.target
```

### `digest-enqueue@.service` (lo lanzan los temporizadores)

```ini
[Unit]
Description=daily-digest: encolar %i

[Service]
Type=oneshot
ExecStart=/opt/daily-digest/venv/bin/digest --config /etc/daily-digest/config.yaml enqueue %i --requested-by timer
# + bloque común
```

`digest enqueue KIND` es un alias interno de `digest run` sin `--now` (solo inserta en `job`).

### Temporizadores

```ini
# digest-daily.timer
[Unit]
Description=daily-digest: informe diario
[Timer]
OnCalendar=*-*-* 20:00:00 Europe/Madrid
Persistent=true
Unit=digest-enqueue@daily.service
[Install]
WantedBy=timers.target
```

```ini
# digest-weekly.timer
[Unit]
Description=daily-digest: informe semanal
[Timer]
OnCalendar=Sat *-*-* 10:00:00 Europe/Madrid
Persistent=true
Unit=digest-enqueue@weekly.service
[Install]
WantedBy=timers.target
```

```ini
# digest-capture.timer
[Unit]
Description=daily-digest: captura periódica
[Timer]
OnCalendar=*-*-* 08/2:00:00 Europe/Madrid
Unit=digest-enqueue@capture.service
[Install]
WantedBy=timers.target
```

```ini
# digest-backup.timer
[Unit]
Description=daily-digest: copia de SQLite
[Timer]
OnCalendar=*-*-* 03:30:00 Europe/Madrid
Persistent=true
Unit=digest-enqueue@backup.service
[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now digest-worker.service digest-web.service
sudo systemctl enable --now digest-daily.timer digest-weekly.timer digest-capture.timer digest-backup.timer
systemctl list-timers 'digest-*'
journalctl -u digest-worker -f
```

Para usar solo el disparo manual: `sudo systemctl disable --now digest-daily.timer`.

`Persistent=true` lanza la ejecución perdida al arrancar, pero no reconstruye varios días; la recuperación de intervalos pendientes la hace el worker desde SQLite (`ARCHITECTURE.md` §4).

## 3. Disparo manual

```bash
digest run              # encola el diario
digest run --now        # lo ejecuta en primer plano (útil para depurar)
digest run --preview    # avance, sin cerrar el intervalo ni entregar
digest run --weekly
```

Desde el móvil: pantalla Generar de la webapp.

## 4. Acceso a la webapp con Tailscale

```bash
sudo dnf config-manager --add-repo https://pkgs.tailscale.com/stable/rhel/9/tailscale.repo
sudo dnf install -y tailscale && sudo systemctl enable --now tailscaled
sudo tailscale up --accept-dns=false
sudo tailscale serve --bg 8090
tailscale serve status        # muestra https://HOST.TAILNET.ts.net
```

- Para la URL HTTPS de Serve: habilitar los certificados y nombres de MagicDNS en la tailnet. En el servidor del centro se conserva su DNS institucional mediante `--accept-dns=false`; la resolución de nombres de la tailnet desde ese servidor puede requerir configuración adicional acordada con sistemas.
- En el móvil: app de Tailscale con la misma cuenta.
- `web.public_base_url` = la URL que muestra `tailscale serve status`.
- Si Tailscale no es posible en el móvil o en la red del centro: Tailscale Funnel o Cloudflare Tunnel **con inicio de sesión obligatorio delante**; decisión pendiente en `DECISIONS.md`.

### DNS institucional e IPA/Kerberos

En equipos del centro, coordinar Tailscale con sistemas y conservar el DNS
institucional. Tailscale es una dependencia del acceso remoto previsto para la
webapp; la captura local y la generación de informes no lo necesitan.

Incidencia del piloto, 5 de noviembre de 2026:

- Tras instalar Tailscale, `/etc/resolv.conf` indicaba que lo generaba Tailscale y
  usaba sus resolutores `100.100.100.100` y `fd7a:115c:a1e0::53`.
- Sistemas advirtió de posibles retrasos en la resolución de los servidores IPA
  y fallos iniciales de Kerberos. Se confirmó el cambio de DNS; no se demostró
  que explicase todos los fallos de autenticación.
- Se indicó desactivar la aceptación del DNS de Tailscale en el servidor. La
  persona compartió después un `resolv.conf` gestionado por NetworkManager,
  con el dominio de búsqueda institucional y los tres DNS del centro restaurados.
- Queda comprobar con sistemas los accesos que fallaban. La restauración de DNS
  por sí sola no acredita que Kerberos esté reparado ni que el futuro acceso
  móvil a la webapp esté validado.

Para dejar de aceptar el DNS de Tailscale en un equipo ya conectado:

```bash
sudo tailscale set --accept-dns=false
cat /etc/resolv.conf
```

El administrador debe verificar que el gestor de red recupera los resolutores y
el dominio de búsqueda originales. Si no ocurre, debe restaurarlos mediante el
gestor de red o su configuración original. No fijar DNS públicos, editar IPA ni
copiar una configuración DNS de otra máquina para solventarlo. Tampoco editar
manualmente un `resolv.conf` que gestione otro servicio.

Este ajuste afecta a la aceptación de DNS en ese equipo; no desinstala Tailscale
ni desactiva por sí solo su conexión. El móvil conserva su configuración propia.
No habilitar de nuevo `--accept-dns=true` en el servidor sin acordarlo con sistemas.
Si se retira Tailscale por completo, revisar con sistemas los efectos sobre las
conexiones remotas y decidir el acceso a la webapp antes de publicarla.

Referencia: [Tailscale y la sustitución de resolv.conf](https://tailscale.com/docs/reference/faq/dns-resolv-conf).

## 5. Google Drive con rclone

```bash
rclone config      # n → nombre: gdrive → tipo: drive → scope: drive.file → auto config
                   # en un servidor sin navegador: «rclone authorize "drive"» en otro equipo y pegar el token
rclone mkdir gdrive:DailyDigest
rclone lsd gdrive:
```

- Alcance `drive.file`: rclone solo ve los archivos que él crea.
- Subidas: `rclone copy --immutable <local> gdrive:DailyDigest/<ruta>`. Nunca `sync`.
- Poda: `rclone delete --min-age 30d gdrive:DailyDigest/backups` (única operación de borrado permitida).
- Estructura remota:

```text
DailyDigest/
  2026/11/2026-11-04/informe.md, informe.pdf, figuras/, revisiones/
  semanal/2026-W45/informe.md, informe.pdf, figuras/
  briefs/2026-11-08-protocol-res_proj-a_DV-03/     (fase 6)
  indice.md
  backups/digest-2026-11-04.db
```

## 6. Correo

- Gmail por SMTP (`smtp.gmail.com:587`, STARTTLS) con contraseña de aplicación (requiere verificación en dos pasos), o Gmail API con OAuth si se prefiere (decisión pendiente).
- `Message-ID: <rep_daily_2026-11-04_r1@daily-digest.HOST>`; los correos generados se guardan en `data_dir/outbox/` antes de enviar.
- Si el servidor acepta y la conexión se corta antes de confirmar, la entrega queda `uncertain`; se resuelve a mano desde la pantalla Generar.

## 7. SELinux

Mantener `enforcing`. Si algo falla por permisos:

```bash
sudo ausearch -m avc -ts recent
sudo journalctl -t setroubleshoot
```

Ajustar contextos de archivo con `semanage fcontext` y `restorecon`; nunca `setenforce 0` como solución.

## 8. Copias y restauración

- `digest backup` usa la API de copia en línea de SQLite (`sqlite3.Connection.backup`) a `data_dir/backups/` y sube a Drive.
- `digest restore --from DIR` restaura base, informes y revisiones desde una carpeta local o descargada de Drive (`rclone copy gdrive:DailyDigest ./restore`).
- La restauración se prueba en la fase 4 (escenario obligatorio en `TESTING.md`).

## 9. Diagnóstico

| Síntoma | Dónde mirar |
| --- | --- |
| No llega el correo | Pantalla Generar → canal correo; `journalctl -u digest-worker`; `digest deliver --retry --channel email` |
| La webapp no abre desde el móvil | `tailscale serve status`; app de Tailscale activa en el móvil; `systemctl status digest-web` |
| Cobertura incompleta | Sección «Evidencias y cobertura» del informe; `digest doctor` |
| Drive sin subir | `rclone lsd gdrive:`; token caducado → `rclone config reconnect gdrive:` |

### Credenciales del piloto local

Las credenciales locales se guardan fuera del repositorio, en
`~/.config/daily-digest/credentials/secrets.env`, con permisos `600` y directorio
`700`. La aplicación las lee mediante `CREDENTIALS_DIRECTORY`. No las copies a
`config.yaml`, al tablero ni a mensajes.

Para guardar o cambiar la contraseña de aplicación de Gmail sin mostrarla en
pantalla ni incluirla en el historial de comandos:

```bash
.venv/bin/python scripts/set_smtp_password.py
```

El asistente conserva las otras claves del archivo. Para comprobar los servicios
sin enviar correo:

```bash
CREDENTIALS_DIRECTORY="$HOME/.config/daily-digest/credentials" \
  .venv/bin/digest --config config.yaml doctor
```

### Worker durante la fase 1

`digest run` encola; `digest run --now --no-send` procesa mediante el mismo worker
serializado, con un bloqueo de archivo que impide dos capturas simultáneas. Se
puede procesar un único trabajo pendiente con `digest worker --once`.

El informe mecánico conserva todos los resultados seleccionados y la cobertura,
sin generar conclusiones ni planes con un modelo. JSON almacena UTC; Markdown y
HTML muestran Europe/Madrid. Un avance no cierra el intervalo ni crea entregas.
El informe se valida antes de crear sus archivos, y cada revisión usa una carpeta
nueva. Un trabajo interrumpido se registra como fallido al recuperar el worker.


## Entregas de informes mecánicos (fase 1)

Cada informe validado se entrega de forma independiente a Obsidian, Drive y correo.
Un fallo de correo no repite una copia de Drive ya completada. Los avances y los
informes generados con `--no-send` no se entregan automáticamente.

```bash
digest --config config.yaml deliver --report rep_daily_FECHA_r1
digest --config config.yaml deliver --retry --channel email
```

Los comandos de entrega pasan por la cola y el bloqueo del worker. El registro
`delivery` conserva canal, intentos, estado y un código de error sin secretos.
Antes de SMTP DATA se guarda el MIME exacto en `data_dir/outbox/ID.eml` y se marca
`uncertain`. Si no se recibe la confirmación del servidor, no se reenvía solo.
Comprueba primero el buzón receptor y los registros SMTP; solo después utiliza
`deliver --report ID --channel email --force-uncertain` si decides repetirlo.
Los reintentos conservan el Message-ID y los bytes originales del correo.

Las notas generadas van a `Digest/AAAA-MM-DD.md` y las semanales a
`Digest/Semanal/AAAA-Wss.md`. Una regeneración crea `-r2`, `-r3`, etc.
Un archivo existente con contenido diferente provoca un fallo de entrega; nunca
se sustituye. Las figuras rasterizadas se copian junto a la nota y el texto humano
de `Revisiones/` permanece separado. El procesamiento de fichas humanas llegará
en la fase de webapp/revisión.

Drive recibe `reports/TIPO/ID/` con JSON, Markdown, HTML, PDF y figuras mediante
`rclone copy --immutable`. El enlace del correo apunta a esa carpeta privada cuando
se puede obtener su ID; no crea enlaces públicos. La copia continua de revisiones,
planes y backups corresponde a la fase de operación.

WeasyPrint 70 genera el PDF desde la plantilla del servicio, con imágenes PNG
dentro del directorio del informe. El cargador bloquea recursos de red y archivos
externos. La instalación requiere las bibliotecas nativas de Pango indicadas por
WeasyPrint; `make check` valida la generación real contra los fixtures.

Las vistas de prueba locales están en `build/previews/email.html`,
`email-mobile.png` (390 px) y `pdf-page-1.png`; no contienen datos del piloto
ni sustituyen la comprobación humana del correo en su móvil.
