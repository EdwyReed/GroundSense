> Исследовательское приложение. Нормативные решения, API enums и более поздние исправления задаёт [основная спецификация](../GROUNDSENSE-SPEC.md). Общий реестр ссылок — [SOURCES.md](SOURCES.md). Числа sizing, SLO и sample size — проектные гипотезы, если явно не указано иное.

# GroundSense: прикладная техническая архитектура

**Назначение.** GroundSense — B2B-платформа для планирования обслуживания промышленных скважин и иных удалённых объектов через грунтовые/лесные подъезды. Пользователь вводит только **дату** и **полную массу автомобиля**; область анализа выбирается из рабочего контекста организации. Система возвращает состояние участка, прогноз окна восстановления, неопределённость, факторы и доказательную цепочку. Это поддержка решения, а не инженерная гарантия несущей способности: для нового региона и каждого класса техники нужен полевой scientific gate.

## 1. Выбор стека и границы первой версии

| Слой | Решение сейчас | Почему / что позже |
|---|---|---|
| Web GIS | **Vue 3 + TypeScript, Vite, Pinia, Vue Router** | Vue рекомендует Composition API + SFC для полноценных приложений; компактный компонентный стек удобен для карты, фильтров и рабочих экранов.[38] Не React: у GroundSense нет существующего React-ландшафта или потребности в React Native; это убирает одну категорию выбора, а не утверждает превосходство Vue. |
| Карта | **MapLibre GL JS**, самохостируемый style JSON и vector/raster sources | WebGL-клиент для интерактивных vector tiles; его стиль — переносимый JSON-документ.[39] Не использовать публичные OSM tiles как production-базу: OSM прямо не предоставляет бесплатный API/tiles третьим лицам.[33] |
| Графики | **Apache ECharts** | Time-series recovery, bands неопределённости, quality flags и сравнительные периоды без отдельной GIS-зависимости. Держать адаптер `ChartPort`; заменить можно без изменения доменной модели. |
| API | **Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, uvicorn/gunicorn** | FastAPI подходит для I/O-bound API, но CPU/GDAL/science не должны выполняться в request process: async помогает ожиданию I/O, а не превращает расчёт в параллельный CPU.[40] |
| Научный контур | **xarray, numpy, rasterio/GDAL, geopandas/pyogrio, pyproj, dask** | Проектный план: xarray/NumPy для именованных массивов, rasterio/pyproj для геоданных; начать с одного process-per-run. Dask cluster не является обязательной dependency G0 и включается только после профилирования, без ссылки на документацию Prefect как доказательство Dask. |
| Гео-БД | **PostgreSQL + PostGIS** | Tenant-scoped metadata, геометрии объектов и подъездов, AOI, field evidence, catalogue, run/manifests. RLS — защитный нижний слой, а не только API-проверка.[41] |
| Очередь/оркестрация | **Prefect 3 self-hosted + PostgreSQL**, отдельные Docker workers; **Valkey** только для коротких locks/cache/rate-limit | Prefect даёт Python-native flows, retries/state/recovery и запускается от single process до containers/Kubernetes.[50] Не начинать с Celery: события, schedules, retry и lineage run уже являются предметом оркестратора. Valkey — BSD, имеет TTL/LRU/репликацию, но не является источником истины.[51] |
| Объекты | **S3-compatible managed object storage** на старте (предпочтительно AWS S3/региональный провайдер с versioning и object lock); API абстрагировать через `ObjectStorePort` | S3 — масштабируемый object storage.[57] Self-hosted только при сформулированном residency/air-gap требовании: **SeaweedFS** (Apache-2.0) для малого ops; **Ceph RGW** — зрелый S3-compatible, но оправдан лишь при существующей storage-команде.[48][49] |
| Raster tiles | COG + **TiTiler** за API-gateway, CDN только для публичных baseline | TiTiler строит FastAPI dynamic tiling для COG/STAC/Zarr и заявляет OGC Tiles support.[42] Пиновать namespace-пакеты (`titiler.core`, `titiler.xarray`): metapackage `titiler` больше не поддержан после late-2025.[42] |
| Вектор | PostGIS → tippecanoe/pg_tileserv-like build в **PMTiles** для неизменяемых базовых слоёв; MVT endpoint для tenant/run data | Базовые дороги/объекты редко меняются — portable PMTiles через CDN. Данные результата и evidence остаются защищёнными MVT/API. OGC API Tiles — стандартный REST building block для tiled геоданных.[58] |
| Наблюдаемость | OpenTelemetry Collector → Tempo/Jaeger, Prometheus → Grafana, Loki/structured JSON logs | OTel — vendor-neutral framework для traces/metrics/logs; Prometheus хранит метрики как time series с labels.[54][55] |

