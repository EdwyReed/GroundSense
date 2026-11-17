# V8 — датированное спутниковое наблюдение в выбранном участке

## Пользовательский результат

Продолжает `inputs/user-requirements-extract.md` (доступ к скважине через поле/лес после дождя и зимой) и `design/route-planner-v2/DESIGN.md`: карта остаётся главным экраном, новых обязательных входов нет. В существующем инспекторе выбранного off-road участка появляется компактное **«Супутникове спостереження»** из Sentinel-2 L2A Scene Classification (SCL). Показать дату/давность, фактический класс и размер родной ячейки, отсутствие наблюдения и облака/тени/снег. Нельзя назвать неводный класс «сухо», снег «промёрзло», облака «воды нет», или старую сцену текущим затоплением. Проходимость и ширина коридора остаются неизвестными.

## Объём и ограничения

- Только midpoint выбранного server-owned участка terrain_transect через существующий `/api/v1/route-context`; не новая геометрия или endpoint. Road mode не обращается к этому источнику.
- Один фиксированный Earth Search POST: collection sentinel-2-l2a, point intersects, до 12 результатов, datetime descending. Просмотрено <=12; не пагинировать и не утверждать глобально самое свежее/безоблачное наблюдение. Выбрать наиболее позднюю валидную UTC сцену среди ответа; не перебирать старые сцены ради зелёного статуса.
- Поиск в десятидневном lookback относительно min(trip_date, retrieval UTC date), не позже конца выбранной даты **и фактического retrieval instant**. Будущие/старые/невалидные timestamps отсеять локально. Дата поезда в будущем не создаёт спутникового прогноза.
- HTTP response streaming <=1 MiB, timeout <=12 s; SCL только один COG, один native 1x1 read, GDAL timeout/no retries/no directory scans; allowlisted canonical HTTPS public S3 asset, без credentials/query/fragment/custom port. HTTP/STAC redirects запрещены; GDAL COG transport может следовать redirects самого доверенного хранилища: документированного запрета не установлено, нулевые redirects для него не заявляются. Использовать существующий RemoteSources endpoint/allowlist/evidence primitives; не запускать полный legacy read с ERA5/IFS/SAR/RGB.
- WGS84 -> native CRS, exact row/col (включая края), no clamping, explicit bounds. Masked/NoData/NaN/Inf/fractional/out-of-range SCL остаются unknown, не int-truncation/zero. Scale/offset/native metadata проверять и сохранять; unexpected SCL scaling не интерпретировать. Native resolution_m только при установленной метрической единице.
- Constructor network-free. Бounded <=64 cache entries/five minutes, deepcopy, защищённая сериализация cold reads. Raw catalogue и pixel evidence hashed, strict finite JSON. Повторный cached route-context не вызывает I/O/бюджет; существующие workspace/CSRF/Origin/body/queue/source-budget gates сохранены. Ошибки source изолированы, безопасны и не скрывают почву/DSM/погоду. Signed URL/исключения в DTO не раскрывать.

## Контракт для двух независимых владельцев

`apps/api/surface_observation.py`: `SurfaceObservation(cache_dir, *, transport=None, clock=None)`; `read_point(latitude, longitude, assessment_date) -> (observation, source)`.

Добавочный top-level `surface_observation` только в off-road response:

```json
{
  "status": "available",
  "basis": "sentinel2_l2a_scl_point",
  "assessment_date": "2026-10-26",
  "requested_point": {"latitude": 59.985, "longitude": 10.734},
  "observed_at": "2026-10-25T10:35:00Z",
  "retrieved_at": "2026-10-26T12:00:00Z",
  "scene_age_days": 1,
  "scene_id": "native-scene-id",
  "scl_class": 6,
  "condition": "water",
  "resolution_m": 20,
  "selection_scope": "bounded_catalogue_result"
}
```

Неизвестные поля — null, `condition: unknown`, `status: unavailable/partial`, не fabricated scene. SCL4 vegetation,5 not_vegetated,6 water: available classification; 2/3 shadow,8/9/10 cloud,11 snow_ice: partial;0/1/7 и invalid: unknown/partial. Condition сам по себе не оценка поверхности на дату поездки. Сохранить точный код (или null для invalid), не только объяснение. Source id `sentinel-2-l2a`, extraction_scope `scene_classification_point`, observed/retrieved/digest, product/provider/selection limits, native row/col/crs/transform/raw class и window в data/evidence.

Frontend: optional typed field, отдельный compact `SurfaceObservation.vue`, внутри существующего `SectionContext.vue` перед weather-day. Проверить basis, assessment_date, scene timestamps <=retrieval and selected UTC day, strict integer class/condition agreement, finite positive resolution и server selected point binding перед отображением числового класса. При malformed/stale/error показать unknown, не старый water/clear/snow. Смена участка/даты/плана очищает card; late response прежнего участка не возвращает его. Источник доступен в existing disclosure; не показывать fake photo или новый водный map overlay.

## Приёмка

1. RED→GREEN: native 1x1 local raster fixtures для water, cloud/shadow/snow, zero/NoData/NaN, projected CRS и edge/outside; timestamps/future/no-scene, response bounds, asset rejection, finite digest, cache и ошибки.
2. Existing-route integration: exact server sample, off-road only, source fail preserves other data; cached/foreign/CSRF/oversize остаются guarded.
3. UI: date/class/native resolution, cloudy != dry, nonwater != dry, future != observation forecast, malformed and late/stale clearing, no extra frontend request; desktop/mobile no overflow and original map-first layout.
4. Genuine public non-operational Norway read independently replayed from native SCL pixel, raw evidence/digest проверены; real cloud/absence допустимы и не заменяются fixture. Existing off-road/profile/cover/weather/road regressions сохранены. Скриншоты до/после и receipt под `qa/route-v2/wakeup10-*`.

## Семантика источника

Официальная SCL — классификация сцены с кодами0–11; native map производится при20м и может пересчитываться в60м. UI показывает разрешение реально прочитанного растра, а не обещает20м без metadata.[1]

Даже класс5 NOT_VEGETATED не доказывает отсутствие облаков или воды: документация отмечает пропуск низких облаков/тумана с классификацией «not vegetated». Поэтому вывод остаётся датированным классом пикселя, а состояние поверхности/проходимость не выводятся.[2]

Реальный native prepublish контроль Норвегии вернул `S2A_32VNM_20261025_0_L2A`,2026-10-25T10:44:25.821000Z, EPSG:32632,20×20м, SCL8. Это облачное наблюдение, а не прочитанный грунт под ним; receipt `qa/route-v2/wakeup10-surface-native-prepublish.json`.

## Sources

[1] https://sentiwiki.copernicus.eu/web/s2-processing.md
[2] https://sentiwiki.copernicus.eu/web/s2-products
