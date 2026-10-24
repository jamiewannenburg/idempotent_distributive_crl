# Isabelle/Nitpick searches for 1-generated RSI iCRPs

Standalone theories (they import only `Main`, with the iCRP axioms stated flat)
that use Nitpick to look for 1-generated RSI iCRPs of a given size.

| Session      | Theory                         | Question                          |
|--------------|--------------------------------|-----------------------------------|
| `RSI11`      | `RSI_iCRP_11_Search.thy`       | 11 elements (plus sanity checks at 4, 7, 9 = none, 10) |
| `RSI11_fast` | `RSI_iCRP_11_Search_fast.thy`  | same, generation encoded by an injective rank function |
| `RSI12`      | `RSI_iCRP_12_Search.thy`       | 12 elements                       |

Run from the repository root, e.g.

```
isabelle build -d isabelle -v RSI12
```

Results so far (Nitpick, one thread, ubuntu desktop): sizes 9 and 11 have no
1-generated RSI iCRP ("found no counterexample"; 11 took about 6 hours);
sizes 2-8 and 10 exist (see `model_outputs/rsi_icrp-*_one_generated.model`).
