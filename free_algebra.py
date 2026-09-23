import asyncio
import gc
import itertools
import logging
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import matplotlib.backends.backend_pdf
import matplotlib.pyplot as plt
import networkx as nx
from pyp9m4 import ClauseTester, Mace4, Prover9, ProverOutcome, Theory

from tptp_provers import (
    TptpProverSpec,
    convert_ladr_to_tptp,
    discover_tptp_provers,
    try_prove_tptp,
)

logger = logging.getLogger(__name__)


class OperationType(Enum):
    INFIX = "infix"
    PREFIX = "prefix"
    POSTFIX = "postfix"

class Operation:
    arity: int
    type: OperationType
    symbol: str
    commutative: bool
    idempotent: bool
    def __init__(self, arity: int, type: OperationType, symbol: str, commutative: bool = False, idempotent: bool = False):
        self.arity = arity
        if type == OperationType.INFIX:
            assert arity == 2, f"Infix operation {symbol} expects 2 arguments, but {arity} were given"
        self.type = type
        self.symbol = symbol
        self.commutative = commutative
        self.idempotent = idempotent

    def __call__(self, arguments: Sequence[str]) -> str:
        assert len(arguments) == self.arity, f"Operation {self.symbol} expects {self.arity} arguments, but {len(arguments)} were given"
        if self.type == OperationType.INFIX:
            return f"({arguments[0]} {self.symbol} {arguments[1]})"
        elif self.type == OperationType.PREFIX:
            return f"{self.symbol}({','.join(arguments)})"
        elif self.type == OperationType.POSTFIX:
            return f"({','.join(arguments)}){self.symbol}"

def expand_terms(operations: list[Operation], current: Sequence[str]) -> list[str]:
    """Apply each operation once to *current*, returning newly formed terms.

    Commutative and idempotent operations use unordered argument tuples, matching
    ``terms``. The input sequence is not modified.
    """
    ts = list(current)
    seen = set(ts)
    new_terms: list[str] = []
    for operation in operations:
        if operation.arity <= 0:
            continue
        if operation.commutative and operation.idempotent:
            arg_iter: Iterable[tuple[str, ...]] = itertools.combinations(ts, operation.arity)
        elif operation.commutative:
            arg_iter = itertools.combinations_with_replacement(ts, operation.arity)
        else:
            arg_iter = itertools.product(ts, repeat=operation.arity)
        for args in arg_iter:
            new_term = operation(args)
            if new_term not in seen:
                seen.add(new_term)
                new_terms.append(new_term)
    return new_terms


def seed_terms(operations: list[Operation], variables: Sequence[str]) -> list[str]:
    """Variables followed by constant (arity-0) operation symbols."""
    ts = list(variables)
    for operation in operations:
        if operation.arity == 0:
            ts.append(operation.symbol)
    return ts


# Generate all terms up to a given level
def terms(operations: list[Operation], variables: list[str], max_level: int = 10, progress: bool = False) -> Iterator[str]:
    ts = seed_terms(operations, variables)
    yield from ts
    level = 0
    if progress:
        print(f"Level {level}: {len(ts)} terms")
    while level < max_level:
        new_terms = expand_terms(operations, ts)
        ts.extend(new_terms)
        yield from new_terms
        level += 1
        if progress:
            print(f"Level {level}: {len(ts)} terms")

# Generate all equations up to a given level with zig zag pattern.
# Like sympy.utilities.iterables.iproduct, but yields combinations (not the
# full product): equality is reflexive and symmetric, so we skip t=t and
# only yield each unordered pair once.
def icombinations(iterable: Iterable[str], r: int) -> Iterator[tuple[str, ...]]:
    if r < 0:
        raise ValueError("r must be non-negative")
    if r == 0:
        yield ()
        return

    elems: list[str] = []
    for x in iterable:
        elems.append(x)
        n = len(elems)
        if n < r:
            continue
        # Diagonal / online order: when a new element arrives, yield every
        # combination that includes it (paired with combinations of size
        # r-1 from earlier elements). Every finite combination appears
        # eventually, even if `iterable` is infinite.
        for prefix in itertools.combinations(elems[:-1], r - 1):
            yield prefix + (elems[-1],)


class Decision(Enum):
    PROVED = "proved"
    FALSIFIED = "falsified"
    UNKNOWN = "unknown"

class EquationVerdict(Enum):
    EQUAL = "="
    UNEQUAL = "!="
    UNKNOWN = "unknown"

class PartialOrderVerdict(Enum):
    EQUAL = "="
    LESS_THAN = "<"
    GREATER_THAN = ">"
    INCOMPARABLE = "|"
    UNKNOWN = "unknown"


