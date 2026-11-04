"""Store a Gmail app password privately without terminal echo or shell history."""

import getpass
import os
from pathlib import Path


def main() -> None:
    directory = Path.home() / ".config/daily-digest/credentials"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "secrets.env"
    password = getpass.getpass("Contraseña de aplicación SMTP (no se mostrará): ")
    if not password or any(char in password for char in "\r\n\0"):
        raise SystemExit("Contraseña vacía o inválida; no se ha guardado.")
    # Keep all existing lines; replace only the credential explicitly entered.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+", encoding="utf-8") as stream:
        lines = stream.read().splitlines()
        replacement = "SMTP_PASSWORD=" + password
        updated = []
        found = False
        for line in lines:
            if line.partition("=")[0].strip() == "SMTP_PASSWORD":
                if not found:
                    updated.append(replacement)
                found = True
            else:
                updated.append(line)
        if not found:
            updated.append(replacement)
        os.fchmod(stream.fileno(), 0o600)
        stream.seek(0)
        stream.write("\n".join(updated) + "\n")
        stream.truncate()
        stream.flush()
        os.fsync(stream.fileno())
    print("Contraseña SMTP guardada en el archivo privado con permisos 600.")


if __name__ == "__main__":
    main()
