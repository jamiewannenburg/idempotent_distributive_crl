import asyncio
import gc
import itertools
import logging
import re
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

def _argument_tuples(
    operation: Operation,
    pool: Sequence[str],
    frontier: set[str] | None,
) -> Iterator[tuple[str, ...]]:
    """Argument tuples from *pool*.

    When *frontier* is given, skip tuples whose arguments all lie outside it.
    Those tuples were already formed at an earlier level.
    """
    if operation.arity <= 0:
        return
    if operation.commutative and operation.idempotent:
        arg_iter: Iterable[tuple[str, ...]] = itertools.combinations(pool, operation.arity)
    elif operation.commutative:
        arg_iter = itertools.combinations_with_replacement(pool, operation.arity)
    else:
        arg_iter = itertools.product(pool, repeat=operation.arity)
    for args in arg_iter:
        if frontier is not None and not any(arg in frontier for arg in args):
            continue
        yield args


def expand_applications(
    operations: Sequence[Operation],
    current: Sequence[str],
    frontier: Sequence[str] | None = None,
) -> list[tuple[str, Operation, tuple[str, ...]]]:
    """New operation applications on *current*.

    Each item is ``(term, operation, arguments)``. If *frontier* is given, at
    least one argument comes from it, so products of older elements are not
    built again. The input sequence is not modified.
    """
    pool = list(current)
    frontier_set = None if frontier is None else set(frontier)
    seen = set(pool)
    found: list[tuple[str, Operation, tuple[str, ...]]] = []
    for operation in operations:
        if operation.arity <= 0:
            continue
        for args in _argument_tuples(operation, pool, frontier_set):
            new_term = operation(args)
            if new_term in seen:
                continue
            seen.add(new_term)
            found.append((new_term, operation, args))
    return found


