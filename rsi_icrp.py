# %%
import os
import sys
import asyncio
from pyp9m4 import Mace4, pipeline, parse_mace4_output
from pyp9m4.options import Mace4CliOptions, IsofilterCliOptions, InterpformatCliOptions
from axioms import to_p9m4, rsi_icrp_axioms

options = Mace4CliOptions(
    domain_size=2,
    max_models=-1,
)

# def print_interpretation(interpretation,er):
#     print(interpretation)

# get relatively subdirectly irreducible idempotent commutative residuated pomonoids
async def main(n):
    result = await (
        pipeline(to_p9m4(rsi_icrp_axioms))
            .run("mace4", Mace4CliOptions(domain_size=n,max_models=-1,max_seconds=-1))
            .pipe(
                "interpformat",
                InterpformatCliOptions(
                    output_operations="* \\ e",
                ),
            )
            .pipe(
                "isofilter",
                # IsofilterCliOptions(
                #     check_operations="* \\ e",      # your subsignature ops to check
                #     output_operations="* \\ e",     # optional: restrict output ops
                #     # ignore_constants=True,   # optional
                # ),
            )
            # .execute(on_last_mace4_interpretation=print_interpretation)
            .execute(last_stdout_path=f"rsi_icrp-{n}.model",buffer_last_stdout=True)
    )
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("n", type=int)
    args = parser.parse_args()
    n = args.n
    result = asyncio.run(main(n))
    print(result.final_stdout)
