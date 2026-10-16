# Solo .deb (Debian / Ubuntu)

This folder builds a native Debian package for the **Solo** desktop application.
It does not change the existing ZIP / Git-clone installation workflow.

```bash
python3 packaging/deb/build.py --version 1.0.1 --output dist
sudo apt install ./dist/solo-agent_1.0.1_all.deb
```

The package installs the application at `/usr/share/solo-agent/`, a command at
`/usr/bin/solo-agent`, a desktop launcher at
`/usr/share/applications/solo-agent.desktop`, and the original icon in the
system hicolor icon theme. Dependencies are declared in the Debian metadata.

**It does not use `sudo`, `pkexec`, or `apt` from a maintainer script.** In fact,
there are no `postinst`, `preinst`, `prerm`, or `postrm` scripts at all. The
system package manager owns the installed files. User data such as
`~/.config/solo-mcp/`, GitHub credentials and workspaces is never included,
replaced, or removed by installing/updating/removing the package.

An older installation from a ZIP or git clone can coexist with the .deb. It
may leave a user-scoped desktop entry (`~/.local/share/applications/solo-mcp.desktop`)
and a user service pointing at the old checkout. The .deb deliberately does
not migrate or stop those entries automatically. Verify the new application
first, then decide manually whether to retire the old launcher/service.

This is **not** an AppImage, not a Flatpak, and not a universal Linux installer.
Debian/Ubuntu package versions must provide WebKitGTK 4.1. Fedora and Arch
use the source install documented in `docs/GUI.md`.

For removal:

```bash
sudo apt remove solo-agent
```

That command removes package-owned application files only. User workspaces
and configuration remain intact; `purge` also cannot delete personal home
files because the package has no maintainer scripts and no conffiles.
