> Исследовательское приложение. Нормативные решения, API enums и более поздние исправления задаёт [основная спецификация](../GROUNDSENSE-SPEC.md). Общий реестр ссылок — [SOURCES.md](SOURCES.md). Числа sizing, SLO и sample size — проектные гипотезы, если явно не указано иное.

# GroundSense: проверенные источники данных

**Проверка выполнена:** 2026-10-24.  
**Назначение:** гражданская промышленная доступность объектов (включая скважины и площадки) в пилоте Харьковской области. Этот документ — инвентарь источников и контрактов данных, **не** результат расчёта проходимости. Здесь нет маршрутов, координат объектов, оценки конкретных дорог или анализа FPV.

## Краткий вывод

Для пилота есть жизнеспособный открытый контур: Sentinel-1/2 для наблюдаемых признаков поверхности, CLMS SWI/SSM для фоновой влажности, SoilGrids/HWSD для свойств грунта, DEM для рельефа, ERA5-Land для истории, а открытые прогнозы — для сценариев осадков/температуры. Однако ни один подтверждённый источник не измеряет несущую способность дорожного полотна, материал подсыпки, колейность или наличие каждой полевой/лесной дороги. Выход модели должен быть региональным индексом состояния и неопределённости; эксплуатационные решения требуют собственных полевых наблюдений и валидации.

«Открытые данные» не означают «бесплатный hosted API для коммерческого продукта»: особенно это касается Open-Meteo, CDSE processing/download-квот и сервисного уровня DWD.

## Матрица пригодности

