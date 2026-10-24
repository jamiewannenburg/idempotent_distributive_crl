"""Congruence closure over ground terms in one generator ``x`` and constant ``e``.

Used by ``verify_free_icrp.py`` as a sound fast path: if a table equation
already follows from previously proven equations by pure equational reasoning
(reflexivity, symmetry, transitivity and congruence), no prover call is needed.

Only terms built from ``x``, ``e`` and the binary operations ``*`` and ``\\``
are handled. Formulas must be fully parenthesised, as written by
``free_icrp.py`` (``(a * b)``, ``(a \\ b)``). Anything else raises
:class:`TermParseError` so callers can skip it.

Supported formulas: ``s = t.`` and ``s <= t.``. Inequalities are recorded;
:meth:`CongruenceClosure.saturate_order` turns cycles of them into equations
(antisymmetry and transitivity of the order).

Because ``x`` is the only variable, treating it as a constant is sound: an
equation between ground terms derived here is an equation in ``x`` that
follows from the input equations (which are themselves universally valid).

Optional axiom instances (all are iCRP axioms): commutativity and idempotence
of ``*``, and ``e`` as the unit of ``*``. They are added for every ``*`` node
created.
"""

from __future__ import annotations

BINARY_OPS = ("*", "\\")
CONSTANTS = ("x", "e")


class TermParseError(ValueError):
    pass


