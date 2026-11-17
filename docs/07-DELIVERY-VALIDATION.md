# Реализация, проверка и эксплуатационная приёмка

Это план разработки и научной проверки. Сроки — сценарная оценка труда, не обещание точности через фиксированное число недель. Реальная весенняя оттепель может наступить после завершения интерфейса; исторические картинки её не заменят.

## 1. Work packages

| WP | Результат | Зависимости | Кто нужен | Труд, person-days | Приёмка |
|---|---|---|---|---:|---|
| WP-00 | источник требований, definitions/outcomes, owner approvals, field/legal constraints | нет | lead + геотехник + владелец процесса | 5–9 | согласованы date+mass, science gates, unknown и события |
| WP-01 | source registry/license review, реальный download, product-variable-step inventory, сохранение forecast issues с первого дня | WP-00 | geo/data + legal reviewer | 10–18 | metadata≠данные; фактические поля/units/steps/retention и gaps записаны; raster и weather sample обработаны |
| WP-02 | units/time/CRS normalization и replay | WP-01 | geo/data | 12–20 | scale/deaccumulation/DST fixtures и provenance, no future leakage |
| WP-03 | asset/road import, segmentation/versioning, known approaches | WP-01 | data/backend + GIS | 10–18 | quality report, missing surface, real coverage denominator |
| WP-04 | двухслойная warm/snow-free research water card, initialization и thermal applicability screen | WP-02 | scientific engineer + гидролог | 22–40 | literal closures/order, approved priors, residual/sensitivity/reference comparison; вне домена abstain |
| WP-05 | immutable runs/manifest/API/jobs, auth and RLS | WP-00, WP-02 | backend | 18–30 | crash/race/cross-tenant tests и read-back integration |
| WP-06 | карта/date+mass/unknown/series и observatory | WP-03, WP-05 | frontend + UX | 20–35 | работающий vertical slice, accessibility, E2E tests |
| WP-07 | field evidence, QA и safe inspection workflow | WP-03, WP-05 | backend/frontend + field lead | 12–22 | raw/revision/QA, no-attempt labels, private photos |
| WP-08 | warm-domain environmental recovery: exact/bounds/unavailable | WP-04 | scientific/backend | 10–18 | event-specific ascertainment, единый predicate, persistence, late-failure/bounds/horizon tests |
| WP-09 | historical/spatial holdout, ablation и shadow reporting | WP-04, WP-07, WP-08 | science + validation reviewer | 18–32 | preregistered test report, baseline comparison, failure strata |
| WP-10 | CI, deploy, quotas, security, metrics, restore drill | WP-05, WP-06 | devops + backend + QA | 14–24 | staging fail/restart/restore, no secret leakage |
| WP-11 | pilot user testing, bugfix, runbooks и handover | WP-06, WP-09, WP-10 | вся команда + заказчик | 12–24 | operational screening pilot acceptance, не G2 accuracy claim |
| WP-12 | field campaign design и protocol trial | WP-00, WP-03 | геотехник + field team | 8–14 | доступ/безопасность/процедуры; сезонная кампания оплачивается отдельно |
| WP-13 | calibrated vehicle/mechanism model и validated-domain gate | WP-07, WP-09, репрезентативные labels | geotechnical + science + независимый reviewer | 35–70 | prospec holdout/calibration/error-cost/coverage gate |

WP-13 не входит в G1 promise. Полная coupled snow/freeze–thaw модель — отдельный `G1-SnowThermal` scientific gate, вне 22–40 person-days warm WP-04; оценить её после source/parameter/initialization spike. До этого зимние/весенние frozen-state outputs unknown. Это ограничение первой версии, а не решение основной весенней проблемы. Fleet integrations, ML residuals, full SAR retrieval, CMMS и offline pack — P1/P2 после полезности. Не превращать 70 функций в требования до первого pilot.