| Источник | Покрытие Харьковской области | Время / latency | Нативная поддержка в задаче | Подтверждённые поля / единицы / QC | Доступ, лицензия, риск и роль |
|---|---|---|---|---|---|
| Sentinel-1 GRD | Миссия/коллекция глобальная; доступность конкретной сцены проверяется STAC | CDSE указывает ожидаемые 24 ч после съёмки для S1/S2; в S1 API есть классы `NRT10m`, `NRT1h`, `NRT3h`, `Fast24h` | Прокси: обратное рассеяние поверхности; не измерение проходимости | GRD: VV/VH для типичного IW; high pixel spacing 10 m (IW/SM), EW 25 m. Processing: calibration + thermal-noise removal; опционально speckle, RTC и orthorectification | CDSE/STAC для discovery; обработка требует учитывать квоты/аутентификацию сервиса. Нужны единая геометрия, поляризация, orbit direction, incidence-angle/QC, маски воды/снега/растительности. Роль: временной признак, не «влажность дороги». [17][19][16] |
| Sentinel-2 L2A | Глобально; следовательно, Украина входит. STAC smoke-probe реально вернул L2A item (но в Берлине, не на пилоте) | Ожидаемая доступность CDSE — 24 ч после съёмки; повторяемость миссии в документации: 5 дней с двумя спутниками, 2–3 дня на средних широтах | Прокси: поверхность, растительность, вода/снег/облака; оптика не работает под облаком | MSI имеет 13 bands, но это не inventory каждого L2A: B10 нельзя автоматически ожидать в surface-reflectance assets. Проверяется manifest выбранной processing baseline; L2A reflectance, AOT, WV, SCL; SCL не является строгой картой land cover. В проверенном item есть `eo:cloud_cover=95.85`, B02/B03/B04 10 m и AOT assets | Использовать L2A + SCL/облачные маски и отклонять невалидные сцены; не интерполировать категориальные SCL. Роль: QC/контекст, не датчик несущей способности. [18][19] |
| CLMS SWI 1 km v2 | Продукт заявлен для Europe; страница не перечисляет страны. Украина не названа явно, поэтому покрытие пилота надо подтвердить по конкретному тайлу/API перед включением в production | Daily; 2025-07-13—present; timeliness: within 2 days after observation | Фоновое увлажнение на глубинных индексах, не узкая дорога | EPSG:4326; 1°/112 (~1 km); validated; Sentinel-1 C-SAR + Metop ASCAT. Недавний дефект spatial shift с 2025-07-14 исправлен v2.1.1, revised archive/NRT заявлен с 2026-02-23 | CDSE Browser/OData/S3/CSV. Роль: крупномасштабный влажностный prior и QC, не road-level классификатор. Версию и product baseline хранить на каждое значение. [20][21] |
| CLMS SSM 1 km | Europe-портфель; отдельная country/tile-проверка требуется так же, как для SWI | Связь с SWI подтверждена портфелем: SSM — относительная вода верхних нескольких см; точные поля/латентность конкретной версии в этом проходе не извлекались | Поверхностная влажность, не подстилающий слой | Не заявлять единицы, QC-флаги или latency без product metadata выбранной версии | Роль: кандидат на input SWI/поверхностного индекса после отдельного metadata gate. [20] |
| SoilGrids | Global — Украина покрыта по заявлению «global» | Статический/периодически обновляемый слой; не NRT | Свойства естественного грунта вокруг объекта | 250 m; шесть standard depth intervals; pH, SOC, bulk density, coarse fragments, sand/silt/clay, CEC, N, SOC density/stock. Неопределённость: 90% prediction interval (`Q0.05`, `Q0.95`) и relative uncertainty. Единицы и точные глубины каждого band надо читать из metadata конкретного COG/VRT, не угадывать | CC-BY 4.0. REST API временно paused, beta, без гарантии uptime; подтверждённые fallback: WCS, WebDAV/VRT, WMS, GEE. Smoke WMS endpoint ответил HTTP 200, но MapServer вернул `msLoadMap` error: это **не** успешная проверка растра. Роль: долговременный soil prior; не свойства насыпи дороги. [22] |
| HWSD v2.0 | Global; технический отчёт прямо упоминает Ukraine среди reviewed national soil data | Историко-статический, не оперативный | Классы/свойства грунта как второй источник | ~1 km / 30 arc-second; raster BIL, unsigned 16-bit map-unit id + MS Access attribute DB; атрибуты для семи depth layers. Не путать map-unit id с непрерывным свойством участка | Отчёт имеет NC-SA; права конкретных downloadable data files здесь не установлены. Исключить из обязательного commercial pipeline до dataset-specific legal clearance. Роль: историческая сверка SoilGrids и provenance, не единственный production-source. [23][24] |
| ESDAC EUDASM Ukraine | Прямо подтверждена карточка `Soil Map of Ukraine`, Ukraine, 1977, author Voronina et al.; изображение доступно без регистрации | 1977, скан исторической карты | Исторический тематический контекст | Подтверждены только наличие скана и библиографические метаданные; не подтверждены в этом проходе машиночитаемые классы, масштаб, геопривязка, лицензия reuse | Не использовать как автоматический raster feature, пока не проверены права, georeferencing и легенда. ESDAC-коллекция содержит >5400 сканов; это не доказательство единообразной лицензии. [25] |
| Copernicus DEM | EEA-10 покрывает 39 европейских стран; страница не подтверждает явно Ukraine. GLO-30/GLO-90 — global, поэтому безопасный путь для пилота — GLO-30 | Съёмки TanDEM-X 2011–2015, с local gap filling; не оперативный | Уклон, относительный рельеф, гидрологические производные | Это **DSM**, включает здания, инфраструктуру и растительность; DTM удаляет их. GLO-30: 30 m, глобальный; GLO-90: 90 m. Vertical unit m (EGM2008); HEM/WBM/editing/filling masks доступны | GLO-30/90 free license worldwide, но доступ/download зависит от категории зарегистрированного пользователя; EEA-10 download ограничен. Не трактовать DSM slope под лесным пологом как bare-earth DTM. Роль: рельеф/дренаж + quality masks. [26] |
| CLC / land cover | Pan-European продукт, но страница не утверждает Украину поимённо: tile/coverage check обязателен | 1990, 2000, 2006, 2012, 2018; 6-yearly, наиболее позднее на странице — 2018 | Land-cover контекст | 44 класса; 100 m raster/vector; areal MMU 25 ha, linear minimum width 100 m | Подходит для грубой стратификации, не для узких подъездов. Роль: статический context/QC. [27] |
| CLMS HRL Tree Cover Density | У продукта coverage EEA38 (2021), а не глобальный; **Украина не должна считаться покрытой без явной tile-проверки** | Reference years 2018/2021, не оперативный | Полог/затенение как контекст | TCD: 10 m, 0 = non-tree, 1–100 = % tree-cover density, 255 = outside; COG; validation report указывает target ≥90% producer/user accuracy | Не подтверждён тайл для Харьковской области. Роль: optional canopy prior только после coverage check; fallback — S2 L2A/SCL как временный контекст, но это не canopy-height product. [36][18] |
| ERA5-Land | Global; Украина покрыта | Jan 1950—present, hourly, daily update frequency. Это reanalysis, не forecast; точная operational latency в catalogue page не указана | История погоды/водно-тепловой фон | Regular lat/lon 0.1°, native ~9 km; soil layers: 0–7, 7–28, 28–100, 100–289 cm; глубина до 289 cm. Model estimates имеют uncertainty; можно использовать uncertainty equivalent ERA5 fields | Для total precipitation важно различать ERA5 и ERA5-Land: hourly ERA5 обычно содержит часовой accumulation, а ERA5-Land hourly — накопление от 00 UTC внутри forecast cycle. Для ERA5-Land получаем часовой прирост разностью соседних шагов одного цикла, на первом шаге берём значение; следующий 00 UTC содержит сумму предшествующих суток. Перевод m → mm = ×1000; локальные сутки собираются после deaccumulation и timezone conversion. Роль: history/forcing, не road-scale observation. [28][37] |
| ECMWF Open Data IFS/AIFS | Global forecast subset; покрытие Украины логически глобальное | Real-time, 4 cycles (00/06/12/18), rolling 12 runs ≈2–3 дня в public archive; medium range до 15 дней. 0.1° IFS публикуется примерно на 2 ч позже 0.25° | Forecast precipitation, temperature, snow, soil water/temperature (поля зависят от subset) и ensemble/probability | GRIB2; IFS 0.25° и 0.1° (с 2026-10-20), AIFS 0.25°. Подтверждены IFS control/perturbed ensemble и soil water / soil temperature levels 1–4; нельзя подменять это локальной почвенной валидацией | Subset CC-BY 4.0 с attribution. Доступ лимитирован 500–2000 simultaneous connections; fallback replicas AWS/Azure/GCP. Роль: основной open probabilistic forecast, обязательно cache/retain собственные runs. [29] |
| DWD Open Data / ICON | Open-data server содержит model forecasts; конкретный global ICON grid/field/lead-time для Ukraine должен быть закреплён по directory metadata | Оперативный, но service/availability не гарантируются | Резервный forecast provider | Подтверждено наличие model forecasts, radar, observations; конкретные поля/единицы в этой проверке не извлекались | Mostly free of charge, но DWD явно предлагает secure geospatial service для business/management с требованием более высокой continuity. Роль: fallback/ensemble diversity, не SLA-free production API. [30] |
| NOAA GFS | Global; Украина покрыта | 4 cycles/day 00/06/12/18; 0.25° forecast 3-hourly to +384 h; trailing 30-day high-res window | Резервный meteorological forcing | Температура, ветер, осадки, soil moisture среди десятков atmosphere/land-soil variables. NODD 0.25°/0.5°. Не выдавать GFS soil moisture за измеренную влажность на дороге | Public NODD/AWS, no sign-up used in this check. Роль: open fallback и model-spread, не ground truth. [31] |
| Open-Meteo | API point/grid aggregation; не отдельный первичный набор наблюдений | Ответ smoke-probe для Berlin вернул hourly temperature °C и precipitation mm; использовался только как технический sample | Удобный aggregator, не первичный authoritative archive | Free API: 10,000 calls/day, 5,000/hour, 600/min; terms disclaim accuracy/availability | Free tier **non-commercial only**. Для коммерческого GroundSense нужен paid API subscription или прямые поставщики. Роль: только dev/prototype без коммерческого запуска либо paid integration. [32] |
| OpenStreetMap + Geofabrik | OSM contributor-dependent: нельзя утверждать полноту «всех дорог». Geofabrik публикует Ukraine (with Crimea) extract; subregions на странице не определены | Live/community-maintained; Geofabrik daily extract/update files | Инвентаризация известных mapped объектов/дорог, не доказательство существования/состояния | Подтверждены PBF, SHP/GPKG extracts; 2026-10-24 page: PBF 840 MB, latest data timestamp 2026-10-23T20:20:51Z — **не скачан** | ODbL 1.0: attribution и share-alike/database obligations при распространении производной БД. OSMF не предоставляет бесплатный third-party map API/tiles: self-host/cache extracts; не строить production на public tiles. Роль: baseline network + explicit completeness/confidence field. [33][35] |

