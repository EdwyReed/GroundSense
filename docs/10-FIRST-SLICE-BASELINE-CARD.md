# 10. Карта первого среза: тёплый двухслойный water baseline

**Статус:** нормативная исследовательская reference card `warm-soil-6h/v1`; не является калиброванной моделью и не разрешает продуктовый physical output без gates ниже.

## 1. Решение о первом срезе

**G0b product slice** выпускает provenance forcing, time/availability lineage и authenticated presentation. До утверждения этой карты и конкретного `ApprovedParameterSet` он обязан вернуть `water_state=abstained` и `environmental_recovery=abstained`; не подменять это нулями, climatology или дорожной прочностью.

Эта карта задаёт исполнимый reference transition для исследования после утверждения параметров. Допустим labelled synthetic toy для арифметической проверки. Он не является доказательством параметров, точности или применимости к дороге. Полная freeze–thaw модель остаётся отдельным будущим gate, а не удалённой функцией.

Применимость: один `analysis_unit`, natural-soil profile, тёплый бесснежный режим, ровно две effective layers, фиксированный UTC шаг `Δt=6 h`. Ни один параметр ниже не получает численного default. Литературный natural-soil prior допустим только в `ApprovedParameterSet` с `approver`, `evidence_level`, source refs, domain и sensitivity ensemble; он никогда не является параметризацией дорожной одежды.[2][22][65]

## 2. Обязательные входы и отказ

До первого интервала нужны:

- `ApprovedParameterSet`: версия, digest, approver, evidence level, support/geometry, valid domain и все поля §3;
- depth-compatible observed initialization (§4), QA-approved и доступное до `knowledge_cutoff`;
- полный inventory forcing (§5), eligible native intervals и thermal/snow evidence (§6).

Инициализация через warm spin-up — отдельная будущая card; этот первый путь не требует spin-up и не может молча заменить отсутствующее наблюдение «нейтральной влажностью».

При отсутствии любого обязательного входа результат — `abstained` с одним или несколькими codes: `HYDRAULIC_CLOSURE_UNAVAILABLE`, `STATE_INITIALIZATION_UNAVAILABLE`, `CRITICAL_SOURCE_MISSING`, `FREEZE_THAW_AMBIGUOUS`, `SOURCE_STALE` либо `MODEL_NUMERICAL_FAILURE`.

## 3. Состояние, единицы и параметры

Все запасы и интегрированные потоки — `mm w.e.` на горизонтальную площадь за один шаг; все rates предварительно интегрируются на `Δt`. Все потоки неотрицательны.

Состояние в начале шага `k`: поверхностный запас `H_k`, жидкие запасы `L_1,k`, `L_2,k`. В этой warm card `S_k=I_1,k=I_2,k=0`; это разрешено **только** после успешного §6. Внешние интервальные входы: liquid precipitation `P_k`, ET demand `D_k`. Внешние потери: surface evaporation `E_H,k`, layer ET `E_1,k,E_2,k`, runoff `R_k`, bottom drainage `D_b,k`.

| Поле `ApprovedParameterSet` | Единица | Нормативное значение |
|---|---:|---|
| `dz_1,dz_2` | m | effective layer thickness; `dz_i>0` |
| `theta_por_i` | m³/m³ | porosity; `0<theta_wp_i<theta_fc_i<theta_por_i` |
| `theta_fc_i` | m³/m³ | field-capacity threshold: начало gravity drainage, не жёсткая ёмкость |
| `theta_wp_i` | m³/m³ | wilting threshold для ET availability |
| `K_in` | mm/h | infiltration-capacity rate |
| `K_12` | mm/h | downward exchange-capacity rate 1→2 |
| `K_b` | mm/h | bottom-drainage capacity rate |
| `H_max` | mm | maximum retained surface water before runoff |
| `a_H,a_1,a_2` | 1 | non-negative ET-demand weights, `a_H+a_1+a_2=1` |
| `eta_H,eta_1,eta_2` | 1 | ET efficiency/conversion factors, `0≤eta_q≤1` |

Derived storages (`mm w.e.`):

```text
L_sat,i = 1000 · dz_i · theta_por_i
L_fc,i  = 1000 · dz_i · theta_fc_i
L_wp,i  = 1000 · dz_i · theta_wp_i
A_i(L)  = min(max(L - L_wp,i, 0), L_sat,i - L_wp,i)
```

`L_sat` — physical saturation storage. `L_fc` применяется только как отдельный drainage threshold. Запрещены `clip` и неучтённый overflow.

## 4. Инициализация

`L_i,0` берётся из observation, чей depth support документированно пересекается с `[0,dz_1]` и `[dz_1,dz_1+dz_2]`; transform в `mm w.e.` и support mapping version обязательны. После transform должно быть `0≤L_i,0≤L_sat,i`. `H_0` — наблюденный/явно подтверждённый нулевой поверхностный запас; иначе initialization unavailable. Observation после cutoff, несоответствующей глубины или неизвестного support не используется.