Критический путь G1: WP00→WP01→WP02→WP04→WP08→WP09 плюс готовность полевых данных. UI и API развиваются параллельно на fixtures, но fixtures всегда маркируются. WP12 стартует до красивого интерфейса, иначе научная валидация станет поздним сюрпризом.

## 2. Этапы и решения о продолжении

### G0a: feasibility, 2–4 календарные недели как planning assumption

Малый безопасный цивильный участок без публикации чувствительных координат: реальный ограниченный download, source metadata, units/time conversion, SQLite/локальные artifacts для spike допустимы. Выбираем пилотные owner-approved approaches, проверяем SoilGrids/DEM/forecast fields, сохраняем raw manifests. Не скачиваем всю историю Sentinel на область, чтобы проверить одну гипотезу.

Выход: source→нормализованные forcing series→immutable local receipt→smoke UI с fixture/live separation; feasibility report, cost profile и field plan. Research water card приложения10 вычисляется только при допустимом parameter set/initialization/screen, иначе state/recovery abstain. Go/no-go: доступ к данным/правам, совместимые переменные/шаги, путь к independent observations. Нет field data — environmental monitoring track без обещания validated mobility.

### G0b: authenticated forcing-only implementation slice

Результат: date+mass→durable request/job→реальный normalized forcing artifact→canonical internal manifest→authorized ManifestView→карта/series. API same-origin BFF, CSRF/Origin, RLS+site scopes, no-overwrite storage и current-policy-before-304 обязательны. Water state/recovery unknown с reason codes; forcing не подменяет soil moisture. Минимальный DTO bundle/fixtures задают контракт, но backend ещё нужно реализовать.

| Часть WP | Person-days low–high | Ограниченный scope |
|---|---:|---|
| WP-00 | 2–3 | два поля, modes, workspace/grants, unknown |
| WP-01 | 5–8 | один реальный forcing adapter, inventory и retained issues |
| WP-02 | 4–6 | units/time, exact accumulation intervals, provenance |
| WP-03 | 3–5 | минимальный owner-approved реестр, не автоматический поиск подъездов |
| WP-05 | 10–16 | BFF/auth, requests/jobs, schema, immutable publication и scoped выдача |
| WP-06 | 7–12 | карта известных entities + forcing chart, unknown water/recovery |
| WP-10 | 7–12 | CI/deploy, access negatives, backups и fail-closed restore |

Машинный итог `G0b_person_days=[38,62]`; при условной ставке150–350 USD/day стоимость5,700–21,700 USD. Это **подмножество**, не добавка к G1 171–304 person-days. Calendar зависит от людей/разрешений; source queues и security integration не делятся идеально между разработчиками. G0a переиспользуется только после code/data/license review, throwaway часы отдельно не считаются повторно готовой production работой. Uploads, exports, GC executor, Prefect, TiTiler, Valkey и Zarr не prerequisites G0b. Квота/append-only и reservations обязательны даже без GC.

### G1: закрытый screening pilot

После G0b добавляются approved natural-soil parameter/initialization/thermal-screen cards, проверенный warm water transition, environmental condition/recovery, evidence/QA, осмотры, independent validation, мониторинг и restore. Диспетчер вводит два поля, видит причины unknown. G1 warm не выдаётся за проверенный снег/оттаивание; `G1-SnowThermal` отдельно добавляет эти возможности после evidence gate. Дизайн экрана может показывать будущий G1 на синтетических данных, не готовность G0b.

Календарь определяется доступными людьми, разрешениями и data integration. В work package estimate один person-day — производственный рабочий день; сверх него нужны календарные паузы провайдера, полевого доступа и сезонности. При трёх разработчиках нельзя делить весь объём ровно на три: geotechnical review и QA не взаимозаменяемы с frontend coding.

### G2: ограниченный количественный продукт

Сначала заранее фиксируем validation domain и критерии ошибки. Потом сбор и adjudication labels, обучение/калибровка, frozen holdout, проспективный shadow phase, независимый geotechnical review. Подтверждение одного грунта/дороги/машины не выдаёт сертификат на всю область.

