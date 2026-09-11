import asyncio
import gc
import itertools
import sys
import networkx as nx
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

    def _choice_key(self, x: str) -> tuple[int, int, str]:
        return (len(x), self._birth[x], x)

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

async def decide(theory_text: str, mace4: Mace4, prover9: Prover9) -> Decision:
    """Run Mace4 and Prover9 together; stop both as soon as either decides the theory."""
    mace_job = mace4.start_amodels(input=theory_text)
    proof_job = prover9.start_aprove(input=theory_text)

    async def first_counterexample() -> Decision | None:
        async for _model in mace_job.amodels():
            return Decision.FALSIFIED
        return None

    async def first_proof() -> Decision | None:
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

    mace_task = asyncio.create_task(first_counterexample())
    proof_task = asyncio.create_task(first_proof())
    pending: set[asyncio.Task[Decision | None]] = {mace_task, proof_task}
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
        return Decision.UNKNOWN
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


def _formula_body(formula: str) -> str:
    return formula.strip().removesuffix(".").strip()


def _apply_proven_formula(formula: str, order: TermPartialOrder) -> None:
    """Replay a saved identity or inequality into the running partial order."""
    body = _formula_body(formula)
    if "<=" in body:
        left, right = body.split("<=", 1)
        order.add_less_than(left.strip(), right.strip())
    elif "=" in body:
        left, right = body.split("=", 1)
        order.union(left.strip(), right.strip())


def _draw_term_hasse(ax, graph: nx.DiGraph, title: str = "") -> None:
    """Draw a Hasse diagram of term representatives using the project layout."""
    from draw_orders import hasse_layout

    if graph.number_of_nodes() == 0:
        ax.set_title(title, fontsize=10)
        ax.axis("off")
        return
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


def write_free_icrp_pdf(
    order: TermPartialOrder,
    unknowns: Sequence[str],
    pdf_filename: str,
) -> None:
    """Draw the known Hasse diagram with unknown identities listed below it."""
    import matplotlib.backends.backend_pdf
    import matplotlib.pyplot as plt
    from pathlib import Path

    pdf_path = Path(pdf_filename)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

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

    _draw_term_hasse(ax_graph, order.hasse, title="Known partial order")

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
    fig.suptitle("Free ICRP", fontsize=14, fontweight="bold")

    pdf = matplotlib.backends.backend_pdf.PdfPages(filename=str(pdf_path))
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

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


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-level", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("-o", "--output", type=str, default="output/free_icrp.pdf")
    args = parser.parse_args()

    operations = [
        Operation(2, OperationType.INFIX, "*", commutative=True, idempotent=True),
        Operation(2, OperationType.INFIX, "\\"),
        Operation(0, OperationType.PREFIX, "e")
    ]

    variables = ["x"]

    # m4 = Mace4(options=Mace4CliOptions(max_seconds=10,max_models=1))
    # p9 = Prover9(options=Prover9CliOptions(max_seconds=10))
    axioms = [str(line) for line in icrp_axioms.split("\n")]
    m4_timeout = args.timeout
    m4_options = Mace4CliOptions(max_seconds=m4_timeout,max_models=1)
    p9_timeout = args.timeout
    p9_options = Prover9CliOptions(max_seconds=p9_timeout)

    equivalence_classes = TermPartialOrder()
    mace4 = Mace4(options=m4_options, timeout_s=m4_timeout)
    prover9 = Prover9(options=p9_options, timeout_s=p9_timeout)

    input_dir = Path("input")
    input_dir.mkdir(parents=True, exist_ok=True)
    axioms_path = input_dir / "free_icrp_axioms.txt"
    unknown_path = input_dir / "free_icrp_unknown.txt"

    if axioms_path.exists():
        loaded = 0
        for line in axioms_path.read_text(encoding="utf-8").splitlines():
            formula = line.strip()
            if not formula or formula.startswith("%"):
                continue
            if not formula.endswith("."):
                formula += "."
            if formula not in axioms:
                axioms.append(formula)
            _apply_proven_formula(formula, equivalence_classes)
            loaded += 1
        print(f"Loaded {loaded} proven statements from {axioms_path}")

    axioms_file = axioms_path.open("a", encoding="utf-8")
    unknown_file = unknown_path.open("w", encoding="utf-8")
    unknowns: list[str] = []

    def save_axiom(formula: str) -> None:
        axioms.append(formula)
        axioms_file.write(formula + "\n")
        axioms_file.flush()

    def save_unknown(formula: str) -> None:
        print("  undecided")
        unknowns.append(formula)
        unknown_file.write(formula + "\n")
        unknown_file.flush()

    async def classify() -> None:
        try:
            for left, right in icombinations(terms(operations, variables, max_level=args.max_level, progress=True), 2):
                po = PartialOrderVerdict.UNKNOWN
                if equivalence_classes.same(left, right):
                    continue
                if equivalence_classes.known_unequal(left, right):
                    continue
                # decide equality
                theory = Theory(assumptions=axioms, goals=[f"{left} = {right}."])
                verdict = await decide(theory.to_theory_text(), mace4, prover9)
                if verdict is Decision.PROVED:
                    po = PartialOrderVerdict.EQUAL
                elif verdict is Decision.FALSIFIED: # not equal in free algebra
                    equivalence_classes.mark_unequal(left, right)
                    # decide ordering
                    theory = Theory(assumptions=axioms, goals=[f"{left} <= {right}."])
                    verdict = await decide(theory.to_theory_text(), mace4, prover9)
                    if verdict is Decision.PROVED:
                        po = PartialOrderVerdict.LESS_THAN
                    elif verdict is Decision.FALSIFIED: # not less than or equal in free algebra
                        theory = Theory(assumptions=axioms, goals=[f"{right} <= {left}."])
                        verdict = await decide(theory.to_theory_text(), mace4, prover9)
                        if verdict is Decision.PROVED:
                            po = PartialOrderVerdict.GREATER_THAN
                        elif verdict is Decision.FALSIFIED: # not greater than or less than or equal in free algebra
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
                elif po is PartialOrderVerdict.INCOMPARABLE:
                    pass
                else:
                    pass

            await _drain_subprocess_transports()
        finally:
            axioms_file.close()
            unknown_file.close()
            write_free_icrp_pdf(equivalence_classes, unknowns, args.output)

    _run_asyncio(classify())

