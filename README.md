# LPJ-GUESS regrowth experiments

A cluster-local Python controller for single-clear-cut experiments with global PFTs.
It retains the supplied Slurm/MPI pattern: one simulation job per experiment,
`runN` directories containing balanced gridlist chunks, per-rank scratch execution,
and a dependent finish-up job. No SSH service is needed.

**Status:** implemented and locally tested. No new LPJ-GUESS simulation or Slurm
job has been run. The single-cut protocol and deployed executable must pass a
cluster pilot before scientific use. See [verification](docs/VERIFICATION.md).

## Installation on the cluster

Copy this project to a stable shared directory visible to compute nodes.
Use Python 3.10 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python regrowth.py --help
python -m unittest discover -s tests -v
```

Core generation, collection and scheduler control use the Python standard library.
PyYAML enables YAML configurations; Matplotlib generates PNG/PDF figures. JSON is
supported without PyYAML. The examples use JSON so their structure is unambiguous.
Bash, rsync, sbatch, srun, sacct, and scancel must be available on the cluster.

## Configure a study

Copy `examples/cluster.json`, `examples/study.json`, and `examples/experiments.csv`
into your study configuration directory. Relative paths resolve against the
configuration file containing them, not against your current shell directory.

Edit cluster settings:

- `executable`: the deployed model binary or symlink.
- `python`: absolute path to the cluster virtual environment's Python executable.
- `partition`, `finish_partition`: cluster-specific partitions, independently selectable.
- `nodes`, `processes_per_node`: number of MPI simulation processes is their product.
- `finish_tasks`: requested finish-up tasks and maximum concurrent file-merge workers.
- `max_active`: maximum simultaneously active experiment pipelines in this study.
- `walltime`, `finish_walltime`; optional `account`, `qos`, and `memory`.
- `environment`: trusted Bash setup lines, e.g. the exact module loads required by
  your executable. These execute in both simulation and collection batch jobs.
- `submission_root`, `work_root`, `archive_root`: optional absolute shared paths; omitted values are inferred as described below.

`reference_helpers` records the original helper locations for documentation only.
The tool uses its own tested templates/collector, not those mutable shared scripts.

Edit study settings:

- `main_ins`, `gridlist`, and `model_source`: paths to your instruction setup,
  sites and compatible model source. The model source checks generated parameter names;
  it does not prove that a binary was built from that source.
- `workspace`: durable controller database, generated configurations, analysis and figures.
- `selection`: global tree PFTs to plant. **BNE is a development example, not a
  site recommendation or an exact species.**
- `cut_year`, `first_year`, `last_year`: development defaults are 1905 and 1901–2020.
  Omit first/last years to inherit them from the supplied instructions.
- `killgrass_at_cc`: defaults to 0; held fixed in the comparison table.
- `outputs`: exact keywords, filenames, columns, units and area definitions.

Climate, CO2, deposition, soils and land cover remain in your supplied `.ins`
files. No fixed-climate scenario is substituted. Keep environmental inputs unchanged
while comparing the five treatments.

The example includes review fields required before submission:

- `disturbance_audit_confirmed`: check storm, insect and external disturbance settings.
- `landcover_audit_confirmed`: verify the forest exists at the cut year, persists
  throughout recovery, and the land-cover input covers or validly extends across the period.
- `executable_compatibility_confirmed`: check the binary supports these input/output keywords.
- `biomass.definition_reviewed` and `biomass.definition`: document actual output semantics.

These are scientific/configuration declarations, not an interactive permission flow.
Do not set them true merely to bypass a failed check. Generation and dry runs work
before these reviews are complete.

## First run

```bash
python regrowth.py validate --study /path/to/study.json
python regrowth.py generate --study /path/to/study.json
```

Review `generated/<experiment>/guess.ins`, `changes.txt`, and `manifest.json`.
The import graph is flattened in order into a self-contained instruction file;
original imported files are kept under `source/`. Relative environmental file
paths are resolved against the file containing them. Verify this matches your setup.
The generator replaces the target management and stand definitions deliberately;
all before/after settings are recorded. It does not change PFT physiology.

The target stand must already reference the configured management and must be the
only active FOREST stand. Management rotations and external cutting overrides are
rejected. Other land-cover types are not silently removed.

For a one-site pilot, request one node and one process per node. Then:

```bash
python regrowth.py validate --study /path/to/study.json --remote-checks
python regrowth.py prepare --study /path/to/study.json --experiments baseline
python regrowth.py submit --study /path/to/study.json --experiments baseline --dry-run
python regrowth.py submit --study /path/to/study.json --experiments baseline
python regrowth.py status --study /path/to/study.json --refresh
```

`prepare` stages files and generates scripts but never submits. Submission is always
explicit. Paths in locally generated Windows development runs are not cluster paths;
generate and prepare again on the cluster using its configuration.

## Five comparisons

| ID | Density per selected PFT (seedlings/ha) | Re-establishment | Twig removal |
|---|---:|---|---:|
| baseline | 2000 | NONE | 0.4 |
| density_low | 1000 | NONE | 0.4 |
| density_high | 3000 | NONE | 0.4 |
| recruitment_all | 2000 | ALL | 0.4 |
| twig_retained | 2000 | NONE | 0.0 |

Values are illustrative, not calibrated. For several selected PFTs, provide a
space-separated density for each PFT in selection order. Densities are **per PFT**,
not an implicitly divided total. `twig_retained` retains twigs/branches relative to
the baseline; it does not automatically retain all wood, stumps or other residues.

All scenarios use explicit planting and the same first-year cut. `reestab ALL`
allows other eligible natural PFTs to recruit later; `NONE` suppresses subsequent
tree recruitment but does not disable mortality.

## Multi-site production

Supply a gridlist with longitude and latitude first on each record; optional trailing
fields are preserved. Empty lines and `!`/`#` comment lines are ignored. Duplicate
coordinates and process counts exceeding site counts are rejected.

