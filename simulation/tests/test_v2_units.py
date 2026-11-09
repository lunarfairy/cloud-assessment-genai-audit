"""Unit checks: v1 layout equivalence at J=28, J=56 allocation constraints, v1 seed keys, one legacy reproduction, J=56 timing."""

import sys, time, numpy as np, pandas as pd
import os
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "inputs"))
import rct_sim_v2 as v2, rct_sim_v1 as v1
# layout equivalence for J=28
for al in ("equal","control_heavy"):
    st = v2.structure(28); a1, s1, Z1 = v1.layout(28, al)
    assert (v2.legacy_arms(st, al) == a1).all() and (st["stratum"] == s1).all(), al
    Z = v2.design_Z(st, v2.legacy_arms(st, al)[None])[0]; assert np.allclose(Z, Z1)
st56 = v2.structure(56); print("J56 c", st56["c"], "G", st56["G"], np.bincount(st56["stratum"]))
rng = np.random.default_rng(0); A = v2.draw_arms(st56, "equal", rng, 2000)
for o in (0,1):
    tot = np.array([np.bincount(A[r, st56["offering"]==o], minlength=3) for r in range(2000)])
    assert (tot == [10,9,9]).all()
per = np.array([[np.bincount(A[r, st56["stratum"]==g], minlength=3) for g in range(8)] for r in range(200)])
assert set(map(tuple, per.reshape(-1,3))) == {(3,2,2),(2,3,2),(2,2,3)}
# probability a given stratum gets extra A ~0.5, B ~0.25
print("P(extra A in stratum0)", (per[:,0,0]==3).mean())
Ach = v2.draw_arms(st56, "control_heavy", rng, 50); assert all((np.bincount(Ach[r], minlength=3)==[24,16,16]).all() for r in range(50))
print("tutor arms crossing example", [np.bincount(A[0, st56["tutor"]==t], minlength=3).tolist() for t in range(3)])
# seed keys equal v1 sids
orig = pd.read_csv(os.path.join(ROOT, "inputs", "rct_design_results_v1.csv"))
osids = set(orig.sid)
sc = v2.scenarios()
for s in sc:
    if s["family"] in ("base","partial_null","legacy_check"):
        assert s["seed_key"] in osids, s["seed_key"]
print("n scenarios", len(sc), pd.Series([s["family"] for s in sc]).value_counts().to_dict())
# legacy reproduction one scenario
s = [s for s in sc if s["family"]=="legacy_check"][5]
t0=time.time(); recs = v2.run_scenario(s); print("legacy secs", time.time()-t0)
r2 = pd.DataFrame(recs); o = orig[orig.sid == s["seed_key"]]
mp = {"LMM_t":"LMM_tJc","CR2_tJ6":"CR2_tJc","CL_HM":"TwoStage_CL"}
o = o.assign(estimator=o.estimator.replace(mp)).set_index("estimator"); r2 = r2.set_index("estimator")
cols = [c for c in o.columns if c in r2.columns and o[c].dtype != object and c not in ("seconds","J","c")]
print("max abs diff legacy", float((o.loc[r2.index, cols] - r2[cols]).abs().max().max()))
# timing J56
s = [s for s in sc if s["scenario_id"]=="BASE-J56-eq-icc0.05-R0.3-cv0.3-d0.3"][0]
t0=time.time(); recs = v2.run_scenario(s); print("J56 1000 reps secs", time.time()-t0)
d = pd.DataFrame(recs)[["estimator","BvsA_rej","holm_BvsA","holm_both","BvsA_df_mean","BvsA_cov","analytic_power_BvsA"]]; print(d.to_string())
