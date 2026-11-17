# Данные, API и контракты GroundSense

Редакция после второго ревью; wire contract 1.1. Первичная публикация scientific bytes не включает динамическую актуальную eligibility; она проверяется ServingEnvelope согласно `09-SECURITY-PUBLICATION-ADR.md`. Нормативный контекст: `../GROUNDSENSE-SPEC.md`. Идентификаторы примеров вымышленные, UUID не указывают реальные объекты. Общие schema examples находятся в `contracts/`; наличие этих файлов не означает реализацию endpoint. G0b возвращает normalized forcing и явно abstained water/recovery, не физический прогноз грунта.

## 1. Термины состояния

Состояние результата не кодируется одним цветом:

- `publication_status`: draft | published | withdrawn. Публикуется один immutable manifest; withdrawal не переписывает первоначальный расчёт.
- `assessment_mode`: reconstruction | forecast | climatology. Climatology не возвращает vehicle recovery window.
- `assessment_level`: screening | validated_domain. Research experiments не попадают в public-serving API.
- `completeness`: complete | partial | unavailable.
- `freshness`: current | stale | expired. Это derived access policy, а не изменение старых scientific bytes.
- `environmental_condition`: less_adverse | adverse | severe | unknown. Описательные screening категории по versioned policy; это не вероятности застревания. У unknown обязательны собственные `environmental_condition.reason_codes`. Известная категория требует condition policy и physical series refs.
- `mobility_status`: lower_risk | elevated_risk | high_risk | unknown. Только validated-domain модель может публиковать первые три. Unknown имеет `risk=null`; null не превращается в 0 при SQL/JS serialization.

Основные reason codes: `MODEL_NOT_VALIDATED`, `INSUFFICIENT_FIELD_EVIDENCE`, `ROAD_STRUCTURE_UNKNOWN`, `VEHICLE_ENVELOPE_UNSUPPORTED`, `FORECAST_HORIZON_EXCEEDED`, `ENSEMBLE_INSUFFICIENT`, `FREEZE_THAW_AMBIGUOUS`, `CRITICAL_SOURCE_MISSING`, `SOURCE_STALE`, `OUT_OF_DOMAIN`, `ACCESS_CONSTRAINT_UNRESOLVED`, `REQUIRES_REPAIR`, `MODEL_WITHDRAWN`, `ASSET_ACCESS_UNVERIFIED`, `HYDRAULIC_CLOSURE_UNAVAILABLE`, `STATE_INITIALIZATION_UNAVAILABLE`, `MODEL_NUMERICAL_FAILURE`. Полный нормативный enum — в wire schema; не дописывать значения без версии.

Reason code — стабильный API token. Украинский/русский текст выдаёт UI dictionary. Не сравнивать бизнес-логику по локализованному сообщению. Новые enum values требуют версии контракта или documented tolerant-reader policy.

## 2. Основные сущности

### 2.1 Справочники и геометрии

| Сущность | Минимум полей | Инварианты |
|---|---|---|
| Tenant | id, legal_name, retention_policy_id | id из verified session, не browser payload |
| Workspace | tenant_id, id, aoi_version_id, timezone, default_mass_policy_id | IANA timezone; region как versioned AOI geometry |
| Asset | tenant_id, id, external_id, type, name, geometry, source_ref, version, active_from/to | unique tenant+source+external_id; private coordinates |
| RoadNetworkVersion | id, geometry_hash, source_snapshot_ids, CRS, imported_at | immutable, source policy и license |
| RoadSegmentVersion | tenant_id, id, stable_feature_id, network_version, geometry, length_m, coverage_metadata | no zero length/invalid geometry; splits/merges explicit |
| ApproachVersion | id, asset_version_id, ordered_segment_ids, entry_ref, confirmation_source, valid period | geometric proximity недостаточна; нет пустого «успешного» списка |
| AccessConstraint | id, scope, kind, status, source, observed/valid interval, expiry, QA | bridge/culvert/legal/access separate from ground model |
| RoadStructureVersion | segment/version refs, layers, drainage, survey_date, procedure, support, uncertainty | natural soil profile не копируется сюда как факт |
| VehicleEnvelope | id, version, mass range, configuration intervals, pass_policy, provenance, weights_status | required mass in range; веса unknown != равновероятные конфигурации |