## 5. Forcing и время

Каждый run до исполнения сохраняет immutable `forcing_inventory`: `product`, `variable`, units, `stepType`, native `[start,end)`, issue/cycle, member, `provider_available_at`, ingestion revision, transform version и выбранный 6-hour bin. `computed_at` — время расчёта GroundSense; `forecast_issue_time` — выпуск прогнозного slice; оба обязательны и не взаимозаменяемы. Eligibility для replay проверяется по `recorded_at`/`ingested_at` и, где известно, `provider_available_at≤knowledge_cutoff`.

Card принимает только общий горизонт из полных покрытых bins `[t,t+6h)`. Для каждого bin:

- additive interval amounts суммируются только по совместимым полным native intervals, точно покрывающим 6 h;
- rates интегрируются по duration только из совместимых полных intervals;
- coarser precipitation не disaggregate, partial coverage не масштабируется, accumulated precipitation не интерполируется;
- отсутствие точного покрытия любого обязательного variable делает bin unavailable и останавливает physical trajectory.

Для accumulation-since-cycle adapter хранит native `startStep/endStep`. Для ERA5-Land последний interval цикла: `step 23→24`, где `step 24` записан в следующий 00 UTC, принадлежит **старому** 00 UTC cycle; затем новый cycle начинается `step 1`. Нельзя вычитать накопления через boundary, но нельзя терять этот последний час.[28][37]

History→reference bridge выбирает для каждого прошлого interval latest eligible retained issue, полностью покрывающий interval при одной declared member policy. Historical/reanalysis разрешён только до появления покрывающего forecast gap; forecast после `reference_time` не чинит пропущенную историю. Retention forecast runs начинается в WP-01; skill archive не обещан без действительно доступного issue-time archive.

## 6. Тепловой и snow screen

Screen — versioned input, не неявный порог: `thermal_screen_version`, required variables, units, lookback duration, margins, snow-absence evidence, source revisions и rule version обязательны. Он PASS только если все требуемые проверки утверждённой card явно прошли на полном lookback и шаге: snow absence подтверждено, thermal margins выполнены, residual frozen-state evidence известно и равно «no frozen state». Любой missing/unknown residual frozen state, snow evidence, interval или margin даёт `FREEZE_THAW_AMBIGUOUS`. Эта логика не утверждает глубину промерзания и не изобретает validated temperature thresholds. `S=I=0` только при PASS. Для тепло-водной физики будущая модель может сравниваться с SHAW, но не подменяет эту card.[62]

## 7. Детерминированный transition `k→k+1`

Порядок ниже единственный. Surface evaporation расходуется **до** infiltration/runoff. Transfers происходят до layer ET. Один и тот же `L` нельзя потратить дважды.

### 7.1 Surface ET, precipitation, infiltration и runoff

```text
Q_H     = max(0, H_k)
E_H,k   = min(Q_H, eta_H · a_H · D_k)
H_a     = Q_H - E_H,k + P_k
C_in,k  = min(K_in · Δt, max(0, L_sat,1 - L_1,k))
F_k     = min(H_a, C_in,k)
H_b     = H_a - F_k
R_k     = max(0, H_b - H_max)
H_{k+1} = H_b - R_k
L_1^0   = L_1,k + F_k
L_2^0   = L_2,k
```

Это literal `min/max` closure infiltration. `H_max≥0`; равенство `H_b≤H_max` не создаёт runoff. После этого `0≤H_{k+1}≤H_max` без clipping.

### 7.2 Downward exchange и bottom drainage

```text
X_1,k   = max(0, L_1^0 - L_fc,1)
C_12,k  = min(K_12 · Δt, max(0, L_sat,2 - L_2^0))
J_1,k   = min(X_1,k, C_12,k)
L_1^1   = L_1^0 - J_1,k
L_2^1   = L_2^0 + J_1,k

X_2,k   = max(0, L_2^1 - L_fc,2)
D_b,k   = min(X_2,k, K_b · Δt)
L_2^2   = L_2^1 - D_b,k
```

`J_1` is only 1→2; capillary/upward flow не входит в эту card. `D_b` — только excess above `L_fc,2`, не default free drainage. Эти два closure literal и используют разные threshold/limits.

### 7.3 Moisture-limited layer ET

Остаток demand после surface allocation не переносится на другой component: фиксированные weights задают allocation; недоступная часть остаётся unmet demand. Для слоя `i`:

```text
D_i,k   = a_i · D_k
U_i,k   = eta_i · D_i,k
f_i,k   = 0,                              if L_sat,i = L_wp,i
          A_i(L_i^2) / (L_sat,i-L_wp,i), otherwise
E_i,k   = min(U_i,k · f_i,k, A_i(L_i^2))
```

где `L_1^2=L_1^1`, `L_2^2=L_2^2` из §7.2. Затем:

