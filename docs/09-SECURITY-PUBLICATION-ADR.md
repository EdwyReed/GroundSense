# Нормативные ADR: serving, доступ, публикация и первый срез

Принято после двух рецензий. Эти решения заменяют исследовательские рецепты, противоречащие им. Это протокол будущей реализации; crash/security tests здесь не объявляются выполненными. Первый G0b — forcing-only с честным abstention; физический исследовательский переход отдельно задан приложением10.

## ADR-01. Контракты результата и текущей выдачи

`ScientificAssessment` — immutable результат для entity/version, requested local day, mass и resolved context. `RecoveryDistribution` — вложенный полный объект той же версии; если размер требует endpoint, immutable `recovery_artifact_ref` указывает точный digest, а schema совпадает с встроенным объектом. `ResultManifest` — publication-time receipt и список точных output objects. `ServingEnvelope` — динамическая оболочка выдачи, не часть научных bytes. `run_id/release_id` выделяются заранее. Assessment ссылается на них и input snapshot, но НЕ на digest содержащего его ResultManifest. Manifest ссылается на SHA assessment; его собственный digest хранится в SQL/envelope, а не внутри хешируемых bytes. Получается DAG, а не цикл хешей.

DTO по endpoint:

| Endpoint family | DTO |
|---|---|
| POST analyses | AnalysisAcceptance |
| GET jobs | JobStatus |
| GET results/{id} | ServingEnvelope<ManifestView>, разрешённая проекция |
| GET segments/{version} | ServingEnvelope<ScientificAssessment> |
| GET recovery/{entity} | ServingEnvelope<RecoveryDistribution> |
| assets/list/count | ServingEnvelope<AuthorizedEntityPage> |
| tiles / range / artifact bytes | отдельный authorization middleware и transport headers, не JSON wrapper |
| exports | ExportStatus и затем ServingEnvelope<ExportManifest> |

`ServingEnvelope` содержит `served_at`, `principal_scope_digest`, `policy_revision`, `approval_revision`, `eligibility` (`current|historical_only|withdrawn|expired`), `freshness`, `completeness`, `warnings`, digest publication manifest и payload/opaque reference. Synthetic true в production serving запрещён независимо от похожих на настоящие model/report IDs. Production registry lookup проверяет не просто существование строки, а совпадение model/event/envelope/domain/operation и подписи допуска.

`ManifestView` перечисляет только разрешённые entity metadata и opaque artifact IDs. Не содержит bucket/key/version locators, скрытых site IDs, чужих footprints, evidence links или исключённых outputs; full-manifest total не выдаётся как count разрешённой проекции. Канонические bytes доступны отдельным admin/auditor endpoint лишь при полном праве на весь scope и отдельной операции `read_canonical_manifest`. Model card не даёт автоматически право на полевой validation report; report также фильтруется либо закрыт. Проекция может нести digest канонического manifest для корреляции, но её bytes не называются canonical manifest и не проверяются против его SHA.

`source_support_m:[250,9000]` заменяется типизированными связями `quantity/source_id/transform_id/spatial_support/temporal_support/depth`. Два числа без имени источника недостаточны. Assessment schema в contracts описывает ScientificAssessment, не заменяет все DTO и не называется production OpenAPI. До реализации endpoint требуются OpenAPI/Pydantic definitions остальных DTO; начальный implementation slice включает именно AnalysisAcceptance/JobStatus/ServingEnvelope/manifest/segment.

## ADR-02. Запрос и вычислительная идентичность

Scope Idempotency-Key: `(tenant_id, workspace_id, operation='create_analysis', client_key)`. Fingerprint — canonical запрос date+mass, endpoint/workspace и contract version; он не зависит от будущего обновления данных. Computation digest — resolved snapshot/cutoff/model/parameters/envelope/event/operation versions и private scope.

Порядок server transaction:

1. Verified principal → authorize current workspace/create_analysis.
2. Lookup idempotency record; same key/same fingerprint возвращает первоначальный request/job после повторной current authorization, same key/different fingerprint →409.
3. Для нового key разрешить доступный input snapshot/model/date policy и зафиксировать resolved context; race unique constraint переводит проигравшего в lookup, а не запускает второй run.
4. Semantic computation dedupe допустим только в пределах совместимого tenant/access scope. Private inputs не объединяются cross-tenant.