Release decision: использовать ли outcome risk для действующего процесса при данном false-favourable ceiling и useful coverage. При failed science gate software release может состояться в screening; научный результат честно фиксируется как отрицательный.

## 3. Полевой дизайн

### 3.1 Выборка

Предлагаемый начальный sampling frame: 24–40 owner-approved контрольных участков с повторными обследованиями; это бюджетная гипотеза, не достаточный sample size для точности. Стратификация включает texture, road construction, canopy/drainage, relief, wet/dry/freeze-thaw episodes, service vehicle class. Отдельно выбираются случаи missing construction, чтобы измерить abstention; исключать их из отчёта нельзя.

Пенетрометр/CI и DCP требуют отдельного протокола; лабораторный CBR по выбранным слоям — по необходимости геотехника. Влажность, плотность, температура/снег и фактический outcome должны совпадать по времени и support. Координатная неопределённость замера учитывается; не приписывать ближайшей дороге автоматически.

Повторные визиты после дождя/оттепели нужны для recovery; заранее фиксируются периодичность и пропуски. Нельзя требовать машину ехать до застревания для получения negative labels. Используются независимые испытания и факты обычной безопасной эксплуатации с recording of interventions.

### 3.2 Единица независимости

`road/site × wet-thaw event × vehicle/operation regime`, а не каждый 50-метровый сегмент и не каждый снимок. Whole-road/asset holdout и blocked temporal split предотвращают spatial/temporal leakage. Единый шторм не находится одновременно в train/test через соседние объекты без отдельно обозначенного interpolation test.

Старые успешные рейсы имеют selection bias: диспетчер уже избегал самых плохих условий. Missing failure reports и no-attempt отличны от success. Отслеживаем policy changes, ремонты и effect of advisories: после запуска системы distribution outcomes меняется.

## 4. Метрики и preregistration

### 4.1 Physical layer

Moisture bias/MAE/RMSE по слою/сезону/материалу/поддержке, температура MAE и freeze/thaw timing error с разрешением датчиков. Source model soil moisture не служит независимой ground truth. Water mass residual, numerical stability и physical bounds — отдельные software/science checks, не skill metrics.

### 4.2 Outcome layer

На публикуемой благоприятной части считаем `false-favourable = failures among favourable assessments / independently ascertained favourable assessments`. Рядом coverage/abstention и число независимых событий. Без denominator, CI и ascertainment нельзя писать «ошибка 1%». Если автомобили только объезжают advisories, их непоездки не подтверждают корректность рекомендации.

Brier score и reliability diagrams для вероятностей, discrimination как дополнительный показатель, precision/recall по outcome и error-cost weighted loss. `lower_risk` threshold выбирается по validation set/cost policy, затем фиксируется до test. Selective-risk versus coverage curve обязательна: модель, которая всё объявляет unknown, не полезна, но может выглядеть безошибочной.

Порог false-favourable и minimum useful coverage выбирают owner+инженер на G0, до тестовой выборки. Числа ниже только объясняют объём доказательств: при нуле ошибок one-sided exact binomial upper bound зависит от числа независимых испытаний; корреляция делает наивный n сегментов недопустимым. Машинный расчёт приведён в `research/planning-estimates.json`; это статистический пример, не приёмочный показатель продукта.

### 4.3 Recovery

Проверяются event occurrence/calibration к горизонту, time-dependent calibration, interval/right censoring и persistence. MAE только на uncensored recovered cases отчётно допустим с явным selection caveat, но не основной показатель. Brier/survival metrics требуют assumptions о censoring; информативные пропуски инспекций анализируются отдельно.

Распределение unconditional event times хранит массу «не достигнуто к горизонту». Если 30% trajectories восстановились, p50 не существует в горизонте. При 60% p50 может быть, p90 — нет. Не заменять отсутствующие квантили концом горизонта.

### 4.4 Абляции

