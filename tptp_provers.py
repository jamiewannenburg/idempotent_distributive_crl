"""TPTP conversion and ATP backends (Vampire, Zipperposition) for free-algebra search.

LADR theories are converted with the LADR ``ladr_to_tptp`` binary (located via
``pyp9m4.BinaryResolver``) using ordinary ``subprocess`` pipes. ``LadrToTptp.run``
is not used: on Windows it drives the child through asyncio Proactor pipes, which
can deliver empty stdin/stdout once other solvers (especially Cygwin Vampire) are
running. Infix ``<=`` is sometimes left as infix in FOF formulas; we rewrite those
atoms to the ``tptp1/2`` predicate that the converter already uses in CNF.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pyp9m4 import BinaryResolver

logger = logging.getLogger(__name__)

_SZS_STATUS_RE = re.compile(r"%\s*SZS\s+status\s+(\w+)", re.IGNORECASE)
_PROVED_STATUSES = frozenset({"Theorem", "Unsatisfiable"})
_TPTP_FORMULA_RE = re.compile(r"(?:fof|cnf|tff|thf)\s*\(", re.IGNORECASE)
_UNSAT_LINE_RE = re.compile(r"(?m)^\s*unsat\s*$")


def _find_term_left(s: str, end: int) -> tuple[int, int]:
    i = end - 1
    while i >= 0 and s[i].isspace():
        i -= 1
    if i < 0:
        raise ValueError("missing left operand of <=")
    if s[i] == ")":
        depth = 0
        while i >= 0:
            if s[i] == ")":
                depth += 1
            elif s[i] == "(":
                depth -= 1
                if depth == 0:
                    j = i - 1
                    while j >= 0 and (s[j].isalnum() or s[j] == "_"):
                        j -= 1
                    return j + 1, end
            i -= 1
        raise ValueError("unbalanced parentheses in left operand of <=")
    j = i
    while j >= 0 and (s[j].isalnum() or s[j] == "_"):
        j -= 1
    return j + 1, end


def _find_term_right(s: str, start: int) -> tuple[int, int]:
    i = start
    n = len(s)
    while i < n and s[i].isspace():
        i += 1
    if i >= n:
        raise ValueError("missing right operand of <=")
    j = i
    while j < n and (s[j].isalnum() or s[j] == "_"):
        j += 1
    if j < n and s[j] == "(":
        depth = 0
        while j < n:
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    return start, j + 1
            j += 1
        raise ValueError("unbalanced parentheses in right operand of <=")
    return start, j


def replace_infix_le(tptp: str, pred: str = "tptp1") -> str:
    """Rewrite remaining infix ``<=`` atoms to ``pred(Left,Right)`` (skip ``<=>``)."""
    out: list[str] = []
    i = 0
    while True:
        k = tptp.find("<=", i)
        if k < 0:
            out.append(tptp[i:])
            break
        if k + 2 < len(tptp) and tptp[k + 2] == ">":
            out.append(tptp[i : k + 3])
            i = k + 3
            continue
        left_start, left_end = _find_term_left(tptp, k)
        _right_start, right_end = _find_term_right(tptp, k + 2)
        out.append(tptp[i:left_start])
        left = tptp[left_start:left_end].strip()
        right = tptp[_right_start:right_end].strip()
        out.append(f"{pred}({left},{right})")
        i = right_end
    return "".join(out)


_LADR_TO_TPTP_EXE: Path | None = None
_LADR_TO_TPTP_TIMEOUT_S = 60.0


def _ladr_to_tptp_executable() -> Path:
    """Resolve ``ladr_to_tptp`` once (pyp9m4 may download the LADR tools)."""
    global _LADR_TO_TPTP_EXE
    if _LADR_TO_TPTP_EXE is None:
        _LADR_TO_TPTP_EXE = BinaryResolver().resolve("ladr_to_tptp")
    return _LADR_TO_TPTP_EXE


def _conversion_failure_detail(stdout: str, stderr: str, exit_code: int | None) -> str:
    """Prefer LADR diagnostics. Parse errors often go to stdout; exit 1 is normal."""
    err = stderr.strip()
    if err:
        return f": {err}"
    out = stdout.strip()
    if out:
        snippet = out if len(out) <= 400 else f"{out[:400]}…"
        return f": {snippet}"
    return f" (exit {exit_code})"


def convert_ladr_to_tptp(ladr_text: str) -> str:
    """Convert a LADR/Prover9 theory to TPTP FOF/CNF and fix infix ``<=``.

    Invokes ``ladr_to_tptp`` with ``subprocess.run`` (blocking pipes). The binary
    always ``exit(1)`` even on success, so only missing TPTP formulas are a failure.
    """
    payload = ladr_text if ladr_text.endswith("\n") else f"{ladr_text}\n"
    try:
        completed = subprocess.run(
            [os.fspath(_ladr_to_tptp_executable())],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_LADR_TO_TPTP_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ladr_to_tptp timed out after {_LADR_TO_TPTP_TIMEOUT_S:g}s"
        ) from exc
    stdout = (completed.stdout or "").strip()
    if not stdout or not _TPTP_FORMULA_RE.search(stdout):
        raise RuntimeError(
            "ladr_to_tptp produced no usable TPTP formulas"
            + _conversion_failure_detail(stdout, completed.stderr or "", completed.returncode)
        )
    return replace_infix_le(stdout)


def parse_szs_status(line: str) -> str | None:
    match = _SZS_STATUS_RE.search(line)
    return match.group(1) if match else None


def _output_shows_proof(text: str) -> bool:
    """True if output reports a proof (SZS Theorem/Unsatisfiable, or smtcomp ``unsat``).

    Portfolio modes (e.g. Vampire ``casc``) may emit several SZS lines; a later
    ``Theorem`` still counts even if an earlier strategy reported ``GaveUp``.
    """
    if any(status in _PROVED_STATUSES for status in _SZS_STATUS_RE.findall(text)):
        return True
    return _UNSAT_LINE_RE.search(text) is not None


_TPTP_TMP = Path(__file__).resolve().parent / ".tptp_tmp"


def _expand_win_path(path: Path) -> Path:
    """Resolve 8.3 short names (``U28409~1``) that Cygwin mishandles."""
    path = Path(os.path.abspath(path))
    if sys.platform != "win32":
        return path
    import ctypes

    probe = path if path.exists() else path.parent
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetLongPathNameW(str(probe), buffer, 32768)
    if not length:
        return path
    long_probe = Path(buffer.value)
    if probe == path:
        return long_probe
    return long_probe / path.name


def _tptp_temp_dir() -> Path:
    """Gitignored workspace dir with a long Windows path (no ``~`` short names)."""
    _TPTP_TMP.mkdir(exist_ok=True)
    return _expand_win_path(_TPTP_TMP)


def _posix_path(path: Path) -> str:
    """Forward-slash long path. Cygwin Vampire mishandles backslashes and ``~`` names."""
    return str(_expand_win_path(path)).replace("\\", "/")


def _cygwin_env() -> dict[str, str]:
    """Point Cygwin Vampire's temp dir at the long-path workspace folder."""
    env = os.environ.copy()
    tmp = _posix_path(_tptp_temp_dir())
    env["TMP"] = tmp
    env["TEMP"] = tmp
    env["TMPDIR"] = tmp
    return env


