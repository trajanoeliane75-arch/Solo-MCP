"""Rootless Podman sandbox for Solo-MCP.

Networked dependency installation receives NO project directory mount.
Project execution mounts the project read-only and disables networking.
This is risk reduction, not a malware-proof VM.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

DEFAULT_IMAGE = "docker.io/library/python:3.12-slim"
PACKAGE_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"(?:(?:==|~=|!=|>=|<=|>|<)[A-Za-z0-9.*+_-]+)?\Z"
)
RUN_PROGRAMS = frozenset({"python", "python3", "pytest"})
MEMORY = "1g"
CPU = "1"
PIDS = "128"


def package_volume(project_name, root):
    if not isinstance(project_name, str) or not project_name:
        raise ValueError("Projeto inválido")
    salt = (str(root.resolve()) + "\n" + project_name).encode("utf-8")
    return "solo-mcp-packages-" + hashlib.sha256(salt).hexdigest()[:20]


def validate_packages(packages):
    if not isinstance(packages, list) or not (1 <= len(packages) <= 20):
        raise ValueError("Forneça de 1 a 20 pacotes")
    if not all(isinstance(p, str) and 1 <= len(p) <= 96 and PACKAGE_PATTERN.fullmatch(p)
               for p in packages):
        raise ValueError("Pacote inválido: forneça nomes, versões ou intervalos simples; sem flags nem URLs")
    return packages


def validate_run_command(argv):
    if not isinstance(argv, list) or not (1 <= len(argv) <= 25):
        raise ValueError("Comando sandbox inválido")
    if not all(isinstance(x, str) and 0 < len(x) <= 2048 and "\x00" not in x
               for x in argv):
        raise ValueError("Argumento inválido")
    if argv[0] not in RUN_PROGRAMS:
        raise ValueError("Executável permitido na sandbox: python, python3 ou pytest")
    return argv


def podman_preflight():
    """Require rootless mode; never run the agent or container as host root."""
    if os.name != "posix" or os.geteuid() == 0:
        raise RuntimeError("Podman deve ser executado sem root/sudo")
    if not shutil.which("podman"):
        raise RuntimeError("Instale Podman: sudo apt install podman (depois rode sem sudo)")
    info = subprocess.run(["podman", "info", "--format", "{{.Host.Security.Rootless}}"],
                          text=True, capture_output=True, timeout=25)
    if info.returncode or info.stdout.strip().lower() != "true":
        raise RuntimeError("Podman não está disponível em modo rootless: " + info.stderr[:250])


def base_argv(image=DEFAULT_IMAGE):
    """No privilege escalation, no host home mount, no host root."""
    if image != DEFAULT_IMAGE:
        raise ValueError("Imagem não permitida; use somente a imagem configurada")
    return [
        "podman", "run", "--rm", "--pull=never", "--read-only",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=" + PIDS, "--memory=" + MEMORY, "--cpus=" + CPU,
        "--ipc=private", "--http-proxy=false",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=512m",
        "--env=HOME=/tmp", "--env=PYTHONDONTWRITEBYTECODE=1"
    ]


def build_install_command(project_name, root, packages):
    """Network allowed; only a named dependency volume is mounted, never the project."""
    packages = validate_packages(packages)
    volume = package_volume(project_name, root)
    return (
        base_argv() +
        ["--mount=type=volume,source=" + volume + ",destination=/packages",
         "--workdir=/tmp",
         # Default rootless networking only for the dependency-fetching phase.
         DEFAULT_IMAGE, "python", "-m", "pip", "install",
         "--disable-pip-version-check", "--only-binary=:all:",
         "--no-cache-dir", "--target=/packages", "--"] +
        packages
    )


def build_run_command(project_name, root, argv):
    """Offline execution: read-only project and dependencies, no home or GitHub token."""
    argv = validate_run_command(argv)
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Diretório do projeto inexistente")
    if any(c in str(root) for c in (',', '\n', '\r', '\x00')):
        raise ValueError('Caminho contém caracteres incompatíveis com a montagem Podman')
    volume = package_volume(project_name, root)
    return (
        base_argv() +
        ["--network=none",
         "--mount=type=bind,source=" + str(root) + ",destination=/work,readonly=true",
         "--mount=type=volume,source=" + volume + ",destination=/packages,readonly=true",
         "--env=PYTHONPATH=/packages", "--workdir=/work", DEFAULT_IMAGE] + argv
    )


def run_sandbox(command, timeout=120):
    podman_preflight()
    if not isinstance(command, list) or command[:2] != ["podman", "run"]:
        raise ValueError("Comando Podman inválido")
    limit = min(180, max(10, int(timeout)))
    try:
        result = subprocess.run(command, text=True, capture_output=True,
                                timeout=limit, check=False)
    except subprocess.TimeoutExpired:
        return {"status":"timeout", "seconds":limit}
    return {"returncode":result.returncode,
            "stdout":result.stdout[:20000], "stderr":result.stderr[:20000]}
