# Portable example files

- `cluster.json`: replace executable/Python paths and both partitions before remote use.
  Work storage is inferred using data_prefix/work_prefix; roots may be overridden.
- `study.json`: references your supplied main instructions and gridlist. BNE and
  1905 are development defaults; review them. TREE_PFTS is expanded from the active
  instruction definitions. It includes model woody types represented as trees.
- `experiments.csv`: the five requested one-factor comparisons. Mixed planting
  needs one space-separated density per selected PFT in each row.

JSON and YAML are accepted. Paths in study.json resolve relative to study.json, except relative main_ins resolves
against ins_directory when supplied;
paths in cluster.json resolve relative to cluster.json. YAML support requires PyYAML.
Use absolute cluster paths for shared inputs/executables and compute-node-visible
virtual-environment Python. No environmental input data are bundled here.

- `study-forcing.json`: three forcing treatments using the patched cfx executable; see docs/FORCING_EXPERIMENT.md.

- `study-scenarios.json`: includes `site_preparation` with six geographic search
  regions, a minimum of 50 forest-rich points per region, and gaps allowed within
  selected rectangles. Set `source_gridlist` and `source_landuse` to your cluster
  input files before preparing sites. Existing scenario and regeneration settings
  are retained; this example still uses explicit planting.

```bash
regrowth prepare-sites --study /path/to/examples/study-scenarios.json
regrowth validate --study /path/to/examples/prepared-sites/study.json
```

The generated `prepared-sites` directory is next to the source JSON by default.
Use its `study.json` for simulation commands; it points to the selected gridlist and
prepared land-use files. The selection uses FOREST >= 0.3 in 2000. Land-use years
beyond source coverage use the explicitly configured `hold_boundary` policy.