`RoadSegmentVersion` может ссылаться на один и тот же публичный road baseline у нескольких tenants; закрытые assessments и обследования не разделяются автоматически. Composite FK фиксирует scope данных; public base features имеют explicit `public` namespace и отдельный permission path.

### 2.2 Источники и вычисления

| Сущность | Минимум полей | Инварианты |
|---|---|---|
| DatasetProduct | provider/product/release, license, access policy, support, vars, update cadence | release и license не inferred из имени URL |
| SourceAsset | product_id, provider_id, version, object digest, times, footprint, QC, units, CRS, correlation_group | content digest фиксирует revision; locator не является идентичностью |
| InputSnapshot | id, canonical manifest digest, ordered source refs, knowledge cutoff, transform versions | no source acquired/available/ingested after relevant cutoff policy |
| TransformRecord | code image, parameters, input hashes, output hashes, units conversion log, time rules | применённый scale/offset и deaccumulation ровно один раз |
| ModelVersion | artifact digest, code/parameter schema, validation_domain_id, card, approval | registry label alone не разрешает serving |
| ValidationDomain | soil/road/vehicle/climate/season ranges, exclusions, test report, expiry | applicability проверяется на каждый result |
| ModelApproval | version, scope, approver, effective/withdrawn times, evidence report | изменение approval отдельным событием |
| AnalysisRequest | tenant, workspace, idempotency key/hash, date, mass, requested_at, state | payload tenant не принимается как authority |
| AnalysisRun | request refs, versions, input_snapshot, worker lease/fence, status, started/ended, error | повторный запуск не мутирует published result |
| ResultManifest | tenant/run/release, canonicalization, outputs, time context, gate attestation | publication только после object verification; собственный digest только в SQL/envelope |
| OutboxEvent | tenant, aggregate, event_type, payload digest, committed_at, delivered_at | delivery at-least-once; consumers dedupe |

`available_at` записывается только при наличии сведения провайдера; иначе null и `availability_evidence=unknown`, а собственный `ingested_at` остаётся известным. Нельзя подставить acquired_at вместо available_at ради заполненного столбца.

### 2.3 Поля измерений и uncertainty

Каждое измерение хранит `quantity`, `value`, `unit`, `depth_top_m`, `depth_bottom_m`, `valid_interval`, `support_geometry`, `support_type`, `method`, `source_id`, `qc`. Отсутствующий показатель — null; ноль — реальное числовое значение. Vertical depth coordinate отделена от elevation datum.

Для series: `estimate_kind=observed|modelled|derived|imputed`, `uncertainty_kind=ensemble_spread|calibrated_predictive|source_quantiles|parameter_range|none`, `quantile_levels`, `ensemble_weight_ref`, `calibration_report_id`. Пустое `calibration_report_id` запрещает label «предиктивный интервал».

Observed soil moisture — либо gravimetric kg/kg, либо volumetric m³/m³; автоматическая конверсия без bulk density запрещена. Probe depth, calibration, time и coordinate uncertainty обязательны. DCP сохраняет raw depth/blows и конфигурацию прибора, CI — силу/конус/скорость/глубину, CBR — conditioning и lab/field method. Показатели не агрегируются одной колонкой `soil_strength` без явного метода.

## 3. Полевая evidence и приватность

FieldObservation: `id`, tenant/workspace, observed_at, entered_at, location/support, segment version relation, observer role, procedure version, raw data object digest, QA status, evidence links, consent/legal basis, vehicle/road conditions when relevant, intervention flags. Original immutable; correction — новая revision with supersedes. Rejected evidence остаётся в audit с причиной, но не участвует в features.

