# Multi-site scenario experiments

The `scenarios` interface extends existing studies. Existing CSV-only and
`forcing_experiment` configurations retain their previous behavior. Do not combine
`scenarios` with `forcing_experiment`. The examples are templates, not ready-to-run
cluster configurations: edit paths, input coverage, grid resolution, PFTs, output
columns, carbon fraction and the existing review flags for your study.

Start with `examples/study-scenarios.json` and `scenario-management.csv`. The CSV
supplies base management settings. Each scenario selects a CSV row with `base`
(default: the study's baseline). Scenario IDs identify experiments and directories.
A `sweep` expands to IDs such as `sla_1`, `sla_2`, `sla_3`, in configured value order.
The generated manifest records the effective numerical PFT values.

## Running on the cluster

```bash
python regrowth.py validate --study study-scenarios.json
python regrowth.py generate --study study-scenarios.json
python regrowth.py prepare --study study-scenarios.json
python regrowth.py submit --study study-scenarios.json --watch
python regrowth.py analyze --study study-scenarios.json
python regrowth.py plot --study study-scenarios.json
```

Submission retains the existing Slurm simulation job, scratch wrapper, MPI runN
folders and dependent collection job. Plotting follows successful collection using
the last two commands. Partition, work/archive/submission roots and concurrency
remain controlled by cluster.json. No jobs are submitted by generate or prepare.
Each scenario gets its own job; grid cells are divided across its MPI ranks.
If a scenario selects fewer sites than configured ranks, its layout becomes one
node with one rank per selected site. Review the generated submit.sh.

## Sites, regions and weights

`gridlist` remains the authoritative simulation grid. Top-level `regions` contain
longitude/latitude bounds, optional explicit `sites: [[lon,lat], ...]`, and
`weighting`. Bounds are inclusive and select cell centres. A longitude range whose
first value exceeds its second crosses the antimeridian. Regions can overlap. Empty analysis ranges are allowed.
An optional scenario `sites: "region_name"` limits that simulation's gridlist;
otherwise every gridlist cell runs. Comparison regions only affect analysis. To simulate exactly your supplied grid
points, omit scenario-level `sites`; every scenario will run the entire gridlist.
The tool then groups those simulated points by the configured ranges. If a
comparison omits `regions`, all configured regions are included automatically
(or `all` if none are configured).

A range containing no gridlist points produces a zero for each variable, treatment,
and time step in regional_summary.csv, with `sites=0`, `weight_sum=0`, and
`status=empty_region`. Mean/minimum/maximum and absolute differences are zero;
percentage differences remain blank because division by a zero baseline is
undefined. These zero trajectories are plotted. No artificial site records are
created. `analysis.json` lists empty regions and region_sites.json records them as
empty lists. Missing or failed outputs from actual simulated points still fail
validation. An explicitly selected scenario simulation subset must be nonempty.

Weighting options:

- `equal`: equal weight per sampled location.
- `cell_area`: spherical cell area, using `analysis.grid_resolution_degrees:
  [longitude_width, latitude_height]`, or a CSV specified by `analysis.cell_areas`
  with columns `longitude,latitude,area_m2`. Prefer supplied areas for irregular grids.
- `forest_area`: cell area times each output's `area_fraction_variable`. That name
  must refer to another configured output containing a dimensionless fraction in
  [0,1]. Define it for every output being aggregated, including the fraction output
  itself if included. Fractions may change with scenario and year. The denominator
  is exported as `weight_sum`; zero aggregation area fails explicitly.

A cell-area mean of forest-stand output is an area-weighted mean across locations,
not biomass per unit regional forest area. Use the matching forest/stand fraction
for forest-area weighting. Equal weighting is often appropriate for sparse samples.
The tool does not infer complete regional coverage from sparse grid points.

## Climate and CO2

```json
"climate": {"mode":"recycle", "window_start":1980,
            "window_end":2000, "apply_from":2001},
"co2": {"mode":"fixed_year", "reference_year":1901, "apply_from":2001}
```

This repeats all 21 source climate years in order beginning in simulation year
2001. The original daily forcing stays unchanged. The source window and history
must exist in all climate variables; the patched CFX reader checks completeness
and supported calendars when the simulation reads them. Python checks window
bounds and the reader's 100-year maximum. Original nitrogen deposition and other
forcings remain as supplied. They must cover the simulation period or have their
own model-supported settings configured in the source instructions.

Climate mode `historical` follows the original time series. CO2 supports
`historical`, `fixed_year`, and `fixed_ppm` (replace reference_year with `ppm`).
The ppm mode generates a two-column annual CO2 file, preserving pre-treatment
history. The original file must contain year/concentration pairs. Derived files
are copied into each execution's inputs folder and archived. Input hashes are
recorded for changed input files; the existing size/mtime provenance remains for
large shared environmental inputs.

The illustrative example deliberately applies 2000-2020 climate from 2001; this
is a prescribed counterfactual using future source years, not historical weather.
1901-1921 is early twentieth-century climate, not pre-industrial climate. The
example extends runs to 2121 using recycled climate and fixed CO2; check coverage
of every other forcing. The tool does not invent pre-industrial forcing.

## PFT sensitivity

```json
"sweep": {"parameter":"sla", "pfts":["TrBE","TrIBE"],
          "multipliers":[0.75,1.0,1.25]}
```

Use `values` instead of `multipliers` for absolute values, or specify
`pft_overrides: {"TrBE":{"sla":20,"k_latosa":5000}}` directly.
Supported bounds match the inspected model: SLA 1-1000 m2/kgC and k_latosa
100-100000. These are parser limits, not scientifically recommended ranges.
SLA is a leaf trait; k_latosa is the leaf-area/sapwood-area allometric parameter.
For SLA overrides, the generator sets ifcalcsla=0 and writes all PFT SLA values,
preserving baseline calculated values with this model's leaf-longevity formula.
This requires resolvable leaflong/leafphysiognomy or explicit SLA for every PFT.
Overrides affect spin-up and the whole simulation; changed allometry is not
injected into an incompatible saved vegetation state. Pre-treatment states may
therefore differ. Source .ins files are never edited.

## Site-specific management

A scenario's management object may override `selection`, `densities`,
`twig_removal`, `reestab`, `cut_year`, `stand`, and `management`. Density entries
must match selected PFTs in order. These profiles use the established single-cut
protocol. To run different profiles at different sites, use separate scenarios
with named site groups. Source instructions still need suitable stand/management
definitions. Changing selection changes planting eligibility, not the list of
all tree PFTs used by TREE_PFTS outputs.

## Land-use experiments

Use `mode: "landuse_change"`. This preserves original stand/management definitions,
allows external land-use/harvest inputs, uses calendar time, and does not require
one measured clear-cut or positive forest biomass at every site. Output coverage,
finite values, duplicate checks, process success and fatal-log checks remain.
This mode does not imply fire/disturbance suppression; those settings come from
your original instructions. Managed clear-cut treatments use controlled_regrowth.

`examples/study-landuse.json` illustrates historical/present fixed land use.
Supply coherent input sets with:

```json
"landuse": {
  "mode":"supplied",
  "files":{"file_lu":"inputs/land_fractions.txt"},
  "audit_confirmed":true
}
```

For `mode: "fixed_year"`, provide reference_year, apply_from, freeze_inputs and
zero_inputs. Fractions in freeze_inputs repeat the reference-year row; transition
or harvest fluxes in zero_inputs become zero from apply_from. Earlier records are
preserved. The transformation currently supports numeric annual text tables with
headers beginning `Lon Lat Year`; other formats must be supplied preprocessed.
There is no generic NetCDF or binary land-use rewriting. Every active file_lu*,
grossLUC, grossSTC and woodharv input must be explicitly frozen, zeroed or disabled
with an empty files override. The user audit covers other site-specific controls;
the tool cannot infer ecological consistency from filenames. Inspect transitions
at the switching year, especially when present-day fractions differ from history.

Land-use experiments can combine climate/CO2 settings just like any scenario.
Use matching landuse_change baselines to avoid confounding a changed stand setup
with forcing effects. Keep outputs on compatible area bases.

## Comparisons and outputs

Named comparisons specify experiments, baseline, regions, axis (`calendar_year`
or `years_since_cut`) and `vary` (allowed changed factors: climate, co2,
pft_overrides, management, landuse). Supply vary explicitly for controlled
comparisons. The default allows all five declared factors. Original instruction
snapshots and executable must match. For nonempty regions, site sets within each comparison region,
units, area bases and time coverage must match; no failed/missing sites are silently
dropped. Use separate comparison groups for disjoint site sets. Cross-site figures
also show individual locations under each treatment.

Set `component_aggregation` on each output to `sum`, `mean` or `single`; the default
is sum for compatibility. Do not sum PFT mean heights or diameters. `mean` is an
unweighted component mean, not a density-weighted mean. For explicit dry biomass:

```json
"biomass": {"kind":"dry_mass", "carbon_fraction":0.5,
            "output_unit":"kg dry matter m-2",
            "definition_reviewed":true, "definition":"Your verified definition"}
```

Use a justified carbon fraction; 0.5 in the example is illustrative. Raw model
carbon is divided by that fraction, with no factor of ten for kg dry matter/m2.
Other outputs retain their units. No stand-area conversion is inferred.

Results include timeseries.csv, regional_summary.csv, comparison_differences.csv,
site_differences.csv, selected_ages.csv and region_sites.json. `summary_ages`
(default 0,20,...,120) selects available annual records; missing ages are not
extrapolated. Analysis uses a disk-backed SQLite intermediate, then processes one
comparison region at a time. Very large regions can still require substantial
RAM for the comparison step.

Figures include all configured variables: site trajectories, regional means,
absolute/percentage differences, cross-site trajectories and sweep responses at
selected ages. A coordinate map shows region membership (without a bundled
coastline dependency). `plot_sites` or `plot_max_sites` limits individual-site
figures; regional aggregation still uses all selected sites. Colors are stable
within a plot run; sweep values use numeric colormap positions. Numeric management
comparisons use the previous palette rules. Comparisons with conflicting numeric
color requirements for a shared experiment retain stable categorical colors. Top/right spines are removed.
Plot files and a color manifest are recorded in figures/plot_scope.json. Old
figures are retained, so use that manifest to identify current outputs.

These additions are verified with synthetic fixture outputs. A small cluster pilot
is still needed to verify real land-use formats, model reader availability, PFT
behavior and physical output definitions before a large production submission.
