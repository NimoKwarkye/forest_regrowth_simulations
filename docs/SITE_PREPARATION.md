# Rectangular forest-site preparation

Run from the tool directory:

```bash
python prepare_sites.py --study study.json
```

The root study.json is the source configuration for this preparation step.
It contains six broad geographic climate search strata under site_preparation.zones.
The generated prepared-sites/study.json is the configuration to pass to regrowth.py.
The original gridlist, land-use data and source instructions are not modified.

On the cluster, set the two source paths in study.json to the cluster copies, or use:

```bash
python prepare_sites.py --study study.json \
  --source-gridlist /your/cluster/gridlist_hurtt_RNDM_midpoint_S0_state_ok.txt \
  --source-landuse /your/cluster/net_lu_hilda_global.txt
python regrowth.py validate --study prepared-sites/study.json
python regrowth.py generate --study prepared-sites/study.json
python regrowth.py prepare --study prepared-sites/study.json
```

No preparation command submits a job. The Python preparation script uses only the
standard library and bundled lpjregrowth modules. It scans the large land-use file
twice, retaining reference-year candidates and then only selected-site histories.

## Selection

Current controls in site_preparation:

```json
"reference_year": 2000,
"minimum_forest_fraction": 0.3,
"selection_mode": "rectangle_minimum_points",
"minimum_points_per_zone": 50,
"grid_resolution_degrees": [0.5, 0.5]
```

Each zone gets a grid-aligned rectangle containing at least 50 eligible points.
Gaps are allowed where points are absent or below the forest threshold. All eligible
points within the chosen rectangle are retained, so the total can exceed 300.
Selection first minimizes rectangle area (grid slots), then aspect ratio, then
maximizes mean FOREST fraction. Remaining ties favor more points, then coordinates.
The supplied inputs yield exactly 50 points per region, or 300 in total.

Coordinates cannot be reused across zones. A zone with fewer than 50 eligible points
fails with a message to expand search bounds or lower the threshold. This is separate
from the analysis feature that zero-fills empty comparison regions.

The older selection_mode="complete_rectangle" is also supported, with
rectangle_shape=[rows, columns]; it requires every cell in the block to qualify.

Selection on FOREST favors forest-rich locations; these clusters are not random
or statistically representative samples of an entire climate zone. FOREST is the
actual column in the supplied LPJ-GUESS input, not FOREST+NATURAL. That land-cover
category need not equal independently observed total tree cover.

The labels Amazon, southeastern US, central Europe, Scandinavia, Iberia and southern
Chile are broad geographic climate strata. No per-pixel climate classification was
used: downloading the published climate grid failed. In particular, Iberia includes
Atlantic/Mediterranean transitions and central Europe includes elevation effects.
For formal climate-class attribution, use a climate classification grid or derive
classes from climate variables. The [Kottek et al. classification source](https://koeppen-geiger.vu-wien.ac.at/present.htm)
describes the separate 0.5-degree, 1951-2000 climate classification product.

## Generated files

- gridlist.txt: all selected simulation coordinates (300 points in the supplied run).
- zones/*.txt: the 50 coordinates in each cluster.
- rectangles.json: cell-edge bounds and the original forest fraction statistics.
- selected_sites.csv: coordinates, source FOREST fractions and zone names.
- cell_areas.csv: full spherical grid-cell areas in m2, for regional weights; no
  ocean/land-mask area correction is inferred.
- landuse_forest1.txt: FOREST=1 and every other land-cover fraction=0.
- landuse_dynamic.txt: source fractions at the selected sites, with the explicit
  extension policy below.
- extended_years.csv: exact simulation-year/source-year mapping outside coverage.
- selection_report.json: inputs, selection settings, counts and coverage metadata.
- study.json: companion automation configuration with selected zones and input paths.

The generated region definitions include the rectangle bounds AND explicit sites.
This retains exact membership and lets the existing plotting code group the blocks.
The input example enables zone_management to create independent scenarios per zone.
The current study uses regeneration="natural": no assumed regional PFT pairs are
planted. It writes planting_system="", selection="", set_planting_density=0,
reestab="ALL", relaxed_establishment=0, and naturalveg="all". The model admits
included natural PFTs and determines establishment and persistence through its
bioclimatic limits, growth, competition and mortality. It does not infer observed
species composition. Source include flags still determine the available PFT pool.

In this model version, the first establishment after clear-cutting uses special
forestry rules: temperature limits remain enforced, but some other establishment
filters are bypassed that year. Subsequent recruitment uses the usual rules.
Thus this is the model's unrestricted post-cut regeneration, not a guarantee of
strictly unmanaged seed dispersal or actual local composition.

Density comparisons have been removed from the active study because fixed planting
density is disabled in natural mode. Legacy CSV density values are unused in this
mode. Set regeneration="planted" and supply reviewed selections and densities for
separate planting experiments. Allometry sweeps use NATURAL_TREE_PFTS, resolved from
the included natural tree definitions in the source instructions. They modify all
such tree PFTs together. The current study expands to 72 experiments (12 per zone).
Landuse_change preserves source management and rejects a natural regeneration
override; it requires its own explicit management design.

## Simulation years and land use

The supplied land-use file covers 1800-2020. The configured simulation is 1901-2121.
With include_source_history=true, both generated files include 1800-2121 so that
source history before firsthistyear remains available for initialization/spin-up.

outside_source_years="hold_boundary" explicitly repeats the nearest boundary-year
fractions beyond input coverage. In this example, 2021-2121 repeat 2020. This is an
assumption of unchanged future land use, not a land-use projection. Choose "error"
to prohibit extending the source period. Internal missing years always fail.

The companion prepared_landuse mapping is honored by instruction generation:

- controlled_regrowth (climate, CO2, allometry and managed-regrowth experiments)
  uses landuse_forest1.txt. External sub-land-cover, gross-transition and wood-harvest
  inputs are disabled to prevent them from contradicting the all-forest experiment.
  The generated single-cut management still operates.
- landuse_change uses landuse_dynamic.txt and preserves the existing stand definitions.
  An explicit scenario landuse.files override takes precedence; fixed_year land-use
  transformations use the prepared dynamic file when not explicitly overridden.

Derived inputs are copied into each execution and archived, as with earlier forcing
products. Other supplied forcings, such as nitrogen deposition, still need valid
coverage or their own model extension controls through the requested end year.

The generated grid and land-use files are checked for unique points, region membership,
and FOREST=1 with all other fractions zero. The supplied run contains 96,600 site-year
records in each land-use file (1800-2121). Focused tests cover selection with gaps,
minimum counts, dates, fractions, input staging and regressions. No simulation or
Slurm job was run. prepared-sites/clusters.png shows the actual selected points and
their source-year forest fractions.