OutcomeObservation содержит event и ascertainment: `successful_passage`, `immobilized`, `rut_measurement`, `inspection_only`, `no_attempt`, `unknown`; полную массу/тип/проходы, параметры попытки и влияния буксировки/ремонта. `No attempt` не negative label. Поездка прошла не значит, что damage отсутствовал. Recovery inspection хранит времена отдельных мгновенных наблюдений. Последняя неблагоприятная и первая благоприятная проверка сами по себе не доказывают первое устойчивое recovery; persistence support/recurrence задаёт приложение08.

InspectionRequest создаётся явным оператором с reason, assigned_role, checklist, access_authorization_state, due/expiry, status. Модель не отдаёт распоряжение въехать на непроверенную дорогу. Notification и CMMS ticket — отдельные side effects с own idempotency keys и read-back verification.

## 4. API v1

API закрыт same-origin BFF session по ADR-10; TLS обязателен. OAuth tokens остаются server-side, cookie HttpOnly/Secure, mutations требуют Origin+CSRF. MapLibre получает cookie без URL token. JSON RFC7807-like errors, `request_id`, trace correlation. Единицы фиксированы; пагинация cursor-based. Курсор подписан и привязан к data snapshot, principal scope, tenant/workspace/filter/sort, authz revision и policy epoch; смена прав →409 `CURSOR_SCOPE_CHANGED`, нужна новая пагинация. Bounding box ограничен workspace/AOI; запрос карты не принимает произвольный SQL/COG URL.

| Метод/путь | Вход | Ответ и условия |
|---|---|---|
| GET /v1/workspaces | авторизованный пользователь | доступные workspace IDs; никакого общего списка чужих tenants |
| GET /v1/workspaces/{id}/capabilities | workspace | supported date ranges, policy version, input coverage, assessment levels, contract version |
| POST /v1/workspaces/{id}/analyses | JSON date+mass; Idempotency-Key | 202 job с Location, либо 200 existing immutable result; 409 same key different hash |
| GET /v1/jobs/{id} | job id | stage/status, progress as stage counts, last_heartbeat, safe error; без fake precision percent |
| POST /v1/jobs/{id}/cancel | job id, If-Match | 202 cooperative cancellation; опубликованный result не удаляет, conflict при поздней отмене |
| GET /v1/results/{manifest_id} | manifest ref | ServingEnvelope<ManifestView>, только разрешённые metadata/opaque artifact refs; не внутренние locators |
| GET /v1/results/{id}/assets | filter/cursor/limit | page + explicit matched total/as_of; snapshot-consistent count |
| GET /v1/results/{id}/segments/{segment_version} | versioned key | assessment, support, missing evidence, physical series refs |
| GET /v1/results/{id}/series | entity/quantity/time range | aligned time axis, units, quantiles, null gaps, immutable pagination |
| GET /v1/results/{id}/recovery/{entity} | event definition | reached CDF, censoring/eligibility, quantiles or null |
| GET /v1/results/{id}/tiles/{layer}/{z}/{x}/{y}.mvt | allowed layer/tile range | auth per request; cache key tenant+manifest+scope+layer+style+tile |
| GET /v1/results/{id}/raster-tiles/{layer}/{z}/{x}/{y}.png | layer id, не URL | approved manifest locator lookup; no SSRF |
| POST /v1/imports | bounded manifest/upload refs | quarantine task, validation report, preview, explicit commit for asset import |
| POST /v1/uploads | purpose, MIME, declared size/hash | server-generated upload session; limited object key; finalize validates SHA/MIME/decode |
| POST /v1/observations | observation schema | revision receipt; pending QA, ещё не model truth |
| POST /v1/observations/{id}/adjudications | reviewer action/evidence | versioned QA decision, conflict on stale revision |
| POST /v1/inspections | explicit request, target, reason | task record; permissions and safe access policy |
| GET /v1/data-status | workspace | product footprint/QC/freshness/access and upcoming jobs |
| GET /v1/model-versions/{id}/validation | permission | model card, tested domain, counts/metrics, report artifacts |
| POST /v1/exports | manifest+format+allowed scope | asynchronous export; digest and expiry, no field evidence by default |

