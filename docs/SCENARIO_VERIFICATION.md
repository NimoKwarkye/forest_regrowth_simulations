# Scenario implementation verification

The original 41-test regression suite passed. The expanded 51-test suite passed,
then the additional scenario coverage passed in targeted runs (15 scenario tests
in total). Checks cover climate-window mapping, independent CO2 settings, derived
input staging/archiving, PFT SLA preservation, MPI site subsets, regional analysis
and plotting, unequal area weights, forest fractions, land-use text transformation,
transition-policy completeness, stale scenarios and undeclared management changes.

A synthetic regional figure was visually inspected. Preview figures under
scenario-preview are synthetic and are not LPJ-GUESS scientific results.

No remote Slurm submission or full LPJ-GUESS simulation was run for this update.
The existing patched CFX executable is required; this update does not change C++.
The reader validates daily forcing coverage/calendar support at simulation time.
Land-use transformation supports annual numeric Lon Lat Year text tables; supply
other formats preprocessed. A small cluster pilot remains necessary.

Empty-range update: targeted tests check zero-valued summaries and figures,
unchanged simulation gridlists, automatic grouping into configured regions,
and continued rejection of mismatched or empty simulation subsets.
