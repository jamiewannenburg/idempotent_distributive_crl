import sys
from pathlib import Path

from pyp9m4 import Mace4, Prover9
from pyp9m4.options import Mace4CliOptions, Prover9CliOptions

from axioms import (
    bciwme_axioms,
    icrp_axioms,
    idcrl_axioms,
    rsi_icrp_axioms,
    si_idcrl_axioms,
)
from free_algebra import (
    Operation,
    OperationType,
    TermPartialOrder,
    _drain_subprocess_transports,
    _run_asyncio,
    classify_term_order,
    write_free_algebra_pdf,
)

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--max-level", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("-o", "--output", type=str, default="output/free_bciwme.pdf")
    parser.add_argument(
        "--axioms",
        type=str,
        default="input/free_bciwme_axioms.txt",
        help="Path to the proven-statements file (default: input/free_bciwme_axioms.txt)",
    )
    parser.add_argument(
        "--lookup-only",
        action="store_true",
        help=(
            "Do not add proven statements from the axioms file as theory "
            "assumptions; use them only to restore the partial order when both "
            "sides are generated. Append only newly proven formulas."
        ),
    )
    parser.add_argument("--axiom-base", type=str, default="bciwme", choices=["bciwme", "icrp", "idcrl", "rsi_icrp", "si_idcrl"])
    args = parser.parse_args()

    operations = [
        Operation(2, OperationType.INFIX, "\\"),
        Operation(0, OperationType.PREFIX, "e")
    ]

    variables = ["x"]

    # m4 = Mace4(options=Mace4CliOptions(max_seconds=10,max_models=1))
    # p9 = Prover9(options=Prover9CliOptions(max_seconds=10))
    if args.axiom_base == "bciwme":
        axioms = [str(line) for line in bciwme_axioms.split("\n")]
    elif args.axiom_base == "icrp":
        axioms = [str(line) for line in icrp_axioms.split("\n")]
    elif args.axiom_base == "idcrl":
        axioms = [str(line) for line in idcrl_axioms.split("\n")]
    elif args.axiom_base == "rsi_icrp":
        axioms = [str(line) for line in rsi_icrp_axioms.split("\n")]
    elif args.axiom_base == "si_idcrl":
        axioms = [str(line) for line in si_idcrl_axioms.split("\n")]
    axioms.extend([
        r"(((x \ e) \ x) \ (x \ x)) = (((x \ e) \ e) \ (x \ x))."
    ])
    print("\n".join(axioms))
    # manually add some difficult theorems
    m4_timeout = args.timeout
    m4_options = Mace4CliOptions(max_seconds=m4_timeout,max_models=1)
    p9_timeout = args.timeout
    p9_options = Prover9CliOptions(max_seconds=p9_timeout)

    equivalence_classes = TermPartialOrder()
    mace4 = Mace4(options=m4_options, timeout_s=m4_timeout)
    prover9 = Prover9(options=p9_options, timeout_s=p9_timeout)

    input_dir = Path("input")
    input_dir.mkdir(parents=True, exist_ok=True)
    axioms_path = Path(args.axioms)
    axioms_path.parent.mkdir(parents=True, exist_ok=True)
    unknown_path = input_dir / "free_bciwme_unknown.txt"

    # Formulas already on disk: used to avoid re-appending.
    known_formulas: set[str] = set()
    pending_lookup: list[str] = []

    if axioms_path.exists():
        loaded = 0
        for line in axioms_path.read_text(encoding="utf-8").splitlines():
            formula = line.strip()
            if not formula or formula.startswith("%"):
                continue
            if not formula.endswith("."):
                formula += "."
            known_formulas.add(formula)
            loaded += 1
            pending_lookup.append(formula)
            if not args.lookup_only and formula not in axioms:
                axioms.append(formula)
        if args.lookup_only:
            print(
                f"Queued {loaded} proven statements from {axioms_path} "
                f"for lookup when generated (not added as axioms)"
            )
        else:
            print(
                f"Queued {loaded} proven statements from {axioms_path} "
                f"for lookup when generated (also added as axioms)"
            )

    axioms_file = axioms_path.open("a", encoding="utf-8")
    unknown_file = unknown_path.open("w", encoding="utf-8")
    unknowns: list[str] = []

    def save_axiom(formula: str) -> None:
        if formula not in axioms:
            axioms.append(formula)
        # Append only formulas that are not already recorded on disk.
        if formula not in known_formulas:
            known_formulas.add(formula)
            axioms_file.write(formula + "\n")
            axioms_file.flush()

    def save_unknown(formula: str) -> None:
        print(f"  {formula} undecided")
        unknowns.append(formula)
        unknown_file.write(formula + "\n")
        unknown_file.flush()
    
    async def classify() -> None:
        try:
            await classify_term_order(
                operations,
                variables,
                max_level=args.max_level,
                axioms=axioms,
                equivalence_classes=equivalence_classes,
                mace4=mace4,
                prover9=prover9,
                save_axiom=save_axiom,
                save_unknown=save_unknown,
                progress=True,
                pending_lookup=pending_lookup,
            )
            await _drain_subprocess_transports()
        finally:
            axioms_file.close()
            unknown_file.close()
            if pending_lookup:
                print(
                    f"{len(pending_lookup)} queued statement(s) unused "
                    f"(mention terms never generated this run)"
                )

    try:
        completed = _run_asyncio(classify())
    finally:
        if not axioms_file.closed:
            axioms_file.close()
        if not unknown_file.closed:
            unknown_file.close()
        write_free_algebra_pdf(equivalence_classes, unknowns, args.output, operations, "BCIWME")
    if not completed:
        sys.exit(130)

