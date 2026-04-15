# %%
import os
import sys
from pyp9m4 import Theory, Model, InterpFilter, parse_models_from_file, parse_mace4_output
from pyp9m4.options import Mace4CliOptions
from axioms import idcrl_axioms
import re
import itertools
import tempfile
from icrp import leq_arrows
from conic_icrp import get_extension_interpretation_text, is_conic

def _terminal_status(msg: str, *, stream=None) -> None:
    """Print msg on one terminal line, replacing the previous status line."""
    stream = stream or sys.stdout
    stream.write("\r" + msg + "\033[K")
    stream.flush()

def diagram(model: Model):
    diagram_sentence = ""
    card = model.domain_size
    for symbol, n in model.functions.items():
        symbol_only = symbol
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
    max_seconds=60,
)



def check_formulas(formulas: str, model: Model, print_output: bool = False):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    temp_file.write(formulas.encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model.raw,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        if print_output:
            print(result.stdout)
        return False

seperable_conic = f"""
({leq_arrows('e','x')})|({leq_arrows('x','e')}).
({leq_arrows('x','e')})->({leq_arrows('(x*y)','y')}).

"""

def is_seperable_conic(model: Model, print_output: bool = False):
    return check_formulas(seperable_conic, model, print_output)

# def print_interpretation(interpretation,er):
#     print(interpretation)

# get relatively subdirectly irreducible idempotent commutative residuated pomonoids
def main(n):
    difficult_filename = f"input/difficult-{n}.txt"
    if os.path.exists(difficult_filename):
        os.remove(difficult_filename)
    filename = f"model_outputs/rsi_icrp-{n}.model"
    result = {}
    print(f"Reading models from {filename!r}...", flush=True)
    for icrp in parse_models_from_file(filename):
        name = re.search(r"number\s*=\s*(\d+)",icrp.raw).group(1)
        diagram_sentence = diagram(icrp)
        assumptions = idcrl_axioms+diagram_sentence
        

        found = False
        if is_conic(icrp):
            for alg in parse_mace4_output(get_extension_interpretation_text(name, icrp)).interpretations:
                if check_formulas(assumptions, alg):
                    result[name] = alg
                    found = True
                    _terminal_status(
                        f"model {name}: expansion found manually {len(result)} total so far)"
                    )
                    continue
                else:
                    print()
                    print(f"model {name}: is seperable but expansion does not work")
                    print("Trying other methods...")

        max_dom = 2**n + 2
        _terminal_status(
            f"model {name}: searching idempotent CRL expansions (domain up to {max_dom})..."
        )
        idcrl_theory = Theory(assumptions=assumptions)
        
        for idcrl in idcrl_theory.mace4(options=options,domain_size=n,end_size=max_dom,timeout_s=60).models():
            found = True
            result[name] = idcrl
            _terminal_status(
                f"model {name}: expansion found ({len(result)} total so far)"
            )
        if not found:
            with open(difficult_filename, "a") as f:
                f.write(f"{name}\n")
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
    filename = f"output/rsi_icrp-{n}_expansions.pdf"
    if args.ignore_distributive:
        filename = f"output/rsi_icrp-{n}_proper_expansions.pdf"
    pdf = matplotlib.backends.backend_pdf.PdfPages(filename = filename)
    total = len(result)
    pages = 0
    for i, (model, idcrl) in enumerate(result.items(), start=1):
        if not args.ignore_distributive or idcrl.domain_size != n:
            _terminal_status(f"PDF {i}/{total}: drawing model {model}...")
            fig = draw_idempotent_crl(idcrl,name=model,n=n)
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)
            pages += 1
    sys.stdout.write("\n")
    pdf.close()
    if args.ignore_distributive:
        print(f"Wrote {pages} page(s) to {filename!r}.", flush=True)
    
    print(len(result), "expansions found")