@dataclass(frozen=True, slots=True)
class TptpProverSpec:
    """How to invoke a TPTP ATP that reports SZS status / smtcomp unsat."""

    name: str
    executable: str
    argv_builder: Callable[[str, float, str | None], list[str]]
    """``(problem_path, timeout_s, proof_file | None) -> argv`` including the executable."""
    posix_paths: bool = False
    wants_proof_file: bool = False


def _vampire_argv(problem: str, timeout_s: float, proof_file: str | None = None) -> list[str]:
    limit = max(1, int(timeout_s))
    argv = [
        "vampire",
        "--mode",
        "casc",
        "--input_syntax",
        "tptp",
        "--time_limit",
        str(limit),
        "--proof",
        "off",
    ]
    if proof_file:
        argv.extend(["--print_proofs_to_file", proof_file])
    argv.append(problem)
    return argv


def _zipperposition_argv(problem: str, timeout_s: float, proof_file: str | None = None) -> list[str]:
    # Zipperposition's --timeout uses Unix signals and crashes on Windows
    # (Sys.signal: unavailable signal). Enforce the limit in Python instead.
    del timeout_s, proof_file
    return ["zipperposition", "-i", "tptp", "-o", "tptp", problem]


def discover_tptp_provers(
    *,
    include: Sequence[str] | None = None,
) -> list[TptpProverSpec]:
    """Return Vampire/Zipperposition specs for binaries found on ``PATH``.

    *include* restricts names (case-insensitive). ``None`` means all known.
    """
    wanted = None if include is None else {n.strip().lower() for n in include if n.strip()}
    catalog: list[tuple[str, str, Callable[[str, float, str | None], list[str]], dict[str, bool]]] = [
        (
            "vampire",
            "vampire",
            _vampire_argv,
            {
                "posix_paths": True,
                "wants_proof_file": True,
            },
        ),
        ("zipperposition", "zipperposition", _zipperposition_argv, {}),
    ]
    found: list[TptpProverSpec] = []
    for name, exe, builder, flags in catalog:
        if wanted is not None and name not in wanted:
            continue
        path = shutil.which(exe)
        if path is None:
            if wanted is not None:
                logger.warning("requested TPTP prover %s not found on PATH", name)
            continue
        found.append(
            TptpProverSpec(
                name=name,
                executable=path,
                argv_builder=lambda problem, timeout, proof, _b=builder: _b(problem, timeout, proof),
                **flags,
            )
        )
    return found


