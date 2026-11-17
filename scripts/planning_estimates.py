#!/usr/bin/env python3
"""Reproducible planning arithmetic; no measured benchmarks or live prices."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]
work_packages = [(5,9),(10,18),(12,20),(10,18),(22,40),(18,30),(20,35),(12,22),(10,18),(18,32),(14,24),(12,24),(8,14)]
scenarios = {}
for name, units, segments, members, steps in [('pilot',8000,2500,31,169),('regional',50000,20000,51,337)]:
    state_bytes = units * members * steps * 8 * 4
    segment_output_bytes = segments * members * steps * 6 * 4
    chunk_bytes = min(units,256) * members * steps * 8 * 4
    scenarios[name] = dict(assumptions=dict(units=units,segments=segments,joint_trajectories=members,time_states=steps,state_variables=8,segment_output_variables=6,float_bytes=4,retained_runs=31),formulas=dict(state_bytes='units * joint_trajectories * time_states * state_variables * float_bytes',segment_output_bytes='segments * joint_trajectories * time_states * segment_output_variables * float_bytes'),state_raw_GiB=state_bytes/2**30,segment_output_raw_GiB=segment_output_bytes/2**30,chunk_state_raw_MiB=chunk_bytes/2**20,thirty_one_runs_state_GiB=31*state_bytes/2**30,compression_assumed=False,benchmark=False)
n_zero_failures = {str(p): math.ceil(math.log(0.05)/math.log(1-p)) for p in [0.05,0.02,0.01]}
lo, hi = map(sum,zip(*work_packages))
g0b_parts = {'WP-00':[2,3], 'WP-01':[5,8], 'WP-02':[4,6], 'WP-03':[3,5], 'WP-05':[10,16], 'WP-06':[7,12], 'WP-10':[7,12]}
g0b_lo, g0b_hi = [sum(v[i] for v in g0b_parts.values()) for i in (0,1)]
infra = {'api_tiles_USD':[50,150],'science_duty_cycle_USD':[80,350],'database_backup_USD':[60,250],'storage_egress_USD':[20,150],'observability_USD':[0,100]}
result = dict(label='Planning assumptions only, not provider quotes, not scientific acceptance thresholds',workloads=scenarios,G1_person_days_low=lo,G1_person_days_high=hi,G2_extra_person_days=[35,70],illustrative_day_rate_USD=[150,350],G1_development_cost_USD=[lo*150,hi*350],field_campaign_excluded=True,infra_scenario_monthly_USD=infra,infra_total_monthly_USD=[sum(v[0] for v in infra.values()),sum(v[1] for v in infra.values())],zero_failure_independent_binomial_trials_for_one_sided_95pct_upper_bound=n_zero_failures,binomial_assumptions='Independent identically distributed ascertained trials with zero observed failures; clustered segment counts do not satisfy this assumption')
result.update(G0b_work_package_subset=g0b_parts, G0b_person_days=[g0b_lo,g0b_hi], G0b_development_cost_USD=[g0b_lo*150,g0b_hi*350], G0b_additive_to_G1=False, G0b_scientific_output='forcing_only_water_and_recovery_abstain')
path=ROOT/'research/planning-estimates.json'
path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
