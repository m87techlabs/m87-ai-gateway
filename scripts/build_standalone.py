"""Build portable preview artifacts natively on Windows or Linux."""

import sys
import hashlib
import json
import platform
import zipfile
from importlib import metadata
from pathlib import Path

from PyInstaller.__main__ import run

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform not in {"linux", "win32"}:
        raise SystemExit("Build on a supported native Windows or Linux platform")
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
    from m87_gateway import __version__

    target = "windows" if sys.platform == "win32" else "linux"
    binary = ROOT / "dist" / ("m87-gateway.exe" if target == "windows" else "m87-gateway")
    manifest = {
        "gateway_version": __version__,
        "platform": target,
        "architecture": platform.machine().lower(),
        "python_version": platform.python_version(),
        "dependencies": {
            name: metadata.version(name)
            for name in (
                "fastapi",
                "uvicorn",
                "pydantic",
                "pyyaml",
                "httpx",
                "cryptography",
                "prometheus-client",
                "pyinstaller",
            )
        },
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "scope": "Developer preview. Read WORKSTATION.md for verification limits.",
    }
    package = ROOT / "dist" / f"m87-gateway-{__version__}-{target}-{platform.machine().lower()}.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(binary, binary.name)
        archive.writestr("build-info.json", json.dumps(manifest, indent=2))
        archive.write(ROOT / "docs/runbooks/workstation-distribution.md", "WORKSTATION.md")
        archive.write(ROOT / "LICENSE", "LICENSE")
        archive.write(ROOT / "NOTICE", "NOTICE")
        for asset in sorted((ROOT / "deploy/observability").rglob("*")):
            if asset.is_file():
                name = (
                    "observability/" + asset.relative_to(ROOT / "deploy/observability").as_posix()
                )
                if asset.name == "README.md":
                    archive.writestr(name, asset.read_text().replace("../../docs/", "../docs/"))
                else:
                    archive.write(asset, name)
        archive.writestr(
            "MONITORING.md",
            "# Optional monitoring\n\n"
            "See [setup and verification](docs/runbooks/grafana-monitoring.md). "
            "Templates are in observability/. Services are optional and are not started.\n",
        )
        for document in sorted((ROOT / "docs").rglob("*.md")):
            archive.write(document, document.relative_to(ROOT).as_posix())
        extension = "cmd" if target == "windows" else "sh"
        for action in ("start", "stop", "status"):
            script = ROOT / "deploy/workstation" / f"{action}.{extension}"
            archive.write(script, script.name)
    checksums = ROOT / "dist" / f"{package.stem}.sha256"
    checksums.write_text(
        "".join(
            f"{hashlib.sha256(item.read_bytes()).hexdigest()}  {item.name}\n"
            for item in (package, binary)
        )
    )


if __name__ == "__main__":
    main()