**Почему не Kubernetes сначала.** MVP — 1 production VM/managed DB + object store, Docker Compose, reverse proxy, Terraform/OpenTofu и daily backup. Это минимизирует эксплуатацию. Переход на managed containers/Kubernetes — только после устойчивой нагрузки, HA-цели или нескольких workers/регионов; код и images проектируются portable с первого дня.

## 2. Модель продукта и данных

### 2.1 Научная семантика

Единица результата — `segment_assessment` для сегмента подъезда/площадки, а не заявление «дорога проходима». Результат содержит:

- `environmental_condition=less_adverse|adverse|severe|unknown`, отдельные reasons и `mobility.kind=calibrated_probability|probability_bounds|unavailable`; risk только G2, не осевая грузоподъёмность;
- recovery exact/partial-bounds/unavailable с confirmation_end, CDF/квантилями только по правилам wire1.1; произвольного recovery_window без event/uncertainty нет;
- driver decomposition: осадки, snowmelt/freeze-thaw proxy, moisture proxy, slope/drainage, soil priors, vegetation/land-cover, свежесть наблюдения;
- `unknown` вместо ложной точности при stale forecast, облачности/отсутствии SAR, выходе из калиброванной области или недостатке полевых наблюдений.

Sentinel-1 даёт all-weather/day-night SAR, но один источник не измеряет несущую способность; его текущая документация фиксирует изменение покрытия после потери S1B и восстановление 6-day цикла двумя спутниками.[46]

Sentinel-2 L2A даёт surface reflectance и scene classification на 10/20/60 м.[18] Оптический источник зависит от облаков.[unverified]

ERA5-Land — почасовой reanalysis, 0.1°/native около 9 км, с собственными неопределённостями; он задаёт regional forcing, а не «истину» для конкретной дороги.[28]

SoilGrids — 250-метровые свойства и 90% prediction interval; использовать как prior с uncertainty, не как дорожную конструкцию.[22]

### 2.2 Canonical model: valid time и knowledge time

В каждой таблице/asset обязательны:

- `tenant_id`, `region_id`, `source_id`, `asset_id` (UUID), `content_sha256`, `schema_version`;
- **valid time**: `valid_from`, `valid_to` — когда факт/прогноз применим к миру (например, forecast step 2026-10-27T00Z);
- **knowledge time**: `observed_at`, `published_at`, `ingested_at`, `superseded_at` — когда источник и GroundSense реально могли это знать;
- `model_version`, `parameter_set_digest`, `code_image_digest`, CRS/resolution/nodata, licensing/attribution, quality flags.

Запрос «на дату D» не имеет права читать данные, `published_at > requested_as_of` в режиме воспроизведения. Обычный current-run явно показывает `as_of`. Historical backtest использует bitemporal cut: `valid_time contains D AND knowledge_time <= cutoff`. Forecast хранится как выпуск (`forecast_issue_time`) и valid step — поздний forecast не переписывает ранний.

### 2.3 Форматы и layout

- **Raw**: неизменяемое source-bytes + checksum; STAC/HTTP request receipt и licence.
- **Analysis raster**: один/несколько COG на date/AOI для завершённых 2D layers. COG driver GDAL создаёт overviews; создание требует временное место — около 1/3 размера финального файла при `CreateCopy`, до 2×+ при `Create`.[43]
- **Cube**: Zarr v3 pinned после compatibility test; chunked `time,y,x` для multi-date moisture/forecast ensembles. Zarr предназначен для больших N-dimensional arrays, совместимых с parallel/distributed computing.[44]
- **Features**: partitioned GeoParquet (`tenant/region/date/model/run`), WKB/GeoArrow geometry, `geo` metadata; спецификация требует `geo` metadata key.[45]
- **Operational query**: PostGIS tables/indexes, не дублировать туда все raster cells.

