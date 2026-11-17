# Контракт реального открытого среза

Цель: основной интерфейс показывает настоящую картографию и загруженные внешние модельные данные; никаких seed-скважин, вымышленных дорог, случайных статусов и fallback на синтетику. Старый стенд остаётся только явно отдельным тестовым режимом. UI — украинский, существующие IBM Plex/зелёно-серые стили, без редизайна бренда.

## Карта

MapLibre 6, same-origin emitted worker. Style `https://tiles.openfreemap.org/styles/liberty`; проверять его зависимости и разрешать CSP только требуемые hosts. Статическая видимая attribution OpenFreeMap / OpenMapTiles / OpenStreetMap, без вставки непроверенного HTML. Начальный вид — общий обзор Европы, не выдуманные промышленные объекты. Клик по карте выбирает фактические координаты; числовые поля широты/долготы позволяют выбрать точку точно. Сохранённые пользовательские точки — отдельный реестр, не утверждение идентичности/состояния скважины.

## API

Все endpoint `/api/v1/live/*`, same-origin. Реальный bootstrap не вызывает clone_seed. Изолированная browser session/CSRF сохраняется. UI получает только real-assets, не legacy seed-assets. Промышленные конфиденциальные данные на публичный прототип не загружать.

- GET `/api/v1/live/bootstrap` -> `{workspace:{id,mode:'public_data',synthetic:false,private_data_allowed:false},csrf_token,user:{role},assets:[LiveAsset],sources:[...],today:'YYYY-MM-DD'}`.
- POST `/api/v1/live/assets` JSON `{name,latitude,longitude,source_ref}` -> 201 `LiveAsset` `{id,version,name,latitude,longitude,geometry:{type:'Point',coordinates:[lon,lat]},source_ref,synthetic:false,data_origin:'user_supplied',condition:'unknown'}`. Имя и source_ref обязательны. Никакого утверждения измеренной/верифицированной идентичности. Хранить в Resource.kind=`live_assets`.
- POST `/api/v1/live/assets/import` JSON `{format:'csv'|'geojson',data:string}` -> 201 `{items:[LiveAsset],imported:N}`. Атомарно, не более 1000 валидных точек, только Point. CSV колонки name,latitude,longitude,source_ref; GeoJSON FeatureCollection с properties.name/source_ref. Без пустых/некорректных координат и без подстановки default. Подготовит родитель.
- GET `/api/v1/live/weather?latitude=...&longitude=...&assessment_date=YYYY-MM-DD` -> ниже. При выходе даты за доступный горизонт 422; upstream failure/invalid units/schema 502/503, никакой синтетической подстановки. Запросы ограничены/cached. Сохраняется подлинный raw JSON и digest, права доступа к snapshot — по workspace.
- GET `/api/v1/live/weather/snapshots/{hex_sha256}` -> подлинный сохранённый JSON только запросившего workspace.

## Weather DTO

```
{
 mode:'live', synthetic:false, assessment_date:'YYYY-MM-DD',
 requested_point:{latitude:number,longitude:number},
 grid_point:{latitude:number,longitude:number,elevation_m:number|null},
 source:{id:'open-meteo-icon-global',provider:'Open-Meteo',product:'DWD ICON Global via Open-Meteo',model:'icon_global',request_url:string,retrieved_at:ISO_UTC,issue_time:null,license:'CC BY 4.0',service_usage:'non_commercial_prototype',attribution_url:'https://open-meteo.com/',content_sha256:'sha256:'+hex,cached:boolean},
 units:{temperature_2m:'°C',precipitation:'mm',soil_moisture_0_to_1cm:'m³/m³',soil_moisture_1_to_3cm:'m³/m³',soil_temperature_0cm:'°C'},
 series:[{time:ISO_UTC,temperature_2m:number|null,precipitation:number|null,soil_moisture_0_to_1cm:number|null,soil_moisture_1_to_3cm:number|null,soil_temperature_0cm:number|null,precipitation_interval_start:ISO_UTC,precipitation_interval_end:ISO_UTC}],
 qc:{status:'available'|'partial',missing_variables:string[],is_observation:false,spatial_support:'model_grid_not_road'},
 mobility:{kind:'unavailable',reason:string}
}
```

Ключи переменных ровно как у API. `series` — доступные почасовые значения выбранной UTC-даты; осадки относятся к предыдущему часу. Не суммировать их как полные календарные сутки без корректной полноты/границ. Нет issue time в API — не выдумывать его из retrieval/generationtime_ms. ICON API почасовой ряд может быть интерполирован; это не нативная частота всех полей и не измерения на дороге. Отсутствующие значения null, ноль не подставлять. Влажность — модельный слой 0–1/1–3 см, не измеренная несущая способность. Никаких вычисленных вероятностей или water/recovery из неизвестных параметров.

Реальные чтения endpoint с этими переменными, `models=icon_global`, `forecast_days=7`, `timezone=UTC` на публичной точке Осло уже вернули HTTP200, правильные units и численные значения. Финальный QA обязан выполнить реальный read-back, не выдавать моки за доступный источник.

## Модуль backend для независимой реализации

`apps/api/live_data.py`:
- `LiveDataError(status_code:int, message:str)`.
- `LiveWeatherClient(cache_dir:Path, ..., transport=None)` с `forecast(latitude,longitude,assessment_date=None)->WeatherDTO` и `snapshot_path(hex_digest)->Path`. Зафиксировать Open-Meteo URL/параметры, конечные bounds/units, отсутствие NaN/bool numeric, API error handling/timeout/no redirects, bounded cache (fresh only, no stale fallback). Честные retrieval metadata и raw digest. Родитель интегрирует маршруты/session/ACL в main.py; модуль не меняет main.py.
- Не добавлять зависимости: httpx/stdlib уже установлены.

## Frontend для независимой реализации

Новые `components/LiveWorkspace.vue`, `RealMap.vue`, `LiveWeatherChart.vue`, `lib/liveData.ts` и их тесты. Не менять App.vue/старые компоненты/global style — это интеграция родителя. LiveWorkspace сам получает live/bootstrap, создаёт ApiClient и работает с endpoint выше; emit `open-synthetic` для отдельного стенда. Заголовок GroundSense + реальные вкладки карта/объекты/данные/источники, кнопка отдельного тестового режима. Не показывать несуществующий industrial registry: пустое состояние и импорт CSV/GeoJSON. При смене точки/даты немедленно очищать прежние значения, AbortController/generation guard для late responses. Видимые loading/error/retry, не переносить данные другой точки. Погода/грунт/источники/единицы/UTC/получено/модель/digest и download snapshot — доступны без JSON как основного UI. Масса может быть контекстом, но не менять реальную погоду и не давать допуска.

Open-Meteo public endpoint используется только для некоммерческого прототипа; его нельзя объявлять разрешённой коммерческой интеграцией. Указать ограничение и attribution в UI/источниках. Ключи/аккаунты этому срезу не нужны. No OIDC/production certification claims.