## Sentinel: минимальный воспроизводимый preprocessing

### Sentinel-1

1. Ищем scene metadata через CDSE STAC; фиксируем item id, acquisition datetime, orbit direction, `sar:instrument_mode`, polarization, `s1:resolution`, `s1:timeliness`, processing baseline/asset href, а также AOI version. CDSE STAC — отдельный discovery API и не заменяет OData. [16][17]
2. Для сравнимых временных рядов не смешиваем orbit direction, IW/EW и VV/VH с другими геометриями. Pixel spacing 10 m — не доказательство 10-m физической точности или видимости дороги.
3. Зафиксированная processing-chain: calibration + thermal-noise removal; далее осознанно выбираем/логируем speckle filter, `gamma0_terrain`+RTC, DEM и orthorectification. RTC требует orthorectification; default speckle filter в API — `NONE`. [17]
4. В model store сохраняем linear backscatter, а dB получаем только явно как `10 log10(linear)` с защитой от нуля; dB не смешивать с linear в feature store. Это инженерное правило, не отдельная product claim.
5. QC: border/no-data, layover/shadow, water/snow, vegetation, rain-at-acquisition, temporal outlier, DEM/RTC flags. Полученный сигнал — proxy поверхности; он не является измерением CBR, rut depth или допустимой массы.

