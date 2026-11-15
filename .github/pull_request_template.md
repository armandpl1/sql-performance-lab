## What changed

<!-- One or two sentences: what and why. -->

## How it was tested

- [ ] `make ci` passes locally (lint, unit tests)
- [ ] New query files are added to `scripts/check_equivalence.py`
      (an equivalence group, or RUN_ONLY)
- [ ] Optimized queries return the same checksum as the query they replace
- [ ] Timing claims come from `scripts/benchmark.py` at full scale, with the
      plan saved in `results/plans/`

## Notes for the reviewer

<!-- Anything to look at closely, trade-offs, follow-ups. -->