### 4.1 Запрос анализа

```json
{"assessment_date":"2027-03-15","gross_mass_t":20}
```

Region, soil type, weather scenario и vehicle tires в этом запросе отсутствуют. Допустимая масса ограничена transport policy для механического вывода; положительная масса вне домена не блокирует просмотр environmental conditions. Неправильная дата/масса — 422; отсутствие рабочего прогноза на далёкую дату — climate mode при доступной климатологии либо explicit 422 `DATE_UNSUPPORTED`, но никогда незаметный переход в «прогноз».

### 4.2 Ответ принятия

`AnalysisAcceptance` содержит request/job identity, mode, статус, canonical request fingerprint, status reference и факт reuse. Точный минимальный DTO и синтетический пример — в `contracts/`, вместе с `JobStatus`, `ServingEnvelope`, `ManifestView` и `ResultManifest`. Это минимальный bundle первого пути, не весь production OpenAPI. Client использует Retry-After с backoff; API не держит многочасовой HTTP запрос до GDAL. Cancel racing с publish разрешает одна authoritative DB transaction; fencing token исключает позднюю публикацию.

### 4.3 Segment assessment

Нормативная JSON Schema: `contracts/assessment.schema.json`. Обязательны context date/mass/mode, source support, state/reason codes, risk with calibration, recovery definitions, immutable provenance. Fixtures показывают forcing-only abstention, будущий exact G1 и partially-identified recovery; `validated.json` — вымышленный пример G2 структуры, не существующая калибровка. `computed_at` — время расчёта GroundSense; `forecast_issue_time` — выпуск погоды или null вне forecast. `knowledge_cutoff<=computed_at`, eligible weather issue<=cutoff. Будущий valid time модельного состояния допустим: cutoff ограничивает знания входов, а не дату прогноза.

Результат за локальный день хранит interval `[start,end)` в UTC, учитывающий DST. Требуется полное покрытие всех обязательных segment supports и интервалов: любой unknown/неприменимый required support делает основную дневную категорию unknown. Для полного покрытия policy последовательно выбирает худшую категорию среди положительно-взвешенных сценариев, required units и интервалов дня. Это conservative scenario envelope, не вероятность отказа и не усреднение. SegmentSupportMapping версионирует геометрии и footprint/depth/time поддержку; centroid assignment не доказывает покрытия. Веса и thresholds входят в policy manifest. Приложение10 задаёт детали; 1-hour вход не становится точностью механического вывода.

## 5. Recovery контракт

Recovery имеет независимые discriminator `distribution_kind=exact_scenario_distribution|partially_identified|unavailable` и event status. Event time token — `confirmation_end`. Exact-вариант содержит unconditional CDF по исходным известным номинальным весам и доступные квантили. Partial-вариант содержит `cdf_bounds:[{time,lower,upper}]`, `bounds_by_horizon`, `ensemble_policy_ref` и причины missing mass; точечная probability/CDF и point quantiles отсутствуют. При unavailable ансамбль мог не генерироваться: masses null, а не выдуманные нули.

`right_censored` exact имеет нулевую CDF/probability и null quantiles. `unknown|unsupported` не содержат numeric recovery вывода. `forecast_distribution` не имеет `distribution_kind=unavailable`. Calibrated status всегда требует calibration report; vehicle recovery дополнительно требует G2 domain, matching и envelope. G1 сценарная доля не калибрована. Climatology запрещает количественную mobility и vehicle recovery.