Смена snapshot требует нового request/key; UI action «Оновити дані» явно создаёт новое вычисление. Повтор HTTP после потери ACK не переоценивает latest. Текущая неполная дата показывает observed interval + forecast interval отдельно; отсутствие пригодного forecast не позволяет дорисовать оставшиеся часы как наблюдения. Idempotency binding хранится не меньше жизни request/job/result, после удаления результата сохраняется tombstone key/fingerprint/result ID: тот же key получает 410, а не новое вычисление. В пилоте tombstone удерживается до удаления workspace; UI после такого удаления не повторяет старый key. Удаление workspace отзывает его credentials; вновь созданный workspace имеет другой UUID.

## ADR-03. Tenant, workspace и site grants

Tenant RLS — только нижняя граница. Единый `ScopeAuthorizer` использует principal, tenant, workspace grants, site/asset grants, operation, valid time grant и текущую `authz_revision`. Закрытая entity без разрешённого scope возвращает единый not-found/forbidden по согласованной anti-enumeration policy.

Для LIST, total/count, series и MVT фильтр доступных entity IDs применяется в SQL до агрегации/encoding. Limit/pagination и matched total используют одну разрешённую совокупность одного snapshot. Общий raster/artifact с несколькими site scopes нельзя выдавать целиком по разрешению на один site: server строит разрешённый subset или отказывает. Публичный baseline отдельно, без приватных feature properties. Подписанный cursor содержит data snapshot, principal scope digest, workspace, filter/sort, authz revision, policy epoch и expiry. Изменение прав/epoch даёт 409 `CURSOR_SCOPE_CHANGED` и перезапуск; старый cursor не сохраняет старые grants. Истёкший cursor — 410. Total относится только к разрешённому subset той же ревизии.

Cross-tenant FK/RLS сохраняются; дополнительно API authorizer и service role обеспечивают workspace/site scope. Tiler/science worker получает только refs и scoped read credentials своего run. Export проверяет права при enqueue, compute-read и выдаче; revoked grant исключает получение уже построенного export. CMMS/notification проверяют scope при внешнем эффекте и записывают receipt.

Prefect UI/API — административная control plane, закрытая от tenant users. Ни upload, ни анализ не позволяют менять flow code, entrypoint, image, environment или secret blocks. Service identity worker не является пользовательским tenant-admin.

## ADR-04. Current policy до cache и 304

Каждый private request, включая HEAD, conditional GET, Range и tile, сначала проверяет current authz и approval/withdrawal policy. Cache hit не обходит эту проверку. Cache key включает tenant, workspace/site scope digest, current authz revision, artifact/manifest digest, layer/style/tile и contract version. Ревизия policy централизованная; stale authz cache не может жить дольше явно утверждённого окна. Для первого pilot выбран запрос к authoritative policy store на каждую private выдачу; оптимизация откладывается до измеренной нагрузки.

Transport policy pilot:

- ServingEnvelope, jobs, current status — `Cache-Control: no-store`.
- Private tiles/artifact responses — `Cache-Control: private, no-cache, max-age=0, must-revalidate`; сервер авторизует и проверяет current policy до 304.
- Public immutable baseline — долгий public cache только по public namespace без приватных атрибутов.
- Download/offline receipt содержит computed_at, policy revision, expiry и предупреждение о невозможности remote revoke downloaded bytes.

Strong ETag private bytes = SHA-256 фактической разрешённой representation после scope projection и конкретного content encoding; другой subset/encoding имеет другой validator. Digest полного manifest не является ETag его проекции. Для ServingEnvelope с `served_at` ETag не применяется. Range обслуживается по immutable authorized artifact/representation с фиксированной длиной; `If-Range` проверяет её ETag после authorization. Перед отправкой заголовков long-running download/range/stream единая middleware повторно сверяет scope, policy epoch и approval. В пилоте каждый chunk до 1 MiB / не более 1 s между проверками вновь проверяет epoch/revocation; при обнаружении утраты полномочий stream прекращается. Для уже начатого stream заявлен ограниченный lag до следующей проверки и одного buffered chunk, не нулевая задержка; уже отправленные bytes не отзываются. При недоступности policy store private response закрывается, а не использует stale grant.

Presigned URL — bearer capability, не audience-bound credential. Для чувствительного private evidence и немедленного withdrawal используется authenticated proxy. Если для больших нечувствительных private downloads разрешён presigned URL, UI/contract фиксирует конкретное maximum revocation lag=TTL; обещание instant revocation в этом режиме запрещено. Не выдавать URL с broad prefix permission. Исторический authorized view отозванной модели подписан `withdrawn`, не появляется как current.

## ADR-05. Durable prepare/publish и GC

SQL является единственным authoritative catalogue публикаций и reservations. `ObjectStorePort` обязан поддерживать immutable conditional create или эквивалент, exact-version read/head, digest verification, explicit delete(version), retention controls и непротиворечивую mapping key→version. S3-compatible label этого не доказывает: adapter проходит integration tests на выбранном провайдере.