### Sentinel-2

1. Предпочтительно L2A. Он содержит atmospherically corrected SR, AOT, WV и SCL; bands/resampling 10/20/60 m. [18]
2. Cloud/shadow/snow QC обязателен: SCL применяем nearest-neighbour, не используем как строгий land-cover layer. Облачность следует проверять по пиксельной/масочной информации, не только tile-level `eo:cloud_cover`.
3. Для time series фиксируем `processingBaseline`/Collection и scene id. В smoke-probe `s2:processing_baseline` оказался `null`: следовательно, pipeline обязан допускать отсутствие поля и брать baseline из полного metadata/manifest, а не считать его гарантированным.

## Почва и исторические карты

### SoilGrids: нужны metadata-first и uncertainty-first

Перед загрузкой каждого нужного свойства открыть его VRT/COG metadata и записать: product/release, depth label, statistic (`Q0.05`, `Q0.5`, `Q0.95`), `scale_factor`, `nodata`, unit и CRS. Документация подтверждает свойства, 250 m, шесть интервалов и 90% interval, но не оправдывает перенос единиц «по памяти» между band-ами. [22]

Для GroundSense хранить как минимум `clay`, `sand`, `silt`, `bdod`/bulk density, `cfvo`/coarse fragments, SOC и соответствующие lower/median/upper; модель должна передавать uncertainty в конечный confidence. REST API не является production dependency: он presently paused, beta и без uptime guarantee; использовать WCS/обрезку или зеркальный versioned cache после правовой и технической оценки. [22]

### HWSD и ESDAC

HWSD полезен как историческая map-unit/attribute база и согласование классов, но license в техническом отчёте NC-SA не следует автоматически считать лицензией каждого файла датасета. Поэтому dataset-specific коммерческие права остаются непроверенными, HWSD исключается из обязательного production пути до clearance. Источники могут разделять исходные обследования с SoilGrids, потому независимость не предполагается. ESDAC содержит реально доступный скан Soil Map of Ukraine 1977 без регистрации, но это не лицензия на машиночитаемое производное и не evidence точного локального состава. [24][25]

## Рельеф, land cover и лес

Copernicus DEM — DSM: деревья входят в высоту. Для полей/лесополос это принципиально: не рассчитывать bare-earth уклон/flow accumulation из него без масок и чувствительности к canopy. GLO-30 — реалистичный общий baseline, но 2011–2015 acquisition era и 30 m не отражают современные насыпи/колеи. Использовать HEM, WBM, filling/edit masks в QC. [26]

