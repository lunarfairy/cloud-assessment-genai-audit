# rct_sim_v2 -- design analysis of the three-arm cluster-randomised AI-policy trial (version 2)

Simulation study (ADEMP) of the planned trial: 28 tutorial groups per offering, 4 strata of 7 within each offering.
J = 28: one offering, c = 6, planned analysis LMM t(22). J = 56: two offerings (8 strata nested in offering), c = 10,
planned analysis LMM t(46). Methods and all reported numbers: rct_design_methods_v2.md (generated from results/).

## Contents
- rct_sim_v2.py         design, allocation, data generation, six estimators, scenarios, sharded runner, merge, manifest
- validate_v2.py        REML vs statsmodels MixedLM (60 data sets); CR2/Bell-McCaffrey vs dense; HC1 and two-stage vs statsmodels OLS
- summarise_v2.py       tables + results/rct_design_summary_v2.json
- figures_v2.py         figures/ (PNG + PDF)
- make_methods_v2.py    rct_design_methods_v2.md
- tests/test_v2_units.py  layout equivalence with v1, allocation constraints, v1 seed keys, one legacy reproduction
- inputs/               v1 code and v1 results (used only for the J = 28 continuity checks)
- results/              rct_design_results_v2.csv (scenario x estimator), contrast_cells_long.csv (scenario x estimator x contrast),
                        scenario_manifest.csv, manifest_reconciliation.csv, type1_by_estimator.csv, power_headline.csv,
                        partial_null_results.csv, sample_size_grid.csv, analytic_mdes.csv, bias_coverage_base.csv,
                        sensitivity_summary.csv, rct_design_summary_v2.json
- validation/           reml_vs_statsmodels.csv, cr2_dense.csv, validation_summary.json
- figures/              fig_type1_by_estimator, fig_power_BvsA, fig_sensitivity_noncompliance (.png, .pdf)

## Reproduce (results do not depend on the number of shards K)
    for k in 0..K-1:  python rct_sim_v2.py --shard k --nshards K     (independent processes; OMP_NUM_THREADS=1)
    python rct_sim_v2.py --merge
    python rct_sim_v2.py --manifest
    python validate_v2.py
    python summarise_v2.py
    python figures_v2.py
    python make_methods_v2.py
Estimator labels: OLS_HC1 = OLS-HC1 ignoring clustering; LMM_z = LMM Wald z; LMM_tJc = LMM t(J-c) (planned);
CR2_tJc = CR2 with t(J-c); CR2_BM = CR2 with Bell-McCaffrey df; TwoStage_CL = Two-stage cluster-level analysis.