def _kill_process_tree(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.debug("process %s did not exit after kill", proc.pid)


async def try_prove_tptp(
    prover: TptpProverSpec,
    tptp_text: str,
    *,
    timeout_s: float,
) -> bool:
    """Run *prover* on *tptp_text*; return True iff the output indicates a proof."""
    temp_dir = _tptp_temp_dir()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".p",
        prefix=f"{prover.name}_",
        dir=temp_dir,
        delete=False,
    ) as handle:
        handle.write(tptp_text)
        if not tptp_text.endswith("\n"):
            handle.write("\n")
        problem_path = Path(handle.name)
    proof_path = problem_path.with_suffix(".proof") if prover.wants_proof_file else None
    out_path = problem_path.with_suffix(".out")
    problem_arg = _posix_path(problem_path) if prover.posix_paths else str(problem_path)
    proof_arg = _posix_path(proof_path) if proof_path is not None else None
    argv = [prover.executable, *prover.argv_builder(problem_arg, timeout_s, proof_arg)[1:]]

    proc: subprocess.Popen[bytes] | None = None
    try:
        env = _cygwin_env() if prover.posix_paths else None

        def run() -> bytes:
            nonlocal proc
            # Create the process on this worker thread so Windows uses ordinary
            # pipes, not the asyncio Proactor overlapped handles that stall
            # Cygwin Vampire's casc fork.
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            stdout, stderr = proc.communicate(timeout=timeout_s)
            return (stdout or b"") + (stderr or b"")

        try:
            stdout = await asyncio.to_thread(run)
        except subprocess.TimeoutExpired:
            logger.warning("%s timed out after %ss", prover.name, timeout_s)
            return False
        chunks = [stdout.decode("utf-8", errors="replace")]
        if proof_path is not None and proof_path.exists():
            try:
                chunks.append(proof_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        if out_path.exists():
            try:
                chunks.append(out_path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        return _output_shows_proof("\n".join(chunks))
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("%s failed", prover.name)
        return False
    finally:
        if proc is not None:
            await asyncio.to_thread(_kill_process_tree, proc)
        for path in (problem_path, out_path, proof_path):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