def expand_terms(
    operations: list[Operation],
    current: Sequence[str],
    frontier: Sequence[str] | None = None,
) -> list[str]:
    """Apply each operation once, returning newly formed term strings.

    Commutative and idempotent operations use unordered argument tuples, matching
    ``terms``. Pass *frontier* to skip combinations already formed from older terms.
    """
    return [term for term, _operation, _args in expand_applications(operations, current, frontier)]


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
    frontier = list(ts)
    level = 0
    if progress:
        print(f"Level {level}: {len(ts)} terms")
    while level < max_level:
        new_terms = expand_terms(operations, ts, frontier)
        ts.extend(new_terms)
        yield from new_terms
        frontier = new_terms
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
    """Union-find of terms proven equal.

    Each class is named by a choice-function representative: the shortest term,
    breaking ties by insertion order. ``find`` returns that representative.

    Only representatives stay in the partition. A term that has been identified
    with a shorter one is kept as an alias until :meth:`forget_non_representatives`
    drops it. Callers that still need the identification should read the
    operation table instead of the alias.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._birth: dict[str, int] = {}
        self._next_birth = 0
        self._alias: dict[str, str] = {}
        self._unequal: set[frozenset[str]] = set()

    def add(self, x: str) -> None:
        if x in self._alias or x in self._parent:
            return
        self._parent[x] = x
        self._birth[x] = self._next_birth
        self._next_birth += 1

    def __contains__(self, x: object) -> bool:
        return isinstance(x, str) and (x in self._parent or x in self._alias)

    def _choice_key(self, x: str) -> tuple[int, int, str]:
        return (len(x), self._birth[x], x)

    def representatives(self) -> list[str]:
        """Canonical class names, shortest first (then insertion order)."""
        return sorted((x for x in self._parent if self._parent[x] == x), key=self._choice_key)

    def find(self, x: str) -> str:
        if x in self._alias:
            root = self.find(self._alias[x])
            self._alias[x] = root
            return root
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
        self._unequal = self._rewrite_pairs(self._unequal, rx, ry)
        self._on_merged(rx, ry)

    def _rewrite_pairs(
        self,
        pairs: set[frozenset[str]],
        survivor: str,
        absorbed: str,
    ) -> set[frozenset[str]]:
        rewritten: set[frozenset[str]] = set()
        for pair in pairs:
            if absorbed not in pair:
                rewritten.add(pair)
                continue
            other = next(iter(pair - {absorbed}))
            if other != survivor:
                rewritten.add(frozenset((survivor, other)))
        return rewritten

    def _on_merged(self, survivor: str, absorbed: str) -> None:
        """Hook for subclasses that index data by canonical representatives."""

    def mark_unequal(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._unequal.add(frozenset((rx, ry)))

    def forget_non_representatives(self, keep: set[str] | None = None) -> int:
        """Drop absorbed terms that are not class names.

        *keep* holds strings that a later lookup may still mention. The
        operation table already records products of representatives, so the
        other absorbed strings are not needed to extend the algebra.
        """
        keep = keep or set()
        removed = 0
        for term in list(self._parent):
            if self._parent[term] == term or term in keep:
                continue
            root = self.find(term)
            del self._parent[term]
            self._birth.pop(term, None)
            removed += 1
        return removed

    def classes(self) -> list[set[str]]:
        groups: dict[str, set[str]] = {}
        for x in self._parent:
            groups.setdefault(self.find(x), set()).add(x)
        return [groups[rep] for rep in sorted(groups, key=self._choice_key)]


class TermPartialOrder(TermEquivalence):
    """Equivalence classes with a strict order on their representatives.

    ``_above[a]`` is the set of representatives strictly above ``a``. That is
    the transitive closure, stored directly so a comparison does not search a
    graph. The Hasse diagram is the covering relation of this closure and is
    built only when the picture is drawn.

    ``_incomparable`` holds pairs known to be incomparable. A pair that is
    merely not yet decided is in neither the order nor this set. ``_separator``
    stores one model index that separates the two classes, used to label
    covering edges.
    """

    def __init__(self) -> None:
        super().__init__()
        self._above: dict[str, set[str]] = {}
        self._incomparable: set[frozenset[str]] = set()
        self._separator: dict[frozenset[str], int] = {}
        self._products: dict[tuple[str, tuple[str, ...]], str] = {}

    def add(self, x: str) -> None:
        if x in self._alias or x in self._parent:
            return
        super().add(x)
        self._above[x] = set()

    @property
    def hasse(self) -> nx.DiGraph:
        """Covering graph whose nodes are the current class representatives."""
        graph = nx.DiGraph()
        graph.add_nodes_from(self.representatives())
        graph.add_edges_from(self.cover_edges())
        return graph

    def cover_edges(self) -> list[tuple[str, str]]:
        """Pairs ``(lower, upper)`` with nothing strictly between them."""
        covers: list[tuple[str, str]] = []
        for lower, above in self._above.items():
            if self._parent.get(lower) != lower:
                continue
            for upper in above:
                if any(upper in self._above.get(mid, ()) for mid in above if mid != upper):
                    continue
                covers.append((lower, upper))
        return covers

    def _strictly_ordered(self, pair: frozenset[str]) -> bool:
        left, right = tuple(pair)
        return right in self._above.get(left, ()) or left in self._above.get(right, ())

    def known_incomparable(self, x: str, y: str) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        return frozenset((rx, ry)) in self._incomparable

    def mark_incomparable(self, x: str, y: str) -> None:
        """Record that the two classes are distinct and neither is below the other."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry or self.known_less_than(rx, ry) or self.known_less_than(ry, rx):
            return
        self.mark_unequal(rx, ry)
        self._incomparable.add(frozenset((rx, ry)))

    def note_separator(self, x: str, y: str, model: int | None) -> None:
        """Remember one model index that separates the two classes."""
        if model is None:
            return
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        self._separator.setdefault(frozenset((rx, ry)), model)

    def separator(self, x: str, y: str) -> int | None:
        rx, ry = self.find(x), self.find(y)
        return self._separator.get(frozenset((rx, ry)))

    def record_product(self, symbol: str, arguments: Sequence[str], result: str) -> None:
        """Remember ``symbol(arguments)`` as the class of *result*."""
        key = (symbol, tuple(self.find(arg) for arg in arguments))
        self._products[key] = self.find(result)

    def product(self, symbol: str, arguments: Sequence[str]) -> str | None:
        """Representative of a recorded product, if both the arguments and the result are known."""
        if any(arg not in self for arg in arguments):
            return None
        key = (symbol, tuple(self.find(arg) for arg in arguments))
        found = self._products.get(key)
        if found is None:
            return None
        return self.find(found)

    def _on_merged(self, survivor: str, absorbed: str) -> None:
        above_absorbed = self._above.pop(absorbed, set())
        above_absorbed.discard(survivor)
        below_absorbed = [node for node, above in self._above.items() if absorbed in above]
        for above in self._above.values():
            if absorbed in above:
                above.discard(absorbed)
                above.add(survivor)
        survivor_above = self._above.setdefault(survivor, set())
        survivor_above.update(above_absorbed)
        survivor_above.discard(survivor)
        upper = set(survivor_above)
        for node in below_absorbed:
            if node == survivor:
                continue
            self._above[node].update(upper)
            self._above[node].discard(node)
        for node, above in self._above.items():
            if survivor in above:
                above.update(upper)
                above.discard(node)
        rewritten_incomparable = self._rewrite_pairs(self._incomparable, survivor, absorbed)
        self._incomparable = {
            pair
            for pair in rewritten_incomparable
            if not self._strictly_ordered(pair)
        }
        rewritten: dict[frozenset[str], int] = {}
        for pair, model in self._separator.items():
            if absorbed not in pair:
                rewritten.setdefault(pair, model)
                continue
            other = next(iter(pair - {absorbed}))
            if other != survivor:
                rewritten.setdefault(frozenset((survivor, other)), model)
        self._separator = rewritten
        rewritten_products: dict[tuple[str, tuple[str, ...]], str] = {}
        for (symbol, args), result in self._products.items():
            args = tuple(survivor if arg == absorbed else arg for arg in args)
            if result == absorbed:
                result = survivor
            rewritten_products.setdefault((symbol, args), result)
        self._products = rewritten_products

    def add_less_than(self, x: str, y: str) -> None:
        """Record that the class of ``x`` is strictly below the class of ``y``."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if ry in self._above.get(rx, ()):
            return
        if rx in self._above.get(ry, ()):
            self.union(x, y)
            return
        gained = {ry} | self._above.get(ry, set())
        sources = [rx]
        for node, above in self._above.items():
            if rx in above:
                sources.append(node)
        for source in sources:
            bucket = self._above.setdefault(source, set())
            bucket.update(gained)
            bucket.discard(source)
        self._incomparable.discard(frozenset((rx, ry)))
        self.mark_unequal(rx, ry)

    def known_less_than(self, x: str, y: str) -> bool:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        return ry in self._above.get(rx, ())

    def known_leq(self, x: str, y: str) -> bool:
        return self.same(x, y) or self.known_less_than(x, y)

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
    """Return ``(op, left, right)`` for a saved ``=``, ``<=``, or ``|`` formula.

    ``|`` means the two sides are known to be incomparable.
    """
    body = _formula_body(formula)
    if "<=" in body:
        left, right = body.split("<=", 1)
        return ("<=", left.strip(), right.strip())
    if "|" in body:
        left, right = body.split("|", 1)
        return ("|", left.strip(), right.strip())
    if "=" in body:
        left, right = body.split("=", 1)
        return ("=", left.strip(), right.strip())
    return None


def _pending_mentions(pending: Sequence[str]) -> set[str]:
    """Terms named by lookups that have not been applied yet."""
    mentioned: set[str] = set()
    for formula in pending:
        parsed = _formula_sides(formula)
        if parsed is None:
            continue
        _op, left, right = parsed
        mentioned.add(left)
        mentioned.add(right)
    return mentioned


def _apply_proven_formula(formula: str, order: TermPartialOrder) -> None:
    """Replay a saved identity, inequality, or incomparability into the order."""
    parsed = _formula_sides(formula)
    if parsed is None:
        return
    op, left, right = parsed
    if op == "<=":
        order.add_less_than(left, right)
    elif op == "|":
        order.mark_incomparable(left, right)
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
    if op == "|":
        return None
    if op == "<=":
        if not leq_is_relation:
            return None
        return f"{left} <= {right}."
    return f"{left} = {right}."


def clause_checks(
    formulas: Sequence[str],
    interpretations: Path | str,
) -> list[tuple[bool, int | None]]:
    """Evaluate each clause against every algebra in the model file.

    One ``clausetester`` run. Each result is ``(holds_in_all, one_failing_index)``.
    The index is the 1-based interpretation number of one algebra where the
    clause fails, or ``None`` when the clause holds everywhere.
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
    checks: list[tuple[bool, int | None]] = []
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
        missing = expected - found
        checks.append((not missing, min(missing) if missing else None))
    return checks