| Baseline / increment | Проверяемая гипотеза |
|---|---|
| last verified condition | даёт ли forecast добавочную ценность сверх свежего осмотра |
| rainfall/temperature-only | не избыточен ли сложный pipeline на pilot data |
| +natural soil + terrain | есть ли улучшение для сравнимых объектов/эпизодов |
| +road structure/drainage | уменьшается ли false-favourable и abstention |
| +snow/thermal state | улучшение thaw-specific timing и ошибки |
| +EO без assimilation | добавочная ценность валидного SAR/оптики как evidence |
| +assimilation | улучшение по independent field measurements при тех же inputs |
| +ML residual | holdout skill, calibration, domain stability, compute cost |

Сравнение должно использовать одинаковые cutoff, sampling frame и test cases; нельзя дать полной модели свежие observations, а baseline — вчерашние. Высокая feature importance SAR не доказывает causal benefit или честную predictive gain.

## 5. Тестовая матрица реализации

### 5.1 Unit/property/scientific

- tonnes↔kg; SoilGrids scales; fractions sum; gravimetric vs volumetric units; nodata/NaN detection.
- ERA5-Land accumulation reset, missing hour, следующий 00UTC, DST 23/25-hour local day; не смешивать ERA5 step semantics.
- SWE>=0, water-equivalent conservation, overflow→runoff/storage, stable time-step refinement; freeze branch не создаёт воду.
- Soil source depth remapping сохраняет integral для water storage и отмечает imputation; classification не bilinear.
- P10≤P50≤P90 при наличии; depth and support в результате сохраняются.
- Recovery: all/none/some reach, известные nominal weights, exact/partial/unavailable, event retained после позднего failure, поздний candidate с полной trajectory, predicate reset, already-recovered basis, неизвестные configuration weights отдельно.
- Fixed configuration mass increase не улучшает load margin при неизменных physics; неизвестный envelope не становится благоприятным.
- Quantitative mobility запрещён в screening и climatology; unknown risk=null.

### 5.2 Integration/contract

- Provider fixtures отдельно от сетевых tests; real limited source sample обязателен для каждого adapter до pilot.
- Retry/idempotent upsert; same Idempotency-Key+different body→409; worker crash/lease expiry; cancellation before/after publish.
- Умерший worker со старым fencing token не публикует; rejected model gate не обходится прямым API.
- S3/object checksum mismatch, expired credentials, DB rollback, orphan cleanup; readers не видят partial manifest.
- Reanalysis revision и late-arriving observation не утекли в operational as-of backtest.
- Cross-tenant FK/RLS/cache/tile/exports; missing tenant context; wrong audience/issuer, stale token; private bytes не попадают в public CDN.
- Archive traversal/symlink/bomb, image pixel bomb, MIME spoof, CSV formula injection в export, SSRF redirect/private IP.
- Offline pack expiry и unsigned/corrupted manifest; у downloaded files нет обещания remote revocation.
- Browser BFF/HttpOnly cookie/CSRF/Origin; ManifestView не раскрывает чужие site metadata/locators; full report требует полного scope.
- Canonical RFC8785 vectors, manifest/assessment hash DAG, filesystem EEXIST/crash/fsync; cursor scope revision и representation-specific ETag/If-Range.
- Restore старого snapshot после grant revoke/model withdrawal/photo deletion: новый policy epoch, invalidated sessions/cursors/leases, scopes закрыты до reconciliation/reattestation.

### 5.3 UI/E2E

Playwright: date/mass validation, stale run survives as historical, partial layer hatching, date beyond horizon label, model-withdrawn state, opening inspection doesn't dispatch it automatically, empty/slow/error states, chart table/keyboard/screen-reader alternatives. Screenshots фиксируют fixture+manifest+screen size; они не доказывают scientific correctness.

### 5.4 Performance и resilience

Замерить на реальном deployment: first map interactive, tile/cache latency, 10/50 concurrent users, maximum supported AOI, worker chunk memory, parallel ingestion cancellation, p95 job time. Отчёт содержит dataset size, CPU/RAM, software versions, cache warm/cold. Synthetic sizing ниже — не benchmark и не замена этим tests.