CLC годится для broad class (лес/сельхоз/urban), но MMU 25 ha и 100 m raster не покрывают узкие дороги. TCD 10 m имеет подходящую семантику canopy %, но его заявленное покрытие EEA38 не подтверждает Украину: сначала проверить tiles. Не использовать «отсутствие пикселя» как отсутствие полога. [27][36]

## Погода и водный баланс

**History:** ERA5-Land применяется для ретроспективного forcing и base climatology. Spatial grid ~9 km и model-only land estimate исключают использование как локального датчика дороги. Soil layers указаны выше; все accumulations конвертировать по dataset-specific ECMWF rules, не вычитать соседние forecast steps по аналогии с reanalysis. [28][37]

**Forecast:** первичный открытый вариант — ECMWF IFS/AIFS Open Data с control+perturbed ensemble и вероятностными product fields. Для доступности нужны retries, local cache и запасной источник (DWD ICON, GFS), потому open portal ограничивает simultaneous connections и хранит лишь короткий rolling archive. Нельзя обещать user «бесплатный коммерческий API» на основании того, что данные открыты. [29][30][31]

**Open-Meteo:** free tier годится только для non-commercial use. Для платного сервиса — subscription либо прямые ECMWF/DWD/NOAA/Copernicus paths. [32]

## OSM: честный контракт на сеть

OSM — reference network, а не ground truth. В production на каждый segment следует хранить: `osm_id`, extract timestamp, `highway`, `surface`, `tracktype`, `access`, `smoothness`, `width`, `maxweight`, `bridge`, `ford`, `source:*`, version/change timestamp и missing-tag flags. Полноту и правильность нельзя вывести из лицензии, одного extract или наличия `highway=track`.

Для bulk ingestion скачать один фиксированный PBF/replication sequence, обработать локально, хранить attribution и применить ODbL assessment к распространению полученной database. Не полагаться на public OSM tile/API: OSMF прямо не предоставляет free-of-charge map API/tiles для третьих лиц. Geofabrik Ukraine extract подтверждён, но это национальный архив, а не готовый coverage guarantee для Харьковской области. [33][35]

## Что именно подтверждают smoke-probes

`probes.json` содержит сырой, read-only результат:

1. CDSE STAC root: HTTP 200; `stac_version=1.0.0`, title `Copernicus Data Space Ecosystem (CDSE) asset-level STAC catalogue`, есть `search` links.
2. Metadata-only STAC search на публичный bbox Berlin, 2026-10-01…24: HTTP 200, один S2 L2A item, datetime, cloud cover и band asset keys. Ни asset, ни imagery не скачивались.
3. SoilGrids WMS GetCapabilities: HTTP 200, **но тело — MapServer `msLoadMap` error**, поэтому это отрицательный result для usable raster metadata, а не подтверждение доступного WMS. SoilGrids WCS/WebDAV остаются документированными fallback, но не smoke-tested здесь.
4. Weather sample: Open-Meteo Berlin (не Украина) HTTP 200; получены units °C/mm и один hourly sample. Это проверка формы ответа, не прогноз и не анализ доступности.

## Production gate / fallback

| Контракт | Primary | Fallback | Блокер/правило |
|---|---|---|---|
| EO discovery | CDSE STAC | CDSE OData | token/quotas и item metadata versioning |
| S1 feature | GRD preprocessing, logged | предыдущая валидная дата с age penalty | не восстанавливать «дорогу» из отсутствующей сцены |
| Soil prior | SoilGrids versioned WCS/WebDAV cache | HWSD только после legal clearance | REST paused; uncertainty mandatory |
| Terrain | COP-DEM GLO-30 + masks | approved local bare-earth DTM, если появится | DSM ≠ DTM |
| Land/canopy | ESA WorldCover 2020/2021 static context | verified TCD tile / S2 context | WorldCover не текущая карта 2026; не обещать TCD Ukraine coverage без tile check |
| Historic forcing | ERA5-Land | retained local cache | deaccumulate per documentation |
| Forecast | ECMWF Open Data | DWD ICON + NOAA GFS | retain own runs; no assumed SLA |
| Roads/assets | OSM PBF local import | owner-maintained asset/road registry | OSM not complete; no all-roads claim |

## Границы вывода