The splitter uses contiguous balanced chunks: the first remainder processes get one
extra site. `nodes * processes_per_node`, run-folder count and MPI rank mapping agree.
Adjust resource counts before preparing production executions.

```bash
python regrowth.py prepare --study /path/to/production.json
python regrowth.py submit --study /path/to/production.json --watch --poll-seconds 60
```

`--watch` refreshes Slurm state and refills available experiment slots until selected
executions finish. Run it in a cluster-approved persistent session or controller job.
Without `--watch`, submission fills currently available slots and leaves remaining
prepared experiments deferred; invoke submission again after refreshing status.
Already submitted simulation/finish-up jobs do not depend on the controller remaining
alive. Interrupting the controller does not cancel them. Unknown submission outcomes
are never automatically retried.

## Results and plotting

The dependent finish-up job automatically merges, validates, compresses and archives
results. There is no custom `postproc.sh`. It marks completion only after checks pass.

```bash
python regrowth.py status --study /path/to/study.json --refresh
python regrowth.py analyze --study /path/to/study.json
python regrowth.py plot --study /path/to/study.json
```

Analysis requires complete validated executions and includes the baseline. It uses
the latest completed execution per selected experiment and rejects incompatible
sites, periods, executables, source instruction snapshots and output definitions.
Analysis streams the tables and uses a temporary disk database for comparison totals.

Outputs:

- `results/timeseries.csv`: PFT/column series and explicitly identified `__sum__` series.
- `results/differences.csv`: baseline differences; percentages omitted near zero.
- `results/site_summary.csv`: equally weighted site means and spatial ranges.
- `results/analysis.json`: execution provenance and conventions.
- `figures/*.png` and `*.pdf`: biomass, diagnostics, composition and differences.
- `figures/plot_scope.json`: exactly which sites were plotted.

By default individual plots show the first 10 gridlist sites, avoiding thousands of
figures. Set `analysis.plot_max_sites` or `analysis.plot_sites: [[lon, lat], ...]`.
Multi-site summaries always include every validated site. Spatial ranges are not
confidence intervals, and means are not land-area weighted.

Year zero is the cutting year's **year-end** output. It is not an instantaneous
post-harvest measurement. No theoretical growth curve is fitted automatically.

## Aboveground biomass conventions