def clauses_true_in_all(formulas: Sequence[str], interpretations: Path | str) -> list[bool]:
    """Evaluate each clause in *formulas* against every algebra in the model file.

    One ``clausetester`` run. Results are in the same order as *formulas*.
    A clause is true when it holds in every interpretation.
    """
    return [holds for holds, _witness in clause_checks(formulas, interpretations)]


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
    ready_incomparable: list[str] = []
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
        if op == "|":
            ready_incomparable.append(formula)
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
    if ready_incomparable:
        parsed_incomp = [_formula_sides(formula) for formula in ready_incomparable]
        eq_checks = clause_checks(
            [f"{left} = {right}." for _op, left, right in parsed_incomp if _op is not None],
            interpretations,
        )
        for formula, (_op, left, right), (equal_everywhere, witness) in zip(
            ready_incomparable, parsed_incomp, eq_checks
        ):
            if equal_everywhere:
                if progress:
                    print(f"  Cached incomparability fails in the algebras: {formula}")
                continue
            order.note_separator(left, right, witness)
            order.mark_incomparable(left, right)
            applied += 1
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
    save_incomparable: Callable[[str], None] | None = None,
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
    checks = clause_checks(clauses, interpretations)
    n = len(chosen)
    eq_checks = checks[:n]
    eq_true = [holds for holds, _witness in eq_checks]
    for (left, right), (holds, witness) in zip(chosen, eq_checks):
        if not holds:
            order.note_separator(left, right, witness)
    if not leq_is_relation:
        n_eq = _apply_algebra_equalities(chosen, eq_true, order, save_axiom)
        _mark_undecided_unequal(chosen, order)
        if progress:
            print(f"  Algebras: {n} pairs, {n_eq} identities")
        return
    le_true = [holds for holds, _witness in checks[n : 2 * n]]
    ge_true = [holds for holds, _witness in checks[2 * n :]]

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
        if less:
            save_axiom(f"{left} <= {right}.")
            order.add_less_than(left, right)
            n_le += 1
        elif greater:
            save_axiom(f"{right} <= {left}.")
            order.add_less_than(right, left)
            n_ge += 1
        else:
            order.mark_incomparable(left, right)
            if save_incomparable is not None:
                save_incomparable(f"{left} | {right}.")
    if progress:
        print(
            f"  Algebras: {n} pairs, {n_eq} identities, "
            f"{n_le} less-than, {n_ge} greater-than"
        )