По каждому h индикатор события — yes/no/unknown: поздний сбой не стирает уже подтверждённый first passage. Candidate позже H−persistence при полной траектории даёт NO confirmation-by-H, не missing mass. `already_recovered` различает `confirmation_basis=model_history|field_protocol` с точными evidence refs; модельная persistence не называется полевым подтверждением. Сброс persistence происходит при нарушении единого predicate C; дождь сбрасывает его лишь если criterion осадков включён в C. Schema/semantic validator проверяет представленные формальные комбинации; реальность evidence refs, approvals и непрерывного persistence support проверяет будущий runtime, а не JSON Schema.

`mobility.kind` — `calibrated_probability | probability_bounds | unavailable`. Bounds без bounds-полей недопустимы. Количественные variants требуют outcome, `estimand`, `operation_ref`, pass/envelope/configuration aggregation identity и report refs. Outcomes включают `immobilization`, `rut_depth_exceeded_after_n_passes`, `structural_damage`, `traction_loss`. Operation — authoritative ordered pass/load policy; остальные refs обязаны ссылаться на неё без расходящихся N. Unknown configuration weights не становятся mixture probability: нужны identified bounds/robust policy или unavailable. `mobility_status` из раздела1 — derived UI category, не отдельное произвольное schema поле. Непустой report ref ещё не доказывает approval: runtime registry check обязателен.

`source_supports[]` хранит quantity, source, estimate kind, transform/geometry/depth/time support. Static SoilGrids texture/плотность не служит источником daily moisture; model-derived moisture ссылается на scientific artifact/transform, сохраняя его inputs. Publication/freshness/eligibility выдаёт ServingEnvelope. Локальный validator проверяет форматы/семантику, но не настоящий registry, гидравлику, browser boundary или access policy.

Threshold uncertainty и finite ensemble sampling хранятся отдельно от CDF. Если типично прогнозный risk threshold не определён или отсутствует applicability domain, recovery unknown, а не «ожидаем 19 марта». При отозванной модели историческая CDF остаётся immutable, но serving eligibility withdrawn.

## 6. Проект таблиц и индексов

Реальная Alembic migration создаётся при реализации. Ниже требования, не production-ready migration.

```sql
-- Для всех закрытых сущностей: составная уникальность и составные внешние ключи.
CREATE TABLE asset_version (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL,
  stable_asset_id uuid NOT NULL,
  workspace_id uuid NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  geom geometry(Point,4326) NOT NULL,
  source_ref uuid NOT NULL,
  recorded_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id,id),
  UNIQUE (tenant_id,stable_asset_id,version),
  FOREIGN KEY (tenant_id,workspace_id) REFERENCES workspace(tenant_id,id)
);
CREATE INDEX asset_version_geom ON asset_version USING gist (geom);
ALTER TABLE asset_version ENABLE ROW LEVEL SECURITY;
ALTER TABLE asset_version FORCE ROW LEVEL SECURITY;
-- Tenant setting устанавливает только server-side auth middleware в transaction scope.
CREATE POLICY tenant_asset ON asset_version
USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
```

Connection pool возвращает session state в безопасное значение; предпочтительно `SET LOCAL` внутри transaction. Отсутствующий tenant context не даёт доступ. Тесты проверяют API role и worker role отдельно, включая owner/superuser bypass. Такой session variable не является защитой от произвольного SQL execution: parameterized queries и отсутствие SQL injection обязательны.

Индексы: tenant+workspace+latest pointers; tenant+manifest+entity; GiST geometry; btree source product+valid time+issue time; BRIN для крупных ordered ingest logs; partial index unpublished jobs; UNIQUE `(tenant_id,workspace_id,operation,client_key)` для idempotency. Binding/tombstone хранится до удаления workspace по ADR-02, а не забывается при коротком HTTP retry TTL. Timeseries cube не раскладывается в billions SQL rows. В Postgres — thin indexes и summary/features, в object store — массивы/кубы и historical partitions.