The example requests `file_agb_gridcell`, sums the enabled model TREE PFT columns
(`values: "TREE_PFTS"`), and excludes grasses. Global shrub types represented with
`lifeform tree` are included; call this woody-PFT biomass if that distinction matters.
Other diagnostics use the Forest stand-type column where available.

Grid-cell aboveground output includes area weighting. If natural forest or other
wooded stands coexist with the treatment, it is not treatment-only biomass. For
isolated treatment curves, use sites with the intended forest fraction (the reference
uses 100% FOREST), or supply a suitable output/normalization definition. This tool
does not invent a forest-area correction.

The inspected source uses `0.78 * (leaf carbon + wood carbon)` in its common aboveground
output. The deployed binary's formula still needs verification. The default label is
carbon (`kg C m-2`), not dry biomass. For dry biomass, set `biomass.kind: "dry_mass"`
and an explicit `carbon_fraction`; conversion is `kg C m-2 * 10 / fraction`, giving
`Mg dry matter ha-1`. Output keywords and units must match your executable.

`values` must contain additive columns when multiple are supplied. Height and diameter
examples each select just one PFT; do not sum several species' mean heights.

## Failures and recovery

See [operations](docs/OPERATIONS.md). Failed collection retains run directories and a
partial archive. No successful work is overwritten and no recursive scratch deletion
is performed. Scratch is retained for the cluster's normal cleanup policy.

A single-cut configuration is a proposed protocol until the cluster pilot verifies
one harvest event per site and no later harvest. Exact planted density, tree-size
initialization, regeneration timing, and carbon balances also need pilot inspection.

## Initial-condition comparisons

Independent full spin-ups are used in this version; compatible restart reuse is not
implemented. The inspected source calls `Stand::set_management` during stand
initialization. PFT eligibility and planting/recruitment settings can consequently
affect the ecosystem before the nominal management year. Changing recruitment may
therefore change the pre-cut soil/vegetation history as well as later recruitment.

