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