Object key only generated server-side, e.g. `prod/tenant={uuid}/run={uuid}/kind=derived/sha256={digest}/part-000.parquet`; ни filename, ни tenant slug из пользовательского ввода.

## 3. Поток, lineage и атомарная публикация

```text
CDSE/ERA5/SoilGrids/OSM + approved tenant field evidence
  -> restricted downloader -> raw immutable objects + source_receipt
  -> normalize/QA -> feature assets (COG/Zarr/GeoParquet)
  -> model run (input manifest digest, code+parameter digests)
  -> candidate output objects, checksums, validation
  -> SQL commit: immutable RunManifest status=published
  -> cache/event invalidation -> API/tiles/UI
```

### 3.1 Append-only lineage

`source_asset` → `normalized_asset` → `feature_asset` → `model_run` → `result_asset` → `published_manifest`. Каждый edge хранит input digest и transformation identity. Никогда не overwrite asset/run; исправление — новый asset и новый manifest, `supersedes_manifest_id`. Field evidence имеет consent/policy version и может быть revoked; хранится tombstone и impact analysis. Cryptographic deletion не обещается при существующих backup/download copies; процедуры retention определяются отдельно.

### 3.2 Atomic manifest across SQL + objects

SQL и S3 не дают общей транзакции; нельзя обещать двухфазную атомарность. Практический protocol:

1. Durable reservation удерживает exact immutable final keys/version IDs до публикации; staging при необходимости копируется в final до commit. Все bytes и manifest проверены и закреплены.
2. В одной SQL transaction проверяются run fence, cancellation, reservation и current approval revision; создаются published references, manifest pointer и outbox. Резервация атомарно становится published reference.
3. Readers принимают только опубликованный SQL manifest; current policy проверяется перед каждой private выдачей. Post-commit copying объектов, необходимых для чтения, запрещён.
4. GC согласует delete claims с теми же reservation rows и не удаляет pinned/published exact versions. Полный протокол и гонки — `09-SECURITY-PUBLICATION-ADR.md`.

PostgreSQL Serializable гарантирует эффект как от последовательного выполнения; транзакцию надо retry при serialization failure.[56] S3 presigned URLs дают ограниченный по времени доступ и зависят от credentials principal — выдавать на конкретный immutable key, короткий TTL, checksum и content-length policy.[57]

### 3.3 Invalidation и cache isolation

Cache key включает tenant/workspace/site scope, policy epoch/authz revision, manifest/layer/style/tile/encoding. Current policy проверяется ДО cache/304. ETag — SHA фактически выданных scope-filtered bytes/encoding, не digest полного manifest. ServingEnvelope no-store. Cursor привязан к snapshot+authz revision и перезапускается при смене grants. CDN только public baseline. SQL uniqueness `(tenant,workspace,operation,client_key)` окончательна; Valkey вспомогателен. Полные правила ADR-02/03/04.

## 4. API, UI и job design

**Экран**: date + gross mass (т) → `POST /v1/workspaces/{id}/analyses`. Region берётся из tenant workspace/site portfolio, а не свободного геопоиска. Ответ сначала `202 AnalysisAcceptance {job_id,status,status_url,reused}`; UI poll/SSE status. После published manifest: карта risk/coverage/staleness, time chart recovery window, explainability drawer, source freshness, field-verification request. Не строить точный route optimizer или выдачу конкретных live маршрутов.

**API contracts.** Local calendar date + positive gross mass; mechanical applicability отдельна от input validity. Нет универсального обязательного confidence. ScientificAssessment, RecoveryDistribution, ServingEnvelope и manifest разделены, DTO mapping в `09-SECURITY-PUBLICATION-ADR.md`; основной API в `05-DATA-API.md`. GDAL/parser workers имеют network isolation и scoped prepared inputs, а не широкие app credentials.

**Jobs.** Request idempotency key — клиентский key в scope tenant+workspace+operation; fingerprint неизменного запроса отделён от resolved computation digest. Повтор сначала lookup, потом current authorization; не re-resolve latest. G0b — один process worker с SQL job state, forcing-only и abstained science. Поздний scheduled pipeline имеет stages discover→fetch→validate→normalize→science→validate-output→publish; Prefect предназначен для workflows/retries/state recovery.[50] Он не prerequisite первого manual slice. Retry safe stages; poison input quarantine. Forecaster raw issues удерживаются с WP-01.

## 5. Security, privacy и supply chain

