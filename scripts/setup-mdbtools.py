#!/usr/bin/env python3
"""Install bounded, project-local mdbtools without changing the system."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0+dfsg-1.1"
PACKAGES = ("mdbtools", "libmdb3", "libmdbsql3")
ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / ".venv" / "runtime" / "mdbtools"
DOWNLOAD = DESTINATION / "packages"


def main() -> int:
    if not (shutil.which("apt-get") and shutil.which("dpkg-deb")):
        print("apt-get and dpkg-deb are required", file=sys.stderr)
        return 2
    DOWNLOAD.mkdir(parents=True, exist_ok=True)
    subprocess.run(["apt-get", "download", *(f"{package}={VERSION}" for package in PACKAGES)], cwd=DOWNLOAD, check=True)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for package in PACKAGES:
        archives = sorted(DOWNLOAD.glob(f"{package}_*.deb"))
        if len(archives) != 1:
            raise RuntimeError(f"expected exactly one downloaded archive for {package}")
        subprocess.run(["dpkg-deb", "-x", str(archives[0]), str(DESTINATION)], check=True)
    executable = DESTINATION / "usr" / "bin" / "mdb-sql"
    if not executable.is_file():
        raise RuntimeError("mdbtools extraction did not provide mdb-sql")
    print(executable)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
