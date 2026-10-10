# Assurance mutation harness

## Purpose

`scripts/run_assurance_mutation_harness.py` exercises the deterministic evaluator and release gate with one valid synthetic control and five deliberately corrupted observations. It makes no model calls and requires no external service.

## How to run

```bash
python scripts/run_assurance_mutation_harness.py
python -m unittest tests.test_mutation_harness
```

The JSON report includes:
- control decision and whether it remained `GO`;
- seeded fault count, detections, misses and detection rate;
- false-rejection count for the control;
- repeatability of the release decision and checks;
- explicit scope limitations.

## Interpretation

A passing run means only that the current implementation detected these five specified input faults and preserved the expected decision for this synthetic control. It is **not** a source-code mutation score, production reliability estimate, statistical confidence interval, or safety certification. The mutations are deliberately narrow and should be expanded across more workflow types, threshold boundaries, malformed inputs, baseline/candidate comparisons, source-code mutations, and independent real-world evidence before drawing broader conclusions.

## Guardrail

Do not treat `GO` as a general guarantee of agent safety. AWA evaluates supplied observations and configured criteria; it does not itself execute or sandbox arbitrary agents.

## Focused source-code mutation smoke test

A separate, deliberately small source-code mutation check is also included. It copies the core module and a focused regression test into a temporary directory, changes one source expression at a time, and checks that the corresponding test fails against each mutated implementation:

```bash
python scripts/run_source_mutation_smoke.py
```

The current smoke set includes:
- Removing strict boolean-versus-integer equality handling.
- Relaxing the JSON nesting-depth boundary by one level.

The baseline tests must pass before mutations are applied. A mutant counts as **killed** only when its targeted test fails; a surviving mutant or invalid mutation anchor fails the command and CI. The temporary copy is discarded afterward, so the production source is not edited by the run.

This is focused source-code mutation testing, but it is **not** a comprehensive mutation score for the project: only two hand-selected mutations are included. Expand the set as meaningful regression tests are added, or adopt a general mutation-testing tool for broader operator coverage.