### 5.0 Byte identity

Выбран `RFC8785-JCS`: UTF-8, детерминированная сортировка properties, ECMAScript/I-JSON числа, отсутствие whitespace; Unicode сохраняется без NFC/NFKC. JCS не нормализует Unicode и запрещает duplicate property names.[68] Перед canonicalization schema проверяет типы, UTC timestamps и units; JSON duplicate keys, NaN/Infinity, lone surrogates и целые вне безопасного диапазона отвергаются. Большие точные счётчики/decimal values имеют schema-declared string encoding. Нельзя заменить JCS на `json.dumps(sort_keys=True)`. Hash = SHA-256 канонических bytes; `sha256:` — только текстовый prefix в DTO. Output object digest считается над фактически сохранёнными bytes, включая формат/сжатие, и не подменяется JCS digest произвольного преобразования. Golden RFC vectors, Unicode/supplementary-plane ordering и Python↔browser tests обязательны до adapter release.

Filesystem adapter пишет temporary file в том же volume, fsync(file), затем `link(temp, final)` с отказом EEXIST, затем fsync(parent). Не использует заменяющий destination `rename`. Существующий final принимается только после exact SHA/size comparison. Directory — generated trusted paths без symlink, root недоступен другим writers; crash remnants удаляются только через reservations. `renameat2(RENAME_NOREPLACE)` допустим как отдельно проверенная эквивалентная реализация. Это выбранный POSIX deployment profile, не обещание для любого filesystem/Windows/NFS.

### 5.1 Reservation

1. Worker получает lease/fencing token run. Создаёт durable `ArtifactReservation` под будущие immutable final keys и upload receipts, state=preparing.
2. Записывает final immutable bytes, фиксирует version ID/SHA/size; при retry использует существующий exact object и сверяет digest. Collision с другими bytes — integrity error, не overwrite.
3. В read-after-write проверяет именно эти версии, validator reports и retention. Prepared manifest с exact refs также готов до SQL publication.
4. Reservation.state=prepared; продление reservation требует действующего run fencing token. Timeout сам по себе не разрешает GC: abandonment подтверждается SQL.

### 5.2 Commit

Одна SQL transaction блокирует run/reservation и applicable ModelApproval/PolicyRevision row; проверяет lease, cancellation, approval revision, applicability, object receipts и prepared state. Withdraw operation блокирует ту же approval row; publish не проходит с устаревшим допуском. Manifest bytes/digest и references записываются; reservations атомарно превращаются в published references, run published, outbox event committed.

`LatestPointer` key = `(tenant_id, workspace_id, authorized_dataset_scope_id, aoi_version_id, assessment_date, gross_mass_kg, assessment_mode, model_epoch)`. Mode и model epoch не сравниваются между собой: активация нового epoch — отдельная current-policy transaction, она не переносит старый result автоматически. Внутри key сравнивается tuple `(forecast_issue_time либо fixed reconstruction sentinel, knowledge_cutoff, server_request_generation)` лексикографически; generation — monotone SQL sequence per key. Equal tuple обязан иметь тот же manifest digest, иначе integrity conflict. CAS обновляет pointer только при большем tuple и текущем approval/epoch; cancelled/failed/unpublished run не участвует. Время завершения worker не используется. Старый epoch, даже с более новым cycle, не подменяет активный; новый epoch со старым cycle виден только как явно исторический до утверждённого current run. Историческая reconstruction не заменяет forecast. Mass/date contexts не спорят за глобальный pointer.

### 5.3 GC

GC не опирается на eventual object listing как источник достижимости. Он находит кандидат через SQL catalogue, берёт ту же reservation/object coordination row lock, повторно проверяет отсутствие published refs и действующих prepared reservations, а также terminal/abandoned run. В transaction ставит `delete_claimed`; publisher не может перепинить claimed version и обязан создать новую reservation/key. Затем удаляет exact version; receipt/failure записывается и повторяется идемпотентно. Grace period — дополнительная защита, не доказательство отсутствия гонки.

Object lifecycle не должен удалять reachable/prepared versions независимо от catalogue. Provider retention/permissions исключают произвольное удаление этими средствами; удаление privileged admin вне протокола — integrity incident, обнаруживается периодическим HEAD/hash audit и restore, а не скрывается в «atomic publish».

Тесты до допуска: crash после prepare до commit; GC одновременно с publish; fencing loss; approval withdrawn между validation и commit; old cycle completes late; manifest object corrupted/missing; outbox delivery повторён; exact-version delete повторён после ACK loss.

