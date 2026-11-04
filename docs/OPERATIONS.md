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
sudo tailscale up
sudo tailscale serve --bg 8090
tailscale serve status        # muestra https://HOST.TAILNET.ts.net
```

- Requiere MagicDNS y certificados HTTPS activados en la consola de Tailscale.
- En el móvil: app de Tailscale con la misma cuenta.
- `web.public_base_url` = la URL que muestra `tailscale serve status`.
- Si Tailscale no es posible en el móvil o en la red del centro: Tailscale Funnel o Cloudflare Tunnel **con inicio de sesión obligatorio delante**; decisión pendiente en `DECISIONS.md`.

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