```text
L_1,k+1 = L_1^2 - E_1,k
L_2,k+1 = L_2^2 - E_2,k
```

Следовательно `E_i≤A_i≤L_i^2`; ET не может опустить запас ниже `L_wp`, а drainage и ET не тратят одну воду. FAO-56 reference ET допустим лишь как проверенный `D_k`; он не задаёт actual road evaporation.[63]

### 7.4 Инварианты и mass residual

После каждого шага обязательно: `0≤L_i,k+1≤L_sat,i`, `H_k+1≥0`, все flows finite/non-negative. External storage:

```text
B_k = H_k + L_1,k + L_2,k
ε_k = (B_k+1 - B_k) - (P_k - E_H,k - E_1,k - E_2,k - R_k - D_b,k)
```

`ε_k` считается без внутренних `F,J`. Если `|ε_k|` выше утверждённой numerical tolerance, либо нарушен invariant, output invalid: `MODEL_NUMERICAL_FAILURE`; implementation не исправляет state клиппингом.

## 8. Ensemble, recovery и aggregation

Parameter/initial-state uncertainty образует joint trajectory `j` с nominal `ω_j`, `Σω_j=1`; weights фиксируются до запуска и не являются vehicle-configuration weights. По отказу member веса не renormalize.

Для event predicate `C_j(t)` card хранит `last_evaluable_time_j` и ascertainment indicator `A_j(h)∈{YES,NO,UNKNOWN}` для каждого `h`:

- `YES`, если `T_confirm,j≤h`; сохраняется при любом последующем failure;
- `NO`, если до `h` есть observed/computed-valid path и `T_confirm,j>h`;
- `UNKNOWN` иначе.

`T_confirm` — конец первого interval длиной `P`, на котором один versioned predicate `C_j` непрерывно true. Если отсутствие дождя необходимо, precipitation criterion с units входит в `C_j`; отдельного «any wetting reset» нет. Candidate `c>H-P` при полном valid path до `H` даёт `A_j(H)=NO`, а не missing mass. First-passage CDF `P(T_confirm≤h)` отличается от текущего persisted condition после recurrence.

```text
W_yes(h)       = Σ ω_j · 1[A_j(h)=YES]
W_unknown(h)   = Σ ω_j · 1[A_j(h)=UNKNOWN]
frequency_bounds(h) = [W_yes(h), W_yes(h)+W_unknown(h)]
```

Точечная `probability_by_horizon` допустима только при `W_unknown=0`; иначе null и bounds обязательны. Поле `known_weight_mass` означает именно «масса, ascertained-by-horizon», не глобально valid trajectory: `Σω_j·1[A_j(h)≠UNKNOWN]`.

`already_recovered` требует либо `confirmation_basis=model_history` с eligible model history и refs, либо `confirmation_basis=field_protocol` с protocol/evidence refs. Первое не является field confirmation. Intervention — regime boundary.

Для environmental category required `SegmentSupportMapping` перечисляет `(segment, analysis_unit, geometry/support version, positive weight)`. Для complete known scenarios: сначала наиболее неблагоприятная category среди positive-weight trajectories, затем среди units, затем среди intervals, overlapping local day. Unknown required unit/time делает primary category `unknown`; missing hours никогда не улучшают цвет. Threshold card и category ordering versioned/approved; эта карта их численно не придумывает.

## 9. Bitemporal provenance и gates

Все inputs, transforms, parameter/card/policy revisions и fitted artifacts append-only: `valid_time` описывает предметное время, `recorded_at` — system time; supersession не удаляет прошлую revision. As-of replay включает лишь revisions и QA, известные на cutoff; serving authorization всегда current, даже при historical replay.

Research execution разрешён только после approval: `ApprovedParameterSet`, thermal/snow screen, observed-initialization mapping, forcing inventory/adapter, event predicate and threshold card. До каждого approval G0b остаётся forcing-only with abstention. Freeze–thaw, physical road state, bearing/traction/rutting и field-calibrated recovery остаются за отдельными gates.

## Sources

[2] https://www.fhwa.dot.gov/engineering/geotech/pubs/05037/05b.cfm — Geotechnical Engineering Circular No. 5, Chapter 5
[22] https://docs.isric.org/globaldata/soilgrids — ISRIC SoilGrids documentation
[28] https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — ERA5-Land hourly data from 1950 to present
[37] https://confluence.ecmwf.int/spaces/CKB/pages/197702790/Conversion+table+for+accumulated+variables+total+precipitation+fluxes — ECMWF conversion table for accumulated variables
[62] https://www.ars.usda.gov/pacific-west-area/boise-id/northwest-watershed-research-center/docs/shaw-model — SHAW Model : USDA ARS
[63] https://www.fao.org/4/x0490e/x0490e06.htm — Chapter 2 - FAO Penman-Monteith equation
[65] https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html — SoilGrids layers – SoilGrids Documentation
