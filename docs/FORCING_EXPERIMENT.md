# Climate and CO2 regrowth comparison

This mode requires the rebuilt `cfx` executable with the reference-forcing patch.
It uses the original climate and CO2 input files. No NetCDF copying, truncation or
splitting is performed. Grid-cell splitting and Slurm submission are unchanged.

## Configure from your existing working study

Copy your current study configuration to `study-forcing.json`, retaining your
actual cluster, instruction, gridlist, output and PFT settings. Add:

```json
"forcing_experiment": {
  "reference_year": 1901,
  "start_year": 1905,
  "management_experiment": "baseline",
  "treatments": {
    "baseline": {"fix_climate": false, "fix_co2": false},
    "co2_constant": {"fix_climate": false, "fix_co2": true},
    "climate_constant": {"fix_climate": true, "fix_co2": false}
  }
},
"workspace": "./forcing-study-workspace"
```

These fields belong inside the existing JSON object. Use a NEW workspace, not the
one holding the earlier regeneration experiments. Keep `baseline` set to
`"baseline"`. `examples/study-forcing.json` is a complete illustrative example;
it contains placeholder paths and requires the same reviews as the normal example.

The selected row in your existing experiments file supplies planting density,
recruitment and residue removal for ALL THREE runs. Other rows are not run in
forcing mode. This creates three treatments, not a cross-product with the five
regeneration experiments:

| ID | Climate | CO2 |
| --- | --- | --- |
| baseline | Historical | Historical |
| co2_constant | Historical | Reference-year concentration from start_year |
| climate_constant | Reference-year daily weather from start_year | Historical |

`start_year` defaults to the cut year. It can be earlier if you intend to include
pre-cut environmental effects, or later for a delayed treatment. `reference_year`
is the year supplying weather and CO2, not necessarily the treatment start year.
For climate, the complete daily seasonal sequence is repeated; it is not a fixed
daily mean. Other input paths (including nitrogen deposition) remain unchanged.

Each treatment runs independently with `restart 0` and `save_state 0`, identical
management and existing spin-up settings. Original full forcing files remain
available for spin-up. Saved-state orchestration is not part of this mode.

## Run

Activate your Python environment, then use the existing commands:

```bash
python regrowth.py validate --study study-forcing.json --remote-checks &&
python regrowth.py prepare --study study-forcing.json &&
python regrowth.py submit --study study-forcing.json --watch &&
python regrowth.py analyze --study study-forcing.json &&
python regrowth.py plot --study study-forcing.json
```

The existing cluster partitions, resource allocation and concurrency limits apply.
Each experiment still has its simulation job and dependent collection job. Keep
`--watch` running in a persistent terminal. The final analyze/plot commands run in
that terminal after submission monitoring finishes; they are not new Slurm jobs.
Forcing-file coverage and calendar checks are performed by the model reader;
Python validates configuration and generated keyword availability when model_source
is supplied, but does not independently inspect NetCDF data.

## Results

All original validated tables and plots remain available. Additional PNG/PDF
figures are named `forcing_comparison_<biomass-variable>_<longitude>_<latitude>`
under the configured workspace's `figures` folder. Each shows:

1. The three biomass curves with descriptive treatment labels.
2. Fixed-forcing treatment minus historical baseline, in the same biomass units.

Existing difference plots also show percentage differences (undefined near zero
baseline), and the equal-site summary includes all simulated sites. By default,
individual plots cover the first ten grid cells; use analysis.plot_sites or
analysis.plot_max_sites to change that. The analysis tables include every site.
Other configured diagnostics (NPP, mortality, density, etc.) get their usual
three-treatment comparisons as well.

`results/analysis.json` and each execution manifest record the forcing design.
`results/pre_cut_comparison.csv` checks the last available year before cutting.
For experiments beginning at the cut, inspect this file for unexpected differences;
optionally enable `analysis.require_equal_precut` when that year is available.
This is an output-level check, not proof that every hidden ecosystem state matches.
If treatments start before the cut, pre-cut differences can be intentional.

Source files and input metadata must still match across treatments: the intentional
differences are instruction controls, not modified forcing files. Analysis rejects
stale executions if the requested forcing or management settings have changed.
Use a new workspace for each revised study design.

The effects are conditional: baseline minus fixed CO2 measures changing CO2 under
historical climate; baseline minus fixed climate measures changing climate under
historical CO2. They are not necessarily additive. No interaction term is claimed.

## JSON-to-instruction mapping

`examples/study.json` explicitly sets `forcing_experiment` to null (regeneration
mode). Replace null with the object shown above to enable forcing mode, or use
`examples/study-forcing.json`, which places this object at the top.

| Instruction | baseline | co2_constant | climate_constant |
| --- | --- | --- | --- |
| extend_climate | 0 | 0 | 1 |
| extend_climate_nyears | 1 | 1 | 1 |
| extend_climate_startyear | reference_year | reference_year | reference_year |
| climate_recycle_from_year | start_year | start_year | start_year |
| fixed_spinup_climate | 0 | 0 | 0 |
| fixed_co2 | 0 | 1 | 0 |
| fixed_co2_year | reference_year | reference_year | reference_year |
| fixed_co2_from_year | start_year | start_year | start_year |
| restart | 0 | 0 | 0 |
| save_state | 0 | 0 | 0 |

`validate` reports forcing.enabled and the exact instruction_settings per treatment.
`generate` writes these at the end of the flattened guess.ins and checks them by
reading it back. Each generated experiment also contains forcing-settings.json.
The original imported climate ins is preserved; inspecting that original file will
not show generated overrides. The effective generated guess.ins is what gets
copied into each runN directory by prepare.

Existing prepared jobs are immutable snapshots: changing your JSON does not update
them. Use a new workspace and prepare again, or clean inactive old executions first.

## Explicit fixing switches

The `treatments` object directly controls the generated experiments. For each entry,
`fix_climate: true` writes `extend_climate 1` with a one-year weather sequence;
`false` writes `extend_climate 0`. `fix_co2: true` writes `fixed_co2 1`;
`false` writes `fixed_co2 0`. Reference and treatment-start years still come from
`reference_year` and `start_year`. Use JSON true/false, not quoted strings or 0/1.

Names identify treatments; the switches determine their behavior and plot labels.
You can add `both_fixed` with both switches true, or remove unwanted comparisons.
Keep baseline with both switches false, and at least one comparison. Analysis
requires every configured treatment. Plot colors and labels adapt to the configured
set. If treatments is omitted, the original three-treatment design remains the
default for compatibility. Update the JSON and prepare fresh executions whenever
you change a switch; previously submitted snapshots are not rewritten.