Допустимы: региональные карты факторов, давности данных, QC/uncertainty, мониторинг availability объектов и validation workflow. Нельзя выдавать: факт проходимости конкретной полевой или лесной дороги, допустимую массу, состояние покрытия, «все дороги покрыты», или безопасность какого-либо маршрута — без ground observations, обследования и эксплуатационного контекста.

## Evidence и источники

- `sources.json` — URL, title, evidence path, verbatim quote, перечень поддерживаемых claims и статус fetch для 22 первичных источников.
- `evidence/` — извлечённые тексты страниц; `evidence/tcd.pdf` — исходный publisher PDF, для которого в среде нет PDF text extractor; `evidence/tcd.txt` содержит проверяемый excerpt.
- [16] `https://documentation.dataspace.copernicus.eu/APIs/STAC.html`
- [17] `https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html`
- [18] `https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html`
- [19] `https://documentation.dataspace.copernicus.eu/FAQ.html`
- [20] `https://land.copernicus.eu/en/products/soil-moisture/daily-soil-water-index-europe-1km-v2`
- [21] `https://land.copernicus.eu/en/production-updates/fix-of-spatial-shift-in-soil-water-index-1km-v2-product`
- [22] `https://docs.isric.org/globaldata/soilgrids/`
- [23] `https://www.fao.org/land-water/resources/tools/databases/hwsd/en`
- [24] `https://openknowledge.fao.org/server/api/core/bitstreams/149f1562-bf6a-439f-9d3a-eb93940f39cf/content`
- [25] `https://esdac.jrc.ec.europa.eu/content/title-russia-soil-map-ukraine`
- [26] `https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM`
- [27] `https://land.copernicus.eu/en/products/corine-land-cover`
- [36] `https://land.copernicus.eu/en/technical-library/validation-report-tree-cover-and-forests-2018-and-2021/@@download/file`
- [28] `https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land`
- [37] `https://confluence.ecmwf.int/spaces/CKB/pages/197702790/Conversion+table+for+accumulated+variables+total+precipitation+fluxes`
- [29] `https://www.ecmwf.int/en/forecasts/datasets/open-data`
- [30] `https://www.dwd.de/EN/ourservices/opendata/opendata.html`
- [31] `https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast`
- [32] `https://open-meteo.com/en/terms`
- [33] `https://www.openstreetmap.org/copyright`
- [35] `https://download.geofabrik.de/europe/ukraine.html`


## Product-specific processing contract

G0 выбирает raw CDSE GRD adapter либо processed-service adapter явно. В raw GRD preprocessing chain выполняется собственными pinned tools; документация Sentinel Hub не означает, что raw download уже откалиброван/terrain-corrected. В processed-service adapter сохраняются processing request, baseline, quota/access contract и receipt. Product manifest проверяет фактические S2 L2A bands, processing baseline, reflectance scaling/offset и SCL QC. Смешение processing pipelines без отдельных versions запрещено.

## Дополнения итоговой спецификации

В обязательный static context добавлен ESA WorldCover с глобальной картой 10m; версии 2020/2021 нельзя сравнивать как чистую карту изменений из-за разных алгоритмов.[66] Продукт 2021 не является актуальной картой построек/дорог 2026 года. Почвенные единицы, depth mapping и uncertainty приведены в отдельной полной таблице SoilGrids.[65]

Здесь smoke-probes подтверждают только указанные ответы. На G0 обязателен реальный небольшой download и чтение каждого выбранного dataset asset. Рабочий API SoilGrids или покрытие CLMS для региона этими probes не доказаны.

## Sources

[16] https://documentation.dataspace.copernicus.eu/APIs/STAC.html — CDSE STAC product catalogue
    > "Copernicus Data Space Ecosystem STAC Catalog can be accessed using the following URL:"
[17] https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html — Sentinel-1 GRD — CDSE documentation
    > "Calibration to the chosen backscatter coefficient and thermal noise removal applied."
[18] https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html — Sentinel-2 — CDSE documentation
    > "The satellites carry a single payload: the optical Multi-Spectral Instrument (MSI) that samples 13 spectral bands: four bands at 10 m, six bands at 20 m and three bands at 60 m spatial resolution."
    > "Level 2A product provides atmospherically corrected Surface Reflectance (SR) images"
[19] https://documentation.dataspace.copernicus.eu/FAQ.html — CDSE FAQ
    > "24 hours after sensing for Sentinel-1 and Sentinel-2"
