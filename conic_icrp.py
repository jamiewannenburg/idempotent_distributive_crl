from pyp9m4 import Model, parse_models_from_file, InterpFilter
import tempfile
import os
import re

def is_conic(model: Model, print: bool = False):
    temp_file = tempfile.NamedTemporaryFile(delete=False)
    # -> version of x<=e | e<=x
    temp_file.write("(x=x\\x)|( (x\\e) = (x\\e)\\(x\\e) ).\n".encode('utf-8'))
    temp_file.close()
    result = InterpFilter().run(input=model.raw,formulas_file=temp_file.name,test='all_true')
    os.unlink(temp_file.name)
    m = re.search("checked 1, passed 1", result.stdout)
    if m:
        return True
    else:
        if print:
            print(result.stdout)
        return False



if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", type=str)
    args = parser.parse_args()
    model_filename = Path(args.input)
    models = parse_models_from_file(model_filename)
    for model in models:
        name = re.search(r"number = (\d+)",model.raw).group(1)
        if is_conic(model):
            print(f"model {name} is conic")
        # else:
        #     print(f"model {name} is not conic")