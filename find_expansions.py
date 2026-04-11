# %%
import os
import sys
import asyncio
from pyp9m4 import Mace4, pipeline, parse_mace4_output
from pyp9m4.parsers.mace4 import Mace4Interpretation, Mace4InterpretationBuffer
from pyp9m4.options import Mace4CliOptions, IsofilterCliOptions, InterpformatCliOptions
from axioms import to_p9m4, idcrl_axioms
import re
import itertools
import uacalc_lib
Mace4Reader = uacalc_lib.io.Mace4Reader

def _terminal_status(msg: str, *, stream=None) -> None:
    """Print msg on one terminal line, replacing the previous status line."""
    stream = stream or sys.stdout
    stream.write("\r" + msg + "\033[K")
    stream.flush()

def diagram(model: Mace4Interpretation):
    diagram_sentence = ""
    card = model.domain_size
    for symbol, n in model.functions.items():
        match = re.search(r"(.+?)\(",symbol)
        symbol_only = symbol
        if match:
            symbol_only = match.group(1)
        if n == 0:
            diagram_sentence += f"{symbol_only}={model.get_value(symbol)}.\n"
        elif n == 1:
            for a in range(card): # note this assumes prefix notation
                diagram_sentence += f"{symbol_only}({a})={model.get_value(symbol,a)}.\n"
        elif n == 2:
            for a,b in itertools.product(range(card), repeat=2): # assume infix notation
                diagram_sentence += f"{a} {symbol_only} {b}={model.get_value(symbol,a,b)}.\n"
        else:
            for a in itertools.product(range(card), repeat=n):
                a_str = ','.join(str(a) for a in a)
                diagram_sentence += f"{symbol_only}({a_str})={model.get_value(symbol,*a)}.\n"
    
    for symbol, n in model.relations.items():
        symbol_only = symbol
        if match:
            symbol_only = match.group(1)
        if n == 0:
            neg = "-" if model.holds(symbol) else ""
            diagram_sentence += neg+f"{symbol_only}().\n"
        else:
            for a in itertools.product(range(card), repeat=n):
                a_str = ','.join(str(a) for a in a)
                neg = "-" if model.holds(symbol,*a) else ""
                diagram_sentence += neg+f"{symbol_only}({a_str}).\n"
    return diagram_sentence

options = Mace4CliOptions(
    end_size=12,
    max_models=1,
    max_seconds=60
)

# def print_interpretation(interpretation,er):
#     print(interpretation)

# get relatively subdirectly irreducible idempotent commutative residuated pomonoids
def main(n):
    m4 = Mace4()
    filename = f"rsi_icrp-{n}.model"
    buffer = Mace4InterpretationBuffer()
    result = {}
    print(f"Reading models from {filename!r}...", flush=True)
    with open(filename) as f:
        for line in f:
            for icrp in buffer.feed(line):
                icrp = icrp[0]
                name = re.search(r"number = (\d+)",icrp.raw).group(1)
                max_dom = 2**n + 2
                _terminal_status(
                    f"model {name}: searching idempotent CRL expansions (domain up to {max_dom})..."
                )
                diagram_sentence = diagram(icrp)
                for idcrl in m4.models(to_p9m4(idcrl_axioms+diagram_sentence),domain_size=n,end_size=max_dom):
                    reader = Mace4Reader.new_from_stream(list(idcrl.raw.encode('utf-8')))
                    alg = reader.parse_algebra_from_stream(list(idcrl.raw.encode('utf-8')))
                    alg.set_name(f"model{name} expansion")
                    result[name] = alg
                    _terminal_status(
                        f"model {name}: expansion found ({len(result)} total so far)"
                    )
    sys.stdout.write("\n")
    print(f"Finished expansion search: {len(result)} algebra(s).", flush=True)
    return result

if __name__ == "__main__":
    import argparse
    import matplotlib.backends.backend_pdf
    import matplotlib.pyplot as plt
    from draw_orders import draw_idempotent_crl
    parser = argparse.ArgumentParser()
    parser.add_argument("n", type=int)
    parser.add_argument("-i", "--ignore-distributive", action="store_true")
    args = parser.parse_args()
    n = args.n
    result = main(n)
    filename = f"rsi_icrp-{n}_expansions.pdf"
    if args.ignore_distributive:
        filename = f"rsi_icrp-{n}_proper_expansions.pdf"
    pdf = matplotlib.backends.backend_pdf.PdfPages(filename = filename)
    total = len(result)
    pages = 0
    for i, (model, idcrl) in enumerate(result.items(), start=1):
        if not args.ignore_distributive or len(idcrl.get_universe_list()) == n:
            _terminal_status(f"PDF {i}/{total}: drawing model {model}...")
            fig = draw_idempotent_crl(idcrl,n=n)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
            pages += 1
    sys.stdout.write("\n")
    pdf.close()
    if args.ignore_distributive:
        print(f"Wrote {pages} page(s) to {filename!r}.", flush=True)
    
    print(len(result), "expansions found")
