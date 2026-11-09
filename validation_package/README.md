# Grader verification

Install the repository requirements first. The default original grader is
`../graders/v1.0`; `GV_AUDIT` can override it. Run these commands from this directory:

```sh
python run_mutation_tests.py --verify --jobs 4
python run_cases.py --checker-dir ../graders/v1.1 --tag v11final --jobs 4
python probe_v11.py v11
```

`mutants/` holds the catalogued mutants and the supplementary targeted APP case.
`cases/` holds alternative valid solutions, adversarial cases and targeted probes.
Expected outputs and stored results are included for the grader versions.

To reconstruct the intermediate patched copies used in the historical validation:

```sh
python make_patched_copy.py
```

The complete historical pipeline is `python run_all.py --runs ../data/runs/model_runs`.
It writes new results into this directory and generates `patched_copy/`.
Use a separate working copy when comparing with the stored results.
The LLM-assisted natural-output audit is represented by stored inputs and outputs;
it is not rerun by the offline verification commands.

The original v1.0 APP test A09 is host-dependent for implementations using
`os.path.basename`; its stored grades were produced on Windows. The primary
v1.1 grader tests the POSIX path semantics of the target Linux environment.