## ADR-06. Upload exact-version promotion

Upload session разрешает только quarantine key, bounded bytes/MIME и expiry. Завершение upload не является evidence approval. Receipt фиксирует exact version ID, declared SHA, observed SHA/size и session/finalize idempotency key.

Scanner/parser читает закреплённую exact version. После проверки она копируется/стримится в generated immutable promoted key с own exact-version/digest receipt; evidence revision ссылается только на promoted bytes. Последующий PUT по ещё живому quarantine URL может создать другую версию, но не меняет receipt и не становится approved. Если provider не поддерживает exact-version capture/copy, upload идёт через server-owned bounded staging и immutable promotion; этот adapter не допускает direct mutable uploads.

Finalize того же receipt повторно возвращает тот же promoted result. Same session/different digest — conflict. Нет fallback «возьмём latest uploaded object», даже если key совпадает. Retention pins удерживают bytes до завершения QA/run, затем применяются tenant policies. Original/derivative identities и EXIF stripping не смешиваются.

## ADR-07. Parser isolation

Downloader allowlist недостаточен: VRT, GDAL virtual filesystems, XML entities и sidecar references могут открыть вторичные URL/локальные пути. User-import worker:

- разрешает конкретные formats/drivers; VRT/произвольные XML/STAC href imports пользователем не допускаются;
- работает без egress и без API/DB/master-storage secrets, с минимальным read-only prepared-input mount и ограниченной output directory;
- запрещает external references, symlinks/path escape, /vsi network/cloud/exec paths и неодобренные sidecars;
- ограничивает CPU/RAM/time/temp space/decoded pixels/features и рекурсию; видит только свой quarantined batch;
- нормализует результат в безопасный внутренний формат, затем отдельно проверяет geo/units/schema и provenance;
- не получает broad shared-data mount ради удобства GDAL.

Trusted source adapters могут использовать заранее подготовленный provider VRT лишь в отдельной роли: downloader разрешает declared assets, materializes controlled files, после чего networkless parser читает local allowlisted references. Разрешение известному ISRIC VRT не переносится на uploaded VRT произвольного пользователя.

## ADR-08. G0a versus G0b

**G0a feasibility spike**, planning 2–4 календарные недели при доступных geo/science engineer и part-time reviewer: ограниченные открытые samples, local single-user script, нормализованные forcing series и immutable local artifacts, smoke UI. Исследовательский water transition допускается отдельно только при необходимых параметрах приложения10; иначе water state/recovery недоступны. Не содержит private tenants, production auth/RLS, SLA, enterprise integration или гарантии thermal model. SQLite/локальные файлы допустимы как throwaway spike; этот результат не называется полноценным вертикальным implementation slice.

**G0b первый implementation slice** — инженерный инкремент перед science G1: Postgres/PostGIS, same-origin authenticated API, один process worker, ObjectStorePort с immutable snapshots/reservations, минимальная карта известного реестра и forcing series. Выбор первого научного deliverable — **forcing-only**. Soil state, environmental category и recovery остаются unknown/unavailable с причинами, пока HydraulicParameterSet, InitialState и thermal screen не утверждены. Это не source→water→recovery демонстрация. Включает обязательные части WP05/10 с RLS/scope-authorizer/current-policy checks. Local filesystem adapter допустим только при явном deployment scope; тест такого adapter не доказывает S3. Append-only storage и квота позволяют отложить исполнение GC, но не нарушить reservations/no-overwrite.

На G0b сначала один serving path: thin entity/series API и MapLibre vector overlay на заранее ограниченном наборе; dynamic raster tiles, PMTiles build, Zarr v3, GeoParquet export, Valkey, Dask cluster и полная OTel platform не prerequisites. Prefect добавляется при scheduled ingestion/retries; single manual source spike не требует отдельной orchestration plane.

## ADR-09. Sizing и estimand

`planning-estimates.json` — научный state cube, не весь storage budget. Formula state=hydro_units×joint_trajectories×time_states×8 variables×4 bytes; segment expanded output=segments×trajectories×time_states×6 variables×4 bytes. `8/6` — явные выбранные scenario counts; они не означают native resolution или независимые samples.

Отдельные budget lines: raw input retention; normalized static assets; per-cycle scientific state; thin segment refs; serving raster/vector summaries; temporary scratch; validation archives; backup replicas; egress. Runs/day и retention tier умножаются явно; полученный raw volume не обещает compression ratio. Архитектурный raster-layer пример относится только к serving summaries. Deployment sizing остаётся гипотезой до измерения G0b.

