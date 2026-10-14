"""Local application API. No listener, arbitrary commands or remote web content.

The native WebKit window calls the explicit dispatch table. Long operations run
as jobs, and config mutations are serialized. CLI and GUI use the same files.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time

import solo_desktop
import solo_git
import solo_kit
import solo_mcp as sm
import solo_projects as projects
import solo_workspaces as workspaces
from solo_manager import ManagerBackend


class AppBackend(ManagerBackend):
    def __init__(self, choose_folder=None):
        self.choose_folder = choose_folder
        self.lock = threading.RLock()
        self.job_lock = threading.Lock()
        self.job = None
        self.pending = []
        self.pending_repo = None
        self.pending_lock = threading.Lock()
        self.on_pending = None  # Optional desktop notification callback, no task data.
        self.notified_tasks = set()

    def load(self):
        if not sm.CONFIG_PATH.exists():
            return {"projects": {}}
        config = json.loads(sm.CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or not isinstance(config.get("projects", {}), dict):
            raise ValueError("Não foi possível ler a configuração local. Verifique o arquivo em Configurações.")
        return config

    def github_client(self):
        try:
            return sm.Github(sm.gh_token())
        except RuntimeError as exc:
            raise RuntimeError("Conecte sua conta GitHub em Configurações e tente novamente.") from exc

    def state(self):
        config = self.load()
        items = []
        for name in sorted(config.get("projects", {})):
            detail = workspaces.workspace_info(config, name)
            detail["folder_available"] = Path(detail["root"]).is_dir()
            items.append(detail)
        return {"workspaces": items, "preferred": workspaces.active_workspace(config),
                "control_repo": config.get("control_repo", ""),
                "kit": self.kit_status(), "tools": self.tool_status(),
                "config_path": str(sm.CONFIG_PATH),
                "autostart": solo_desktop.autostart_path().exists()}

    def workspace(self, name):
        detail = self.details(name)
        try:
            git = self.git_info(name)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            git = {"is_repo": False, "message": "Pasta ou Git indisponível: " + str(exc)}
        detail.update(context=self.read_context(name), git=git)
        return detail

    def tool_status(self):
        # This check distinguishes an installed binary from a usable X11 session.
        session = os.environ.get("XDG_SESSION_TYPE", "x11").lower()
        try:
            result = subprocess.run(["systemctl", "--user", "is-active", sm.SERVICE_NAME],
                                    capture_output=True, text=True, timeout=4)
            service = result.stdout.strip() or "unavailable"
        except (OSError, subprocess.TimeoutExpired):
            service = "unavailable"
        return {"service": service, "gh": bool(shutil.which("gh")),
                "podman": bool(shutil.which("podman")),
                "native_missing": solo_kit.native_missing(), "session": session,
                "system_installer": bool(shutil.which("pkexec") and Path("/usr/bin/apt-get").is_file())}

    def create_workspace(self, name, folder):
        if not isinstance(name, str) or not projects.NAME_RE.fullmatch(name):
            raise ValueError("Use de 1 a 50 caracteres: letras sem acento, números, hífen ou sublinhado. Comece com letra ou número.")
        result = self.create(name, folder)
        if not workspaces.active_workspace(self.load()):
            self.select(name)
        return result

    def save_workspace_context(self, name, content):
        target = self.save_context(name, content)
        return {"saved": True, "bytes": len(content.encode("utf-8")), "path": str(target)}

    def set_sharing(self, name, enabled):
        if type(enabled) is not bool:
            raise ValueError("Escolha de compartilhamento inválida")
        if enabled and not self.details(name)["context_available"]:
            raise ValueError("Salve o contexto antes de permitir sua leitura pelas tarefas.")
        return self.share_context(name, enabled)

    def open_folder(self, name):
        folder = Path(self.details(name)["root"])
        if not folder.is_dir():
            raise ValueError("A pasta não foi encontrada. Verifique se ela foi movida ou se o disco está conectado.")
        subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def open_link(self, target, name=None):
        links = {"new_control": "https://github.com/new?visibility=private",
                 "device": "https://github.com/login/device",
                 "docs": "https://github.com/trajanoeliane75-arch/Solo-MCP"}
        if target == "repository":
            url = self.git_info(name).get("github_url")
        elif target == "control":
            repo = self.load().get("control_repo", "")
            url = "https://github.com/" + repo if projects.REPO_RE.fullmatch(repo) else None
        else:
            url = links.get(target)
        if not url or not re.fullmatch(r"https://github\.com/[A-Za-z0-9_./?=&%-]+", url):
            raise ValueError("Link indisponível")
        subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def start_job(self, title, callback):
        with self.job_lock:
            if self.job and self.job["status"] == "running":
                raise ValueError("Uma operação está em andamento. Aguarde sua conclusão.")
            self.job = {"id": time.time_ns(), "title": title, "status": "running",
                        "lines": [], "result": None, "error": None}
            job_id = self.job["id"]
        def progress(line):
            with self.job_lock:
                self.job["lines"] = (self.job["lines"] + [str(line)])[-80:]
        def worker():
            try:
                result = callback(progress)
                with self.job_lock:
                    self.job.update(status="done", result=result)
            except Exception as exc:
                with self.job_lock:
                    self.job.update(status="error", error=str(exc)[:1200])
        threading.Thread(target=worker, daemon=True).start()
        return {"job_id": job_id}

    def job_status(self):
        with self.job_lock:
            return copy.deepcopy(self.job)

    def install_tool(self, tool):
        package_map = {"podman": ["podman"], "github": ["gh"], "python": ["python3-venv"]}
        if tool not in package_map:
            raise ValueError("Ferramenta desconhecida")
        if not self.tool_status()["system_installer"]:
            raise ValueError("Instalação guiada disponível em Debian/Ubuntu com Polkit. Consulte os pacotes em Ajuda.")
        def install(progress):
            progress("Confirme a instalação na janela de autenticação do Linux.")
            solo_kit._run([shutil.which("pkexec"), "/usr/bin/apt-get", "install", "-y", *package_map[tool]], timeout=600)
            progress("Instalação concluída.")
            return True
        return self.start_job("Instalando " + ", ".join(package_map[tool]), install)

    def authenticate(self):
        if not shutil.which("gh"):
            raise ValueError("Instale a conexão GitHub em Ferramentas primeiro.")
        def login(progress):
            # No token is exposed to JavaScript. gh owns credential persistence.
            progress("Solicitando código ao GitHub…")
            env = dict(os.environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
            process = subprocess.Popen(["gh", "auth", "login", "--hostname", "github.com",
                                        "--git-protocol", "https", "--web"],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, env=env)
            timer = threading.Timer(300, process.kill)
            timer.start()
            try:
                for line in process.stdout:
                    clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
                    code = re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", clean)
                    if code:
                        progress("Código de acesso: " + code.group())
                    elif "https://github.com/login/device" in clean:
                        progress("Abra github.com/login/device e informe o código acima.")
                if process.wait() != 0:
                    raise RuntimeError("Conexão não concluída. Tente novamente e autorize o acesso no navegador.")
                progress("Conta GitHub conectada.")
                return True
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
        return self.start_job("Conectar conta GitHub", login)

    def connect(self, repo):
        repo = repo.strip()
        if not projects.REPO_RE.fullmatch(repo):
            raise ValueError("Informe o repositório no formato usuario/repositorio.")
        def connect_repo(progress):
            progress("Verificando sua conta e a privacidade do repositório…")
            gh = self.github_client()
            info = sm.require_private_repo(gh, repo)
            if not info.get("has_issues", True):
                raise ValueError("Ative Issues nas configurações desse repositório no GitHub.")
            with self.lock:
                config = self.load()
                current = config.get("control_repo")
                if current and current.lower() != repo.lower() and self.tool_status()["service"] == "active":
                    raise ValueError("Pause o serviço antes de trocar o repositório de controle.")
                config["control_repo"] = repo
                sm.save_config(config)
                self.pending = []
                self.pending_repo = None
            progress("Repositório privado verificado e salvo.")
            return True
        return self.start_job("Verificar conexão", connect_repo)

    def service(self, action):
        if action not in ("install", "start", "stop", "restart", "repair"):
            raise ValueError("Ação de serviço inválida")
        if action != "stop" and not self.load().get("control_repo"):
            raise ValueError("Salve sua conexão com o GitHub em Configurações antes de ativar o serviço.")
        def change(progress):
            progress("Verificando o serviço em segundo plano…")
            # An extracted ZIP in Downloads must NEVER silently take ownership
            # of the working service from an already installed application.
            if action in ("install", "repair") and sm.SERVICE_FILE.is_file():
                try:
                    installed = sm.SERVICE_FILE.read_text(encoding="utf-8")
                    expected = sm.generate_user_unit()
                except OSError as exc:
                    raise RuntimeError("Não foi possível consultar a unidade do serviço. Nenhuma alteração foi feita.") from exc
                running = self.tool_status()["service"]
                if installed != expected:
                    if running == "active":
                        progress("Seu serviço já está ativo pela instalação existente. "
                                 "Não alterei o serviço nem os backups. A nova janela pode usá-lo normalmente.")
                        return "active"
                    raise RuntimeError(
                        "O serviço está vinculado a outra pasta e não foi alterado. "
                        "Use 'Ativar serviço' para iniciar a instalação existente. "
                        "Não use 'Reparar' a partir de uma cópia temporária em Downloads."
                    )
                if action == "repair" and running == "active":
                    progress("O serviço já está ativo e corretamente configurado. "
                             "Nenhum reparo foi necessário.")
                    return "active"
            if action != "stop":
                config = sm.load_config()
                sm.require_private_repo(self.github_client(), config["control_repo"])
            progress("Aplicando a operação solicitada ao serviço…")
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(sm.__file__).resolve()), "service", action],
                    capture_output=True, text=True, timeout=60
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError("Não foi possível consultar ou alterar o serviço. "
                                   "Seu backup foi preservado; verifique o estado em Configurações.") from exc
            if result.returncode:
                # Never leak raw Python tracebacks into the visible interface.
                if "Backup de unidade já existente" in result.stderr:
                    raise RuntimeError("Já existe um backup da unidade do serviço. "
                                       "Não foi substituído. O serviço anterior foi preservado. "
                                       "Consulte a instalação antes de tentar novamente.")
                raise RuntimeError("A operação não foi concluída. "
                                   "O serviço anterior não foi removido; confira o estado em Configurações. "
                                   f"(código {result.returncode})")
            progress("Operação concluída.")
            return self.tool_status()["service"]
        return self.start_job("Pausar serviço" if action == "stop" else "Ativar serviço", change)

    def approvals(self):
        config = self.load()
        if not config.get("control_repo"):
            return {"items": [], "connected": False}
        with self.pending_lock:
            items = solo_desktop.pending_details(config, self.github_client())
            with self.lock:
                if self.load().get("control_repo") != config["control_repo"]:
                    raise ValueError("A conexão mudou. Atualize a fila.")
                self.pending = items
                self.pending_repo = config["control_repo"]
                identities = {(item["number"], item["digest"]) for item in items}
                new_count = len(identities - self.notified_tasks)
                # Remember the exact preview, so changes to a pending task
                # can trigger another notice without spamming every 15 seconds.
                self.notified_tasks.update(identities)
            if new_count and self.on_pending is not None:
                try:
                    self.on_pending(new_count)
                except Exception:
                    pass  # Desktop notification failures never block approvals.
            return {"items": items, "connected": True}

    def decision(self, number, digest, allow):
        if type(allow) is not bool or type(number) is not int:
            raise ValueError("Decisão inválida")
        config = self.load()
        if config.get("control_repo") != self.pending_repo:
            raise ValueError("A conexão mudou. Atualize a fila antes de decidir.")
        item = next((x for x in self.pending if x["number"] == number and x["digest"] == digest), None)
        if not item:
            raise ValueError("A tarefa mudou. Atualize a fila e revise a prévia.")
        def decide(progress):
            with self.lock:
                current = self.load()
                if current.get("control_repo") != config.get("control_repo"):
                    raise ValueError("A conexão mudou. Revise a tarefa novamente.")
            progress("Verificando se a tarefa ainda corresponde à prévia…")
            result = solo_desktop.decide(current, self.github_client(), number, digest, allow)
            if result.get("ok") is False:
                raise RuntimeError(result.get("error", "A tarefa falhou. Consulte a Issue."))
            progress("Tarefa concluída." if allow else "Tarefa recusada.")
            return result
        return self.start_job("Tarefa #" + str(number), decide)

    def autostart(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Opção inválida")
        solo_desktop.manage_autostart("install" if enabled else "uninstall")
        return enabled

    def dispatch(self, method, params=None):
        params = params or {}
        actions = {
            "state": self.state, "workspace": self.workspace,
            "create_workspace": self.create_workspace, "remove_workspace": self.remove,
            "prefer_workspace": self.select, "save_permissions": self.permissions,
            "save_context": self.save_workspace_context, "share_context": self.set_sharing,
            "link_repository": self.link_repository, "unlink_repository": self.unlink_repository,
            "open_folder": self.open_folder, "open_link": self.open_link,
            "job_status": self.job_status, "install_tool": self.install_tool,
            "authenticate": self.authenticate, "connect": self.connect,
            "service": self.service, "approvals": self.approvals, "decision": self.decision,
            "autostart": self.autostart,
            "diagnostics": lambda: self.start_job("Verificar ferramentas", lambda p: self.system_checks()),
            "prepare_kit": lambda repair=False: self.start_job("Preparar inspeção web", lambda p: self.prepare_kit(p, repair=repair)),
            "prepare_native": lambda: self.start_job("Preparar captura de janelas", self.prepare_native),
            "choose_folder": self.choose_folder,
        }
        if method not in actions or actions[method] is None:
            raise ValueError("Ação indisponível nesta janela")
        if not isinstance(params, dict):
            raise ValueError("Parâmetros inválidos")
        # Network polling and the native folder chooser must not block local edits.
        if method in ("approvals", "choose_folder", "job_status"):
            return actions[method](**params)
        with self.lock:
            return actions[method](**params)