### AuthN/AuthZ/RLS

- Существующий enterprise IdP; Keycloak только при его отсутствии.[59] Same-origin BFF ведёт Code+PKCE/state/nonce, OAuth tokens server-side; browser получает HttpOnly/Secure cookie, mutations проверяют Origin+CSRF. Tiles/API без URL tokens; детали ADR-10.
- Roles: `viewer`, `operator`, `field-contributor`, `tenant-admin`, `platform-operator`, `science-approver`; grants are tenant+region+site scoped. Service identities separate per API/worker/tiler.
- PostgreSQL: `tenant_id NOT NULL` everywhere, `ENABLE/FORCE ROW LEVEL SECURITY`; transaction starts `SET LOCAL app.tenant_id`, app role lacks `BYPASSRLS` and is not table owner. RLS default-denies tables with no policy, while table owners normally bypass policies — use a no-login owner/migration role separate from runtime.[41]
- Object store private; presigned URL — bearer capability с ограниченным TTL, а не audience-bound credential. Для немедленно отзываемого evidence применяем authenticated proxy. ScopeAuthorizer проверяет tenant+workspace+site; policy check предшествует cache/304. Подробности — `09-SECURITY-PUBLICATION-ADR.md`.

### Secrets and supply chain

OIDC workload identity to cloud roles; local dev `.env` never committed; production secrets in managed Secrets Manager/Vault, rotate database/object/OIDC keys, redact in logs/traces. Pin container digests, SBOM + dependency scan, signed release artifacts, least-privilege egress allowlist. No long-lived S3/DB secret in browser, image or Prefect block.

### Imports, SSRF, zip bombs

No arbitrary user URL import in MVP. Administrator-approved source registry has scheme/host/port/path allowlists and DNS/IP resolution checked after redirects; deny `localhost`, RFC1918/CGNAT/link-local, metadata endpoints, IPv6 local/reserved and non-HTTP(S). SSRF can target internal services and cloud metadata through server-side URL functionality.[53]

For uploads: direct-to-quarantine bucket only with scoped upload URL; allowlisted extensions *and* magic/type parser; generated name; max compressed bytes, max files, max expansion ratio and total uncompressed bytes; reject encrypted/nested archives and path traversal/symlinks; scan before promotion; no serving from web root. OWASP explicitly warns about zip/XML bombs and says not to trust Content-Type, to size-limit and validate file types.[52]

### Field evidence privacy

Evidence can reveal people, asset condition and precise sensitive locations. Default to private tenant scope, purpose/consent record, EXIF strip or encrypted original, blur/quantise public derivative, retention class (e.g. raw 90d configurable; approved observation retained per contract), access audit, revocation/deletion workflow and export log. Human review before evidence changes calibration labels; separate `reported`, `verified`, `rejected` status. Never expose uploader identity to ordinary viewers.

### Offline pack

Create an encrypted, signed **read-only** package from a published manifest, scoped to a named user/device/AOI/date window. It includes only needed basemap/results, provenance and expiry; no raw field evidence by default. App checks signature, `not_before/not_after`, tenant/device claim and manifest digest at open; after expiry it becomes view-only “expired—refresh required”, not a live truth source. Revocation list is checked on reconnect; design for inability to retract an already copied offline file, so minimise content and TTL.

## 6. Data-source operational constraints

- SoilGrids REST API is currently paused with no restoration timeline; design against WCS/WebDAV/cache, never make online REST a request-time dependency.[22]
- ERA5-Land is model/reanalysis data, daily updated but native ~9 km: preserve version/request receipts and apply it at forcing scale, not a false road-scale precision.[28]
- Sentinel product availability and processing change; discover through STAC per run and pin scene IDs/processing baseline, rather than assuming cadence.[46][18]
- OSM is ODbL: display attribution and have counsel review produced/redistributed derivative databases; do not depend on public tiles.[33]
- **MinIO risk:** current upstream repository is AGPLv3 and was archived on 2026-04-25.[47][67] It is not the default production store; reassess licensing/maintenance before a fork/commercial agreement. SeaweedFS Apache-2.0 still introduces operational responsibility.[48] Ceph RGW raises ops cost; select only with a storage team.[49]

## 7. Deployment stages, DR, SLOs

### Stages