Дневной operational summary — наиболее неблагоприятная применимая категория за локальные сутки плюс внутрисуточные series, а не вероятность хотя бы одного отказа за сутки. G2 outcome задан стандартной операцией в момент start_time; операция включает inbound/outbound masses, ordered pass counts/directions, speed/stop assumptions и completeness по механизмам. Неизвестный outbound load/traction создаёт отдельное ограничение, а не silently successful round trip.

Для наблюдаемых обычных рейсов estimand ограничивается declared operation policy и selected operating population с overlap/ascertainment. Гипотетический риск любого неосуществлённого рейса не идентифицирован автоматически. Dataset card фиксирует selection policy, причины no-attempt и вмешательства; causal/propensity перенос требует отдельных доказательств.

## ADR-10. Browser session: same-origin BFF

Пилот имеет один origin для UI, `/api`, tiles и authenticated artifact proxy. Browser не получает OAuth access/refresh tokens и не сохраняет их в localStorage/sessionStorage/IndexedDB. BFF хранит tokens server-side, запускает Authorization Code + PKCE S256, проверяет state/nonce, issuer/audience/signature/expiry и exact redirect URI. Session ID — opaque random ≥256 bits; cookie `__Host-gs_session`, Secure, HttpOnly, Path=/, без Domain, SameSite=Lax. Ротация после login/изменения привилегий; idle TTL 30 min и absolute TTL 8 h — стартовая pilot policy. Logout отзывает server session и очищает cookie; revoked grants/approval проверяются независимо от срока сессии. Нельзя запускать private serving, если IdP/policy verification не работает.

Любая mutation POST/PUT/PATCH/DELETE требует verified session, exact Origin allowlist и synchronizer CSRF token в `X-CSRF-Token`, связанный с session и отдаваемый bootstrap endpoint с no-store. Content-Type JSON; CORS credentials с wildcard запрещены. Отсутствующий/чужой Origin/CSRF — 403 до побочного эффекта; для non-browser service clients отдельная authenticated profile, не исключение по User-Agent. GET/HEAD не меняют состояние. Idempotency не заменяет CSRF. Login callback state/nonce имеет одноразовый TTL; внешние return URLs не принимаются.

MapLibre/fetch получают session cookie same-origin; токены в query strings, tile URLs и Referer запрещены. Нет credentialed cross-origin tile host. CSP ограничивает script/connect/img/worker origins согласованной сборкой; персональные evidence не загружаются внешними analytics SDK. Нужны тесты login/logout, fixation, CSRF/Origin, stale epoch, cookie flags, tile/range/HEAD/304 и concurrency session revocation. Это требования, не выполненный pentest.

## ADR-11. Restore без воскрешения прав

После DB/object restore закрыты все private serving и mutations; health check остаётся maintenance, не ready. Доверие к восстановленной policy DB само по себе недостаточно. Процедура:

1. Проверить backup hashes/SQL↔object references; согласовать encryption material. Восстановленный run не получает lease от старого heartbeat.
2. Создать новый deployment/policy epoch вне восстановленного snapshot; инвалидировать все browser sessions, worker leases/fencing tokens, cursors, authz/approval caches и signed capabilities. Перерегистрировать workers, повторный login обязателен.
3. Сверить IdP membership и durable audit/withdrawal/deletion tombstones после backup cutoff. При полном audit применить отозванные grants/approvals и удаления, затем пересчитать eligibility. Пока нельзя доказать полноту audit, все grants/model approvals остаются disabled; owner вручную переаттестует каждый workspace/site/model scope. Старый approved=true не принимается.
4. Quarantined/withdrawn/deleted evidence не возвращается в ingestion/features. Missing original остаётся tombstone и блокирует зависимый quantitative release до impact review. Уже собранные exports проходят повторный current-policy check.
5. Проверить отрицательные restore fixtures: grant revoked после backup; model withdrawn после backup; private photo deleted; active stream/cursor/lease из старого epoch. Только отдельный RestoreReceipt с перечнем reattested scopes открывает выдачу этих scopes.

Неподтверждённые scopes остаются закрытыми, даже если это нарушает RTO target. В пилоте ручная повторная аттестация допустима; отдельный distributed permission ledger не требуется. RPO/RTO не дают права игнорировать revocations.

## Sources

[68] https://www.rfc-editor.org/rfc/rfc8785 — RFC 8785 JSON Canonicalization Scheme
    > "JSON objects MUST NOT exhibit duplicate property names."
    > "JCS-compliant string processing does not take this into consideration. That is, all components involved in a scheme depending on JCS MUST preserve Unicode string data "as is"."
