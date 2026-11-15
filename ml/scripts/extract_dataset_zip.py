"""Verify and extract a locally downloaded research archive."""

import argparse
import os
import shutil
import stat
import zipfile
from pathlib import Path


def extract(archive: Path, destination: Path, password: bytes | None = None):
    marker = destination / ".verified"
    identity = f"{archive.stat().st_size}:{archive.stat().st_mtime_ns}"
    if marker.is_file() and marker.read_text(encoding="utf-8") == identity:
        print(f"Verified archive already extracted: {destination}", flush=True)
        return
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if any(info.flag_bits & 1 for info in entries) and not password:
            raise RuntimeError("Archive is encrypted. Set its password in the local environment.")
        targets = []
        required = 0
        for entry in entries:
            path = (root / entry.filename).resolve()
            if not path.is_relative_to(root) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Unsafe ZIP member: {entry.filename}")
            if not entry.is_dir():
                targets.append((entry, path))
                required += entry.file_size
        if shutil.disk_usage(root).free < required:
            raise OSError(f"The extracted archive requires {required / (1024 ** 3):.1f} GiB of free space.")
        for entry, path in targets:
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_name(path.name + ".unpacking")
            with package.open(entry, pwd=password) as source, part.open("wb") as output:
                # Reading to EOF also verifies the ZIP member CRC.
                shutil.copyfileobj(source, output, 1024 ** 2)
            part.replace(path)
        marker.write_text(identity, encoding="utf-8")
    print(f"Verified and extracted {len(targets)} files into {root}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--password-env", help="Name of a locally configured password variable")
    args = parser.parse_args()
    password = os.getenv(args.password_env) if args.password_env else None
    extract(args.archive, args.destination, password.encode("utf-8") if password else None)