1. **Local/dev** — Compose, synthetic/open small AOI, deterministic fixture inputs; no production credentials.
2. **Integration** — isolated cloud account/project, ephemeral database/bucket prefixes, contract tests for source adapters, migration test and COG/Zarr/GeoParquet validators.
3. **Pilot/staging** — production-shaped managed Postgres, private object store, one worker pool; shadow runs, backtests and field-review only; promote manifest via science approval.
4. **Production minimal ops** — two API replicas if provider supports it, one scheduler, worker autoscale bounded by queue, managed DB PITR, object versioning; change through CI/IaC.
5. **Mature platform** — separate compute/serving namespaces, multi-AZ DB/object replication, regional DR, Dask workers only for profiled workloads, optional managed Kubernetes.

### DR

RPO/RTO are proposed targets, not provider promises: pilot **RPO 24 h / RTO 8 h**; production **RPO 1 h / RTO 4 h** after restore drill; mature **RPO 15 min / RTO 2 h** only with multi-AZ/region design and tested runbook. Nightly encrypted logical PostgreSQL backup + WAL/PITR; object versioning/retention plus cross-account replicated immutable releases; export Terraform/OpenTofu, container digests, Keycloak realm config and manifest catalogue. Quarterly restore exercise must prove: restore DB, restore selected object, resolve manifest checksum, serve a known assessment. Raw public-source data can be re-fetched; tenant evidence cannot be treated as re-fetchable.

Восстановленная policy DB не считается актуальным допуском. До private reopening обязательны новый policy epoch, invalidated sessions/cursors/leases и reconciliation revocations/deletions с audit/IdP. При неполном audit все scopes disabled до ручной переаттестации. Restore тестирует отзыв grants/model approvals и удаление evidence после backup cutoff; checksum известного assessment не заменяет этот security gate (ADR-11).

### Proposed SLOs

| SLI | Pilot proposed target | Mature proposed target |
|---|---:|---:|
| Authenticated read API availability/month | 99.5% | 99.9% |
| Cached tile p95 | <1.0 s | <500 ms |
| Assessment request acceptance p95 | <2 s | <1 s |
| Published daily refresh freshness | 95% before agreed cutoff; show stale otherwise | 99% |
| Successful eligible runs | ≥95%/month excluding upstream outage | ≥99% |
| Manifest reproducibility audit | 100% sampled manifests resolve digests | 100% |

Error budget pauses feature rollout, not scientific validation. Science quality metrics are decided after labels exist: calibration, false-safe rate, coverage/abstention and recovery-window coverage by soil/season/vehicle class.

## 8. Workload sizing — transparent starting calculation

This is a **serving-summary raster scenario only**, not the scientific ensemble cube and **not benchmark**. Full storage breakdown and state/segment formulas: `09-SECURITY-PUBLICATION-ADR.md` ADR-09 and `research/planning-estimates.json`. Pilot assumptions: 1 region; 2,000 km² analysis grid at 30 m; 40 dynamic raster variables/day (observed + forecast features); 14 forecast days; 20 concurrent UI users; 100 assessment requests/day; 300 viewed tiles/user/day; 30% cache misses; 10 field uploads/day.

1. Grid cells = `2,000 km² × 1,000,000 m²/km² / (30 m × 30 m)` = **2,222,222 cells/layer**.
2. One float32 full layer = `2,222,222 × 4 B` = **8.89 MB** uncompressed.
3. Daily 40-layer feature set = `8.89 × 40` = **356 MB/day** uncompressed; 14-day = **4.98 GB** uncompressed. Plan 2–4× temporary I/O during reprojection/COG build (GDAL documents meaningful temporary space requirements), so reserve **20 GB fast ephemeral work space per concurrent regional build**, then measure.[43]
4. Cache-miss tile rate = `20 × 300 × 0.30 / 86,400` = **0.0208 tile/s average**. A 50× peak factor yields **~1.04 tile/s**. This is why one TiTiler replica is adequate as an initial hypothesis, not a capacity claim.
5. If average API payload is 50 KB, 20 concurrent users × 1 request/5 s = 4 req/s, ~0.2 MB/s payload before tiles; 2 API replicas with **2 vCPU/4–8 GB each** provide isolation and rolling deploy headroom.