def _residual_leq(order: TermPartialOrder, left: str, right: str) -> bool | None:
    """Whether ``(left \\ right)`` is known to be idempotent.

    ``None`` means the residual or its square has not been generated yet, so
    the comparison is still open. A stored product is enough; the term string
    does not have to remain in the partition.
    """
    residual = order.product("\\", (left, right))
    if residual is None:
        return None
    squared = order.product("\\", (residual, residual))
    if squared is None:
        return None
    return squared == residual


def _record_residual_order(order: TermPartialOrder, operations: Sequence[Operation]) -> int:
    """Add ``left <= right`` whenever ``(left \\ right)`` is already known to be idempotent.

    Does not write inequalities. The comparison is the equation
    ``(left \\ right) = (left \\ right) \\ (left \\ right)`` inside the partition.
    """
    if not any(op.symbol == "\\" and op.arity == 2 for op in operations):
        return 0
    reps = list(order.representatives())
    recorded = 0
    for left, right in itertools.product(reps, repeat=2):
        if left == right or order.known_less_than(left, right):
            continue
        if _residual_leq(order, left, right) is not True:
            continue
        order.add_less_than(left, right)
        recorded += 1
    return recorded


def _mark_residual_incomparable(
    order: TermPartialOrder,
    operations: Sequence[Operation],
    save_incomparable: Callable[[str], None] | None,
) -> int:
    """Mark pairs whose residuals both fail to be idempotent."""
    if not any(op.symbol == "\\" and op.arity == 2 for op in operations):
        return 0
    marked = 0
    for left, right in itertools.combinations(order.representatives(), 2):
        if order.known_less_than(left, right) or order.known_less_than(right, left):
            continue
        if order.known_incomparable(left, right):
            continue
        less = _residual_leq(order, left, right)
        greater = _residual_leq(order, right, left)
        if less is not False or greater is not False:
            continue
        order.mark_incomparable(left, right)
        if save_incomparable is not None:
            save_incomparable(f"{left} | {right}.")
        marked += 1
    return marked


