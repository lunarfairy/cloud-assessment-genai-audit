# GenAI capability audit of cloud assessments

Code, stored model responses and simulation results for a static audit of a
four-stage cloud computing assessment and the design of an AI-policy trial.
The classroom trial has not been conducted.

## Install

Python 3.11.16. From this directory:

```sh
python -m pip install -r requirements.txt
```

`cfn-lint==1.59.0` must be on PATH for regrading. On Windows PowerShell, set
`$env:PYTHONUTF8="1"` before running the commands so child processes also use UTF-8.

## Reproduce reported outputs

```sh
python reproduce_and_diff.py --keep
python simulation/figures_v2.py
```

The first command rebuilds audit trajectories, statistics, tables and six figures
from `data/`, and compares them with `results/`, `tables/` and `figures/`.
It prints the directory containing the rebuilt outputs. The second command
regenerates three simulation figures from `simulation/results/`.
Neither command makes model API calls or reruns the full design simulation.

Optional stored-response regrading and simulation implementation checks:

```sh
python reproduce_and_diff.py --regrade-sample 60 --keep
python simulation/tests/test_v2_units.py
python simulation/validate_v2.py
```

The default output comparison checks numerical files and table fragments after
normalising line endings. Figure comparisons in that script check file presence
and PNG dimensions; plotted values come from the regenerated numerical outputs.

## Layout

- `analysis/`: audit analysis, table generation and plotting.
- `data/`: stored responses, grades, judge scores, final trajectories and analysis inputs.
- `graders/`: original v1.0, pre-release v1.1a, corrected primary v1.1 and tier-2 sensitivity graders; briefs and reference solutions.
- `validation_package/`: mutants, alternative solutions, adversarial cases and verification scripts.
- `simulation/`: trial-design generator, estimators, tests, stored results and plotting.
- `results/`, `tables/`, `figures/`: reported audit outputs, including `numbers.tex`.

See `simulation/README.md` to rerun the full simulation. That optional run uses
542 scenarios and 720,000 simulated trials; results are independent of shard count.
See `validation_package/README.md` for grader verification.

## Data source

Assessment briefs re-specify the course in Zarnegar, Ofoghi and Chua,
*Head in the Clouds, Feet on the Ground: Integrating Industry Cloud Curriculum
with Project-Based Learning*, https://doi.org/10.1145/3844724.
Student-challenge counts are aggregated values reported in that paper.
The stored responses are model-generated; trial-design data are synthetic.

## License

[MIT](LICENSE).
