# Automatic core discovery

This isolated experiment implements and evaluates five discovery methods that
the repository had not used: Eclat, PrefixSpan, KL-NMF, a Bernoulli mixture,
and Leiden communities. The system discovers candidate build cores itself,
then applies a common outcome/support gate before admitting them for review.

Read [PROTOCOL.md](PROTOCOL.md) for sources and the frozen comparison design;
read [RESULTS.md](RESULTS.md) for the completed evaluation. No existing build
identity, build pool, or future build label is a discovery input. No Steam
or production recommendation file is modified.

## Reproduce

Use the repository's documented uv version (`>=0.12,<0.13`):

```bash
uv sync --project experiments/core_discovery --frozen
uv run --project experiments/core_discovery python -m experiments.core_discovery.data \
  --replay generated/qdfm/item-combos --output generated/core-discovery/data
uv run --project experiments/core_discovery python -m experiments.core_discovery.discover \
  --directory generated/core-discovery/data --output generated/core-discovery/trial-v1
uv run --project experiments/core_discovery python -m experiments.core_discovery.evaluate \
  --runs generated/core-discovery/trial-v1
uv run --project experiments/core_discovery python -m experiments.core_discovery.synthetic \
  --output generated/core-discovery/synthetic-v2
uv run --project experiments/core_discovery python -m pytest experiments/core_discovery -W error
```

Extraction, discovery, and synthetic runs reject existing output directories.
Use new output paths for another run. Evaluation verifies frozen data, source,
models, and nomination hashes before reading later outcomes. Generated artifacts
are ignored by Git; the protocol, implementation, lockfile, and compact results
are tracked. This environment is separate from the earlier torch experiments.

The inventory replay must already exist, with its frozen source database still
available. Its inventory extraction includes all items; its older build-pool
metadata does not determine this experiment's candidates. The new extraction
adds enemy compositions, latest acquisition times, and a separate selection
partition within the old training period.

## Outputs and meaning

- `data/`: frozen observations, per-hero matrices, item catalog, and chronology.
- `trial-v1/hero-*.json`: all discovery runs, latent parameters/graph communities,
  candidate scores, selection outcomes, and rejection reasons.
- `trial-v1/nominations.json`: candidates fixed before this trial's validation.
- `trial-v1/evaluation.json` and `REPORT.md`: corrected validation evidence,
  overlapping coverage, opponent/wealth cells, and acquisition-order evidence.
- `synthetic-v2/report.json`: recovery of planted winning and losing cores.
- `trial-v1/audit.json`: independent SQL count/adjustment checks and sampled replay.

The five methods discover combinations differently. The shared gate evaluates
whether their nominees retain sufficient observed win-rate evidence on later
matches. This does not estimate what would happen if a player switched builds.
Core overlap, tactical identity, meaningful damage/ability scaling, complete
purchase paths, and contextual interventions require further work.