def _mark_distinct_values(order: TermPartialOrder) -> None:
    """Distinct value tuples are unequal even when the order is still open."""
    values = getattr(order, "_values", None)
    if not values:
        return
    reps = order.representatives()
    for index, left in enumerate(reps):
        for right in reps[index + 1 :]:
            if values.get(left) != values.get(right):
                order.mark_unequal(left, right)


def _emit_undecided(order: TermPartialOrder, save_unknown: Callable[[str], None]) -> int:
    """Record pairs that are neither ordered nor known to be incomparable."""
    emitted = 0
    for left, right in itertools.combinations(order.representatives(), 2):
        if order.known_less_than(left, right) or order.known_less_than(right, left):
            continue
        if order.known_incomparable(left, right):
            continue
        if order.known_unequal(left, right):
            save_unknown(f"{left} <= {right}.")
        else:
            save_unknown(f"{left} = {right}.")
        emitted += 1
    return emitted


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
    if isinstance(order, TermPartialOrder):
        found = order.product(operation.symbol, (left, right))
        if found is None and operation.commutative and left != right:
            found = order.product(operation.symbol, (right, left))
        if found is not None:
            return found
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
        if isinstance(order, TermPartialOrder) and order.product(operation.symbol, args) is not None:
            continue
        if term not in order:
            next_layer += 1
    return cells, next_layer


def _rank_layout(graph: nx.DiGraph) -> dict[str, tuple[float, float]]:
    """Place a large Hasse diagram by longest-path rank.

    The crossing-reduction layout is for small diagrams. This keeps the
    vertical order and finishes quickly when there are many classes.
    """
    rank = {node: 0 for node in graph.nodes()}
    for _ in range(graph.number_of_nodes()):
        changed = False
        for lower, upper in graph.edges():
            if rank[upper] < rank[lower] + 1:
                rank[upper] = rank[lower] + 1
                changed = True
        if not changed:
            break
    buckets: dict[int, list[str]] = {}
    for node, level in rank.items():
        buckets.setdefault(level, []).append(node)
    pos: dict[str, tuple[float, float]] = {}
    for level, nodes in buckets.items():
        nodes.sort(key=len)
        for index, node in enumerate(nodes):
            pos[node] = (float(index), float(level))
    return pos


