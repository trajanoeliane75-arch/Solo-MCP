"""Read-only local Git inspection for workspace folders.

No network access, cloning, checkout, staging, commits, or remote mutation.
A URL is exposed only when a local GitHub remote can be canonicalized safely.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

REPO_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def github_remote(raw):
    """Map recognized HTTPS/SSH GitHub remotes to a safe, credential-free URL."""
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    path = None
    if raw.startswith("git@github.com:"):
        path = raw[len("git@github.com:"):]
    else:
        try:
            parsed = urlsplit(raw)
            if (parsed.scheme not in ("https", "ssh")
                    or parsed.hostname != "github.com"
                    or parsed.port is not None
                    or parsed.query or parsed.fragment):
                return None
            if parsed.scheme == "ssh" and parsed.username != "git":
                return None
            path = parsed.path.lstrip("/")
        except ValueError:
            return None
    if path.endswith(".git"):
        path = path[:-4]
    if path and REPO_NAME.fullmatch(path):
        return {"full_name": path, "url": "https://github.com/" + path}
    return None


def run_readonly_git(root, *arguments):
    """Run Git without shell, hooks, external fsmonitor or optional index locks."""
    path = Path(root).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Pasta do workspace não existe")
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_TERMINAL_PROMPT"] = "0"
    command = ["git", "-c", "core.fsmonitor=false",
               "-c", "core.hooksPath=/dev/null", "-C", str(path), *arguments]
    return subprocess.run(
        command, capture_output=True, text=True,
        errors="replace", timeout=12, env=env, check=False
    )


def inspect_local_git(root):
    """Inspect the selected workspace's real local Git checkout, never online."""
    path = Path(root).expanduser().resolve(strict=True)
    if not path.is_dir():
        raise ValueError("Pasta do workspace não existe")
    base = {
        "is_repo": False, "workspace_path": str(path),
        "root": None, "branch": None, "changed": 0, "untracked": 0,
        "remote_name": None, "github_name": None, "github_url": None,
        "message": ""
    }
    if not shutil.which("git"):
        base["message"] = "Git não está instalado no computador."
        return base

    probe = run_readonly_git(path, "rev-parse", "--show-toplevel")
    if probe.returncode:
        base["message"] = "Esta pasta não é um repositório Git local."
        return base
    repo_root = Path(probe.stdout.strip()).resolve(strict=True)
    if not repo_root.is_dir():
        base["message"] = "Raiz do repositório Git não encontrada."
        return base
    base["is_repo"] = True
    base["root"] = str(repo_root)

    branch = run_readonly_git(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    if branch.returncode == 0:
        base["branch"] = branch.stdout.strip()[:150]
    else:
        detached = run_readonly_git(path, "rev-parse", "--short", "HEAD")
        base["branch"] = "HEAD separado" + (
            " (" + detached.stdout.strip()[:32] + ")" if detached.returncode == 0 else ""
        )

    status = run_readonly_git(path, "status", "--porcelain=v1", "--untracked-files=normal")
    if status.returncode == 0:
        files = status.stdout.splitlines()
        base["untracked"] = sum(line.startswith("??") for line in files)
        base["changed"] = len(files) - base["untracked"]
    else:
        base["message"] = "Não foi possível verificar todas as alterações locais."

    remotes = run_readonly_git(path, "remote")
    if remotes.returncode == 0:
        names = remotes.stdout.splitlines()
        if names:
            name = "origin" if "origin" in names else names[0]
            base["remote_name"] = name[:120]
            # Never include the raw URL: it may embed a user access token.
            remote = run_readonly_git(path, "remote", "get-url", name)
            if remote.returncode == 0:
                recognized = github_remote(remote.stdout)
                if recognized:
                    base["github_name"] = recognized["full_name"]
                    base["github_url"] = recognized["url"]
    if not base["message"]:
        base["message"] = "Git local consultado com sucesso, sem alterar arquivos."
    return base
