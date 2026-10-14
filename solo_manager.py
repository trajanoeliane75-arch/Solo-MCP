"""Solo-MCP workspace manager: graphical Linux settings without terminal commands.

All mutations update only private local Solo-MCP configuration and context.
GitHub aliases are metadata; this UI never stores passwords or access tokens.
"""
import json
import os
from pathlib import Path
import subprocess

import solo_git
import solo_kit
import solo_mcp as sm
import solo_projects as projects
import solo_workspaces as workspaces

LABELS = {
    "read": "Ler arquivos e metadados",
    "write": "Criar e alterar arquivos",
    "terminal": "Terminal direto (risco alto)",
    "desktop": "Abrir aplicativos e navegador",
    "environment": "Ambientes e contêineres",
}


class ManagerBackend:
    """Testable local workspace operations, independent of the visual layer."""

    def load(self):
        return sm.load_config()

    def names(self):
        config = self.load()
        return sorted(config.get("projects", {})), workspaces.active_workspace(config)

    def details(self, name):
        return workspaces.workspace_info(self.load(), name)

    def kit_status(self):
        return solo_kit.status()

    def prepare_kit(self, progress, repair=False):
        return solo_kit.prepare(progress, repair=repair)

    def prepare_native(self, progress):
        return solo_kit.prepare_native(progress)

    def prepare_system_python(self, progress):
        return solo_kit.prepare_system_python(progress)

    def git_info(self, name):
        detail = self.details(name)
        return solo_git.inspect_local_git(detail["root"])

    def create(self, name, folder, repo=""):
        config = self.load()
        projects.register_project(config, name, folder, repo)
        sm.save_config(config)
        return self.details(name)

    def select(self, name):
        config = self.load()
        workspaces.select_active(config, name)
        sm.save_config(config)
        return name

    def remove(self, name):
        config = self.load()
        projects.remove_project(config, name)
        if config.get("active_workspace") == name:
            config.pop("active_workspace", None)
        sm.save_config(config)
        return name

    def permissions(self, name, allowed):
        config = self.load()
        allowed = set(allowed)
        unknown = allowed - set(projects.CAPABILITIES)
        if unknown:
            raise ValueError("Permissões inválidas: " + ", ".join(sorted(unknown)))
        result = projects.set_permissions(config, name, ",".join(sorted(allowed)))
        sm.save_config(config)
        return result

    def link_repository(self, name, repo, account=""):
        config = self.load()
        linked = workspaces.link_repository(config, name, repo, account)
        sm.save_config(config)
        return linked

    def unlink_repository(self, name, repo, account=""):
        config = self.load()
        workspaces.unlink_repository(config, name, repo, account)
        sm.save_config(config)
        return True

    def read_context(self, name):
        config = self.load()
        info = workspaces.workspace_info(config, name)
        if not info["context_available"]:
            return ""
        return workspaces.read_context(config, name)

    def save_context(self, name, content):
        config = self.load()
        return workspaces.write_context_text(config, name, content)

    def share_context(self, name, enabled):
        config = self.load()
        if enabled:
            workspaces.read_context(config, name)
        workspaces.set_context_sharing(config, name, enabled)
        sm.save_config(config)
        return enabled

    def system_checks(self):
        """Report local service and optional Python sandbox prerequisites."""
        report = []
        try:
            service = subprocess.run(
                ["systemctl", "--user", "is-active", sm.SERVICE_NAME],
                capture_output=True, text=True, timeout=12
            )
            report.append(
                "Serviço Solo-MCP: ativo" if service.returncode == 0
                and service.stdout.strip() == "active"
                else "Serviço Solo-MCP: parado ou não encontrado"
            )
        except (OSError, subprocess.TimeoutExpired):
            report.append("Serviço Solo-MCP: não foi possível consultar")
        report.append("")
        try:
            podman = subprocess.run(
                ["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
                capture_output=True, text=True, timeout=15
            )
            if podman.returncode == 0 and podman.stdout.strip().lower() == "true":
                report.append("Podman: instalado e funcionando sem root")
                image = subprocess.run(
                    ["podman", "image", "exists", "docker.io/library/python:3.12-slim"],
                    capture_output=True, text=True, timeout=12
                )
                report.append(
                    "Imagem Python 3.12: pronta para uso" if image.returncode == 0
                    else "Imagem Python 3.12: ainda não baixada"
                )
            elif podman.returncode == 0:
                report.append("Podman instalado, mas o modo sem root não foi confirmado.")
            else:
                report.append("Podman encontrado, mas não está funcionando corretamente.")
        except FileNotFoundError:
            report.append("Podman: não instalado no computador.")
        except subprocess.TimeoutExpired:
            report.append("Podman: consulta excedeu o tempo limite.")
        except OSError:
            report.append("Podman: não foi possível executar a verificação.")
        report.extend((
            "",
            "Para que serve? Permite instalar pacotes Python num ambiente separado",
            "e testar código sem modificar as bibliotecas do Python principal.",
            "Sem Podman, a leitura dos seus workspaces continua funcionando.",
            "A instalação de pacotes em contêiner depende de Podman disponível.",
            "Ações de instalação/execução ainda exigem autorização do usuário.",
            "",
            "INSPEÇÃO VISUAL (com aprovação no painel)",
        ))
        kit = self.kit_status()
        report.append(
            "Kit essencial Solo-MCP: PRONTO (Playwright "
            + kit["playwright_version"] + " e Chromium)"
            if kit["ready"] else
            "Kit essencial Solo-MCP: PENDENTE (abra Ferramentas → Preparar kit)"
        )
        report.append("Captura de janela Linux: " + kit["native"])
        report.extend((
            "As ferramentas só capturam imagens após uma autorização local.",
            "Preparação do kit interno: confirme antes de baixar programas.",
            "Pacotes do Linux exigem confirmação e autenticação próprias.",
        ))
        return "\n".join(report)



def start_manager():
    """Compatibility entry point for the unified native application."""
    from solo_app import main
    main()