**Initial pilot footprint (measure and revise after 2 weeks):** managed Postgres 4 vCPU/16 GB RAM, 200 GB fast disk + PITR; one science worker 8 vCPU/32 GB RAM/100 GB ephemeral, concurrency=1 for GDAL/Dask jobs; one tiler 2 vCPU/4–8 GB; API 2×(2 vCPU/4–8 GB); Valkey 1–2 GB; object storage 0.5 TB usable (raw + versions + 2× processed headroom), lifecycle archive verified releases. Scale workers on queue age and observed peak RSS; scale tilers on p95/miss rate. Do not extrapolate a nationwide cost from this regional arithmetic.

## 9. Delivery work packages and science gates

| WP | Deliverable | Exit / gate |
|---|---|---|
| WP0: discovery & governance | Site/asset inventory, allowed regions, legal source register, data classification, scientific protocol, user date+mass contract | Named product/science/data owners; approved no-route-optimizer scope; acceptance criteria for abstention and evidence privacy. |
| WP1: reproducible data foundation | PostGIS schema/RLS, object layout, source adapters, STAC/source receipts, bitemporal catalogue, manifest publisher | Exact retained artifact bytes подтверждаются digest; scientific recompute сравнивается с declared numerical tolerance, не обещает bit-for-bit результат на другом runtime. |
| WP2: baseline science | Feature pipeline, conservative heuristic/probabilistic model, uncertainty + unknown behavior, historical backtest harness | **Science gate 1:** geotechnical reviewer approves feature semantics; holdout is split by site/time (not random pixels); report accuracy/calibration/abstention by season and soil class. Failure means model remains research-only. |
| WP3: pilot UX/serving | Vue/MapLibre UI, date+mass input, tiles/charts/explanations, audit/export and offline proof of concept | Users can reproduce a displayed result from manifest; response visibly distinguishes data age, uncertainty and unknown. |
| WP4: field evidence/calibration | Privacy-preserving collection, QA workflow, calibration dataset and monitoring | **Science gate 2:** prospective field observations cover wet/dry, freeze-thaw, soil and vehicle strata; pre-agreed false-safe ceiling and recovery-window coverage met. Otherwise no operational recommendation class is released. |
| WP5: hardening | backup restore drill, security test, load test with stated profile, SLO dashboards, runbooks | Restore and tenant-isolation tests pass; source outage produces stale/unknown, never fabricated current result. |
| WP6: scale decision | measured costs/p95/RSS/queue age, multi-region plan, Dask/K8s/HA proposal only if trigger met | Architecture review uses observed workload, not a calendar promise. |

No 24-week accuracy guarantee is justified before WP4 labels and prospective gate. A calendar may fund the work packages; it cannot certify physical performance.

## 10. Decision log

- Choose **Vue 3 + MapLibre + ECharts** for a focused GIS SPA; keep interfaces around map/chart providers.
- Choose **FastAPI + scientific Python + PostGIS**, strict separation between request plane and CPU/GDAL job plane.
- Persist raster **COG**, cubes **Zarr**, vectors **GeoParquet**, operational metadata **PostGIS**; tile dynamically with TiTiler and serve immutable baselines as PMTiles.
- Choose **Prefect + Postgres** for workflows; Valkey is auxiliary only.
- Start with managed S3-compatible storage; reject MinIO as default due to AGPL/archive risk; keep SeaweedFS/Ceph as explicit later operational choices.
- Reader-visible atomicity is the immutable SQL-published manifest; not an impossible cross-SQL/object ACID claim.

## Sources

[18] https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html — Sentinel-2 — CDSE documentation
    > "The satellites carry a single payload: the optical Multi-Spectral Instrument (MSI) that samples 13 spectral bands: four bands at 10 m, six bands at 20 m and three bands at 60 m spatial resolution."
    > "Level 2A product provides atmospherically corrected Surface Reflectance (SR) images"
[22] https://docs.isric.org/globaldata/soilgrids — ISRIC SoilGrids documentation
    > "The outputs of SoilGrids are global soil property maps at six standard depth intervals"
    > "we are currently experiencing issues with the REST API for SoilGrids, and have decided to temporarily pause the service."
[28] https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — ERA5-Land hourly data from 1950 to present
    > "Native resolution is 9 km."
    > "The ERA5-Land dataset, as any other simulation, provides estimates which have some degree of uncertainty."
[33] https://www.openstreetmap.org/copyright — OpenStreetMap copyright and license
    > "Although OpenStreetMap is open data, we cannot provide a free-of-charge map API or map tiles for third-parties."
