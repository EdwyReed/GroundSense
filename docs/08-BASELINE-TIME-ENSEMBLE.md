# 08. Baseline времени, ансамбля и recovery

**Статус:** нормативное приложение для G0b/G1. Для конкретного перехода тёплой воды оно делегирует формулы и порядок шагов в `10-FIRST-SLICE-BASELINE-CARD.md`; при конфликте по transition normative является 10. Это приложение не разрешает G2 claims о несущей способности, тяге, допустимой массе, колее или `vehicle_condition_recovery`.

## 1. Границы G0b и scientific gate

G0b — forcing series с data lineage и authenticated UI. Пока не утверждены `ApprovedParameterSet`, observed initialization, thermal/snow screen, forcing inventory/adapter, event predicate и threshold card, water state и environmental recovery имеют `abstained`, а не числовой fallback. Это не обещание physical state/recovery в первом product slice.

После approval допустим только warm, snow-free, natural-soil research baseline по card 10. Литературный parameter prior допустим с evidence level, approver, source refs, domain и sensitivity ensemble; он не создаёт параметризацию дороги. SoilGrids не измеряет дорожную насыпь и не является готовым hydraulic set.[22][65] Полная freeze–thaw functionality остаётся отдельным gate: thermal ambiguity означает abstention, не оценку промерзания.[62]

## 2. Время, forcing и bitemporal lineage

Каждый result содержит отдельно:

- `computed_at` — system time расчёта GroundSense;
- `forecast_issue_time` — выпуск выбранного forecast slice, если он есть;
- `knowledge_cutoff` — предел знания режима replay;
- `state_valid_at` и forecast valid interval — предметное время, не availability time.

До run сохраняется полный `forcing_inventory`: product, variable, units, `stepType`, member, cycle/issue, native `[start,end)`, `startStep/endStep`, `provider_available_at`, source revision, transform и target 6-hour bin. Нельзя угадывать наличие snow/ET variables или compatible steps.

Reference card принимает только complete compatible native intervals, консервативно агрегированные на 6 h: additive amounts суммируются, rates интегрируются по duration; partial intervals, precipitation disaggregation и interpolation accumulated amount запрещены. ERA5-Land `step 23→24` использует запись следующего 00 UTC как конец старого 00 UTC cycle, затем начинается новый cycle step 1.[28][37]

Bridge для каждого history interval выбирает latest eligible retained issue, целиком его покрывающий и согласованный с declared member policy. Historical/reanalysis закрывает только период до gap; forecast after reference не восполняет прошлый gap. Forecast retention начинается в WP-01. Forecast skill не заявляется без доступного issue-time archive.

Все scientific dependencies append-only и bitemporal: `valid_time` — время предмета; `recorded_at` — system time записи; `ingested_at`, `available_at`, QA/status history, supersession link и immutable revision обязательны. Decision replay допускает лишь revision, QA и parents, известные до cutoff. Поздняя QA не существует в прошлом replay. Current serving authorization применяется по текущей policy, включая historical replay.

## 3. Совместный ансамбль и missing mass

`EnsemblePolicy` заранее создаёт joint trajectory `j=(w,p,a,r)` и nominal `ω_j`, где `Σω_j=1`. Weather/forcing path, parameter draw, initial-state draw, residual draw, shared dependencies и seed derivation versioned. Trajectory weights не являются vehicle-configuration weights; неизвестные configuration weights не подменяются равными.

Failure не вызывает renormalization. Для любого event/horizon результат хранит event-specific ascertainment (§4), а не один глобальный `valid` status:

```text
W_yes(h)     = Σ ω_j · 1[A_j(h)=YES]
W_unknown(h) = Σ ω_j · 1[A_j(h)=UNKNOWN]
bounds(h)    = [W_yes(h), W_yes(h)+W_unknown(h)]
```

При `W_unknown(h)>0` точечная `probability_by_horizon=null`; `cdf_bounds`, `bounds_by_horizon`, missing-mass reasons и policy ref обязательны. `known_weight_mass` — масса, ascertained-by-horizon (`A_j(h)≠UNKNOWN`), а не масса полностью valid trajectory. Conditional value `W_yes/known_weight_mass` разрешён только с label `conditional_on_ascertained_members`; он не заменяет bounds.

## 4. Recovery: confirmation-end, recurrence, evidence

Wire token: `confirmation_end`. Если versioned predicate `C_j(t)` истинно непрерывно на `[c,c+P]`, то `T_confirm,j=c+P`. CDF — first-passage `P(T_confirm≤h)`, не current persisted condition и не время начала candidate.

Для каждого member и horizon `h`:

- `YES`, когда `T_confirm≤h`; последующий failure его не отменяет;
- `NO`, когда есть observed/computed-valid path до `h` и confirmation не произошло;
- `UNKNOWN` иначе; `last_evaluable_time` и failure reason обязательны.

Late candidate `c>H-P` при полностью valid path до `H` имеет `A(H)=NO`: confirmation-by-H не произошло. Его дальнейшая судьба неизвестна, но это не missing mass для горизонта `H`.

Persistence сбрасывает только нарушение одного predicate `C`. Если продукт требует dry interval, precipitation condition с units и threshold входит в `C`; «any wetting» как второе правило запрещено. Intervention/repair — regime boundary.

`already_recovered` обязан иметь `confirmation_basis`:

- `model_history` — eligible model history и model evidence refs;
- `field_protocol` — protocol/evidence refs, покрывающие весь persistence interval.

Первое не называется field confirmation. Разреженные adverse/favourable inspections доказывают лишь instantaneous states, не first sustained recovery.

## 5. Environmental aggregation

Каждый segment имеет versioned `SegmentSupportMapping`: analysis unit, geometry/support version и positive weight. Для полного известного набора scenarios primary environmental category выбирается в порядке: worst positive-weight trajectory → worst mapped unit → worst interval, overlapping local day. Category order и thresholds versioned/approved; здесь численные thresholds не вводятся.

Unknown required unit или required time делает primary category `unknown`. Missing category hours никогда не улучшают цвет. Отдельный known lower bound может отображаться только как secondary labelled output, не как primary category.

## 6. Научные gates и приёмка

| Gate | До разрешённого результата |
|---|---|
| Forcing-only G0b | provenance inventory, availability lineage, complete-interval policy, abstention UI |
| Warm research transition | approved card 10, parameter set, observed initialization, PASS thermal/snow screen, mass-conservation test |
| Environmental recovery | versioned `C`, `P`, threshold card, support mapping and category ordering |
| Freeze–thaw | отдельная validated thermal/heat-water card and field comparison |
| G2 | separate operation/outcome/calibration/population gates |

Минимальные tests: confirmed member remains YES after late failure; late candidate yields NO at `H`; forced unknown member expands upper bound; no missing required support may improve category; complete 6-hour forcing conservation; 23→24 adapter handoff retains the last hour; synthetic two-layer toy conserves external mass in real arithmetic. Это acceptance of semantics, не claim empirical accuracy.

## Sources

[22] https://docs.isric.org/globaldata/soilgrids — ISRIC SoilGrids documentation
[28] https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — ERA5-Land hourly data from 1950 to present
[37] https://confluence.ecmwf.int/spaces/CKB/pages/197702790/Conversion+table+for+accumulated+variables+total+precipitation+fluxes — ECMWF conversion table for accumulated variables
[62] https://www.ars.usda.gov/pacific-west-area/boise-id/northwest-watershed-research-center/docs/shaw-model — SHAW Model : USDA ARS
[65] https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html — SoilGrids layers – SoilGrids Documentation