class TermEquivalence:
    """Union-find partition of terms proven equal, with inequalities on class roots.

    Each class is named by a choice-function representative: the shortest term,
    breaking ties by insertion order. ``find`` always returns that representative,
    so later identities only change a class name when two classes merge.

    Proven identities are closed under transitivity. A counterexample between two
    terms is recorded on their current roots, so later members of those classes
    are treated as already distinguished.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._birth: dict[str, int] = {}
        self._next_birth = 0
        self._unequal: set[frozenset[str]] = set()

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._birth[x] = self._next_birth
            self._next_birth += 1

    def __contains__(self, x: object) -> bool:
        return isinstance(x, str) and x in self._parent

    def _choice_key(self, x: str) -> tuple[int, int, str]:
        return (len(x), self._birth[x], x)

    def representatives(self) -> list[str]:
        """Canonical class names, shortest first (then insertion order)."""
        return sorted({self.find(x) for x in self._parent}, key=self._choice_key)

    def find(self, x: str) -> str:
        self.add(x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def same(self, x: str, y: str) -> bool:
        return self.find(x) == self.find(y)

    def known_unequal(self, x: str, y: str) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        return frozenset((rx, ry)) in self._unequal

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self._choice_key(ry) < self._choice_key(rx):
            rx, ry = ry, rx
        self._parent[ry] = rx
        rewritten: set[frozenset[str]] = set()
        for pair in self._unequal:
            if ry not in pair:
                rewritten.add(pair)
                continue
            other = next(iter(pair - {ry}))
            if other != rx:
                rewritten.add(frozenset((rx, other)))
        self._unequal = rewritten
        self._on_merged(rx, ry)

    def _on_merged(self, survivor: str, absorbed: str) -> None:
        """Hook for subclasses that index data by canonical representatives."""

    def mark_unequal(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._unequal.add(frozenset((rx, ry)))

    def classes(self) -> list[set[str]]:
        groups: dict[str, set[str]] = {}
        for x in self._parent:
            groups.setdefault(self.find(x), set()).add(x)
        return [groups[rep] for rep in sorted(groups, key=self._choice_key)]

class TermPartialOrder(TermEquivalence):
    """Equivalence classes with a Hasse diagram on their canonical representatives.

    An edge ``u -> v`` means the class of ``u`` is strictly below the class of
    ``v``. Edges are stored between current representatives; when two classes
    merge, incident edges are moved onto the surviving representative so the
    order relation is preserved.
    """

    def __init__(self) -> None:
        super().__init__()
        self._partial_order: nx.DiGraph = nx.DiGraph()

    @property
    def hasse(self) -> nx.DiGraph:
        """Covering graph whose nodes are the current class representatives."""
        return self._partial_order

    def add(self, x: str) -> None:
        existed = x in self._parent
        super().add(x)
        if not existed:
            self._partial_order.add_node(x)

    def _on_merged(self, survivor: str, absorbed: str) -> None:
        G = self._partial_order
        G.add_node(survivor)
        if absorbed not in G or absorbed == survivor:
            return
        for pred in list(G.predecessors(absorbed)):
            if pred != survivor:
                G.add_edge(pred, survivor)
        for succ in list(G.successors(absorbed)):
            if succ != survivor:
                G.add_edge(survivor, succ)
        G.remove_node(absorbed)
        self._reduce()

    def add_less_than(self, x: str, y: str) -> None:
        """Record that the class of ``x`` is strictly below the class of ``y``."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        G = self._partial_order
        G.add_nodes_from((rx, ry))
        if nx.has_path(G, rx, ry):
            return
        if nx.has_path(G, ry, rx):
            self.union(x, y)
            return
        G.add_edge(rx, ry)
        self.mark_unequal(rx, ry)
        self._reduce()

    def known_less_than(self, x: str, y: str) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        G = self._partial_order
        return rx in G and ry in G and nx.has_path(G, rx, ry)

    def known_leq(self, x: str, y: str) -> bool:
        return self.same(x, y) or self.known_less_than(x, y)

    def _reduce(self) -> None:
        G = self._partial_order
        if G.number_of_edges() == 0:
            return
        nodes = list(G.nodes())
        reduced = nx.transitive_reduction(G)
        reduced.add_nodes_from(nodes)
        self._partial_order = reduced

async def _stop_job(job: Any) -> None:
    """Cancel a Mace4/Prover9 job and wait until its subprocess has actually exited."""
    job.cancel()
    runner = getattr(job, "_runner_task", None)
    if runner is not None:
        await asyncio.gather(runner, return_exceptions=True)
        return
    await asyncio.gather(job.wait(), return_exceptions=True)


async def _drain_subprocess_transports() -> None:
    """Flush pending Proactor pipe-close callbacks while the loop is still open."""
    await asyncio.sleep(0)
    gc.collect()
    await asyncio.sleep(0)
    if sys.platform == "win32":
        await asyncio.sleep(0.05)


def _is_closed_pipe_error(exc: BaseException | None) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    return isinstance(exc, ValueError) and "closed pipe" in str(exc)


