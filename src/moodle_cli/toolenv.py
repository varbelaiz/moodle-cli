"""Changing the environment moodle itself is installed in.

`uv tool install` is the supported path and the awkward one: extras and injected packages
are properties of the whole tool environment, not of a package, and re-running the install
replaces that set rather than adding to it. So the command is rebuilt from the current
state every time, and anything the user injected by hand is carried across untouched.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path
from typing import Literal

from moodle_cli.errors import MoodleError
from moodle_cli.plugins import CORE_DISTRIBUTION

Kind = Literal["uv-tool", "uv-managed", "editable", "unmanaged"]

# `uv tool list --show-with` appends the injected set to the tool's own line.
_WITH_CLAUSE = re.compile(r"\[with:\s*([^\]]*)\]")


@dataclass(frozen=True)
class Environment:
    """Where this moodle is installed, which decides how a plugin can be added to it."""

    kind: Kind
    python: Path
    uv: str | None


def detect() -> Environment:
    """Classify the environment moodle is running from."""
    uv = shutil.which("uv")
    python = Path(sys.executable)

    if _is_editable():
        return Environment("editable", python, uv)
    if uv is None:
        return Environment("unmanaged", python, uv)
    if _is_uv_tool(uv):
        return Environment("uv-tool", python, uv)
    return Environment("uv-managed", python, uv)


def _is_editable() -> bool:
    """Whether the core is installed from a source checkout rather than a built wheel.

    The presence of ``direct_url.json`` is not the question: PEP 610 writes it for any
    install that names a source directly, including a local wheel and a git URL. Only
    ``dir_info.editable`` says the install points back at a checkout, which is what makes
    changing extras here the wrong move.
    """
    try:
        raw = distribution(CORE_DISTRIBUTION).read_text("direct_url.json")
    except (PackageNotFoundError, OSError):
        return False
    if not raw:
        return False
    try:
        direct_url = json.loads(raw)
    except ValueError:
        return False
    return bool(direct_url.get("dir_info", {}).get("editable", False))


def _is_uv_tool(uv: str) -> bool:
    """Whether this interpreter lives in a `uv tool install` environment.

    Asks uv where its tool directory is rather than reading `pyvenv.cfg`: uv writes its own
    version into every venv it creates, including a project's `.venv`, so that key answers
    "made by uv" and not the question being asked here. Going through the command also
    honours UV_TOOL_DIR for free.
    """
    try:
        result = subprocess.run(
            [uv, "tool", "dir"], capture_output=True, text=True, timeout=30, check=True
        )
    except (subprocess.SubprocessError, OSError):
        return False
    root = result.stdout.strip()
    if not root:
        return False
    return Path(sys.prefix).resolve().is_relative_to(Path(root).resolve())


def injected_packages(uv: str) -> list[str] | None:
    """The packages injected into the tool environment with `--with`.

    None when the answer cannot be read, which callers must treat as a stop rather than as
    "none": rebuilding the install without a package someone injected would silently
    uninstall it. Parsed out of `uv tool list --show-with`, the public way to ask; the
    receipt file beside the environment holds the same thing but is private to uv and has
    already changed shape once.
    """
    try:
        result = subprocess.run(
            [uv, "tool", "list", "--show-with"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped.startswith(f"{CORE_DISTRIBUTION} "):
            continue
        clause = _WITH_CLAUSE.search(stripped)
        if clause is None:
            return []
        return [part.strip() for part in clause.group(1).split(",") if part.strip()]

    return None


def install_command(uv: str, extras: Iterable[str], injected: Sequence[str]) -> list[str]:
    """The full `uv tool install` that leaves the environment holding exactly this set.

    Everything is restated because `--with` replaces rather than adds, and `--reinstall` is
    required because uv would otherwise see the requirement already satisfied and do
    nothing.
    """
    wanted = sorted(extras)
    spec = f"{CORE_DISTRIBUTION}[{','.join(wanted)}]" if wanted else CORE_DISTRIBUTION
    argv = [uv, "tool", "install", "--reinstall", spec]
    for package in injected:
        argv += ["--with", package]
    return argv


def pip_command(uv: str, python: Path, spec: str, *, uninstall: bool = False) -> list[str]:
    """Install or remove a package in a plain virtual environment.

    Goes through `uv pip` rather than pip: a uv-created environment has no pip in it, and
    shelling to whichever pip is first on PATH could target a different interpreter.
    """
    action = "uninstall" if uninstall else "install"
    return [uv, "pip", action, "--python", str(python), spec]


def run(argv: Sequence[str], *, capture: bool) -> str:
    """Run a packaging command, raising a MoodleError if it fails.

    Not captured by default: an install is slow, and swallowing uv's progress makes it read
    as a hang.
    """
    try:
        result = subprocess.run(
            list(argv),
            capture_output=capture,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise MoodleError(f"Could not run {argv[0]!r}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise MoodleError(
            f"{' '.join(argv)} failed with exit code {exc.returncode}"
            + (f": {detail}" if detail else "")
        ) from exc
    return (result.stdout or "") if capture else ""
