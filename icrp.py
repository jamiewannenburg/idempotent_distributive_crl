
import uacalc_lib as ua
BasicAlgebra = ua.alg.BasicAlgebra
BasicOperation = ua.alg.BasicOperation
string_to_term = ua.terms.string_to_term
TermOperationImp = ua.terms.TermOperationImp
Variable = ua.terms.VariableImp
Equation = ua.eq.Equation
OrderedSet = ua.lat.OrderedSet
# x = Variable('x')
# y = Variable('y')
# arrow_mod_term = string_to_term('\\(\\(x,y),\\(x,y))')

# def arrow_mod(alg: BasicAlgebra):
#     arrow_op = TermOperationImp(arrow_mod_term, [x, y], alg, name="arrowmod")
#     return arrow_op

#TODO: this is broken somehow
def leq(x,y,arrow_op: BasicOperation,universe):
    i = universe.index(x)
    j = universe.index(y)
    # return arrow_op.int_value_at([x,y]) == arrow_mod_op.int_value_at([x,y])
    arrow = arrow_op.int_value_at([i,j])
    k = universe.index(arrow)
    return arrow == arrow_op.int_value_at([k,k])

def get_filters(alg: BasicAlgebra):
    universe = alg.get_universe_list()
    print(universe)
    arrow_op = None
    for op in alg.operations():
        if op.symbol().name() == "\\":
            arrow_op = op
    # arrow_mod_op = arrow_mod(alg)
    filters = []
    for i,x in enumerate(universe):
        xfilter = []
        for j,y in enumerate(universe):
            if leq(x,y,arrow_op,universe):
                xfilter.append(y)
        filters.append(xfilter)

    return filters

def to_ordered_set(alg: BasicAlgebra):
    filters = get_filters(alg)
    print(alg.get_universe_list(),filters)
    return OrderedSet.from_filters(alg.get_universe_list(),filters,name=alg.name())

if __name__ == "__main__":
    import argparse
    from pathlib import Path
    Mace4Reader = ua.io.Mace4Reader
    from draw_orders import icrps_pdf
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    parser.add_argument("-o", "--output", type=str)
    args = parser.parse_args()
    model_filename = Path(args.input)
    pdf_filename = args.output
    if pdf_filename is None:
        pdf_filename = model_filename.with_suffix(".pdf")
    else:
        pdf_filename = Path(pdf_filename)
    algebras = Mace4Reader.parse_algebra_list_from_file(str(model_filename))
    icrps_pdf(algebras, str(pdf_filename))
    print(f"PDF saved to {pdf_filename}")