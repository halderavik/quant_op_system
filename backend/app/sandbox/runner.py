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
import builtins, os, pathlib
ROOT = pathlib.Path(os.environ["SANDBOX_ROOT"]).resolve()
_open = builtins.open

def _guard(file, mode="r", *args, **kwargs):
    path = pathlib.Path(file)
    if not path.is_absolute():
        path = (pathlib.Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if not str(path).startswith(str(ROOT)):
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


def docker_command(settings: Settings, job_dir: Path, script_name: str) -> list[str]:
    """Build a docker run command that has no network and no API key.

    Args:
        settings: Application settings.
        job_dir: Host job directory mounted at ``/work``.
        script_name: Script filename inside the job directory.

    Returns:
        Argument list. API keys are not included.
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        f"{settings.sandbox_memory_mb}m",
        "-v",
        f"{job_dir.resolve()}:/work:rw",
        "-w",
        "/work",
        settings.sandbox_image,
        "python",
        script_name,
    ]


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
) -> dict:
    """Execute a script in Docker or the labelled subprocess fallback.

    Args:
        settings: Application settings.
        job_dir: Directory that holds the script and receives outputs.
        script: Python source.
        timeout: Seconds before the process is killed.
        job_id: Optional id so a cancel request can kill this process.

    Returns:
        Manifest with isolation mode, exit code, and output tails.
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    script_path = job_dir / "main.py"
    script_path.write_text(script, encoding="utf-8")
    limit = timeout or settings.sandbox_timeout_seconds
    if docker_available():
        command = docker_command(settings, job_dir, "main.py")
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
        code, stdout_b, stderr_b, timed_out = _spawn(
            [sys.executable, str(wrapper)],
            cwd=str(job_dir),
            env=env,
            timeout=limit,
            job_id=job_id,
        )
        isolation = "subprocess_fallback"
        warning = (
            "Docker is not available. This run used a subprocess with the API key removed "
            "and file access limited to the job directory. That is reduced isolation, not a secure sandbox. "
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
    return env
