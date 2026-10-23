# Verification Script Usage Guide

## Quick Start

Verify a free algebra computed by `free_icrp.py`:

```bash
# Step 1: Compute the free algebra
python free_icrp.py --max-level 2 -o output/free_icrp.pdf
# Creates: output/free_icrp.json with representative terms

# Step 2: Verify it
python verify_free_icrp.py output/free_icrp.json
```

## What Changed (Per Jamie's Feedback)

### Primary Input: JSON from free_icrp.py
- **Preferred format**: `.json` files exported by `free_icrp.py`
- Contains representative terms automatically
- No manual term assignment needed

### Secondary Input: Mace4 .model Files
- Supported for compatibility
- If representative terms missing: **computed automatically via BFS** from generator `x` and constant `e`
- Specify generator index with `--generator-index` (default: 1)

### Removed
- ❌ `.ua` (UACalc) support
- ❌ All `uacalc_lib` imports
- ❌ Documentation about `free_rsi_icrp_product.py` workflow
- ❌ `IMPLEMENTATION_SUMMARY.md`
- ❌ `prepare_candidate_example.py`

### Implemented: Actual Parallel Verification
- `--parallel N` now actually works (not just a placeholder)
- **Sound lemma sharing**: Only lemmas proven BEFORE a batch are used in that batch
- **Batch processing**: Verifies N equations in parallel using multiprocessing
- **Incremental**: Proven equations from batch K become lemmas for batch K+1

## Command Examples

### Basic Verification
```bash
python verify_free_icrp.py output/free_icrp.json
```

### Parallel Verification (Recommended for Large Algebras)
```bash
python verify_free_icrp.py output/free_icrp.json --parallel 8
```

### With Custom Timeouts and Output
```bash
python verify_free_icrp.py output/free_icrp.json \
    -o verification_results/ \
    --proof-timeout 60 \
    --counter-timeout 120 \
    --parallel 4
```

### Resume Interrupted Verification
```bash
python verify_free_icrp.py output/free_icrp.json --resume
```

### Using a .model File (with BFS term computation)
```bash
# Terms will be computed automatically via BFS
python verify_free_icrp.py model_outputs/candidate.model

# Specify non-default generator index
python verify_free_icrp.py model_outputs/candidate.model --generator-index 2
```

### Disable Lemma Reuse (Independent Proofs)
```bash
python verify_free_icrp.py output/free_icrp.json --no-lemmas
```

### Prover9 + Mace4 Only (No TPTP)
```bash
python verify_free_icrp.py output/free_icrp.json --no-tptp
```

## How BFS Term Computation Works

When representative terms are missing from a `.model` file, they are computed automatically:

1. Start with `e` (identity, element 0) and `x` (generator, element 1 by default)
2. Apply operations `*` and `\` to generate new terms
3. Continue until all reachable elements have terms
4. Any unreachable elements get generic names `elem_N`

Example terms generated:
- Element 0: `e`
- Element 1: `x`
- Element 2: `(x * x)` or `(x \\ e)` (whichever is found first)
- Element 3: `((x * x) * x)` or similar

## Parallel Verification Details

### How It Works
1. Equations split into batches of size `--parallel`
2. Each batch uses only lemmas proven in PREVIOUS batches (sound!)
3. Batch equations verified in parallel via multiprocessing
4. All proven equations in batch K → lemmas for batch K+1
5. Checkpoint saved after each batch

### Example Output
```
[Batch 1-4/100] Verifying 4 equations in parallel
  Using 25 axioms (20 base + 5 lemmas)
  [1/100] *(0, 0) = 0
    ✓ PROVED by prover9 in 0.15s
  [2/100] *(0, 1) = 1
    ✓ PROVED by vampire in 0.23s
  [3/100] *(1, 1) = 1
    ✓ PROVED by prover9 in 0.31s
  [4/100] *(0, 2) = 2
    ✓ PROVED by prover9 in 0.18s

[Batch 5-8/100] Verifying 4 equations in parallel
  Using 29 axioms (20 base + 9 lemmas)
  ...
```

### Performance Tips
- Start with `--parallel` equal to your CPU core count
- Increase for I/O-bound workloads (provers waiting on disk)
- Decrease if running out of memory
- Use `--no-lemmas` if lemma accumulation slows later batches

## Output Files

### verification_summary.json
```json
{
  "algebra_path": "output/free_icrp.json",
  "cardinality": 5,
  "total_equations": 51,
  "proved": 51,
  "refuted": 0,
  "unknown": 0,
  "verification_complete": true,
  "results": [...]
}
```

### verification_checkpoint.json
- Updated after each equation (sequential) or batch (parallel)
- Resume with `--resume` flag
- Includes proven lemmas list

### counterexamples/
- Contains `counter_NNNN.model` files
- One per refuted equation
- Mace4 models showing counterexamples

## Interpreting Results

| Status | Meaning | Action |
|--------|---------|--------|
| **All proved** | ✅ Algebra is free | Success! |
| **Some refuted** | ❌ Algebra NOT free | Check counterexamples |
| **Some unknown** | ⚠️ Incomplete | Increase timeouts, try stronger provers |

## Testing

### Standalone Tests (No Dependencies)
```bash
python3 test_verify_simple.py
```

### Full Test Suite (Requires pytest)
```bash
pip install pytest pytest-asyncio
python -m pytest test_verify_free_icrp.py -v
```

### Integration Test
```bash
# Generate small algebra
python free_icrp.py --max-level 1 -o test/small.pdf

# Verify it
python verify_free_icrp.py test/small.json --proof-timeout 10
```

## Troubleshooting

### "No models found in .model file"
- File may be malformed
- Use JSON from `free_icrp.py` instead

### "Element N not reachable from generator"
- BFS couldn't reach some elements
- Check if algebra is actually 1-generated
- Specify correct generator with `--generator-index`

### Verification very slow
- Try `--parallel` for speed
- Increase `--proof-timeout` for hard equations
- Use `--no-lemmas` if theory growth is the bottleneck

### Out of memory with parallel
- Reduce `--parallel` value
- Each worker loads provers into memory
- Try `--no-tptp` to use only Prover9/Mace4

## Changes Summary

| Before | After |
|--------|-------|
| `.ua` files supported | ❌ Removed |
| `.model` requires terms in comments | ✅ Computes via BFS if missing |
| `--parallel` placeholder | ✅ Fully implemented |
| Manual term assignment needed | ✅ Automatic via BFS or JSON |
| `free_rsi_icrp_product.py` workflow | ❌ Removed (unnecessary) |
| Extra docs files | ❌ Removed |

## PR Status

- **Branch**: `cursor/algebra-html-viewer-e0fe`
- **PR**: https://github.com/jamiewannenburg/idempotent_distributive_crl/pull/1
- **Status**: ✅ Updated and pushed
- **Tests**: ✅ Passing (standalone suite)
