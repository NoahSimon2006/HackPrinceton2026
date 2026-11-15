"""Locate the SUMO binaries and tools installed by the eclipse-sumo wheel on any platform."""
import os
import subprocess
import sys
from pathlib import Path


def sumo_home() -> Path:
    try:
        import sumo
        return Path(sumo.SUMO_HOME)
    except ImportError:
        env = os.getenv("SUMO_HOME")
        if env:
            return Path(env)
    raise FileNotFoundError("SUMO is not installed. Install requirements-sim.txt.")


def binary(name: str) -> str:
    folder = sumo_home() / "bin"
    for candidate in (folder / f"{name}.exe", folder / name):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(f"SUMO binary {name} not found in {folder}.")


def tool(*parts: str) -> str:
    path = sumo_home() / "tools" / Path(*parts)
    if not path.exists():
        raise FileNotFoundError(f"SUMO tool {path} not found.")
    return str(path)


def environment() -> dict:
    return {**os.environ, "SUMO_HOME": str(sumo_home())}


def run(command, *, cwd, log=None, timeout=600):
    """Run a SUMO command; raise with the log location on failure."""
    result = subprocess.run([str(c) for c in command], cwd=cwd, env=environment(), text=True,
                            capture_output=True, timeout=timeout)
    if log:
        Path(cwd, log).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"{Path(str(command[0])).name} failed: {(result.stderr or result.stdout)[-400:]}")
    return result


PYTHON = sys.executable
