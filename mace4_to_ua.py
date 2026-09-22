"""Convert a Mace4 model file to UACalc ``.ua`` algebra files.

Uses ``uacalc_lib.io.Mace4Reader`` to parse and ``write_algebra_file`` to
serialize. The default writer appends ``.xml``; this script renames the
result to ``.ua``.

When a model file contains more than one algebra, output names are
incremented (``stem_1.ua``, ``stem_2.ua``, ...). A single algebra is
written as ``stem.ua``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from uacalc_lib import io as ua_io


def convert_mace4_to_ua(model_path: Path, out_dir: Path) -> list[Path]:
    """Parse ``model_path`` and write one ``.ua`` file per algebra into ``out_dir``."""
    algebras = list(ua_io.Mace4Reader.parse_algebra_list_from_file(str(model_path)))
    if not algebras:
        raise SystemExit(f"no algebras found in {model_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = model_path.stem
    written: list[Path] = []

    for i, algebra in enumerate(algebras, start=1):
        if len(algebras) == 1:
            ua_path = out_dir / f"{stem}.ua"
        else:
            ua_path = out_dir / f"{stem}_{i}.ua"

        # write_algebra_file appends ".xml" when the path is not already .xml
        ua_io.write_algebra_file(algebra, str(ua_path))
        xml_path = Path(str(ua_path) + ".xml")
        if not xml_path.is_file():
            raise SystemExit(f"expected writer output missing: {xml_path}")
        if ua_path.exists():
            ua_path.unlink()
        xml_path.rename(ua_path)

        written.append(ua_path)
        print(
            f"wrote {ua_path.name} "
            f"(name={algebra.name()}, size={algebra.cardinality()})"
        )

    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a Mace4 model file to UACalc .ua files."
    )
    parser.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="Mace4 model file (e.g. model_outputs/rsi_icrp-3.model)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for .ua files (default: ua_outputs/<input-stem>)",
    )
    args = parser.parse_args()

    model_path = args.input
    if not model_path.is_file():
        raise SystemExit(f"input not found: {model_path}")

    out_dir = args.output_dir
    if out_dir is None:
        out_dir = Path("ua_outputs") / model_path.stem

    written = convert_mace4_to_ua(model_path, out_dir)
    print(f"wrote {len(written)} file(s) to {out_dir}")


if __name__ == "__main__":
    main()
