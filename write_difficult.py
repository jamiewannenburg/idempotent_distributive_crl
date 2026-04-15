from pyp9m4 import parse_models_from_file
from draw_orders import icrps_pdf
import re

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-d","--difficult", type=str, default="input/difficult-7.txt")
    parser.add_argument("-i","--input", type=str, default="model_outputs/rsi_icrp-7.model")
    parser.add_argument("-o","--output", type=str, default="output/rsi_icrp-7_difficult.pdf")
    args = parser.parse_args()
    model_filename = args.input
    pdf_filename = args.output
    with open(args.difficult, "r") as f:
        difficult = [line.strip() for line in f.readlines()]
    algebras = []
    for model in parse_models_from_file(model_filename):
        name = re.search(r"number\s*=\s*(\d+)",model.raw).group(1)
        if name in difficult:
            algebras.append(model)
    icrps_pdf(algebras, pdf_filename)
    print(f"PDF saved to {pdf_filename}")