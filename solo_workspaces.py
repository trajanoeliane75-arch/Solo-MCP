"""Optional workspace metadata and persistent, locally controlled project context.

A workspace is a named Solo-MCP project, not a GitHub repository.
Its context stays outside the project in the user's private config directory.
No context is transmitted in GitHub Issues unless the user explicitly opts in.
"""
import os
from pathlib import Path
import tempfile

import solo_projects as projects

CONTEXT_ROOT = Path.home() / ".config" / "solo-mcp" / "workspaces"
CONTEXT_FILENAME = "CONTEXT.md"
MAX_CONTEXT_BYTES = 16000
ACCOUNT_NAME = projects.NAME_RE


def choose_workspace(task):
    """Require explicit workspace identity in remote requests; no implicit active fallback."""
    project, workspace = task.get("project"), task.get("workspace")
    if project is not None and workspace is not None and project != workspace:
        raise ValueError("project e workspace apontam para projetos diferentes")
    name = workspace if workspace is not None else project
    if not isinstance(name, str) or not projects.NAME_RE.fullmatch(name):
        raise ValueError("Informe um workspace válido usando project ou workspace")
    return name


def entry_for(config, name):
    if not isinstance(name, str) or not projects.NAME_RE.fullmatch(name):
        raise ValueError("Nome de workspace inválido")
    registry = config.get("projects", {})
    if not isinstance(registry, dict) or name not in registry:
        raise ValueError("Workspace não cadastrado: " + name)
    entry = registry[name]
    if not isinstance(entry, dict):
        raise ValueError("Cadastro de workspace inválido")
    return entry


def context_path(name):
    if not isinstance(name, str) or not projects.NAME_RE.fullmatch(name):
        raise ValueError("Nome de workspace inválido")
    return CONTEXT_ROOT / name / CONTEXT_FILENAME


def repository_links(config, name):
    entry = entry_for(config, name)
    links = []
    legacy = entry.get("github")
    if legacy:
        if not isinstance(legacy, str) or not projects.REPO_RE.fullmatch(legacy):
            raise ValueError("Repositório antigo inválido")
        links.append({"provider": "github", "full_name": legacy, "account": ""})
    additional = entry.get("repositories", [])
    if not isinstance(additional, list):
        raise ValueError("Lista de repositórios inválida")
    for link in additional:
        if not isinstance(link, dict) or link.get("provider") != "github":
            raise ValueError("Provedor de repositório inválido")
        repo = link.get("full_name")
        account = link.get("account", "")
        if not isinstance(repo, str) or not projects.REPO_RE.fullmatch(repo):
            raise ValueError("Nome de repositório inválido")
        if not isinstance(account, str) or (account and not ACCOUNT_NAME.fullmatch(account)):
            raise ValueError("Alias de conta inválido")
        normalized = {"provider": "github", "full_name": repo, "account": account}
        if normalized not in links:
            links.append(normalized)
    return links


def link_repository(config, name, full_name, account=""):
    entry = entry_for(config, name)
    if not isinstance(full_name, str) or not projects.REPO_RE.fullmatch(full_name):
        raise ValueError("Repositório deve ter formato proprietário/nome")
    if not isinstance(account, str) or (account and not ACCOUNT_NAME.fullmatch(account)):
        raise ValueError("Alias de conta inválido")
    link = {"provider": "github", "full_name": full_name, "account": account}
    if link in repository_links(config, name):
        raise ValueError("Repositório já está associado ao workspace")
    entry.setdefault("repositories", []).append(link)
    return link


def unlink_repository(config, name, full_name, account=""):
    entry = entry_for(config, name)
    sought = {"provider": "github", "full_name": full_name, "account": account}
    if sought not in repository_links(config, name):
        raise ValueError("Repositório não associado ao workspace")
    if account == "" and entry.get("github") == full_name:
        entry["github"] = ""
    else:
        entry["repositories"] = [x for x in entry.get("repositories", [])
                                 if x != sought]


def select_active(config, name):
    entry_for(config, name)
    config["active_workspace"] = name
    return name


def active_workspace(config):
    name = config.get("active_workspace")
    if name is None:
        return None
    entry_for(config, name)
    return name