[38] https://vuejs.org/guide/introduction.html — Introduction | Vue.js
    > "For production use: Go with Composition API + Single-File Components if you plan to build full applications with Vue."
[39] https://maplibre.org/maplibre-gl-js/docs — Introduction - MapLibre GL JS
    > "MapLibre GL JS is a TypeScript library that uses WebGL to render interactive maps from vector tiles in a browser."
[40] https://fastapi.tiangolo.com/async — Concurrency and async / await - FastAPI
    > "As the execution time is consumed mostly by waiting for I/O operations, they call them "I/O bound" operations."
[41] https://www.postgresql.org/docs/current/ddl-rowsecurity.html — PostgreSQL Row Security Policies
    > "If no policy exists for the table, a default-deny policy is used, meaning that no rows are visible or can be modified."
[42] https://developmentseed.org/titiler — TiTiler
    > "TiTiler, pronounced tee-tiler ... is a set of python modules that focus on creating FastAPI application for dynamic tiling."
[43] https://gdal.org/en/stable/drivers/raster/cog.html — GDAL COG driver
    > "During the writing process, if overviews are generated, they will be created in a temporary dataset, requiring storage capacity of roughly one third of the final file size"
[44] https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html — Zarr core specification
    > "The primary motivation for the development of Zarr is to address this challenge by enabling the storage of large multidimensional arrays in a way that is compatible with parallel and/or distributed computing applications."
[45] https://geoparquet.org/releases/v1.1.0 — GeoParquet Specification 1.1.0
    > "A GeoParquet file MUST include a `geo` key in the Parquet metadata"
[46] https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel1.html — Sentinel-1 – Documentation
    > "C-band synthetic aperture radar imaging has the advantage of operating at wavelengths that are not obstructed by clouds or lack of illumination and therefore can acquire data during day or night under all weather conditions."
[47] https://github.com/minio/minio/blob/master/LICENSE — minio LICENSE
    > "This repository was archived by the owner on Apr 25, 2026. It is now read-only."
[48] https://github.com/seaweedfs/seaweedfs/blob/master/LICENSE — seaweedfs LICENSE
    > "seaweedfs/seaweedfs is licensed under the Apache License 2.0"
[49] https://docs.ceph.com/en/latest/radosgw — Ceph Object Gateway
    > "Ceph Object Storage supports two interfaces: 1. S3-compatible ... 2. Swift-compatible"
[50] https://docs.prefect.io/v3/get-started — Prefect introduction
    > "State & Recovery | Robust state management that tracks success, failure, and retry states."
[51] https://valkey.io/topics/introduction — Valkey introduction
    > "Valkey is an open source (BSD licensed), in-memory data structure store used as a database, cache, message broker, and streaming engine."
[52] https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html — OWASP File Upload Cheat Sheet
    > "Validate the file type, don't trust the Content-Type header as it can be spoofed"
[53] https://owasp.org/www-community/attacks/Server_Side_Request_Forgery — OWASP SSRF
    > "the attacker may be able to read server configuration such as AWS metadata, connect to internal services"
[54] https://opentelemetry.io/docs — OpenTelemetry Documentation
    > "OpenTelemetry is a vendor-neutral open source Observability framework for instrumenting, generating, collecting, and exporting telemetry data such as traces, metrics, and logs."
[55] https://prometheus.io/docs/introduction/overview — Prometheus Overview
    > "Prometheus collects and stores its metrics as time series data"
[56] https://www.postgresql.org/docs/current/transaction-iso.html — PostgreSQL Transaction Isolation
    > "any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order."
[57] https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html — Amazon S3 presigned URLs
    > "You can use presigned URLs to grant time-limited access to objects in Amazon S3 without updating your bucket policy."
[58] https://www.ogc.org/standards/ogcapi-tiles — OGC API Tiles Standard
    > "OGC API — Tiles is a standard defining building blocks for creating Web APIs that support the retrieval of geospatial information as tiles."
[59] https://www.keycloak.org/documentation — Keycloak Documentation
    > "Authorization Services | Centrally manage fine-grained permissions for applications and services."
[67] https://github.com/minio/minio — MinIO upstream archive status
    > "This repository was archived by the owner on Apr 25, 2026. It is now read-only."
