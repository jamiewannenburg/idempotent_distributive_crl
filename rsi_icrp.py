# %%
import os
import sys
from pyp9m4 import Theory, IsomorphismFilter
from pyp9m4.options import Mace4CliOptions, IsofilterCliOptions, InterpformatCliOptions
from axioms import to_p9m4, rsi_icrp_axioms

# get relatively subdirectly irreducible idempotent commutative residuated pomonoids
def main(n):
    # clear file if it exists
    if os.path.exists(f"rsi_icrp-{n}.model"):
        os.remove(f"rsi_icrp-{n}.model")
    result = (
        Theory(assumptions=rsi_icrp_axioms)
        .mace4(domain_size=n,max_models=-1,max_seconds=-1)
        .interpformat(output_operations="* \\ e")
        .isofilter(output_file=f"rsi_icrp-{n}.model")
        .stream()
    )
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("n", type=int)
    args = parser.parse_args()
    n = args.n
    stdout = main(n)
    # This is a <generator object Stage.stream at 0x000001C5E7E57ED0>
    # write stdout to terminal as it is filled
    for line in stdout:
        print(line)
    print()