Analysis writes `pre_cut_comparison.csv` for the year before cutting and reports
between-treatment differences. Use `analysis.require_equal_precut: true` to reject
analysis when any reported pre-cut values differ above `analysis.precut_tolerance`
(default 1e-6 in each output's units), or when pre-cut records are unavailable.
This is a diagnostic, not proof that every hidden state variable is identical.

For a causal comparison that changes only post-cut regeneration, use a carefully
verified common-state/restart or timed management-transition design. That extension
must account for stored management/PFT state and needs model-level pilot validation;
this tool does not claim to provide identical restart states automatically.

## Inferring directories on your cluster

Specify the setup directory once in `study.json`, and identify its entry instruction file:

```json
{
  "ins_directory": "/bg/data/lpj/kwarkye-n/simulations/eu_to_global/forest_regrowth/test_2",
  "main_ins": "guess.ins"
}
```

These are fields to merge into your existing study configuration. Replace `guess.ins`
with the actual entry filename. If the directory has exactly one `.ins` file,
`main_ins` can be omitted. When there are several (including imported files), the
entry filename is required. Relative `main_ins` is resolved against `ins_directory`;
without `ins_directory`, its original configuration-relative behavior is unchanged.
Other input paths, including an explicitly supplied gridlist, retain their existing
configuration-relative interpretation.

Remove `submission_root`, `work_root`, and `archive_root` from `cluster.json` to
use inference. Explicit values always override inference, including old placeholder
values, which must therefore be removed. Default results for this setup are:

- Submissions: `/bg/data/lpj/kwarkye-n/simulations/eu_to_global/forest_regrowth/test_2/submissions`
- Work: `/bg/data/lpj/work/kwarkye-n/simulations/eu_to_global/forest_regrowth/test_2`
- Archives: `/bg/data/lpj/kwarkye-n/simulations/eu_to_global/forest_regrowth/test_2/archives`
- Controller workspace, if `workspace` is omitted: `regrowth-workspace` beneath the instruction directory.

Each root receives experiment/execution subdirectories. Original instruction files
are preserved. This reproduces the data-to-work path mapping of the supplied setup
scripts; the Python tool still generates its own job scripts and does not invoke
`setup_guess.sh`. Node-local scratch behavior and Slurm task allocation are unchanged.

For another cluster layout, set `data_prefix` and `work_prefix` in `cluster.json`.
Defaults are `/bg/data/lpj` and `/bg/data/lpj/work`. Mapping uses path components,
not an unrestricted text replacement. Paths outside the data prefix or already
under the work prefix require an explicit work root. Run
`python regrowth.py validate --study study.json` to display the resolved directories
before preparing any experiments.

## Climate and CO2 experiments

The patched `cfx` model can now be used in a three-treatment forcing comparison.
Add `forcing_experiment` to a copy of your working study configuration and use a
new workspace. The tool generates historical baseline, fixed CO2, and repeated
reference-year climate runs with identical management and original input files.
See [the setup and plotting guide](docs/FORCING_EXPERIMENT.md) and
[the example configuration](examples/study-forcing.json).

## Cleaning a study

Preview cleanup (nothing is deleted):

```bash
python regrowth.py clean --study study-forcing.json
```

Delete the controller workspace and its tracked work/submission execution folders,
retaining archives:

```bash
python regrowth.py clean --study study-forcing.json --yes
```

To also remove final and partial archives, first preview that scope and then execute:

```bash
python regrowth.py clean --study study-forcing.json --include-archives
python regrowth.py clean --study study-forcing.json --include-archives --yes
```

Stop other controllers (including `submit --watch`) before cleanup. Active or
uncertain executions block cleanup; update status with `status --refresh` first
when jobs have finished. Before deletion, the command checks Slurm for recorded
job IDs and refuses to proceed if the scheduler check fails or jobs remain queued.
It does not cancel jobs. Prepared, never-submitted executions can be cleaned.

Scope is the configured controller workspace, including previous experiment IDs
recorded there, not just the currently selected experiment rows. Only verified
execution folders directly under the configured roots are removed; shared roots,
unrelated runs, original inputs, configuration and model code are protected.
Linked paths, changed roots and unverifiable/orphaned executions are rejected.
Node-local scratch is not removed. Empty experiment parents may be removed, but
submission/work/archive roots themselves are retained.

A small `.<workspace-name>-cleanup.json` receipt is retained beside the workspace.
It records ownership so retained archives can be removed later using the same
command with `--include-archives`, even after the workspace database was deleted.
Keep this receipt while those archives exist. If an old workspace was manually
removed before this feature existed, restore its database before automatic cleanup.
After successful cleanup, prepare creates a fresh controller workspace.

## Comparison plot colors

All comparison figures use one shared colormap mapping, defaulting to `jet`.
When the analyzed experiments vary only twig removal, colors are normalized by
actual twig-removal values. The same applies when only one planting-density
component varies. Uneven parameter spacing therefore produces uneven spacing
along the colormap, and equal values receive equal colors.

For mixed-factor, forcing, or other categorical comparisons, colors are sampled
at equally spaced positions in experiment configuration order. Removing baseline
from a difference panel does not change the colors of the remaining experiments.
Summary bands use their curve's color. PFT composition figures use a separate,
consistent mapping of PFT names. Top and right spines are hidden on every figure.

Override the colormap with `analysis.plot_colormap`, for example `"jet"` or
`"viridis"`. The resolved colors, normalized positions and numeric parameter values
are recorded in `figures/plot_scope.json`. Rerun only `plot` to restyle existing
validated analysis; no new model runs are needed.

Multi-site scenario studies: see [docs/scenarios.md](docs/scenarios.md), [examples/study-scenarios.json](examples/study-scenarios.json), and [examples/study-landuse.json](examples/study-landuse.json).

Rectangular forest-rich site selection and land-use preparation: see [docs/SITE_PREPARATION.md](docs/SITE_PREPARATION.md). Run python prepare_sites.py --study study.json, then use prepared-sites/study.json for the automation commands.

## Install a cluster launcher

See [installation and Git updates](docs/INSTALLATION.md). Run `python3 install.py` once
on the cluster, then use `regrowth validate --study /path/to/study.json` and
`regrowth update`. Study configurations remain outside the tool checkout.
