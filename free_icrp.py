import asyncio
import gc
import itertools
import sys
from collections.abc import Iterable, Iterator, Sequence
from enum import Enum
from typing import Any
from axioms import icrp_axioms, rsi_crp_axioms
from pyp9m4 import Mace4, Model, Prover9, ProverOutcome, Theory, Stage
from pyp9m4.options import Mace4CliOptions, Prover9CliOptions

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

# Generate all terms up to a given level
def terms(operations: list[Operation], variables: list[str], max_level: int = 10, progress: bool = False) -> Iterator[str]:
    # Base case: variables
    ts = set[str]()
    for variable in variables:
        ts.add(variable)
        yield variable
    # Base case: constants
    for operation in operations:
        if operation.arity == 0:
            ts.add(operation.symbol)
            yield operation.symbol

    # Recursive case: operations
    level = 0
    if progress:
        print(f"Level {level}: {len(ts)} terms")
    while level < max_level:
        new_terms = set[str]()
        for operation in operations:
            if operation.arity > 0:
                if operation.commutative and operation.idempotent:
                    for args in itertools.combinations(ts, operation.arity):
                        new_term = operation(args)
                        if new_term not in ts:
                            new_terms.add(new_term)
                            yield new_term
                elif operation.commutative:
                    for args in itertools.combinations_with_replacement(ts, operation.arity):
                        new_term = operation(args)
                        if new_term not in ts:
                            new_terms.add(new_term)
                            yield new_term
                else:
                    for args in itertools.product(ts, repeat=operation.arity):
                        new_term = operation(args)
                        if new_term not in ts:
                            new_terms.add(new_term)
                            yield new_term
        ts.update(new_terms)
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


class EquationVerdict(Enum):
    EQUAL = "equal"
    UNEQUAL = "unequal"
    UNKNOWN = "unknown"


class TermEquivalence:
    """Union-find partition of terms proven equal, with inequalities on class roots.

    Proven identities are closed under transitivity. A counterexample between two
    terms is recorded on their current roots, so later members of those classes
    are treated as already distinguished.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}
        self._unequal: set[frozenset[str]] = set()

    def add(self, x: str) -> None:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0

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
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        elif self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1
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

    def mark_unequal(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._unequal.add(frozenset((rx, ry)))

    def classes(self) -> list[set[str]]:
        groups: dict[str, set[str]] = {}
        for x in self._parent:
            groups.setdefault(self.find(x), set()).add(x)
        return sorted(groups.values(), key=lambda members: min(members))


async def _stop_job(job: Any) -> None:
    """Cancel a Mace4/Prover9 job and wait until its subprocess has actually exited."""
    job.cancel()
    runner = getattr(job, "_runner_task", None)
    if runner is not None:
        await asyncio.gather(runner, return_exceptions=True)
        return
    try:
        await job.wait()
    except Exception:
        return


async def _drain_subprocess_transports() -> None:
    """Flush pending Proactor pipe-close callbacks while the loop is still open."""
    await asyncio.sleep(0)
    gc.collect()
    await asyncio.sleep(0)
    if sys.platform == "win32":
        await asyncio.sleep(0.05)


def _run_asyncio(coro: Any) -> None:
    """Like ``asyncio.run``, but lets Windows subprocess transports close first."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        loop.run_until_complete(coro)
        loop.run_until_complete(loop.shutdown_asyncgens())
        if hasattr(loop, "shutdown_default_executor"):
            loop.run_until_complete(loop.shutdown_default_executor())
        gc.collect()
        loop.run_until_complete(asyncio.sleep(0.1))
    finally:
        asyncio.set_event_loop(None)
        loop.close()


async def decide_equality(theory_text: str, mace4: Mace4, prover9: Prover9) -> EquationVerdict:
    """Run Mace4 and Prover9 together; stop both as soon as either decides the equation."""
    mace_job = mace4.start_amodels(input=theory_text)
    proof_job = prover9.start_aprove(input=theory_text)

    async def first_counterexample() -> EquationVerdict | None:
        async for _model in mace_job.amodels():
            return EquationVerdict.UNEQUAL
        return None

    async def first_proof() -> EquationVerdict | None:
        async for event in proof_job.event_stream():
            if event.get("type") == "stdout" and "THEOREM PROVED" in event.get("line", ""):
                return EquationVerdict.EQUAL
        try:
            result = await proof_job.result()
        except RuntimeError:
            return None
        if result.outcome == ProverOutcome.proved:
            return EquationVerdict.EQUAL
        return None

    mace_task = asyncio.create_task(first_counterexample())
    proof_task = asyncio.create_task(first_proof())
    pending: set[asyncio.Task[EquationVerdict | None]] = {mace_task, proof_task}
    try:
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    verdict = task.result()
                except Exception:
                    continue
                if verdict is not None:
                    for leftover in pending:
                        leftover.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    return verdict
        return EquationVerdict.UNKNOWN
    finally:
        for task in (mace_task, proof_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(
            _stop_job(mace_job),
            _stop_job(proof_job),
            mace_task,
            proof_task,
            return_exceptions=True,
        )
        await _drain_subprocess_transports()


if __name__ == "__main__":
    operations = [
        Operation(2, OperationType.INFIX, "*", commutative=True, idempotent=True),
        Operation(2, OperationType.INFIX, "\\"),
        Operation(0, OperationType.PREFIX, "e")
    ]

    variables = ["x"]

    # m4 = Mace4(options=Mace4CliOptions(max_seconds=10,max_models=1))
    # p9 = Prover9(options=Prover9CliOptions(max_seconds=10))
    axioms = icrp_axioms.split("\n")
    m4_timeout = 20
    m4_options = Mace4CliOptions(max_seconds=m4_timeout,max_models=1)
    p9_timeout = 60
    p9_options = Prover9CliOptions(max_seconds=p9_timeout)

    equivalence_classes = TermEquivalence()
    mace4 = Mace4(options=m4_options, timeout_s=m4_timeout)
    prover9 = Prover9(options=p9_options, timeout_s=p9_timeout)

    async def classify() -> None:
        for left, right in icombinations(terms(operations, variables, max_level=2), 2):
            print(f"Checking equation: {left} = {right}")
            if equivalence_classes.same(left, right):
                print("  already equivalent")
                continue
            if equivalence_classes.known_unequal(left, right):
                print("  already distinguished")
                continue
            theory = Theory(assumptions=axioms, goals=[f"{left} = {right}."])
            verdict = await decide_equality(theory.to_theory_text(), mace4, prover9)
            if verdict is EquationVerdict.EQUAL:
                print("  proved equal")
                equivalence_classes.union(left, right)
                axioms.append(f"{left} = {right}.")
            elif verdict is EquationVerdict.UNEQUAL:
                print("  counterexample found")
                equivalence_classes.mark_unequal(left, right)
            else:
                print("  undecided")

        print(Theory(assumptions=axioms).to_theory_text())
        print("Equivalence classes:")
        for members in equivalence_classes.classes():
            print("  {" + ", ".join(sorted(members)) + "}")

        await _drain_subprocess_transports()

    _run_asyncio(classify())