def _tokenize(s: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c in "()*\\=":
            tokens.append(c)
            i += 1
        elif s.startswith("<=", i):
            tokens.append("<=")
            i += 2
        elif c.isalnum() or c == "_":
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            tokens.append(s[i:j])
            i = j
        else:
            raise TermParseError(f"unexpected character {c!r} in {s!r}")
    return tokens


def _parse_term(tokens: list[str], pos: int) -> tuple[tuple, int]:
    if pos >= len(tokens):
        raise TermParseError("unexpected end of term")
    tok = tokens[pos]
    if tok in CONSTANTS:
        return (tok,), pos + 1
    if tok != "(":
        raise TermParseError(f"unexpected token {tok!r}")
    left, pos = _parse_term(tokens, pos + 1)
    if pos >= len(tokens):
        raise TermParseError("unexpected end of term")
    if tokens[pos] == ")":  # redundant parentheses around a term
        return left, pos + 1
    op = tokens[pos]
    if op not in BINARY_OPS:
        raise TermParseError(f"expected operator, got {op!r}")
    right, pos = _parse_term(tokens, pos + 1)
    if pos >= len(tokens) or tokens[pos] != ")":
        raise TermParseError("expected ')' (terms must be fully parenthesised)")
    return (op, left, right), pos + 1


def parse_term(s: str) -> tuple:
    tokens = _tokenize(s)
    term, pos = _parse_term(tokens, 0)
    if pos != len(tokens):
        raise TermParseError(f"trailing tokens in {s!r}")
    return term


def parse_formula(s: str) -> tuple[str, tuple, tuple]:
    """Parse ``s = t.`` or ``s <= t.`` into (relation, lhs, rhs)."""
    s = s.strip()
    if s.endswith("."):
        s = s[:-1]
    tokens = _tokenize(s)
    lhs, pos = _parse_term(tokens, 0)
    if pos >= len(tokens) or tokens[pos] not in ("=", "<="):
        raise TermParseError(f"expected '=' or '<=' in {s!r}")
    rel = tokens[pos]
    rhs, pos = _parse_term(tokens, pos + 1)
    if pos != len(tokens):
        raise TermParseError(f"trailing tokens in {s!r}")
    return rel, lhs, rhs


class CongruenceClosure:
    """Incremental congruence closure (union-find + signature table)."""

    def __init__(self, icrp_instances: bool = True) -> None:
        self._icrp_instances = icrp_instances
        self._node_of: dict[tuple, int] = {}  # structural key -> node id
        self._parent: list[int] = []
        self._uses: list[list[int]] = []  # class rep -> nodes using it as argument
        self._nodes: list[tuple] = []  # node id -> (op, left_id, right_id) or (const,)
        self._sig: dict[tuple, int] = {}  # (op, find(l), find(r)) -> node id
        self._le: set[tuple[int, int]] = set()  # recorded (lhs node, rhs node)
        self._pending: list[tuple[int, int]] = []
        self.equations_added = 0
        self.inequalities_added = 0

    # -- union-find ---------------------------------------------------------
    def _find(self, a: int) -> int:
        root = a
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[a] != root:
            self._parent[a], a = root, self._parent[a]
        return root

    def _new_node(self, key: tuple) -> int:
        nid = len(self._parent)
        self._parent.append(nid)
        self._uses.append([])
        self._nodes.append(key)
        self._node_of[key] = nid
        return nid

    def node(self, term: tuple) -> int:
        """Return the node id for ``term``, creating nodes as needed."""
        if len(term) == 1:
            nid = self._node_of.get(term)
            return nid if nid is not None else self._new_node(term)
        op, left, right = term
        l_id = self.node(left)
        r_id = self.node(right)
        key = (op, l_id, r_id)
        nid = self._node_of.get(key)
        if nid is not None:
            return nid
        nid = self._new_node(key)
        sig = (op, self._find(l_id), self._find(r_id))
        self._uses[self._find(l_id)].append(nid)
        if self._find(r_id) != self._find(l_id):
            self._uses[self._find(r_id)].append(nid)
        other = self._sig.get(sig)
        if other is None:
            self._sig[sig] = nid
        else:
            self._pending.append((nid, other))
        if self._icrp_instances and op == "*":
            # commutativity, idempotence, unit
            swapped = self.node(("*", right, left))
            self._pending.append((nid, swapped))
            if l_id == r_id:
                self._pending.append((nid, l_id))
            if left == ("e",):
                self._pending.append((nid, r_id))
            if right == ("e",):
                self._pending.append((nid, l_id))
        self._propagate()
        return nid

    def _propagate(self) -> None:
        while self._pending:
            a, b = self._pending.pop()
            ra, rb = self._find(a), self._find(b)
            if ra == rb:
                continue
            if len(self._uses[ra]) > len(self._uses[rb]):
                ra, rb = rb, ra
            # merge ra into rb
            self._parent[ra] = rb
            moved = self._uses[ra]
            self._uses[ra] = []
            for u in moved:
                op, l_id, r_id = self._nodes[u]
                sig = (op, self._find(l_id), self._find(r_id))
                other = self._sig.get(sig)
                if other is None:
                    self._sig[sig] = u
                elif self._find(other) != self._find(u):
                    self._pending.append((u, other))
                self._uses[rb].append(u)

    def saturate_order(self) -> int:
        """Collapse cycles of recorded inequalities (antisymmetry + transitivity).

        Repeats until no new equalities appear. Returns the number of merges.
        """
        import networkx as nx

        merges = 0
        while True:
            graph = nx.DiGraph()
            for a, b in self._le:
                ra, rb = self._find(a), self._find(b)
                if ra != rb:
                    graph.add_edge(ra, rb)
            changed = False
            for comp in nx.strongly_connected_components(graph):
                if len(comp) > 1:
                    first, *rest = comp
                    for other in rest:
                        self._pending.append((first, other))
                        merges += 1
                    changed = True
            if not changed:
                return merges
            self._propagate()

    # -- public API ---------------------------------------------------------
    def add_equation(self, lhs: tuple, rhs: tuple) -> None:
        a, b = self.node(lhs), self.node(rhs)
        self._pending.append((a, b))
        self.equations_added += 1
        self._propagate()

    def add_inequality(self, lhs: tuple, rhs: tuple) -> None:
        """Record ``lhs <= rhs``. Call :meth:`saturate_order` to use it."""
        self._le.add((self.node(lhs), self.node(rhs)))
        self.inequalities_added += 1

    def add_formula(self, formula: str) -> bool:
        """Add a parsed ``=``/``<=`` formula. Returns False if unparseable."""
        try:
            rel, lhs, rhs = parse_formula(formula)
        except TermParseError:
            return False
        if rel == "=":
            self.add_equation(lhs, rhs)
        else:
            self.add_inequality(lhs, rhs)
        return True

    def equal(self, lhs: tuple, rhs: tuple) -> bool:
        return self._find(self.node(lhs)) == self._find(self.node(rhs))

    def equation_holds(self, equation: str) -> bool:
        """True if ``s = t`` follows by congruence closure. False if unknown/unparseable."""
        try:
            rel, lhs, rhs = parse_formula(equation)
        except TermParseError:
            return False
        if rel != "=":
            return False
        return self.equal(lhs, rhs)