def _draw_term_hasse(
    ax,
    graph: nx.DiGraph,
    title: str = "",
    labels: dict[str, str] | None = None,
    edge_labels: dict[tuple[str, str], str] | None = None,
    undecided: Sequence[tuple[str, str]] = (),
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
    pos = hasse_layout(graph) if graph.number_of_nodes() <= 40 else _rank_layout(graph)
    nx.draw(
        graph,
        pos=pos,
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
    if edge_labels:
        nx.draw_networkx_edge_labels(
            graph, pos, edge_labels=edge_labels, ax=ax, font_size=7, font_color="#455a64"
        )
    if undecided:
        undecided_graph = nx.DiGraph()
        undecided_graph.add_nodes_from(graph.nodes())
        undecided_graph.add_edges_from(undecided)
        nx.draw_networkx_edges(
            undecided_graph,
            pos,
            ax=ax,
            edgelist=list(undecided),
            edge_color="#c62828",
            style="dashed",
            arrows=True,
            arrowsize=12,
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

    symbol = operation.symbol
    if n > 24:
        numeric = [[float(value) if value != "?" else float("nan") for value in row] for row in cells]
        image = ax_table.imshow(numeric, cmap="viridis", aspect="auto", interpolation="nearest")
        fig.colorbar(image, ax=ax_table, fraction=0.046, pad=0.04)
        ax_table.set_xlabel("column index")
        ax_table.set_ylabel("row index")
    else:
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

class _ParsedAlgebra:
    """Operation tables of one Mace4 interpretation."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.binary: dict[str, list[int]] = {}
        self.unary: dict[str, list[int]] = {}
        self.constants: dict[str, int] = {}
        self.relations: dict[str, list[int]] = {}


class ModelTables:
    """Pointwise term evaluation in a file of finite algebras.

    A term in one variable is determined by the tuple of its values at every
    element of every algebra. Two terms are identical in the variety generated
    by those algebras exactly when these tuples agree, so each tuple is stored
    once. The representative is the first term that produced it.
    """

    def __init__(self, path: Path) -> None:
        self.algebras = _parse_mace4_algebras(path)
        if not self.algebras:
            raise ValueError(f"no algebras in {path}")
        self.owners: list[int] = []
        for index, algebra in enumerate(self.algebras, start=1):
            self.owners.extend([index] * algebra.size)
        self.has_leq = all("<=" in algebra.relations for algebra in self.algebras)
        if any("<=" in algebra.relations for algebra in self.algebras) and not self.has_leq:
            raise ValueError(f"{path} mixes algebras with and without <=")

    def variable(self) -> tuple[int, ...]:
        values: list[int] = []
        for algebra in self.algebras:
            values.extend(range(algebra.size))
        return tuple(values)

    def constant(self, symbol: str) -> tuple[int, ...]:
        values: list[int] = []
        for algebra in self.algebras:
            value = algebra.constants[symbol]
            values.extend([value] * algebra.size)
        return tuple(values)

    def apply(self, operation: Operation, arguments: Sequence[tuple[int, ...]]) -> tuple[int, ...]:
        values: list[int] = []
        offset = 0
        for algebra in self.algebras:
            size = algebra.size
            if operation.arity == 1:
                table = algebra.unary[operation.symbol]
                arg = arguments[0]
                values.extend(table[arg[offset + i]] for i in range(size))
            elif operation.arity == 2:
                table = algebra.binary[operation.symbol]
                left, right = arguments
                values.extend(
                    table[left[offset + i] * size + right[offset + i]] for i in range(size)
                )
            else:
                raise ValueError(f"cannot evaluate {operation.symbol} of arity {operation.arity}")
            offset += size
        return tuple(values)

    def leq(self, left: tuple[int, ...], right: tuple[int, ...]) -> bool:
        offset = 0
        for algebra in self.algebras:
            table = algebra.relations["<="]
            size = algebra.size
            for i in range(size):
                if table[left[offset + i] * size + right[offset + i]] == 0:
                    return False
            offset += size
        return True


def _parse_mace4_algebras(path: Path) -> list[_ParsedAlgebra]:
    text = path.read_text(encoding="utf-8")
    algebras: list[_ParsedAlgebra] = []
    for chunk in text.split("interpretation(")[1:]:
        size_text, _rest = chunk.split(",", 1)
        algebra = _ParsedAlgebra(int(size_text.strip()))
        for kind, head, body in re.findall(
            r"(function|relation)\((.*?),\s*\[(.*?)\]\)",
            chunk,
            flags=re.DOTALL,
        ):
            symbol = head.split("(", 1)[0].strip()
            values = [int(token) for token in re.findall(r"-?\d+", body)]
            if kind == "relation":
                algebra.relations[symbol] = values
            elif "(" not in head:
                algebra.constants[symbol] = values[0]
            elif head.count("_") == 1:
                algebra.unary[symbol] = values
            else:
                algebra.binary[symbol] = values
        algebras.append(algebra)
    return algebras


def _separator_from_values(order: TermPartialOrder, left: str, right: str) -> int | None:
    values = getattr(order, "_values", None)
    owners = getattr(order, "_value_owner", None)
    if not values or not owners or left not in values or right not in values:
        return None
    for index, (a, b) in enumerate(zip(values[left], values[right])):
        if a != b:
            return owners[index]
    return None


def _classify_from_models(
    operations: Sequence[Operation],
    variables: Sequence[str],
    max_level: int,
    equivalence_classes: TermPartialOrder,
    tables: ModelTables,
    progress: bool,
) -> None:
    """Build the term algebra by evaluating each new term in the models.

    Only one representative is kept for each tuple of values. Products of
    older representatives are not generated again.
    """
    known: dict[tuple[int, ...], str] = {}
    equivalence_classes._values = {}
    equivalence_classes._value_owner = tables.owners

    def admit(term: str, signature: tuple[int, ...]) -> None:
        known[signature] = term
        equivalence_classes._values[term] = signature
        equivalence_classes.add(term)

    pool: list[str] = []
    variable = variables[0]
    for term in seed_terms(list(operations), variables):
        signature = tables.variable() if term == variable else tables.constant(term)
        if signature in known:
            continue
        admit(term, signature)
        pool.append(term)
    if progress:
        print(f"Level 0: {len(pool)} terms")
    frontier = list(pool)

    for level in range(1, max_level + 1):
        new_terms: list[str] = []
        for term, operation, args in expand_applications(operations, pool, frontier):
            signature = tables.apply(
                operation,
                [equivalence_classes._values[arg] for arg in args],
            )
            result = known.get(signature)
            if result is None:
                admit(term, signature)
                result = term
                new_terms.append(term)
            if operation.arity == 2:
                equivalence_classes.record_product(operation.symbol, args, result)
        if not new_terms:
            print(f"No new terms at level {level}; terminating.")
            return
        frontier = new_terms
        pool.extend(new_terms)
        if progress:
            print(f"Level {level}: {len(pool)} terms")
    for operation in operations:
        if operation.arity == 2 and operation.idempotent:
            for rep in pool:
                equivalence_classes.record_product(operation.symbol, (rep, rep), rep)


def _record_leq_from_values(
    order: TermPartialOrder,
    tables: ModelTables,
    save_axiom: Callable[[str], None],
    save_incomparable: Callable[[str], None] | None,
) -> None:
    """Decide the order from the algebras' ``<=`` tables."""
    values = order._values
    for left, right in itertools.combinations(order.representatives(), 2):
        less = tables.leq(values[left], values[right])
        greater = tables.leq(values[right], values[left])
        if less and greater:
            continue
        order.note_separator(left, right, _separator_from_values(order, left, right))
        if less:
            save_axiom(f"{left} <= {right}.")
            order.add_less_than(left, right)
        elif greater:
            save_axiom(f"{right} <= {left}.")
            order.add_less_than(right, left)
        else:
            order.mark_incomparable(left, right)
            if save_incomparable is not None:
                save_incomparable(f"{left} | {right}.")


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
    save_incomparable: Callable[[str], None] | None = None,
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
    tables = ModelTables(algebras_path) if algebras_path is not None and len(variables) == 1 else None

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
                    equivalence_classes.mark_incomparable(left, right)
                    if save_incomparable is not None:
                        save_incomparable(f"{left} | {right}.")
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
                save_incomparable,
            )
            return
        for left, right in pairs:
            if equivalence_classes.find(left) != left or equivalence_classes.find(right) != right:
                continue
            await classify_pair(left, right)

    try:
        if tables is not None:
            pending.clear()
            _classify_from_models(
                operations,
                variables,
                max_level,
                equivalence_classes,
                tables,
                progress,
            )
            return
        pool = live(seed_terms(operations, variables))
        apply_lookups()
        pool = live(pool)
        if progress:
            print(f"Level 0: {len(pool)} terms")
        await classify_pairs(itertools.combinations(pool, 2))
        pool = live(pool)
        frontier = list(pool)

        for level in range(1, max_level + 1):
            applications = expand_applications(operations, pool, frontier)
            for term, operation, args in applications:
                equivalence_classes.add(term)
                if operation.arity == 2:
                    equivalence_classes.record_product(operation.symbol, args, term)
            apply_lookups()
            new_terms = [
                term for term, _operation, _args in applications
                if equivalence_classes.find(term) == term
            ]
            if not new_terms:
                print(f"No new terms at level {level}; terminating.")
                equivalence_classes.forget_non_representatives(_pending_mentions(pending))
                return
            prev = list(pool)
            await classify_pairs(
                itertools.chain(
                    itertools.product(new_terms, prev),
                    itertools.combinations(new_terms, 2),
                )
            )
            for term, operation, args in applications:
                if operation.arity == 2:
                    equivalence_classes.record_product(operation.symbol, args, term)
            pool = live(prev + new_terms)
            frontier = [rep for rep in pool if rep not in prev]
            equivalence_classes.forget_non_representatives(_pending_mentions(pending))
            if progress:
                print(f"Level {level}: {len(pool)} terms")
    finally:
        if tables is not None and tables.has_leq:
            _record_leq_from_values(
                equivalence_classes, tables, save_axiom, save_incomparable
            )
            for lower, upper in equivalence_classes.cover_edges():
                equivalence_classes.note_separator(
                    lower, upper, _separator_from_values(equivalence_classes, lower, upper)
                )
        elif algebras_path is not None and not leq_is_relation:
            recorded = _record_residual_order(equivalence_classes, operations)
            marked = _mark_residual_incomparable(
                equivalence_classes, operations, save_incomparable
            )
            if progress and recorded:
                print(
                    f"  Order from equalities: {recorded} "
                    f"comparison{'s' if recorded != 1 else ''}"
                )
            if progress and marked:
                print(f"  Incomparable from equalities: {marked}")
            _mark_distinct_values(equivalence_classes)
            undecided = _emit_undecided(equivalence_classes, save_unknown)
            if progress and undecided:
                print(f"  Still open: {undecided}")
            for lower, upper in equivalence_classes.cover_edges():
                equivalence_classes.note_separator(
                    lower, upper, _separator_from_values(equivalence_classes, lower, upper)
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
    hasse = order.hasse
    hasse_labels = {n: str(n) for n in hasse.nodes()}
    index = {rep: str(i + 1) for i, rep in enumerate(reps)}
    for rep in reps:
        hasse_labels[rep] = index[rep] if len(reps) > 40 else f"{index[rep]}: {rep}"
    unknown_lines = list(unknowns)
    n_incomparable = sum(
        1
        for left, right in itertools.combinations(reps, 2)
        if order.known_incomparable(left, right)
    )
    undecided_edges: list[tuple[str, str]] = []
    seen_undecided: set[frozenset[str]] = set()
    for formula in unknown_lines:
        parsed = _formula_sides(formula)
        if parsed is None:
            continue
        _op, left, right = parsed
        if left not in order or right not in order:
            continue
        left, right = order.find(left), order.find(right)
        if left == right or left not in index or right not in index:
            continue
        key = frozenset((left, right))
        if key in seen_undecided:
            continue
        seen_undecided.add(key)
        undecided_edges.append((left, right))
    edge_labels = {
        (lower, upper): str(model)
        for lower, upper in order.cover_edges()
        if (model := order.separator(lower, upper)) is not None
    }
    n_nodes = hasse.number_of_nodes()
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
        hasse,
        title=(
            "Solid: known order. Dashed: not yet decided. "
            f"No edge: incomparable ({n_incomparable}). "
            "Edge numbers are one separating model."
        ),
        labels=hasse_labels,
        edge_labels=edge_labels,
        undecided=undecided_edges[:80],
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
    operation_lines: list[str] = []
    for operation in operations:
        if operation.arity == 2:
            _add_operation_table_page(pdf, order, operation, reps, fig_width)
            cells, _next_layer = _operation_table_cells(order, operation, reps)
            operation_lines.append(f"# {operation.symbol}")
            operation_lines.append("\t" + "\t".join(index[rep] for rep in reps))
            for rep, row in zip(reps, cells):
                operation_lines.append(index[rep] + "\t" + "\t".join(row))
            operation_lines.append("")
    operation_path = pdf_path.with_suffix(".operations.txt")
    operation_path.write_text("\n".join(operation_lines), encoding="utf-8")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

    separator_lines = [
        f"{index[lower]} < {index[upper]} model {model}"
        for lower, upper in order.cover_edges()
        if (model := order.separator(lower, upper)) is not None
    ]
    separator_path = pdf_path.with_suffix(".separators.txt")
    separator_path.write_text(
        "\n".join(separator_lines) + ("\n" if separator_lines else ""),
        encoding="utf-8",
    )
    if separator_lines:
        print(f"One separating model per covering edge written to {separator_path}")

    unknown_pages = 0
    while remaining_unknowns and unknown_pages < 3:
        chunk = remaining_unknowns[:50]
        remaining_unknowns = remaining_unknowns[50:]
        unknown_pages += 1
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
    if remaining_unknowns:
        fig, ax = plt.subplots(figsize=(fig_width, 3))
        ax.axis("off")
        ax.set_title("Unknown identities (continued)", fontsize=10, loc="left")
        ax.text(
            0.0,
            1.0,
            f"{len(remaining_unknowns)} further open comparisons are in the unknown file.",
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=11,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)

    pdf.close()
    print(f"PDF saved to {pdf_path}")
