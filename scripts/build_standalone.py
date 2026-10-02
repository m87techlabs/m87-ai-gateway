"""Build the experimental Linux bundle on its target Linux platform."""

import sys
from pathlib import Path

from PyInstaller.__main__ import run

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != "linux":
        raise SystemExit("Standalone distribution is currently verified only on Linux/WSL")
    run(
        [
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "m87-gateway",
            "--collect-all",
            "m87_gateway",
            "--collect-submodules",
            "uvicorn",
            "--paths",
            str(ROOT / "src"),
            "--specpath",
            str(ROOT / "build"),
            "--workpath",
            str(ROOT / "build" / "standalone"),
            "--distpath",
            str(ROOT / "dist"),
            str(ROOT / "scripts" / "standalone.py"),
        ]
    )


if __name__ == "__main__":
    main()