## 7. Manifest контракт

Canonical internal manifest перечисляет contract/version, tenant scope, result ID, request context, model/code/parameter/input/event/envelope hashes, exact outputs, native support, run timestamps, publication gate и assumptions. Canonicalization `RFC8785-JCS`, UTF8 SHA256; подробности, числовые/Unicode ограничения и golden-vector tests — ADR-05. Manifest не включает собственный digest; assessment не ссылается на его будущий hash. Input snapshot→assessment→publication manifest→ServingEnvelope — однонаправленный DAG.

User endpoint возвращает ManifestView, а не storage keys/version locators этого internal manifest. Для полного canonical artifact нужно отдельное право на весь scope. Авторизованная проекция имеет собственный representation digest/ETag, отличный от original-manifest SHA. Gate attestation — publication receipt, а текущий approval всё равно проверяется при serving.

Локальный POSIX adapter использует fsync temporary file→conditional link no-overwrite→fsync directory; существующий key требует exact digest/size comparison. Заменяющий destination atomic rename не допускается. Это не проверка S3 adapter; S3 key не overwritten, object version/ETag не подменяются SHA256.

Публикация uses authoritative DB pointer; source correction создаёт новую InputSnapshot и AnalysisRun. Старый снимок доступен как исторический, если retention позволяет, но не как current. Dependency graph invalidation затрагивает downstream по digest, а не все результаты организации без разбора.

## 8. Ошибки и лимиты

API payload, upload, AOI, pagination, tiles, ensemble size и scientific run budget ограничиваются workspace quota. Точные лимиты выбираются на G0 нагрузочном spike; релиз не допускается с бесконечными defaults. Рекомендованные исходные настройки для проверки: page≤200, API JSON≤1MiB, image≤20MiB decoded-pixel budget отдельно, archive expanded≤250MiB/count≤1000. Это проектные стартовые лимиты, не измерение объёма исходного проекта. Увеличение лимита не отключает ZIP traversal, MIME или pixel checks.

429 содержит retry hints; 503 относится к недоступному сервису; unknown scientific result возвращается с 200, reason codes и ограничениями, не маскируется под серверный crash. Клиент не делает бесконечный retry schema-invalid input. External credentials, внутренние storage paths и точные stack traces не попадают в user-facing errors.

## 9. Общая bitemporal revision-конвенция

SourceAsset, QC/adjudication, observations, geometry/mapping, road/envelope/operation/event/aggregation policy, fitted preprocessing и model approvals используют один append-only принцип: `logical_id`, immutable `revision_id`, `valid_from/valid_to`, server `recorded_at`, monotone committed `transaction_sequence`, `supersedes_revision_id`, author/provenance, digest. Исправление не перезаписывает старый recorded_at, valid interval или bytes. Supersession/revocation/tombstone — новая запись с собственным commit time. `system_to` может быть вычисляемым view, но не затираемым полем единственной строки.

InputSnapshot фиксирует timestamp cutoff и committed transaction watermark. As-of query сначала оставляет записи, уже committed к watermark/cutoff; затем применяет только известные тогда supersession/QA события; затем проверяет valid time, source availability/ingestion и dependency DAG. Поздняя корректировка с backdated valid_from не изменяет прошлое решение. Последующий withdrawal не удаляет историческую запись из replay, но текущая serving policy может запрещать выдачу её bytes. Fitted transform, обученный после cutoff, не используется в старом operational test. `provider_available_at=null` не заменяется acquisition time.

Forecast raw bytes/issue/member/step inventory удерживаются с WP-01, до настройки model skill tests. Cold-start без retained bridge не создаёт оперативный hindcast: forcing показывается только на покрытой части, state/recovery unavailable. Retrospective reconstruction и external availability hindcast подписаны отдельно. История, archive availability, retention и gaps входят в dataset card; source metadata endpoint не доказывает наличие архива.
