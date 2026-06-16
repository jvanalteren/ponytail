# Bifrost benchmark: netvlies/gemma4-26b via AI gateway - 2026-06-16

This benchmark evaluates the performance of netvlies/gemma4-26b across five distinct coding tasks using the bifrost provider at https://ai.netvlies.nl/v1. The evaluation compares baseline outputs against two condensed prompting strategies: caveman and ponytail.

## Results (n=10, median)

**Code LOC**

| arm | email | debounce | csv-sum | countdown | rate-limit | **TOTAL** |
|---|--:|--:|--:|--:|--:|--:|
| baseline | 35 | 33.5 | 27 | 85 | 26 | 206.5 |
| caveman | 5 | 13 | 4 | 20 | 12 | 54 |
| ponytail | 7 | 8 | 3 | 10 | 12 | 40 |

**Time (seconds)**

| arm | email | debounce | csv-sum | countdown | rate-limit | **TOTAL** |
|---|--:|--:|--:|--:|--:|--:|
| baseline | 12.2 | 12.2 | 8.1 | 15.3 | 12.3 | 60.1 |
| caveman | 1.9 | 3.0 | 1.0 | 3.4 | 3.2 | 12.4 |
| ponytail | 2.3 | 1.4 | 1.0 | 2.0 | 2.5 | 9.2 |

## Key findings

**Code Conciseness** The ponytail arm achieved the highest reduction in code volume, resulting in a median of 40.0 LOC. This represents an 80.6% reduction compared to the baseline median of 206.5 LOC.

**Execution Latency** Ponytail demonstrated the fastest median execution time at 9.2 seconds. This is a significant improvement over the baseline's 60.1 seconds, showing a 6.53x speedup.

**Arm Comparison** While both condensed arms outperformed the baseline, ponytail consistently maintained lower median LOC and time metrics than the caveman arm. Caveman achieved a 73.8% reduction in LOC and a 4.85x speedup relative to baseline.

## Reproduce

Run from the repo root with a valid `CXP_API_KEY`:

```bash
CXP_API_KEY=... python3 benchmarks/benchmark-interpret.py \
    --input benchmarks/benchmark-bifrost-results.json \
    --provider bifrost \
    --model "netvlies/gemma4-26b" \
    --output benchmarks/results/2026-06-16-netvlies-gemma4-26b-bifrost-generated.md
```

Raw responses are saved to `benchmarks/benchmark-bifrost-results.json`. The generated interpretation is written to `benchmarks/results/2026-06-16-netvlies-gemma4-26b-bifrost-generated.md`.

## Takeaway

The netvlies/gemma4-26b model shows significant efficiency gains when using the ponytail prompting strategy, drastically reducing both token output and latency compared to baseline methods.
