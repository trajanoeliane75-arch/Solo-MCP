#!/usr/bin/env python3
"""Build an installable Debian package from an approved Solo source checkout.

No maintainer scripts, no root privileges, no user-home access and no service
migration. The desktop entry starts the application from a fixed system path.
"""

import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PACKAGE = "solo-agent"
VERSION = "1.0.1"
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
CONTROL = """Package: solo-agent
Version: {version}
Architecture: all
Maintainer: Solo contributors <340367484+trajanoeliane75-arch@users.noreply.github.com>
Section: utils
Priority: optional
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, xdg-utils, git
Recommends: gh
Homepage: https://github.com/trajanoeliane75-arch/Solo-MCP
Description: Local Linux companion for ChatGPT with explicit task approvals
 Solo connects ChatGPT task requests sent via private GitHub Issues to
 local Linux workspaces, with human approval for sensitive operations.
 Projects, service settings and existing user data remain in the user's home.
"""

DESKTOP = """[Desktop Entry]
Type=Application
Name=Solo
GenericName=Local AI task companion
Comment=Revise e autorize tarefas do ChatGPT no Linux
Exec=/usr/bin/solo-agent
Icon=solo-agent
Terminal=false
StartupNotify=true
Categories=Development;Utility;
Keywords=AI;ChatGPT;GitHub;Local;Automation;
"""

WRAPPER = """#!/bin/sh
# Installed by the solo-agent Debian package. No changes to the user service.
exec /usr/bin/python3 /usr/share/solo-agent/solo_app.py "$@"
"""


def put(source, target):
    if not source.is_file() or source.is_symlink():
        raise ValueError("Required source file missing or symlink: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)


def write(path, body, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(mode)


def build(root, output, version=VERSION):
    root = root.resolve(strict=True)
    output = output.resolve()
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+:~\-]*", version):
        raise ValueError("Invalid Debian version")
    if not shutil.which("dpkg-deb"):
        raise RuntimeError("dpkg-deb is needed to build a Debian package")
    mandatory = ("solo_app.py", "solo_ui.py", "solo_mcp.py", "solo_bootstrap_ui.py", "launch.py", "ui/index.html", "LICENSE")
    for name in mandatory:
        if not (root / name).is_file():
            raise FileNotFoundError("Missing required source " + name)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "{}_{}_all.deb".format(PACKAGE, version)

    with tempfile.TemporaryDirectory(prefix="solo-deb-build-") as tmp:
        stage = Path(tmp) / "package"
        app = stage / "usr/share/solo-agent"
        app.mkdir(parents=True)
        # Explicit allowlist: cannot package credentials, .git, a local DB, caches,
        # test fixtures, home directories, ZIP backups, or a working control repo.
        for source in sorted(root.glob("solo_*.py")):
            put(source, app / source.name)
        for name in ("launch.py", "install.sh"):
            put(root / name, app / name)
        for folder in ("ui", "share/icons"):
            for source in sorted((root / folder).rglob("*")):
                if not source.is_file():
                    continue
                if source.is_symlink():
                    raise ValueError("Symlink in application assets: " + str(source))
                if source.suffix.lower() not in (".js", ".css", ".html", ".svg", ".png", ".txt") and source.name != "LICENSE":
                    raise ValueError("Unexpected application asset " + str(source))
                put(source, app / source.relative_to(root))
        for size in SIZES:
            source = root / "share/icons/solo-{}.png".format(size)
            put(source, stage / "usr/share/icons/hicolor/{}x{}/apps/solo-agent.png".format(size, size))
        put(root / "share/icons/solo.svg", stage / "usr/share/icons/hicolor/scalable/apps/solo-agent.svg")
        write(stage / "usr/bin/solo-agent", WRAPPER, mode=0o755)
        write(stage / "usr/share/applications/solo-agent.desktop", DESKTOP)
        documentation = stage / "usr/share/doc/solo-agent"
        for name in ("README.md", "README.en.md", "LICENSE"):
            if (root / name).is_file():
                put(root / name, documentation / name)
        write(documentation / "README.Debian", """Solo Debian/Ubuntu package\n========================\n\nLaunch Solo from the desktop app menu, or use /usr/bin/solo-agent.\nThe package contains no maintainer scripts, starts no service automatically,\nand does not access or delete your home files.\n\nExisting Solo installs from extracted ZIPs may have their own local\n~/.local/share/applications/solo-mcp.desktop shortcut and a service\npointing to an older checkout. This package intentionally does not\noverwrite them. To avoid duplicate launchers, remove the old shortcut\nmanually only after verifying the new package works.\n\nTo manage an existing user service, open Solo Settings and inspect\nits configured path. Do not delete ~/.config/solo-mcp or workspaces.\nThis is a source-available, noncommercial project; see LICENSE.\n""")
        write(stage / "DEBIAN/control", CONTROL.format(version=version))
        subprocess.run(["dpkg-deb", "--build", "--root-owner-group", str(stage), str(destination)], check=True, capture_output=True, text=True, timeout=45)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--version", default=VERSION)
    args = parser.parse_args()
    package = build(args.root, args.output, args.version)
    print(str(package))


if __name__ == "__main__":
    main()
