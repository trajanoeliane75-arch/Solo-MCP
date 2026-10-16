# Solo v1.0.1 — Debian/Ubuntu installer

The first native `.deb` for Solo is now available. **Download `solo-agent_1.0.1_all.deb` under Assets** to install on compatible Debian/Ubuntu Linux desktops. GitHub's automatic source archives are still available below it.

## Installation

Open the `.deb` with your Linux package manager, or run:

```bash
sudo apt install ./solo-agent_1.0.1_all.deb
```

The package installs **Solo** into the desktop application menu, with its original icon. It uses the system Python, GTK3 and WebKitGTK 4.1 and declares those as package dependencies. The packaged installer does not install the background service automatically.

**Existing Solo installations:** This package does not replace an already configured user service or its project files. If you installed Solo earlier from a ZIP/git clone, that older desktop shortcut and service may remain alongside the new system-installed launcher. Check them in Solo **Configurações** before removing any old shortcut.

**Removal:** `sudo apt remove solo-agent`. This removes the package-owned files, not your `~/.config/solo-mcp` settings or your workspaces.

**Support:** Debian/Ubuntu with WebKitGTK 4.1 packages. Fedora and Arch users should use the source instructions in [docs/GUI.md](https://github.com/trajanoeliane75-arch/Solo-MCP/blob/v1.0.1/docs/GUI.md). Windows and macOS are not supported. X11 window capture requires an X11 desktop session.

**Security:** Use a private GitHub Issues control repository. Review and approve all sensitive commands. Terminal commands run with your Linux account's privileges and are not sandboxed by default. Solo does not implement an MCP protocol server or bypass AI plan limits.

**License:** [PolyForm Noncommercial 1.0.0](https://github.com/trajanoeliane75-arch/Solo-MCP/blob/v1.0.1/LICENSE) — source-available for noncommercial use, not OSI open source.
