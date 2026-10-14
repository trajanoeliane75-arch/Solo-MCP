"""Local per-project access policy for Solo-MCP.

Policies are stored in ~/.config/solo-mcp/config.json, never in a repository.
Missing policies on older configurations are intentionally read-only.
"""
import re
from pathlib import Path

CAPABILITIES = ("read", "write", "terminal", "desktop", "environment")
ACTION_CAPABILITIES = {
    "list": ("read",),
    "read": ("read",),
    "archive_list": ("read",),
    "file_info": ("read",),
    "workspace_info": ("read",),
    "workspace_context": ("read",),
    "doc_read": ("read",),
    "git_status": ("read",),
    "write": ("write",),
    "doc_create": ("write",),
    "doc_append": ("read", "write"),
    "run": ("terminal",),
    "open_app": ("desktop",),
    "open_document": ("read", "desktop"),
    "web_search": ("desktop",),
    "venv_create": ("write", "environment"),
    "sandbox_install": ("environment",),
    "sandbox_run": ("read", "environment"),
}
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,49}\Z")
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def default_permissions():
    return {name: name == "read" for name in CAPABILITIES}


def parse_permissions(names):
    if not isinstance(names, str):
        raise ValueError("Permissões devem ser separadas por vírgulas")
    enabled = set(filter(None, (item.strip().lower() for item in names.split(","))))
    invalid = enabled - set(CAPABILITIES)
    if invalid:
        raise ValueError("Permissão desconhecida: " + ", ".join(sorted(invalid)))
    return {key: key in enabled for key in CAPABILITIES}


def permissions_for(project):
    if not isinstance(project, dict):
        raise ValueError("Configuração de projeto inválida")
    stored = project.get("permissions")
    if stored is None:
        return default_permissions()
    if not isinstance(stored, dict) or (stored.keys() - set(CAPABILITIES)):
        raise ValueError("Permissões de projeto malformadas")
    merged = default_permissions()
    for key, value in stored.items():
        if type(value) is not bool:
            raise ValueError("Permissão não booleana: " + key)
        merged[key] = value
    return merged


def check_permission(config, project_name, action):
    if not isinstance(config, dict):
        raise ValueError("Configuração inválida")
    projects = config.get("projects", {})
    if not isinstance(projects, dict) or project_name not in projects:
        raise ValueError("Projeto não cadastrado: " + str(project_name))
    needed = ACTION_CAPABILITIES.get(action)
    if needed is None:
        raise ValueError("Ação não suportada: " + str(action))
    permissions = permissions_for(projects[project_name])
    missing = [cap for cap in needed if not permissions[cap]]
    if missing:
        raise PermissionError(
            "Projeto " + str(project_name) + " não permite " + ", ".join(missing) +
            ". Conceda apenas as permissões necessárias com "
            "python3 solo_mcp.py set-permissions --project NOME --allow read,..."
        )


def register_project(config, name, path, repo="", replace=False):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError("Nome de projeto inválido")
    if not isinstance(repo, str) or (repo and not REPO_RE.fullmatch(repo)):
        raise ValueError("Repositório GitHub inválido")
    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Projeto deve ser um diretório existente")
    # Guard against accidental access to an entire home or filesystem.
    home = Path.home().resolve()
    if path == Path("/") or path == home or path in home.parents:
        raise ValueError("Cadastre uma pasta específica, não a raiz ou a HOME inteira")
    if home / ".config" == path or (home / ".config") in path.parents:
        raise ValueError("Não cadastre diretórios de configuração e credenciais")
    existing = config.setdefault("projects", {})
    if name in existing and not replace:
        raise ValueError("Projeto já cadastrado (evita substituição acidental): " + name)
    if name in existing and replace:
        before = existing[name]
        permissions = permissions_for(before)
        # Preserve workspace context/repo links when re-pointing its local folder.
        updated = dict(before)
        if not repo:
            repo = before.get("github", "")
    else:
        permissions = default_permissions()
        updated = {}
    updated.update({"path": str(path), "github": repo, "permissions": permissions})
    existing[name] = updated
    return updated


def set_permissions(config, name, names):
    projects = config.get("projects", {})
    if name not in projects:
        raise ValueError("Projeto não cadastrado: " + str(name))
    perms = parse_permissions(names)
    projects[name]["permissions"] = perms
    return perms


def remove_project(config, name):
    projects = config.get("projects", {})
    if name not in projects:
        raise ValueError("Projeto não cadastrado: " + str(name))
    del projects[name]
