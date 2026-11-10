"""Run generated Python outside the API process.

The subprocess fallback is not a secure sandbox. It strips secrets and blocks
``open`` paths outside the job directory. Docker, when present, adds a network
none container and the configured memory cap.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.config import Settings

_PROCESSES: dict[str, subprocess.Popen] = {}
_DOCKER_READY: bool | None = None

_WRAPPER = """
import builtins, os, pathlib, sys
ROOT = pathlib.Path(os.environ["SANDBOX_ROOT"]).resolve()
_open = builtins.open
_read = []
for item in os.environ.get("SANDBOX_READ_ROOTS", "").split(os.pathsep):
    if item:
        _read.append(pathlib.Path(item).resolve())
if _read:
    _read.append(pathlib.Path(sys.prefix).resolve())
    _read.append(pathlib.Path(sys.base_prefix).resolve())

def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

def _guard(file, mode="r", *args, **kwargs):
    path = pathlib.Path(file)
    if not path.is_absolute():
        path = (pathlib.Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    writing = any(flag in str(mode) for flag in ("w", "a", "x", "+"))
    if writing:
        allowed = _inside(path, ROOT)
    else:
        allowed = _inside(path, ROOT) or any(_inside(path, root) for root in _read)
    if not allowed:
        raise PermissionError("path outside the job directory")
    return _open(path, mode, *args, **kwargs)

builtins.open = _guard
script = pathlib.Path(os.environ["SANDBOX_SCRIPT"])
code = script.read_text(encoding="utf-8")
exec(compile(code, str(script), "exec"), {"__name__": "__main__"})
"""


def docker_available() -> bool:
    """Return whether the docker daemon can run a container.

    Returns:
        True when ``docker info`` exits 0 and does not report a dead engine.
        A CLI that answers ``--version`` while Docker Desktop is stopped is
        treated as unavailable so jobs use the labelled fallback.
    """
    global _DOCKER_READY
    if _DOCKER_READY is not None:
        return _DOCKER_READY
    _DOCKER_READY = _docker_daemon_ready()
    return _DOCKER_READY


def _docker_daemon_ready() -> bool:
    """Probe the Docker daemon once.

    Returns:
        True when the daemon reports a server version.
    """
    if shutil.which("docker") is None:
        return False
    try:
        completed = subprocess.run(
            ["docker", "info"],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = (completed.stdout + completed.stderr).decode("utf-8", errors="replace").lower()
    if completed.returncode != 0 or "error during connect" in text or "cannot connect" in text:
        return False
    return "server version" in text or "serverversion" in text


def docker_command(
    settings: Settings,
    job_dir: Path,
    script_name: str,
    *,
    extra_mounts: list[tuple[Path, str]] | None = None,
    extra_env: dict[str, str] | None = None,
) -> list[str]:
    """Build a docker run command that has no network and no API key.

    Args:
        settings: Application settings.
        job_dir: Host job directory mounted at ``/work``.
        script_name: Script filename inside the job directory.
        extra_mounts: Read-only host path and container path pairs.
        extra_env: Extra environment entries. Do not pass API keys.

    Returns:
        Argument list. API keys are not included.
    """
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        f"{settings.sandbox_memory_mb}m",
    ]
    for key, value in (extra_env or {}).items():
        command.extend(["-e", f"{key}={value}"])
    command.extend(["-v", f"{job_dir.resolve()}:/work:rw"])
    for host, guest in extra_mounts or []:
        command.extend(["-v", f"{host.resolve()}:{guest}:ro"])
    command.extend(["-w", "/work", settings.sandbox_image, "python", script_name])
    return command


def cancel_process(job_id: str) -> bool:
    """Kill a sandbox process that is still running.

    Args:
        job_id: Job id passed to ``run_script``.

    Returns:
        True when a live process was killed.
    """
    proc = _PROCESSES.get(job_id)
    if proc is None or proc.poll() is not None:
        return False
    proc.kill()
    return True


def run_script(
    settings: Settings,
    job_dir: Path,
    script: str,
    timeout: int | None = None,
    job_id: str | None = None,
    *,
    script_name: str = "main.py",
    read_roots: list[Path] | None = None,
    pythonpath: str | None = None,
    force_subprocess: bool = False,
    extra_mounts: list[tuple[Path, str]] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict:
    """Execute a script in Docker or the labelled subprocess fallback.

    Args:
        settings: Application settings.
        job_dir: Directory that holds the script and receives outputs.
        script: Python source.
        timeout: Seconds before the process is killed.
        job_id: Optional id so a cancel request can kill this process.
        script_name: Filename written inside the job directory.
        read_roots: Extra directories the subprocess may read. The interpreter
            prefix is included so pandas and scikit-learn can import.
        pythonpath: ``PYTHONPATH`` for the subprocess.
        force_subprocess: Skip Docker and use the app interpreter.
        extra_mounts: Read-only mounts used only by Docker.
        extra_env: Extra Docker environment entries. Do not pass API keys.

    Returns:
        Manifest with isolation mode, exit code, and output tails.
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    script_path = job_dir / script_name
    script_path.write_text(script, encoding="utf-8")
    limit = timeout or settings.sandbox_timeout_seconds
    if docker_available() and not force_subprocess:
        command = docker_command(
            settings,
            job_dir,
            script_name,
            extra_mounts=extra_mounts,
            extra_env=extra_env,
        )
        code, stdout_b, stderr_b, timed_out = _spawn(
            command, cwd=None, env=_clean_env(), timeout=limit, job_id=job_id
        )
        isolation = "docker"
        warning = None
    else:
        wrapper = job_dir / "_wrapper.py"
        wrapper.write_text(_WRAPPER, encoding="utf-8")
        env = _clean_env()
        env["SANDBOX_ROOT"] = str(job_dir.resolve())
        env["SANDBOX_SCRIPT"] = str(script_path.resolve())
        if read_roots:
            env["SANDBOX_READ_ROOTS"] = os.pathsep.join(str(path.resolve()) for path in read_roots)
        if pythonpath:
            env["PYTHONPATH"] = pythonpath
        code, stdout_b, stderr_b, timed_out = _spawn(
            [sys.executable, str(wrapper)],
            cwd=str(job_dir),
            env=env,
            timeout=limit,
            job_id=job_id,
        )
        isolation = "subprocess_fallback"
        if force_subprocess and docker_available():
            reason = (
                "This analysis used the app interpreter because the configured sandbox image "
                "does not include the scientific libraries. "
            )
        else:
            reason = "Docker is not available. "
        warning = (
            reason
            + "This run used a subprocess with the API key removed and file access limited to the job directory. "
            "That is reduced isolation, not a secure sandbox. "
            f"The configured memory cap is {settings.sandbox_memory_mb} MB and is enforced when Docker runs the job."
        )
    stdout = stdout_b.decode("utf-8", errors="replace")
    stderr = stderr_b.decode("utf-8", errors="replace")
    (job_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (job_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    return {
        "isolation": isolation,
        "warning": warning,
        "exit_code": code,
        "timed_out": timed_out,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
    }


def _spawn(
    command: list[str],
    *,
    cwd: str | None,
    env: dict[str, str],
    timeout: int,
    job_id: str | None,
) -> tuple[int, bytes, bytes, bool]:
    """Run a command and kill it when the timeout or a cancel lands.

    Args:
        command: Argv.
        cwd: Working directory.
        env: Environment without the API key.
        timeout: Seconds.
        job_id: Optional cancel key.

    Returns:
        Exit code, stdout, stderr, and whether the run timed out.
    """
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if job_id:
        _PROCESSES[job_id] = proc
    timed_out = False
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            timed_out = True
        code = proc.returncode if proc.returncode is not None else 1
        return code, stdout or b"", stderr or b"", timed_out
    finally:
        if job_id:
            _PROCESSES.pop(job_id, None)


def _clean_env() -> dict[str, str]:
    """Return an environment without API keys.

    Returns:
        Environment mapping.
    """
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    env.pop("ANTHROPIC_API_KEY", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env