## 6. Workload, хранение и бюджет

`research/planning-estimates.json` вычисляется `scripts/planning_estimates.py` из следующих допущений: pilot 8,000 hydro units, 2,500 segments, 31 total joint trajectories, 169 hourly states, 8 float32 state variables; regional scenario 50,000 units, 20,000 segments, 51 trajectories, 337 states. Это только сценарии sizing. Geographic coverage и эффективная независимость числами не задаются.

Forecast state хранится для воспроизводимости согласно retention tier; не обязательно сериализовать всё для каждого segment/weight. Segment series могут быть thin references на analysis unit + road modifiers. Сначала spatial chunks≈256 units и streaming summaries, затем профилирование. Dask включается только при доказанном spill/throughput ограничении.

Пример deployment pilot: 8–16 vCPU worker, 32–64GiB RAM, отдельный API/tiles 4–8vCPU/8–16GiB и PostgreSQL 4vCPU/16GiB с SSD. Это capacity hypothesis, а не необходимый минимум или проверенный SLA. Для G0 достаточно меньшей машины и ограниченного среза.

Смета разработки вычисляется по low/high person-days и явной условной ставке 150–350 USD/day, не market survey. Полевые работы/датчики/транспорт/безопасный доступ/лаборатория и юридическая проверка задаются отдельным quote-based бюджетом; стоимость разработчиков не скрывает стоимость field campaign.

Инфраструктура считается из itemized сценарных цен: API+tiles, science worker duty cycle, DB/backups, storage/egress, observability. Price inputs — предположения для чувствительности, не предложения конкретного хостера. При выборе провайдера заменить на действующие тарифы с датой, валютой/налогами и egress region. Пример результатов помещён в JSON; source data rights отдельно.

## 7. Runbooks и incident policy

| Ситуация | Действие | Запрещено |
|---|---|---|
| forecast provider задержан | сохранить last-good issue, показать lag/expiry, approved fallback и новый run | смешать циклы/модели без provenance |
| SoilGrids endpoint down | использовать проверенные retained assets; backoff; не имитировать данные | взять первый найденный raster с неизвестными units/license |
| SAR QC failed | missing observation; hydrothermal-only mode при допустимости | считать cloud/frozen invalid «сухо» |
| scientific residual плохой | quarantine run; inspection of units/time; сохранить last-good как historical | silently clip состояние и publish |
| field evidence correction | новая revision, downstream invalidation, audit | менять старый observation на месте |
| false favourable incident | freeze affected domain, withdraw eligibility, preserve evidence, owner notification | удалять ошибочный прогноз или называть его исключением без анализа |
| storage/DB outage | private fail-closed; restore/интегритет; новый policy epoch и reconciliation grants/withdrawals/tombstones до reopening ADR-11 | вернуть старый approved grant; запускать latest из object listing |
| data privacy incident | revoke access, evidence handling, legal process, audit; evaluate exports/backups | обещать remote delete уже скачанных файлов |

Эксплуатационный отчёт: freshness per product, failed QC, unknown coverage, model domain changes, run latency/cost, storage growth, outcome incidents и restore date. Изменение thresholds или vehicle-envelope требует новой версии и сравнения с прежней. Notification об изменении оценки содержит точный manifest, не ссылку на бесконечно меняющийся «latest».

## 8. Definition of Done

G1 готов только если работает реальный source→normalization→science→published manifest→authenticated map/series вертикальный путь на declared pilot data, пройдены security/contract/resilience checks, проведён restore, пользователи понимают unknown, полевые данные не подменены fixtures и отсутствуют скрытые механические обещания.

G2 требует отдельного подписанного validation report и evidence на независимых данных. Demo screenshot, успешный JSON schema check, HTTP 200 upstream и отзыв внешней LLM-панели не заменяют этот gate.
