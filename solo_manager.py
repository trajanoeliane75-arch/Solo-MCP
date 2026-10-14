"""Solo-MCP workspace manager: graphical Linux settings without terminal commands.

All mutations update only private local Solo-MCP configuration and context.
GitHub aliases are metadata; this UI never stores passwords or access tokens.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

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
    """Testable local workspace operations, independent of Tkinter."""

    def load(self):
        return sm.load_config()

    def names(self):
        config = self.load()
        return sorted(config.get("projects", {})), workspaces.active_workspace(config)

    def details(self, name):
        return workspaces.workspace_info(self.load(), name)

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

    def system_checks(self):
        """Collect non-privileged status in a background thread."""
        report = []
        for title, argv in (
            ("Serviço", ["systemctl", "--user", "is-active", sm.SERVICE_NAME]),
            ("Podman", ["podman", "info", "--format", "{{.Host.Security.Rootless}}"]),
        ):
            try:
                result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
                if result.returncode == 0:
                    output = result.stdout.strip()[:350] or "disponível"
                else:
                    output = result.stderr.strip()[:350] or result.stdout.strip()[:350] or "indisponível"
                report.append(f"{title}: {output}")
            except (OSError, subprocess.TimeoutExpired) as exc:
                report.append(f"{title}: indisponível ({type(exc).__name__})")
        report.append("Instalações e privilégios administrativos não são feitos por esta tela.")
        return "\n".join(report)


def start_manager():
    if sys.platform != "linux":
        raise RuntimeError("Gerenciador gráfico disponível somente no Linux")
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise RuntimeError("Tkinter ausente; no Ubuntu instale python3-tk") from exc
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError("Abra o gerenciador na sessão gráfica do Linux") from exc
    try:
        ManagerWindow(root, tk, ttk, ManagerBackend())
        root.mainloop()
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


class ManagerWindow:
    def __init__(self, root, tk, ttk, backend):
        self.root, self.tk, self.ttk, self.backend = root, tk, ttk, backend
        self.current = None
        self._loading = False
        self._repository_rows = []
        self._selected_permissions = {}
        self._last_permissions = {}
        self._events = queue.Queue()
        root.title("Solo-MCP · Gerenciar workspaces")
        root.geometry("1060x670")
        root.minsize(850, 550)

        shell = ttk.Frame(root, padding=12)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Solo-MCP", font=("Sans", 16, "bold")).pack(anchor="w")
        ttk.Label(shell, text="Workspaces, repositórios, permissões e contexto local").pack(
            anchor="w", pady=(0, 12))
        body = ttk.Frame(shell)
        body.pack(fill="both", expand=True)

        side = ttk.Frame(body, width=245)
        side.pack(side="left", fill="y", padx=(0, 12))
        ttk.Label(side, text="MEUS WORKSPACES", font=("Sans", 10, "bold")).pack(anchor="w")
        self.tree = ttk.Treeview(side, show="tree", selectmode="browse", height=20)
        self.tree.column("#0", width=230, minwidth=170)
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_selection)
        sidebar_actions = ttk.Frame(side)
        sidebar_actions.pack(fill="x")
        ttk.Button(sidebar_actions, text="+ Novo", command=self.create_dialog).pack(
            side="left", fill="x", expand=True)
        ttk.Button(sidebar_actions, text="Atualizar", command=self.refresh).pack(side="left", padx=(6, 0))
        ttk.Button(side, text="Remover cadastro", command=self.remove_dialog).pack(
            fill="x", pady=(8, 0))
        ttk.Separator(body, orient="vertical").pack(side="left", fill="y", padx=(0, 12))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        titlebar = ttk.Frame(right)
        titlebar.pack(fill="x")
        self.heading = ttk.Label(titlebar, text="Selecione um workspace", font=("Sans", 13, "bold"))
        self.heading.pack(side="left", fill="x", expand=True)
        self.select_button = ttk.Button(titlebar, text="Tornar ativo", command=self.activate)
        self.select_button.pack(side="right")
        self.active_label = ttk.Label(right, text="")
        self.active_label.pack(anchor="w", pady=(2, 8))
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)

        self.tab_general = ttk.Frame(self.tabs, padding=14)
        self.tab_repos = ttk.Frame(self.tabs, padding=14)
        self.tab_perms = ttk.Frame(self.tabs, padding=14)
        self.tab_context = ttk.Frame(self.tabs, padding=14)
        self.tab_environment = ttk.Frame(self.tabs, padding=14)
        for text, tab in (
            ("Visão geral", self.tab_general),
            ("Repositórios", self.tab_repos),
            ("Permissões", self.tab_perms),
            ("Contexto", self.tab_context),
            ("Ambiente", self.tab_environment),
        ):
            self.tabs.add(tab, text=text)

        self._build_general()
        self._build_repositories()
        self._build_permissions()
        self._build_context()
        self._build_environment()

        footer = ttk.Frame(shell)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Separator(footer).pack(fill="x", pady=(0, 7))
        self.status = ttk.Label(footer, text="Configurações guardadas somente no computador.")
        self.status.pack(anchor="w")
        self.refresh()
        root.after(200, self._drain_events)

    def _build_general(self):
        ttk.Label(self.tab_general, text="Pasta local", font=("Sans", 11, "bold")).pack(anchor="w")
        self.path_text = self.ttk.Label(self.tab_general, text="—", wraplength=600)
        self.path_text.pack(anchor="w", pady=(3, 12))
        self.folder_button = self.ttk.Button(self.tab_general, text="Abrir pasta no gerenciador de arquivos",
                                             command=self.open_folder)
        self.folder_button.pack(anchor="w", pady=(0, 12))
        ttk.Separator(self.tab_general).pack(fill="x", pady=8)
        ttk.Label(self.tab_general, text="Projeto e repositórios são independentes",
                  font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_general,
                  text="Este workspace representa uma pasta e um contexto persistente. "
                       "Você pode associar vários repositórios GitHub, mas o vínculo não "
                       "conecta uma conta nem concede acesso a repositórios privados.",
                  wraplength=600, justify="left").pack(anchor="w", pady=(8, 12))
        self.summary = self.ttk.Label(self.tab_general, text="—", wraplength=600)
        self.summary.pack(anchor="w")

    def _build_repositories(self):
        ttk.Label(self.tab_repos, text="Repositórios associados",
                  font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_repos,
                  text="Associação de metadados: não clona, não altera nem autentica repositórios.",
                  wraplength=610).pack(anchor="w", pady=(4, 8))
        self.repo_tree = self.ttk.Treeview(
            self.tab_repos, columns=("repository", "account"), show="headings",
            selectmode="browse", height=10)
        self.repo_tree.heading("repository", text="Repositório")
        self.repo_tree.heading("account", text="Alias da conta")
        self.repo_tree.column("repository", width=330)
        self.repo_tree.column("account", width=140)
        self.repo_tree.pack(fill="both", expand=True)
        actions = self.ttk.Frame(self.tab_repos)
        actions.pack(fill="x", pady=(10, 0))
        self.add_repo_button = self.ttk.Button(actions, text="+ Vincular repositório",
                                                command=self.repo_dialog)
        self.add_repo_button.pack(side="left")
        self.unlink_repo_button = self.ttk.Button(actions, text="Desvincular selecionado",
                                                   command=self.unlink_repo)
        self.unlink_repo_button.pack(side="left", padx=8)

    def _build_permissions(self):
        ttk.Label(self.tab_perms, text="Acesso permitido neste workspace",
                  font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_perms,
                  text="Marque apenas as capacidades necessárias. Escrita e operações em "
                       "aplicativos ainda exigem aprovação na janela Solo-MCP.",
                  wraplength=610).pack(anchor="w", pady=(6, 10))
        self.permission_vars = {}
        for key in projects.CAPABILITIES:
            var = self.tk.BooleanVar(value=False)
            self.permission_vars[key] = var
            self.ttk.Checkbutton(self.tab_perms, text=LABELS[key], variable=var).pack(
                anchor="w", pady=4)
        ttk.Label(self.tab_perms,
                  text="ATENÇÃO: terminal executa programas com os direitos do usuário Linux. "
                       "Isso não equivale a um ambiente isolado.",
                  wraplength=610, justify="left").pack(anchor="w", pady=(14, 10))
        self.save_permissions_button = self.ttk.Button(
            self.tab_perms, text="Salvar permissões", command=self.save_permissions)
        self.save_permissions_button.pack(anchor="w")

    def _build_context(self):
        ttk.Label(self.tab_context, text="Memória local do workspace",
                  font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_context,
                  text="Markdown privado, até 16 KB. Não coloque senhas nem tokens. "
                       "O conteúdo nunca é enviado ao GitHub sem habilitar o compartilhamento.",
                  wraplength=610).pack(anchor="w", pady=(4, 7))
        text_frame = self.ttk.Frame(self.tab_context)
        text_frame.pack(fill="both", expand=True)
        self.context_text = self.tk.Text(text_frame, wrap="word", undo=True, height=12)
        self.context_text.pack(side="left", fill="both", expand=True)
        sc = self.ttk.Scrollbar(text_frame, orient="vertical", command=self.context_text.yview)
        sc.pack(side="right", fill="y")
        self.context_text.configure(yscrollcommand=sc.set)
        controls = self.ttk.Frame(self.tab_context)
        controls.pack(fill="x", pady=(9, 0))
        self.save_context_button = self.ttk.Button(
            controls, text="Salvar contexto", command=self.save_context)
        self.save_context_button.pack(side="left")
        self.share_var = self.tk.BooleanVar(value=False)
        self.ttk.Checkbutton(controls, text="Permitir leitura remota", variable=self.share_var).pack(
            side="left", padx=(12, 6))
        self.save_share_button = self.ttk.Button(
            controls, text="Aplicar", command=self.save_sharing)
        self.save_share_button.pack(side="left")
        self.context_location = self.ttk.Label(
            self.tab_context, text="O arquivo é salvo na configuração privada local.",
            wraplength=610)
        self.context_location.pack(anchor="w", pady=(8, 0))

    def _build_environment(self):
        ttk.Label(self.tab_environment, text="Execução e desenvolvimento",
                  font=("Sans", 11, "bold")).pack(anchor="w")
        ttk.Label(self.tab_environment,
                  text="O agente pode usar Podman rootless para pacotes e testes isolados "
                       "quando você permitir a capacidade Ambiente. Nenhum instalador ou "
                       "privilégio administrativo é acionado nesta tela.",
                  wraplength=610).pack(anchor="w", pady=(6, 10))
        self.check_button = self.ttk.Button(
            self.tab_environment, text="Verificar serviço e Podman", command=self.check_environment)
        self.check_button.pack(anchor="w")
        self.environment_text = self.tk.Text(
            self.tab_environment, height=10, wrap="word", state="disabled")
        self.environment_text.pack(fill="both", expand=True, pady=(10, 0))
        self._set_environment("Clique em Verificar para consultar os componentes locais.\n"
                              "Contêiner não é uma máquina virtual resistente a malware.")

    def _set_environment(self, content):
        self.environment_text.config(state="normal")
        self.environment_text.delete("1.0", "end")
        self.environment_text.insert("1.0", content)
        self.environment_text.config(state="disabled")

    def _call(self, callback, refresh=False, success="Atualizado."):
        from tkinter import messagebox
        try:
            result = callback()
        except (ValueError, OSError, PermissionError, RuntimeError, UnicodeError) as exc:
            messagebox.showerror("Solo-MCP", str(exc), parent=self.root)
            self.status.configure(text="Erro: " + str(exc)[:160])
            return None
        if refresh:
            self.refresh()
        self.status.configure(text=success)
        return result

    def _has_unsaved_context(self):
        return self.current is not None and bool(self.context_text.edit_modified())

    def refresh(self, prefer=None):
        from tkinter import messagebox
        if self._has_unsaved_context() and not messagebox.askyesno(
            "Solo-MCP", "Descartar alterações não salvas no contexto?", parent=self.root
        ):
            return
        previous = prefer or self.current
        try:
            names, selected = self.backend.names()
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Solo-MCP", str(exc), parent=self.root)
            return
        self._loading = True
        self.tree.delete(*self.tree.get_children())
        for name in names:
            self.tree.insert("", "end", iid=name, text=name + ("  • ativo" if name == selected else ""))
        if previous in names:
            self.tree.selection_set(previous)
        elif selected in names:
            self.tree.selection_set(selected)
        elif names:
            self.tree.selection_set(names[0])
        self._loading = False
        self.show_selected(force=True)

    def on_selection(self, _event=None):
        if self._loading:
            return
        chosen = self.tree.selection()
        name = chosen[0] if chosen else None
        if name == self.current:
            return
        if self._has_unsaved_context():
            from tkinter import messagebox
            if not messagebox.askyesno("Solo-MCP", "Descartar contexto não salvo?", parent=self.root):
                self._loading = True
                if self.current:
                    self.tree.selection_set(self.current)
                self._loading = False
                return
        self.show_selected(force=True)

    def show_selected(self, force=False):
        from tkinter import messagebox
        selection = self.tree.selection()
        name = selection[0] if selection else None
        if name == self.current and not force:
            return
        self.current = name
        if name is None:
            self.heading.configure(text="Nenhum workspace cadastrado")
            self.path_text.configure(text="—")
            self.active_label.configure(text="Clique em + Novo para começar.")
            self.repo_tree.delete(*self.repo_tree.get_children())
            self.context_text.delete("1.0", "end")
            self.context_text.edit_modified(False)
            self._disable_actions(True)
            return
        try:
            detail = self.backend.details(name)
            content = self.backend.read_context(name)
            _, selected = self.backend.names()
        except (ValueError, OSError, RuntimeError, PermissionError) as exc:
            messagebox.showerror("Solo-MCP", str(exc), parent=self.root)
            return
        self.heading.configure(text=name)
        self.path_text.configure(text=detail["root"])
        self.active_label.configure(
            text="Workspace ativo" if selected == name else "Workspace cadastrado (não selecionado)")
        self.summary.configure(
            text=f"Repositórios: {len(detail['repositories'])}    |    "
                 f"Contexto: {'criado' if detail['context_available'] else 'vazio'}    |    "
                 f"Compartilhamento remoto: {'ligado' if detail['context_shared'] else 'desligado'}")
        self._repository_rows = detail["repositories"]
        self.repo_tree.delete(*self.repo_tree.get_children())
        for i, link in enumerate(self._repository_rows):
            self.repo_tree.insert("", "end", iid=str(i),
                                  values=(link["full_name"], link["account"] or "padrão"))
        self._last_permissions = dict(detail["permissions"])
        for key, variable in self.permission_vars.items():
            variable.set(bool(detail["permissions"][key]))
        self.context_text.delete("1.0", "end")
        self.context_text.insert("1.0", content)
        self.context_text.edit_modified(False)
        self.share_var.set(bool(detail["context_shared"]))
        self.context_location.configure(
            text="Contexto privado: " + str(workspaces.context_path(name)))
        self._disable_actions(False)

    def _disable_actions(self, disabled):
        state = "disabled" if disabled else "normal"
        for widget in (self.select_button, self.folder_button, self.add_repo_button,
                       self.unlink_repo_button, self.save_permissions_button,
                       self.save_context_button, self.save_share_button):
            widget.configure(state=state)

    def create_dialog(self):
        from tkinter import filedialog, messagebox, simpledialog
        name = simpledialog.askstring("Novo workspace", "Nome curto do workspace:", parent=self.root)
        if name is None:
            return
        name = name.strip()
        folder = filedialog.askdirectory(
            parent=self.root, title="Escolha a pasta existente deste workspace",
            mustexist=True)
        if not folder:
            return
        result = self._call(lambda: self.backend.create(name, folder),
                            success="Workspace cadastrado com permissão inicial somente de leitura.")
        if result:
            self.refresh(prefer=name)

    def remove_dialog(self):
        from tkinter import messagebox
        if not self.current:
            return
        name = self.current
        if not messagebox.askyesno(
            "Remover cadastro",
            f"Remover o workspace '{name}' do Solo-MCP?\n\n"
            "Os arquivos na pasta e os repositórios não serão apagados.",
            parent=self.root):
            return
        result = self._call(lambda: self.backend.remove(name),
                            success="Cadastro removido, arquivos preservados.")
        if result:
            self.current = None
            self.context_text.edit_modified(False)
            self.refresh()

    def activate(self):
        if not self.current:
            return
        name = self.current
        if self._call(lambda: self.backend.select(name),
                      success=f"Workspace ativo no CLI local: {name}") is not None:
            self.refresh(prefer=name)

    def open_folder(self):
        from tkinter import messagebox
        if not self.current:
            return
        path = self.backend.details(self.current)["root"]
        try:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            messagebox.showerror("Solo-MCP", str(exc), parent=self.root)

    def repo_dialog(self):
        from tkinter import messagebox
        if not self.current:
            return
        window = self.tk.Toplevel(self.root)
        window.title("Vincular repositório")
        window.transient(self.root)
        window.resizable(False, False)
        container = self.ttk.Frame(window, padding=16)
        container.pack(fill="both", expand=True)
        self.ttk.Label(container, text="Repositório (dono/nome)").grid(row=0, column=0, sticky="w")
        repo_input = self.ttk.Entry(container, width=48)
        repo_input.grid(row=1, column=0, pady=(3, 9))
        self.ttk.Label(container, text="Alias da conta (opcional)").grid(row=2, column=0, sticky="w")
        alias_input = self.ttk.Entry(container, width=48)
        alias_input.grid(row=3, column=0, pady=(3, 9))
        self.ttk.Label(container, text="Este vínculo não faz login no GitHub.",
                       wraplength=340).grid(row=4, column=0, sticky="w", pady=(2, 10))
        def submit():
            repo, alias = repo_input.get().strip(), alias_input.get().strip()
            result = self._call(lambda: self.backend.link_repository(self.current, repo, alias),
                                success="Repositório associado como referência.")
            if result:
                window.destroy()
                self.show_selected(force=True)
        actions = self.ttk.Frame(container)
        actions.grid(row=5, column=0, sticky="e")
        self.ttk.Button(actions, text="Cancelar", command=window.destroy).pack(side="left", padx=6)
        self.ttk.Button(actions, text="Vincular", command=submit).pack(side="left")
        window.grab_set()
        repo_input.focus_set()

    def unlink_repo(self):
        from tkinter import messagebox
        selection = self.repo_tree.selection()
        if not self.current or not selection:
            messagebox.showinfo("Solo-MCP", "Selecione um repositório da lista.", parent=self.root)
            return
        link = self._repository_rows[int(selection[0])]
        if not messagebox.askyesno(
            "Desvincular",
            f"Desvincular {link['full_name']}?\nO repositório original não será modificado.",
            parent=self.root):
            return
        self._call(lambda: self.backend.unlink_repository(
            self.current, link["full_name"], link["account"]),
            success="Vínculo removido. Nenhum arquivo foi excluído.")
        self.show_selected(force=True)

    def save_permissions(self):
        from tkinter import messagebox
        if not self.current:
            return
        checked = {key for key, var in self.permission_vars.items() if var.get()}
        enabled = checked - {key for key, ok in self._last_permissions.items() if ok}
        summary = ", ".join(sorted(checked)) or "nenhuma"
        risk = ("\n\nATENÇÃO: você habilitou acesso direto ao terminal."
                if "terminal" in checked and not self._last_permissions.get("terminal") else "")
        if not messagebox.askyesno(
            "Confirmar permissões",
            f"Salvar para '{self.current}': {summary}?{risk}\n\n"
            "Direitos omitidos serão revogados. Aprovação de tarefas continua obrigatória.",
            parent=self.root):
            return
        if self._call(lambda: self.backend.permissions(self.current, checked),
                      success="Permissões salvas localmente.") is not None:
            self.show_selected(force=True)

    def save_context(self):
        if not self.current:
            return
        body = self.context_text.get("1.0", "end-1c")
        if self._call(lambda: self.backend.save_context(self.current, body),
                      success="Contexto salvo somente no computador.") is not None:
            self.context_text.edit_modified(False)
            self.show_selected(force=True)

    def save_sharing(self):
        from tkinter import messagebox
        if not self.current:
            return
        enabled = self.share_var.get()
        if enabled:
            if not messagebox.askyesno(
                "Compartilhamento do contexto",
                "Permitir que solicitações autorizadas de leitura retornem o contexto "
                "através das Issues privadas do GitHub?\n\n"
                "O conteúdo pode permanecer no histórico dessas Issues.",
                parent=self.root):
                self.share_var.set(False)
                return
        if self._call(lambda: self.backend.share_context(self.current, enabled),
                      success=("Leitura remota ativada." if enabled else "Leitura remota desativada.")
                      ) is not None:
            self.show_selected(force=True)

    def check_environment(self):
        self.check_button.configure(state="disabled")
        self._set_environment("Consultando serviço e contêineres...")
        def work():
            try:
                data = self.backend.system_checks()
            except Exception as exc:
                data = f"Falha na verificação: {exc}"
            self._events.put(data)
        threading.Thread(target=work, daemon=True).start()

    def _drain_events(self):
        while True:
            try:
                result = self._events.get_nowait()
            except queue.Empty:
                break
            self._set_environment(result)
            self.check_button.configure(state="normal")
        if self.root.winfo_exists():
            self.root.after(200, self._drain_events)
