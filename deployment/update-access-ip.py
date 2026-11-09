#!/usr/bin/env python3
"""Detecta la IPv4 pública del operador y actualiza los CIDR locales de network."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "stacks/network/terraform.tfvars"
KEYS = ("eks_public_access_cidrs", "app_access_cidrs")


def public_ipv4(value):
    address = ipaddress.IPv4Address(value.strip())
    if not address.is_global:
        raise ValueError("La dirección recibida no es una IPv4 pública.")
    return str(address)


def updated_config(text, address):
    cidr = public_ipv4(address) + "/32"
    for key in KEYS:
        # Solo listas de una línea: no intentar reescribir HCL arbitrario.
        pattern = rf'(?m)^([ \t]*{key}[ \t]*=[ \t]*)\[[^\]\r\n]*\]([ \t]*(?:#[^\r\n]*)?)$'
        text, count = re.subn(pattern, lambda match: f'{match[1]}["{cidr}"]{match[2]}', text)
        if count != 1:
            raise ValueError(f"Se esperaba una asignación de una línea para {key}; no se modificó el archivo.")
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Mostrar el cambio sin escribir archivos.")
    args = parser.parse_args()
    try:
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=15) as response:
            address = public_ipv4(response.read(128).decode("ascii"))
        original = TARGET.read_text()
        updated = updated_config(original, address)
        print(f"IPv4 pública detectada: {address}; acceso: {address}/32")
        print("Se sustituye la lista completa de IP autorizadas en ambos parámetros.")
        if original == updated:
            print("Los valores locales ya coinciden. Esto no verifica el estado en AWS.")
        elif args.check:
            print(f"Se actualizarían {', '.join(KEYS)} en {TARGET}.")
        else:
            # Reemplazo atómico, manteniendo permisos y el resto del contenido.
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", dir=TARGET.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    os.chmod(temporary, TARGET.stat().st_mode & 0o777)
                    stream.write(updated)
                os.replace(temporary, TARGET)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()
            print(f"Actualizado: {TARGET}")
        print("No se ejecutó Terraform. Revisar y aplicar desde la raíz del proyecto:")
        print("terraform -chdir=stacks/network plan -var-file=../../config/common.tfvars")
        print("terraform -chdir=stacks/network apply -var-file=../../config/common.tfvars")
    except (OSError, ValueError, UnicodeError) as error:
        raise SystemExit(f"No se pudo actualizar el acceso: {error}") from None


if __name__ == "__main__":
    main()