def _ignore_closed_pipe_errors(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Drop Windows pipe errors left behind when a solver is killed mid-stdin-write."""
    if _is_closed_pipe_error(context.get("exception")):
        return
    message = str(context.get("message", ""))
    if "unclosed transport" in message or "pipe has been ended" in message.lower():
        return
    loop.default_exception_handler(context)


def _run_asyncio(coro: Any) -> bool:
    """Like ``asyncio.run``, but lets Windows subprocess transports close first.

    Returns True if *coro* finished, False if it was stopped by Ctrl+C.

    KeyboardInterrupt must cancel the task and wait for it: otherwise the
    coroutine is abandoned, its ``finally`` runs only during interpreter
    shutdown, and PDF generation dies with ``sys.meta_path is None``.
    """
    # Windows subprocesses need ProactorEventLoop (SelectorEventLoop cannot spawn them).
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()
    completed = False
    try:
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(_ignore_closed_pipe_errors)
        task = loop.create_task(coro)
        try:
            loop.run_until_complete(task)
            completed = True
        except KeyboardInterrupt:
            print("\nInterrupted — stopping solvers...", flush=True)
            if not task.done():
                task.cancel()
                try:
                    loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
                except KeyboardInterrupt:
                    pass
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
            if hasattr(loop, "shutdown_default_executor"):
                loop.run_until_complete(loop.shutdown_default_executor())
            gc.collect()
            loop.run_until_complete(asyncio.sleep(0.1))
        except KeyboardInterrupt:
            pass
        return completed
    finally:
        asyncio.set_event_loop(None)
        loop.close()

async def decide(
    theory_text: str,
    mace4: Mace4,
    prover9: Prover9,
    *,
    tptp_provers: Sequence[TptpProverSpec] | None = None,
    tptp_timeout_s: float | None = None,
) -> Decision:
    """Race Mace4, Prover9, and any available TPTP ATPs; stop when one decides.

    Mace4 may return ``FALSIFIED``. Prover9 and TPTP provers (Vampire,
    Zipperposition, …) may return ``PROVED``. TPTP backends receive a
    LADR→TPTP conversion of *theory_text* (see :mod:`tptp_provers`).
    """
    if tptp_provers is None:
        tptp_provers = discover_tptp_provers()
    timeout_s = float(tptp_timeout_s) if tptp_timeout_s is not None else 120.0

    tptp_text: str | None = None
    if tptp_provers:
        try:
            tptp_text = await asyncio.to_thread(convert_ladr_to_tptp, theory_text)
        except Exception:
            logger.exception("LADR→TPTP conversion failed; skipping TPTP provers")
            tptp_provers = ()

    mace_job = mace4.start_amodels(input=theory_text)
    proof_job = prover9.start_aprove(input=theory_text)

    async def first_counterexample() -> Decision | None:
        async for _model in mace_job.amodels():
            return Decision.FALSIFIED
        return None

    async def first_prover9_proof() -> Decision | None:
        async for event in proof_job.event_stream():
            if event.get("type") == "stdout" and "THEOREM PROVED" in event.get("line", ""):
                return Decision.PROVED
        try:
            result = await proof_job.result()
        except RuntimeError:
            return None
        if result.outcome == ProverOutcome.proved:
            return Decision.PROVED
        return None

    async def first_tptp_proof(prover: TptpProverSpec) -> Decision | None:
        assert tptp_text is not None
        if await try_prove_tptp(prover, tptp_text, timeout_s=timeout_s):
            return Decision.PROVED
        return None

    mace_task = asyncio.create_task(first_counterexample(), name="mace4")
    proof_task = asyncio.create_task(first_prover9_proof(), name="prover9")
    tptp_tasks = [
        asyncio.create_task(first_tptp_proof(prover), name=prover.name)
        for prover in tptp_provers
        if tptp_text is not None
    ]
    pending: set[asyncio.Task[Decision | None]] = {mace_task, proof_task, *tptp_tasks}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task.cancelled():
                    continue
                if (exc := task.exception()) is not None:
                    logger.error("solver task failed", exc_info=exc)
                    continue
                verdict = task.result()
                if verdict is not None:
                    for leftover in pending:
                        leftover.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    return verdict
        return Decision.UNKNOWN
    finally:
        for task in (mace_task, proof_task, *tptp_tasks):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            _stop_job(mace_job),
            _stop_job(proof_job),
            mace_task,
            proof_task,
            *tptp_tasks,
            return_exceptions=True,
        )
        await _drain_subprocess_transports()


def _formula_body(formula: str) -> str:
    return formula.strip().removesuffix(".").strip()


def _formula_sides(formula: str) -> tuple[str, str, str] | None:
    """Return ``(op, left, right)`` for a saved ``=`` or ``<=`` formula."""
    body = _formula_body(formula)
    if "<=" in body:
        left, right = body.split("<=", 1)
        return ("<=", left.strip(), right.strip())
    if "=" in body:
        left, right = body.split("=", 1)
        return ("=", left.strip(), right.strip())
    return None


def _apply_proven_formula(formula: str, order: TermPartialOrder) -> None:
    """Replay a saved identity or inequality into the running partial order."""
    parsed = _formula_sides(formula)
    if parsed is None:
        return
    op, left, right = parsed
    if op == "<=":
        order.add_less_than(left, right)
    else:
        order.union(left, right)


def _try_apply_pending_lookups(
    pending: list[str],
    order: TermPartialOrder,
) -> int:
    """Apply stored formulas whose both sides are already present in *order*.

    Formulas that mention a term not yet generated stay in *pending* for later.
    Replays until a pass applies nothing, since one merge can unlock others.
    Returns the number of formulas applied in this call.
    """
    applied = 0
    changed = True
    while changed:
        changed = False
        remaining: list[str] = []
        for formula in pending:
            parsed = _formula_sides(formula)
            if parsed is None:
                continue
            _, left, right = parsed
            # Use membership, not find/add: find would insert missing sides.
            if left not in order or right not in order:
                remaining.append(formula)
                continue
            _apply_proven_formula(formula, order)
            applied += 1
            changed = True
        pending.clear()
        pending.extend(remaining)
    return applied


def _algebras_have_leq(interpretations: Path) -> tuple[int, bool]:
    """Return ``(count, every algebra has a <= symbol)`` for a Mace4 model file."""
    text = interpretations.read_text(encoding="utf-8")
    blocks = text.split("interpretation(")[1:]
    if not blocks:
        raise ValueError(f"no algebras in {interpretations}")
    flags = ["<=(" in block for block in blocks]
    if any(flags) and not all(flags):
        raise ValueError(f"{interpretations} mixes algebras with and without <=")
    return len(flags), flags[0]


def _clause_for_algebra(formula: str, leq_is_relation: bool) -> str | None:
    """Rebuild a saved ``=`` or ``<=`` formula as a clause the algebras can evaluate.

    Without a ``<=`` symbol the order is the equation ``(x\\y) = (x\\y)\\(x\\y)``,
    so cached inequalities are left for the equality partition to decide.
    """
    parsed = _formula_sides(formula)
    if parsed is None:
        return None
    op, left, right = parsed
    if op == "<=":
        if not leq_is_relation:
            return None
        return f"{left} <= {right}."
    return f"{left} = {right}."


def clauses_true_in_all(formulas: Sequence[str], interpretations: Path | str) -> list[bool]:
    """Evaluate each clause in *formulas* against every algebra in the model file.

    One ``clausetester`` run. Results are in the same order as *formulas*.
    A clause is true when it holds in every interpretation.
    """
    if not formulas:
        return []
    path = Path(interpretations)
    text = "".join(formula if formula.endswith("\n") else formula + "\n" for formula in formulas)
    result = ClauseTester().run(input=text, interp_file=path)
    if result.exit_code not in (0, None) or "Fatal error" in result.stdout or "Fatal error" in result.stderr:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"clausetester failed on {path}: {detail}")

    n_interps = 0
    rows: list[str] = []
    for line in result.stdout.splitlines():
        if line.startswith("% interp "):
            index = line.removeprefix("% interp ").split(" ", 1)[0]
            if index.isdigit():
                n_interps = max(n_interps, int(index))
            continue
        if not line.strip() or line.startswith("%"):
            continue
        rows.append(line)
    if n_interps == 0 or len(rows) != len(formulas):
        raise RuntimeError(
            f"clausetester returned {len(rows)} rows for {len(formulas)} clauses "
            f"and {n_interps} algebras:\n{result.stdout}"
        )
    expected = set(range(1, n_interps + 1))
    holds: list[bool] = []
    for line in rows:
        _formula, sep, tail = line.partition("  %")
        if not sep:
            raise RuntimeError(f"unexpected clausetester line: {line}")
        found: set[int] = set()
        for token in tail.split():
            if not token.isdigit():
                raise RuntimeError(f"unexpected clausetester line: {line}")
            found.add(int(token))
        if not found <= expected:
            raise RuntimeError(f"unexpected model index in clausetester line: {line}")
        holds.append(found == expected)
    return holds


def _try_apply_pending_lookups_in_algebras(
    pending: list[str],
    order: TermPartialOrder,
    interpretations: Path,
    leq_is_relation: bool,
    progress: bool,
) -> int:
    """Apply cached formulas that hold in every algebra and whose sides exist.

    Formulas the algebras falsify are dropped, so a cache from a larger variety
    cannot collapse classes the models keep apart.
    """
    ready: list[str] = []
    remaining: list[str] = []
    for formula in pending:
        parsed = _formula_sides(formula)
        if parsed is None:
            continue
        op, left, right = parsed
        if op == "<=" and not leq_is_relation:
            continue
        if left not in order or right not in order:
            remaining.append(formula)
            continue
        ready.append(formula)
    pending.clear()
    pending.extend(remaining)
    if not ready:
        return 0
    clauses: list[str] = []
    checkable: list[str] = []
    for formula in ready:
        clause = _clause_for_algebra(formula, leq_is_relation)
        if clause is None:
            continue
        checkable.append(formula)
        clauses.append(clause)
    holds = clauses_true_in_all(clauses, interpretations)
    applied = 0
    for formula, ok in zip(checkable, holds):
        if not ok:
            if progress:
                print(f"  Cached statement fails in the algebras: {formula}")
            continue
        _apply_proven_formula(formula, order)
        applied += 1
    return applied


def _open_pairs(
    pairs: Iterable[tuple[str, str]],
    order: TermPartialOrder,
) -> list[tuple[str, str]]:
    """Representative pairs whose order is not already known."""
    chosen: list[tuple[str, str]] = []
    seen: set[frozenset[str]] = set()
    for left, right in pairs:
        if order.find(left) != left or order.find(right) != right:
            continue
        if left == right or order.known_unequal(left, right):
            continue
        if order.known_less_than(left, right) or order.known_less_than(right, left):
            continue
        key = frozenset((left, right))
        if key in seen:
            continue
        seen.add(key)
        chosen.append((left, right))
    return chosen


def _apply_algebra_equalities(
    chosen: Sequence[tuple[str, str]],
    eq_true: Sequence[bool],
    order: TermPartialOrder,
    save_axiom: Callable[[str], None],
) -> int:
    """Union the pairs whose equation holds in every algebra."""
    n_eq = 0
    for (left, right), ok in zip(chosen, eq_true):
        if not ok:
            continue
        left, right = order.find(left), order.find(right)
        if left == right:
            continue
        save_axiom(f"{left} = {right}.")
        order.union(left, right)
        n_eq += 1
    return n_eq


def _mark_undecided_unequal(
    chosen: Sequence[tuple[str, str]],
    order: TermPartialOrder,
) -> None:
    """Remember that pairs not identified by an equation stay distinct."""
    seen: set[frozenset[str]] = set()
    for left, right in chosen:
        left, right = order.find(left), order.find(right)
        if left == right or order.known_unequal(left, right):
            continue
        if order.known_less_than(left, right) or order.known_less_than(right, left):
            continue
        key = frozenset((left, right))
        if key in seen:
            continue
        seen.add(key)
        order.mark_unequal(left, right)


def _decide_pairs_in_algebras(
    pairs: Iterable[tuple[str, str]],
    order: TermPartialOrder,
    interpretations: Path,
    leq_is_relation: bool,
    save_axiom: Callable[[str], None],
    progress: bool,
) -> None:
    """Decide every still-open pair by one batched evaluation in the algebras.

    Equalities are always sent. Both inequality directions are sent in the same
    run only when the algebras have a ``<=`` symbol. Otherwise the order is the
    residual equation and is recovered from the equality partition at the end.
    """
    chosen = _open_pairs(pairs, order)
    if not chosen:
        return
    clauses = [f"{left} = {right}." for left, right in chosen]
    if leq_is_relation:
        clauses.extend(f"{left} <= {right}." for left, right in chosen)
        clauses.extend(f"{right} <= {left}." for left, right in chosen)
    holds = clauses_true_in_all(clauses, interpretations)
    n = len(chosen)
    eq_true = holds[:n]
    if not leq_is_relation:
        n_eq = _apply_algebra_equalities(chosen, eq_true, order, save_axiom)
        _mark_undecided_unequal(chosen, order)
        if progress:
            print(f"  Algebras: {n} pairs, {n_eq} identities")
        return
    le_true = holds[n : 2 * n]
    ge_true = holds[2 * n :]

    n_eq = _apply_algebra_equalities(chosen, eq_true, order, save_axiom)

    # Several pairs can fall into the same classes once identities are applied.
    # Keep a direction if any of those pairs witnessed it, and fold (a, b)
    # together with (b, a).
    directions: dict[tuple[str, str], tuple[bool, bool]] = {}
    for (left, right), less, greater in zip(chosen, le_true, ge_true):
        left, right = order.find(left), order.find(right)
        if left == right:
            continue
        if (right, left) in directions:
            prev_less, prev_greater = directions[(right, left)]
            directions[(right, left)] = (prev_less or greater, prev_greater or less)
            continue
        prev_less, prev_greater = directions.get((left, right), (False, False))
        directions[(left, right)] = (prev_less or less, prev_greater or greater)

    n_le = 0
    n_ge = 0
    for (left, right), (less, greater) in directions.items():
        if order.known_unequal(left, right):
            continue
        if order.known_less_than(left, right) or order.known_less_than(right, left):
            continue
        if less and greater:
            save_axiom(f"{left} = {right}.")
            order.union(left, right)
            n_eq += 1
            continue
        order.mark_unequal(left, right)
        if less:
            save_axiom(f"{left} <= {right}.")
            order.add_less_than(left, right)
            n_le += 1
        elif greater:
            save_axiom(f"{right} <= {left}.")
            order.add_less_than(right, left)
            n_ge += 1
    if progress:
        print(
            f"  Algebras: {n} pairs, {n_eq} identities, "
            f"{n_le} less-than, {n_ge} greater-than"
        )


def _record_residual_order(order: TermPartialOrder, operations: Sequence[Operation]) -> int:
    """Add ``left <= right`` whenever ``(left \\ right)`` is already known to be idempotent.

    Does not write inequalities. The comparison is the equation
    ``(left \\ right) = (left \\ right) \\ (left \\ right)`` inside the partition.
    """
    arrow = next((op for op in operations if op.symbol == "\\" and op.arity == 2), None)
    if arrow is None:
        return 0
    reps = list(order.representatives())
    recorded = 0
    for left, right in itertools.product(reps, repeat=2):
        if left == right or order.known_less_than(left, right):
            continue
        residual = arrow((left, right))
        if residual not in order:
            continue
        # The square is generated from class representatives, not from a longer
        # term that has already been identified with its representative.
        residual = order.find(residual)
        squared = arrow((residual, residual))
        if squared not in order or order.find(squared) != residual:
            continue
        order.add_less_than(left, right)
        recorded += 1
    return recorded


def _known_operation_result(
    order: TermEquivalence,
    operation: Operation,
    left: str,
    right: str,
) -> str | None:
    """Return the known representative of ``operation(left, right)``, if any.

    Does not add new terms to *order*. Idempotence fills the diagonal; a
    commutative operation also looks up the swapped argument string.
    """
    if operation.arity != 2:
        raise ValueError(f"{operation.symbol} is not binary")
    if left == right and operation.idempotent:
        return left if left in order else None
    candidates = [operation((left, right))]
    if operation.commutative and left != right:
        candidates.append(operation((right, left)))
    for term in candidates:
        if term in order:
            return order.find(term)
    return None


def _operation_table_cells(
    order: TermEquivalence,
    operation: Operation,
    reps: Sequence[str],
) -> tuple[list[list[str]], int]:
    """Cayley table of class indices; ``?`` marks products not yet identified.

    Returns the cell grid and the number of next-layer terms ``expand_terms``
    would still generate for this operation (unknown combinations, counting
    each commutative pair once).
    """
    index = {rep: str(i + 1) for i, rep in enumerate(reps)}
    cells: list[list[str]] = []
    for left in reps:
        row: list[str] = []
        for right in reps:
            result = _known_operation_result(order, operation, left, right)
            row.append(index.get(result, "?") if result is not None else "?")
        cells.append(row)

    next_layer = 0
    seen = set(reps)
    if operation.commutative and operation.idempotent:
        arg_iter: Iterable[tuple[str, ...]] = itertools.combinations(reps, operation.arity)
    elif operation.commutative:
        arg_iter = itertools.combinations_with_replacement(reps, operation.arity)
    else:
        arg_iter = itertools.product(reps, repeat=operation.arity)
    for args in arg_iter:
        term = operation(args)
        if term in seen:
            continue
        seen.add(term)
        if term not in order:
            next_layer += 1
    return cells, next_layer


def _draw_term_hasse(
    ax,
    graph: nx.DiGraph,
    title: str = "",
    labels: dict[str, str] | None = None,
) -> None:
    """Draw a Hasse diagram of term representatives using the project layout."""
    from draw_orders import hasse_layout

    if graph.number_of_nodes() == 0:
        ax.set_title(title, fontsize=10)
        ax.axis("off")
        return
    if labels is None:
        labels = {n: str(n) for n in graph.nodes()}
    max_len = max(len(lab) for lab in labels.values())
    node_size = max(900, min(2800, 110 * max_len))
    font_size = 8 if max_len > 12 else 10
    nx.draw(
        graph,
        pos=hasse_layout(graph),
        ax=ax,
        with_labels=True,
        labels=labels,
        node_color=["lightblue"] * graph.number_of_nodes(),
        node_size=node_size,
        font_size=font_size,
        font_weight="bold",
        arrows=True,
        arrowsize=15,
        edge_color="gray",
    )
    ax.margins(0.18)
    ax.set_title(title, fontsize=10)
    ax.axis("off")


def _add_operation_table_page(
    pdf,
    order: TermEquivalence,
    operation: Operation,
    reps: Sequence[str],
    fig_width: float,
) -> None:
    """Write one Cayley-table page for a binary operation on *reps*."""
    import matplotlib.pyplot as plt

    n = len(reps)
    if n == 0:
        return
    cells, next_layer = _operation_table_cells(order, operation, reps)
    labels = [str(i + 1) for i in range(n)]
    max_term = max((len(t) for t in reps), default=0)
    n_legend_cols = 2 if n > 8 and max_term <= 24 else 1
    legend_rows = (n + n_legend_cols - 1) // n_legend_cols
    legend_height = max(1.4, min(12.0, 0.28 * legend_rows))
    table_height = max(4.5, min(18.0, 0.42 * n + 1.2))
    page_width = max(fig_width, 3.2 + 0.48 * n, 4.0 + 0.09 * max_term * n_legend_cols)
    fig_height = 1.1 + legend_height + table_height

    fig = plt.figure(figsize=(page_width, fig_height), layout="constrained")
    gs = fig.add_gridspec(2, 1, height_ratios=[legend_height, table_height])
    ax_legend = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_legend.axis("off")
    ax_table.axis("off")

    mid = legend_rows
    legend_cols: list[str] = []
    for col in range(n_legend_cols):
        lines = [f"{i + 1:>2}. {reps[i]}" for i in range(col * mid, min(n, (col + 1) * mid))]
        legend_cols.append("\n".join(lines))
    x_positions = [0.0] if n_legend_cols == 1 else [0.0, 0.52]
    for x, body in zip(x_positions, legend_cols):
        ax_legend.text(
            x,
            1.0,
            body,
            transform=ax_legend.transAxes,
            va="top",
            ha="left",
            fontsize=8,
            family="monospace",
            linespacing=1.3,
        )
    ax_legend.set_title("Class representatives", fontsize=10, loc="left")

    table = ax_table.table(
        cellText=cells,
        rowLabels=labels,
        colLabels=labels,
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    fontsize = 9 if n <= 12 else (8 if n <= 18 else 6)
    table.set_fontsize(fontsize)
    table.scale(1.0, 1.35)
    header_color = "#eceff1"
    unknown_color = "#ffe082"
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#b0bec5")
        if row == 0 or col == -1:
            cell.set_facecolor(header_color)
            cell.get_text().set_fontweight("bold")
            continue
        if cells[row - 1][col] == "?":
            cell.set_facecolor(unknown_color)
    if (0, -1) in table.get_celld():
        table[0, -1].get_text().set_text(operation.symbol)
        table[0, -1].get_text().set_fontweight("bold")
    symbol = operation.symbol
    ax_table.set_title(
        f"row {symbol} column; "
        f"{next_layer} new term{'s' if next_layer != 1 else ''} at the next layer",
        fontsize=10,
        pad=8,
    )
    fig.suptitle(
        f"Known {symbol} identities  (? = not yet identified)",
        fontsize=14,
        fontweight="bold",
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

async def classify_term_order(
    operations: list[Operation],
    variables: Sequence[str],
    max_level: int,
    axioms: list[str],
    equivalence_classes: TermPartialOrder,
    mace4: Mace4 | None,
    prover9: Prover9 | None,
    save_axiom: Callable[[str], None],
    save_unknown: Callable[[str], None],
    progress: bool = False,
    pending_lookup: list[str] | None = None,
    tptp_provers: Sequence[TptpProverSpec] | None = None,
    tptp_timeout_s: float | None = None,
    algebras: Path | str | None = None,
) -> None:
    """Classify the free-algebra order by expanding a pruned pool of representatives.

    At each level, new terms are built only from current class representatives.
    When two terms are proved equal, the longer one (the absorbed class name) is
    dropped from the pool so it is not used to generate still-larger terms.
    If a level produces no new representatives, the pool is closed and the
    search stops. ``terms`` and ``icombinations`` are left unchanged for other
    callers.

    If *pending_lookup* is non-empty, stored formulas are applied only once both
    sides have appeared among generated terms, so obsolete terms from an older
    axiom file never become Hasse nodes by themselves.

    If *algebras* is a Mace4 model file, identities are decided by evaluating
    each level's candidate pairs in those algebras (one ``clausetester`` run
    per level) instead of :func:`decide`. ``mace4`` and ``prover9`` may be
    omitted in that case. Cached formulas are kept only when they hold in
    every algebra in the file. When those algebras have no ``<=`` symbol, only
    equations are evaluated and saved; the order is read afterwards from the
    equation ``(x\\y) = (x\\y)\\(x\\y)``.
    """

    algebras_path = Path(algebras) if algebras is not None else None
    if algebras_path is not None:
        if not algebras_path.is_file():
            raise FileNotFoundError(f"model file not found: {algebras_path}")
        n_algebras, leq_is_relation = _algebras_have_leq(algebras_path)
        if progress:
            if leq_is_relation:
                order_note = "<= is a symbol of the algebras"
            else:
                order_note = r"order follows from (x\y) = (x\y)\(x\y) and is not saved"
            noun = "algebra" if n_algebras == 1 else "algebras"
            print(f"Evaluating identities in {n_algebras} {noun} ({order_note})")
    elif mace4 is None or prover9 is None:
        raise ValueError("mace4 and prover9 are required when algebras is not given")
    else:
        leq_is_relation = False

    pending = pending_lookup if pending_lookup is not None else []

    def live(terms_in: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for term in terms_in:
            representative = equivalence_classes.find(term)
            if representative not in seen:
                seen.add(representative)
                out.append(representative)
        return out

    def apply_lookups() -> None:
        if algebras_path is not None:
            n = _try_apply_pending_lookups_in_algebras(
                pending,
                equivalence_classes,
                algebras_path,
                leq_is_relation,
                progress,
            )
        else:
            n = _try_apply_pending_lookups(pending, equivalence_classes)
        if progress and n:
            print(f"  Applied {n} looked-up statement{'s' if n != 1 else ''}")

    async def classify_pair(left: str, right: str) -> None:
        left = equivalence_classes.find(left)
        right = equivalence_classes.find(right)
        if left == right or equivalence_classes.known_unequal(left, right):
            return
        if equivalence_classes.known_less_than(left, right) or equivalence_classes.known_less_than(right, left):
            return
        po = PartialOrderVerdict.UNKNOWN
        assert mace4 is not None and prover9 is not None
        theory = Theory(assumptions=axioms, goals=[f"{left} = {right}."])
        verdict = await decide(
            theory.to_theory_text(),
            mace4,
            prover9,
            tptp_provers=tptp_provers,
            tptp_timeout_s=tptp_timeout_s,
        )
        if verdict is Decision.PROVED:
            po = PartialOrderVerdict.EQUAL
        elif verdict is Decision.FALSIFIED:  # not equal in free algebra
            equivalence_classes.mark_unequal(left, right)
            theory = Theory(assumptions=axioms, goals=[f"{left} <= {right}."])
            verdict = await decide(
                theory.to_theory_text(),
                mace4,
                prover9,
                tptp_provers=tptp_provers,
                tptp_timeout_s=tptp_timeout_s,
            )
            if verdict is Decision.PROVED:
                po = PartialOrderVerdict.LESS_THAN
            elif verdict is Decision.FALSIFIED:  # not less than or equal in free algebra
                theory = Theory(assumptions=axioms, goals=[f"{right} <= {left}."])
                verdict = await decide(
                    theory.to_theory_text(),
                    mace4,
                    prover9,
                    tptp_provers=tptp_provers,
                    tptp_timeout_s=tptp_timeout_s,
                )
                if verdict is Decision.PROVED:
                    po = PartialOrderVerdict.GREATER_THAN
                elif verdict is Decision.FALSIFIED:  # incomparable in free algebra
                    po = PartialOrderVerdict.INCOMPARABLE
                else:
                    save_unknown(f"{right} <= {left}.")
            else:
                save_unknown(f"{left} <= {right}.")
        else:
            save_unknown(f"{left} = {right}.")
        if po is PartialOrderVerdict.EQUAL:
            save_axiom(f"{left} = {right}.")
            equivalence_classes.union(left, right)
        elif po is PartialOrderVerdict.LESS_THAN:
            save_axiom(f"{left} <= {right}.")
            equivalence_classes.add_less_than(left, right)
        elif po is PartialOrderVerdict.GREATER_THAN:
            save_axiom(f"{right} <= {left}.")
            equivalence_classes.add_less_than(right, left)

    async def classify_pairs(pairs: Iterable[tuple[str, str]]) -> None:
        if algebras_path is not None:
            _decide_pairs_in_algebras(
                pairs,
                equivalence_classes,
                algebras_path,
                leq_is_relation,
                save_axiom,
                progress,
            )
            return
        for left, right in pairs:
            if equivalence_classes.find(left) != left or equivalence_classes.find(right) != right:
                continue
            await classify_pair(left, right)

    try:
        pool = live(seed_terms(operations, variables))
        apply_lookups()
        pool = live(pool)
        if progress:
            print(f"Level 0: {len(pool)} terms")
        await classify_pairs(itertools.combinations(pool, 2))
        pool = live(pool)

        for level in range(1, max_level + 1):
            candidates = expand_terms(operations, pool)
            for term in candidates:
                equivalence_classes.add(term)
            apply_lookups()
            new_terms = [term for term in candidates if equivalence_classes.find(term) == term]
            if not new_terms:
                print(f"No new terms at level {level}; terminating.")
                return
            prev = list(pool)
            await classify_pairs(
                itertools.chain(
                    itertools.product(new_terms, prev),
                    itertools.combinations(new_terms, 2),
                )
            )
            pool = live(prev + new_terms)
            if progress:
                print(f"Level {level}: {len(pool)} terms")
    finally:
        if algebras_path is not None and not leq_is_relation:
            recorded = _record_residual_order(equivalence_classes, operations)
            if progress and recorded:
                print(
                    f"  Order from equalities: {recorded} "
                    f"comparison{'s' if recorded != 1 else ''}"
                )


def write_free_algebra_pdf(
    order: TermPartialOrder,
    unknowns: Sequence[str],
    pdf_filename: str,
    operations: Sequence[Operation],
    name: str
) -> None:
    """Draw the known Hasse diagram, operation tables, and unknown identities."""
    
    pdf_path = Path(pdf_filename)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    reps = order.representatives()
    hasse_labels = {n: str(n) for n in order.hasse.nodes()}
    for i, rep in enumerate(reps):
        hasse_labels[rep] = f"{i + 1}: {rep}"
    unknown_lines = list(unknowns)
    n_nodes = order.hasse.number_of_nodes()
    fig_width = max(10, min(20, 6 + n_nodes * 0.45))
    first_unknowns = unknown_lines[:40]
    remaining_unknowns = unknown_lines[40:]
    list_height = max(1.6, min(10.0, 1.0 + 0.24 * max(len(first_unknowns), 1)))
    graph_height = max(7.0, min(16.0, 5.0 + n_nodes * 0.28))
    fig_height = graph_height + list_height

    fig = plt.figure(figsize=(fig_width, fig_height), layout="constrained")
    gs = fig.add_gridspec(2, 1, height_ratios=[graph_height, list_height])
    ax_graph = fig.add_subplot(gs[0])
    ax_text = fig.add_subplot(gs[1])

    _draw_term_hasse(
        ax_graph,
        order.hasse,
        title="Known partial order",
        labels=hasse_labels,
    )

    ax_text.axis("off")
    ax_text.set_title("Unknown identities", fontsize=10, loc="left")
    body = "\n".join(first_unknowns) if first_unknowns else "(none)"
    ax_text.text(
        0.0,
        1.0,
        body,
        transform=ax_text.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        family="monospace",
        linespacing=1.35,
    )
    fig.suptitle(f"Free {name}", fontsize=14, fontweight="bold")

    pdf = matplotlib.backends.backend_pdf.PdfPages(filename=str(pdf_path))
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

    for operation in operations:
        if operation.arity == 2:
            _add_operation_table_page(pdf, order, operation, reps, fig_width)

    while remaining_unknowns:
        chunk = remaining_unknowns[:50]
        remaining_unknowns = remaining_unknowns[50:]
        page_height = max(8.0, min(14.0, 1.2 + 0.24 * len(chunk)))
        fig, ax = plt.subplots(figsize=(fig_width, page_height))
        ax.axis("off")
        ax.set_title("Unknown identities (continued)", fontsize=10, loc="left")
        ax.text(
            0.0,
            1.0,
            "\n".join(chunk),
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            family="monospace",
            linespacing=1.35,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    pdf.close()
    print(f"PDF saved to {pdf_path}")