[20] https://land.copernicus.eu/en/products/soil-moisture/daily-soil-water-index-europe-1km-v2 — CLMS Daily Soil Water Index Europe 1 km v2
    > "Within 2 days after observation"
[21] https://land.copernicus.eu/en/production-updates/fix-of-spatial-shift-in-soil-water-index-1-km-v2-product — CLMS SWI 1 km v2 spatial-shift fix
    > "This spatial shift has now been resolved in SWI 1 km product v2.1.1."
[22] https://docs.isric.org/globaldata/soilgrids — ISRIC SoilGrids documentation
    > "The outputs of SoilGrids are global soil property maps at six standard depth intervals"
    > "we are currently experiencing issues with the REST API for SoilGrids, and have decided to temporarily pause the service."
[23] https://www.fao.org/land-water/resources/tools/databases/hwsd/en — FAO Harmonized World Soil Database
    > "The HWSD v2.0 features a GIS raster image file that is connected to a soil attribute database."
[24] https://openknowledge.fao.org/server/api/core/bitstreams/149f1562-bf6a-439f-9d3a-eb93940f39cf/content — FAO/IIASA HWSD v2.0 technical report
    > "Some rights reserved. This work is made available under the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 IGO licence (CC BY-NC-SA 3.0 IGO; https://creativecommons.org/licenses/by-nc-sa/3.0/igo/legalcode)."
[25] https://esdac.jrc.ec.europa.eu/content/title-russia-soil-map-ukraine — ESDAC Soil Map of Ukraine
    > "Title in Russia. (Soil Map of Ukraine). - ESDAC - European Commission"
[26] https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM — Copernicus DEM collection description
    > "Digital Surface Model (DSM) provided in 3 different resolutions (90m, 30m, 10m) with varying geographical extent (EEA: European and GLO: global) and varying format (INSPIRE, DGED, DTED)."
[27] https://land.copernicus.eu/en/products/corine-land-cover — CLMS CORINE Land Cover
    > "The product is updated with new status and change layers every six years"
[28] https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — ERA5-Land hourly data from 1950 to present
    > "Native resolution is 9 km."
    > "The ERA5-Land dataset, as any other simulation, provides estimates which have some degree of uncertainty."
[29] https://www.ecmwf.int/en/forecasts/datasets/open-data — ECMWF Open Data
    > "Their use is governed by the Creative Commons CC-BY-4.0 licence"
[30] https://www.dwd.de/EN/ourservices/opendata/opendata.html — DWD Open Data Server
    > "includes model forecasts, radar data, current measurements and observations"
[31] https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast — NOAA GFS
    > "The NODD provides 0.25°- and 0.5° analysis and forecast data."
[32] https://open-meteo.com/en/terms — Open-Meteo terms
    > "You may only use the free API services for non-commercial purposes."
[33] https://www.openstreetmap.org/copyright — OpenStreetMap copyright and license
    > "Although OpenStreetMap is open data, we cannot provide a free-of-charge map API or map tiles for third-parties."
[35] https://download.geofabrik.de/europe/ukraine.html — Geofabrik Ukraine extract
    > "Download OpenStreetMap for Ukraine (with Crimea) | Geofabrik Download Server"
[36] https://land.copernicus.eu/en/technical-library/validation-report-tree-cover-and-forests-2018-and-2021/@@download/file — CLMS HRL Tree Cover and Forests validation report
    > "Tree Cover Density (TCD): the proportional tree cover density at pixel level (in %)."
[37] https://confluence.ecmwf.int/spaces/CKB/pages/197702790/Conversion+table+for+accumulated+variables+total+precipitation+fluxes — ECMWF conversion table for accumulated variables
    > "Accumulated variables are those which are aggregated over a particular time periods."
    > "Accumulations are from 00 UTC to the hour ending at the forecast step"
[65] https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html — SoilGrids layers – SoilGrids Documentation
    > "SoilGrids predictions are made for the six standard depth intervals specified in the GlobalSoilMap IUSS working group and its specifications:"
[66] https://esa-worldcover.org/en/data-access — DATA | WORLDCOVER
    > "The ESA WorldCover product is provided free of charge, without restriction of use."