def workspace_info(config, name):
    entry = entry_for(config, name)
    return {
        "workspace": name,
        "root": entry.get("path"),
        "permissions": projects.permissions_for(entry),
        "repositories": repository_links(config, name),
        "context_available": context_path(name).is_file(),
        "context_shared": entry.get("share_context", False) is True,
    }


def _private_dir(name):
    folder = context_path(name).parent
    if folder.is_symlink():
        raise ValueError("Diretório de contexto não pode ser symlink")
    CONTEXT_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    if CONTEXT_ROOT.is_symlink():
        raise ValueError("Diretório base de contexto não pode ser symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    return folder


def init_context(config, name):
    entry = entry_for(config, name)
    folder = _private_dir(name)
    target = folder / CONTEXT_FILENAME
    if target.is_symlink() or target.exists():
        raise ValueError("Contexto já existe; não será sobrescrito")
    template = (
        f"# Workspace: {name}\n\n"
        "## Objetivo\n\n"
        "Descreva o que você pretende construir.\n\n"
        "## Arquitetura e decisões\n\n"
        "Anote as decisões que deseja preservar entre conversas.\n\n"
        "## Estado atual\n\n"
        "O que já funciona e o que ainda não funciona?\n\n"
        "## Próximos passos\n\n"
        "- [ ] Primeira tarefa\n\n"
        "## Cuidados\n\n"
        "Nunca inclua senhas, tokens, chaves de acesso ou dados sigilosos.\n"
    )
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(template)
    return target


def replace_context(config, name, source):
    """Locally chosen text file -> private context; atomic and non-symlinked."""
    entry_for(config, name)
    source = Path(source).expanduser()
    if not source.is_file() or source.is_symlink():
        raise ValueError("Arquivo de contexto de origem inválido")
    data = source.read_bytes()
    if not data or len(data) > MAX_CONTEXT_BYTES or b"\x00" in data:
        raise ValueError("Contexto vazio, binário ou maior que 16 KB")
    data.decode("utf-8")
    folder = _private_dir(name)
    destination = folder / CONTEXT_FILENAME
    if destination.is_symlink():
        raise ValueError("Symlink bloqueado para arquivo de contexto")
    fd, temp = tempfile.mkstemp(prefix=".context-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temp, 0o600)
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return destination


def read_context(config, name, remote=False):
    entry = entry_for(config, name)
    if remote and entry.get("share_context", False) is not True:
        raise PermissionError(
            "Contexto não autorizado para leitura remota. "
            "Autorize localmente com workspace context share --name NOME --on"
        )
    file = context_path(name)
    if file.is_symlink() or not file.is_file():
        raise ValueError("Contexto não encontrado. Crie com workspace context init")
    if file.stat().st_size > MAX_CONTEXT_BYTES:
        raise ValueError("Contexto excedeu o limite de 16 KB")
    blob = file.read_bytes()
    if b"\x00" in blob or len(blob) > MAX_CONTEXT_BYTES:
        raise ValueError("Arquivo de contexto inválido")
    return blob.decode("utf-8")


def set_context_sharing(config, name, enabled):
    if type(enabled) is not bool:
        raise ValueError("Compartilhamento deve ser booleano")
    entry = entry_for(config, name)
    entry["share_context"] = enabled
    return enabled


def write_context_text(config, name, text):
    """Save GUI-edited private Markdown atomically, with no intermediate public file."""
    entry_for(config, name)
    if not isinstance(text, str):
        raise ValueError("Conteúdo de contexto inválido")
    blob = text.encode("utf-8")
    if not blob or len(blob) > MAX_CONTEXT_BYTES or b"\x00" in blob:
        raise ValueError("Contexto vazio, binário ou maior que 16 KB")
    folder = _private_dir(name)
    destination = folder / CONTEXT_FILENAME
    if destination.is_symlink():
        raise ValueError("Symlink bloqueado para arquivo de contexto")
    fd, temp = tempfile.mkstemp(prefix=".context-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(blob)
        os.chmod(temp, 0o600)
        os.replace(temp, destination)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return destination
