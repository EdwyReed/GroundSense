# GroundSense — техническая спецификация

Версия 1.0-rc2, редакция после последовательных рецензий gpt-extra и nous-moe. Дата исследования: 24 октября 2026. Назначение: гражданская промышленная логистика доступа к скважинам и другим удалённым объектам по известным грунтовым, полевым и лесным подъездам. Рецензии — анализ спецификации, не сертификация модели.

## 0. Как пользоваться комплектом

Этот файл задаёт нормативные решения. `docs/01-REQUIREMENTS.md` содержит трассировку переписки; `02-DATA-SOURCES.md` — продукты, доступ, QC и лицензии; `03-SCIENTIFIC-SPEC.md` — физику и калибровку; `04-ARCHITECTURE.md` — эксплуатацию; `05-DATA-API.md` — сущности/контракты; `06-UX-SPEC.md` — экраны; `07-DELIVERY-VALIDATION.md` — работы/проверки/этапы; `08-BASELINE-TIME-ENSEMBLE.md` — время, ансамбли и recovery; `09-SECURITY-PUBLICATION-ADR.md` — serving/publisher/authorization; `10-FIRST-SLICE-BASELINE-CARD.md` — forcing-only первый slice и отдельная конкретная research transition card. Приложения 08–10 имеют приоритет над ранними исследовательскими рецептами; wire schema версии1.1 не переопределяется свободным псевдо-JSON. `docs/FEATURE-MAP.csv` — 70 функций. В `research/` сохранены исследования/evidence; их локальные названия не переопределяют API.

Метки утверждений: внешние факты сопровождаются ссылками из `docs/SOURCES.md`; проектные решения сформулированы как требования; непроверенные параметры не объявляются измеренными. Числа во всех fixtures и макетах вымышленные. Этот комплект не содержит работающего прогнозного сервиса и не сертифицирует проходимость.

## 1. Решение о продукте

Система отвечает на три разных вопроса:

1. Какие условия среды и наблюдаемые дорожные факторы могут затруднять доступ к объекту в выбранный день?
2. Достаточно ли данных и валидации, чтобы оценить риск для объявленного диапазона транспортных конфигураций данной полной массы?
3. В какой период условия могут устойчиво улучшиться? Для G1 показывается сценарная доля/границы, для G2 — только отдельно проверенная вероятность события; неизвестный исход не равен отсутствию события.

Первый коммерчески осмысленный результат — сокращение неподготовленных выездов и приоритизация осмотров известных подъездов. Измерять пользу надо проспективно: количество осмотров, предотвращённых неудачных попыток, задержки обслуживания, ошибочные благоприятные оценки, доля отказа от вывода. Выручка, экономия топлива и «точность» заранее не обещаются.

### 1.1 Релизные уровни

| Уровень | Что выпускается | Что запрещено до следующего gate |
|---|---|---|
| G0a: feasibility | реальные небольшие samples, product/variable/step inventory, нормализованный forcing, полевой протокол | утверждать покрытие дорог, проверенную физику или private serving |
| G0b: engineering slice | authenticated реестр/карта, forcing series, immutable manifest, scope checks; water/recovery abstain | выдавать forcing-only за source→water→recovery продукт |
| G1: screening pilot | карта условий, известные дороги/объекты, триаж осмотров, гидротермический тренд, unknown и provenance | калиброванная вероятность застревания, допустимая масса, дата допуска |
| G2: validated domain | механизм-специфический риск и recovery для перечисленных классов конструкции/техники/сезонов | перенос результата на новый домен без проверки; «безопасно ехать» |
| G3: расширение | дополнительные регионы, fleet integration, ML residuals, эксплуатационные интеграции | автоматическое расширение валидационного домена по факту подключения данных |

G1 остаётся полноценным рабочим продуктом, если G2 не доказан. Научная неудача не должна превращаться в скрытую замену вероятности субъективным баллом.

### 1.2 География и назначение

Региональный пример — Харьковская область. Проверка доступности продуктов для региона не равна анализу реальных подъездов. Точные объекты пилота предоставляет гражданский владелец в закрытом workspace с разрешением на доступ и обследования. Визуальные примеры используют синтетические объекты. Автоматический поиск скрытых коридоров, оценка FPV-угроз и оптимизация перемещения в зоне конфликта не входят в спецификацию. Поддержка гражданской эвакуации остаётся отдельным последующим интеграционным сценарием без вывода «безопасный маршрут».

## 2. Пользовательский контракт

### 2.1 Два поля

Оперативный запрос содержит `assessment_date` и `gross_mass_t`. Регион, разрешённые объекты и известная дорожная сеть уже заданы workspace. Дата — локальная календарная дата в IANA time zone workspace. Масса — полная фактическая масса с грузом, не масса полезной нагрузки. Перевод тонн в kg производится явно и тестируется.

Никаких обязательных сценариев «дождь / сухо / оттепель». Метеорежим получает модель. Никаких обязательных дополнительных вопросов о грунте и шинах. Недостающие физические параметры не угадываются: они задаются диапазоном из fleet policy, историей обследований или сохраняются неизвестными.

Поддержка ввода массы не означает, что environmental score обязан от неё меняться. В screening режиме масса хранится и видна, но `mobility_risk=null` с причиной `MODEL_NOT_VALIDATED`. В validated режиме смена массы выбирает допустимый транспортный envelope и пересчитывает только зависимую от нагрузки часть; вода, температура и снег остаются прежними.

### 2.2 Транспортный envelope

Одной полной массы недостаточно: дорожное воздействие зависит от осей, групп осей, давления и типа шин, подвески и интервалов нагрузок.[13] Поэтому `VehicleEnvelope` — версия множества возможных конфигураций, а не одна выдуманная «средняя фура».

Envelope содержит диапазон полной массы, осевые/колёсные нагрузки, привод, параметры шин/контакта, клиренс, ограничения по уклонам и объявленное число проходов. Источник: реестр предприятия или утверждённая инженерная политика. При отсутствии распределения по конфигурациям вероятности по ним не усредняются с равными весами: результат является диапазоном/robust bound либо unknown. Транспортный результат имеет discriminated kind `calibrated_probability | probability_bounds | unavailable`: при неизвестных весах конфигураций scalar risk=null, а identified/declared bounds имеют отдельные поля и семантику. Сочетания осей/колёс обязаны быть совместно допустимыми и согласованными с общей массой; независимые min/max параметров не определяют физическую конфигурацию. Конечный перечень шаблонов не называется строгой границей непрерывного envelope без доказательства.

Базовый рейс предполагает одно посещение туда/обратно по утверждённой политике числа проходов. Это допущение показывается; convoys и многократная доставка вне домена не получают тот же вывод. Параметры можно импортировать из корпоративного fleet registry, не добавляя анкету диспетчеру.

## 3. Что вычисляется и с какой поддержкой

### 3.1 Пространственные сущности

Различаем `weather_grid`, `soil_cell`, `terrain_cell`, `analysis_unit`, `road_segment`, `field_observation` и `asset`. Дорожный сегмент — единица истории и отображения, а не размер достоверного датчика. Погодный forcing остаётся связанным с нативной ячейкой и ансамблевым участником; соседние сегменты не считаются независимыми измерениями.

Для геометрий храним WGS84, для измерений в региональном проекте используем подходящую метрическую CRS (для пилотного домена выбрать и закрепить по географии; единый UTM-zone нельзя молча переносить на всю страну). Web Mercator используется только для карты. Нативная CRS каждого растра сохраняется. CRS без явного определения не принимается.

Известные дороги сегментируются по пересечениям, смене покрытия/конструкции, дренажа, источника или правового ограничения; дополнительное ограничение длины 50–100 m — настраиваемый storage/inspection параметр. При новой версии сети сохраняется relation `split_from/merged_from`; outcome старого сегмента не переносится без проверки на новый идентификатор.

### 3.2 Минимальный открытый контур

| Обязательный продукт | Роль | Обязательное ограничение |
|---|---|---|
| SoilGrids250m 2.0 | prior свойств природного грунта и неопределённость | не конструкция дороги; six depth intervals, release и Q05/Q50/Q95 сохраняются |
| Copernicus DEM GLO-30 | уклон, относительный рельеф, потенциальный водосбор | DSM, а не bare-earth DTM; кювет/труба неизвестны |
| OSM snapshot + реестр заказчика | инвентаризация известных подъездов и объектов | нет гарантии полноты, существования или текущего состояния |
| ERA5-Land | исторический forcing, spin-up, климатология | реанализ с задержкой, не прогноз и не локальное измерение |
| ECMWF open forecast subset | будущие forcing trajectories | фиксировать cycle/member/step и доступный variable list; не рассчитывать поля, которых нет |
| ESA WorldCover | статический land-cover context вне неподтверждённого EEA покрытия | версии 2020/2021 отличаются алгоритмом, разность карт не равна чистому land change |

Эти роли опираются на документацию SoilGrids, DEM и ERA5-Land.[22][26][28]

Отдельно: WorldCover доступен по CC-BY 4.0; версии 2020/2021 созданы разными алгоритмами.[66]

SAR/оптика подключаются как обоснованное улучшение, а не обязательный тяжёлый конвейер до первого полезного среза. Sentinel-1 pixel spacing не равен эффективному разрешению road assessment; L2A Sentinel-2 не видит полотно под плотным пологом и облаками. Processing и QC определяются продуктом.[17][18]

CLMS SWI/SSM и TCD допускаются только после проверки конкретного покрытия AOI, версии и QC; слово Europe не заменяет tile test.[20][36]

### 3.3 Лицензионный контракт

Free Open-Meteo API предназначен только для non-commercial use; коммерческий продукт использует подписку или прямые открытые поставщики.[32] Бесплатные исходные данные не отменяют стоимость compute, storage, egress, поддержки и обследований.

Права HWSD на конкретный downloadable dataset должны быть проверены отдельно: NC-SA на техническом отчёте не доказывает license всех data files. Пока clearance не завершён, HWSD и исторические сканы ESDAC не входят в обязательный production путь.[24][25] Наличие публичного скана не даёт права на любую производную базу.

OSM-данные и собственные закрытые реестры разделяются по provenance и лицензиям; юридическая проверка определяет, образуется ли derivative database и какие условия распространения применимы.[33] Нельзя копировать публичные стандартные tiles без учёта usage policy; production basemap — свой или договорной.

## 4. Научное ядро

### 4.1 Причинная схема

`weather + snow + initial state + natural soil prior + road structure + terrain/drainage + canopy + maintenance` → `water/thermal state distribution` → `strength/deformation/traction distribution` → `mechanism-specific outcome under vehicle envelope`.

Вода и грунт не идентифицируют мост, трубу, право доступа и опасность территории. Эти ограничения находятся в отдельном реестре `AccessConstraint`, а не в коэффициенте риска. Минимум одной неизвестной критической конструкции может сделать всю цепочку доступа unknown, даже если фоновые условия благоприятны.

### 4.2 Модель G1

Первый G0b — forcing-only; он не требует искусственно заполнить неизвестную гидравлику. Следующий scientific increment — ограниченный warm/snow-free water bucket с двумя эффективными слоями и фиксированным шестичасовым UTC шагом по приложению10. Его переход полностью задан, а численные HydraulicParameterSet, depth-compatible InitialState и thermal applicability screen должны получить evidence/approval. Без них water state и recovery недоступны. Поздняя snow/thermal модель — отдельный gate; она включает SWE, liquid/ice water, температуру и surface storage. Глубины model layers задаёт parameter card, а не автоматически SoilGrids intervals. LLM не является вычислителем физики.

Для слоя `W_i = 1000 dz_i (theta_liquid_i + theta_ice_WE_i)` [mm water equivalent], где ice WE — эквивалент объёма жидкой воды, не фактический объём льда. Физическое занятие пор льдом учитывает плотности отдельно по приложению08. У warm card ice/SWE равны нулю только после screen, не по отсутствию датчика.

Баланс за шаг: `ΔW = P_liquid + M + Q_in - ET - Q_out - D`. Все слагаемые интегрированы за шаг и имеют mm; rate в mm/hour умножается на hours. Избыточная вода уходит в surface storage/runoff, дефицит ограничивает ET/поток. Простое `clip(W,0,Wmax)` без учёта остатка запрещено: оно скрывает потерю воды. Residual фиксируется на каждом шаге и интегрально.

Снег: `SWE_next = SWE + P_solid - M - sublimation`. Начальный melt index `M=min(SWE, DDF*max(Tair-Tm,0)*Δt_day)` — исследовательская degree-day аппроксимация с неопределёнными DDF и rain/snow partition. Rain-on-snow, canopy interception, wind redistribution и ледяные линзы ограничивают её применимость. Температура воздуха/degree-days не публикуется как измеренная глубина промерзания.

Тепло: на G1 freeze–thaw — согласованный с источниками режим и uncertainty; инженерная глубина/толщина несущего мерзлого слоя не выпускается. Если оценка зависит от неизвестного промерзания, ответ unknown. Научный spike сравнивает этот baseline с SHAW column model и данными термодатчиков. SHAW решает совместный перенос тепла и воды, учитывает снег и замерзание, но требует подробных начальных/граничных условий.[62] Noah-MP — ещё один открытый land-surface baseline; его repository требует coupled host system, поэтому это не pip-библиотека, которую можно подключить за вечер.[64]

ET0 от FAO-56 используется только при наличии нужного forcing и после проверки единиц; это reference evapotranspiration, не фактическая скорость высыхания дороги.[63] Для голого/уплотнённого/лесного полотна actual ET и ограничения доступной воды калибруются отдельно. Не подставлять растительный коэффициент без источника.

### 4.3 Предобработка, влияющая на физику

ERA5 и ERA5-Land имеют разные accumulation semantics. Для hourly ERA5-Land precipitation накоплена от 00 UTC внутри forecast cycle; часовой прирост получают разностью соседних шагов того же цикла, а следующий 00 UTC содержит сумму предыдущих суток.[37] Повторная deaccumulation уже подготовленных hourly increments запрещена; transform записывается в provenance. При смене цикла не вычитаем предыдущий день. Суточные локальные суммы рассчитываются после deaccumulation и timezone conversion. Negative jump означает reset или проблему metadata, не отрицательный дождь.

SoilGrids fractions хранятся g/kg, их перевод в % — деление на 10; `bdod` cg/cm³ переводится в kg/dm³ делением на 100, затем в kg/m³ умножением на 1000. Шесть source-интервалов: 0–5, 5–15, 15–30, 30–60, 60–100, 100–200 cm.[65] Нельзя делить повторно, если TIFF scale/offset уже применён драйвером. Конкретный asset metadata имеет приоритет с явной schema validation.

Sand/silt/clay — композиционные признаки; независимое случайное sampling каждой маргинальной квантили может дать сумму не 100%. Выбираем ограниченное joint sampling, сохраняем зависимости и отдельно рассматриваем отклонение исходной суммы как QC. Ренормализация допустима только для малой rounding погрешности, не для nodata или несовместимых источников. Bulk density не равна particle density; pedotransfer не превращает их в измеренную пористость дороги.

### 4.4 Road structure и транспортная модель G2

Road structure хранится отдельно: слои и материал, толщина, уплотнение, drainage, возраст обследования, вмешательства, степень доказанности. Нет структуры — нет количественного bearing margin. DCP, CI, CBR, водосодержание и фактические проезды не взаимозаменяемы. CBR — индекс испытания, а не фундаментальное свойство или допустимые тонны.[2] Прибор, энергия удара, геометрия конуса, глубина и conditioning обязательны.

Обнаружена ошибка-ловушка источников: FHWA Table 5-34 подписывает индекс в in/blow при коэффициенте 292; руководство изготовителя использует mm/blow и отдельные корреляции для CL/CH.[2][61] В production не реализуем универсальную формулу DCP→CBR до проверки стандарта, единиц и локальной применимости. Противоречивый источник не «исправляется» тихо.

Для G2 отдельны исходы: `immobilization`, `rut_depth_exceeded_after_n_passes`, `structural_damage`, `traction_loss`. DTO называет estimand и operation_ref; operation — единственный authoritative порядок проходов и inbound/outbound нагрузок. `traction_not_assessed` — completeness/reason, не outcome. Прочность, тяга и повторные проходы требуют разных параметров; испытания VCI относятся к конкретной машине и режиму, а не любому грузовику данной массы.[7] Мы не заимствуем военные vehicle tables для гражданской техники.

Модель G2 может быть иерархической логистической/событийной моделью по согласованному outcome с механистическими признаками. Выбор алгоритма после определения наблюдаемых меток и baseline; LightGBM residual correction — optional G3. Прогнозная вероятность имеет смысл только при проверенной калибровке и определённой выборке. `q_allow` не получается универсальной формулой из CBR/CI и не хранится как измеренная величина.

### 4.5 Неопределённость и отказ

Раздельно храним: forcing spread; soil/structure parameter uncertainty; initial-state uncertainty; observation representativeness; model discrepancy; vehicle-envelope uncertainty. Источники с общими исходными измерениями получают `correlation_group`, а не два независимых голоса. CLMS/ECMWF soil fields, вычисленные тем же forcing, не являются независимым подтверждением модели.

Сохраняем исходные веса и потерянную массу численно невалидных trajectories. Перенормировка только по оставшимся members может выбросить самые мокрые сценарии и запрещена для основного вывода. Результат — identified bounds с неизвестным исходом потерянного веса либо abstention по versioned policy; conditional-on-valid summary подписывается отдельно. При неизвестных весах не публикуется точечная вероятность. Ensemble spread не становится автоматически предиктивным интервалом. P10/P50/P90 публикуются с указанием величины, conditioning и calibration status. Конформальные методы возможны лишь с проверкой предпосылок/shift; слово conformal само по себе не гарантирует coverage в новом регионе. Data quality — набор категорий/флагов, не «вероятность правильности 87%».

Причины abstention: missing critical input; stale beyond policy; unknown road construction; unsupported vehicle envelope; insufficient valid ensemble members; out-of-domain season/soil/road; thermal ambiguity; unresolved access constraint; invalid observation geometry; model withdrawn. Unknown не понижает значение риска к нулю.

## 5. Recovery как событие

Определяем два разных события:

- `environmental_recovery`: модельное состояние вернулось в согласованный диапазон по выбранным physical variables на непрерывный интервал.
- `vehicle_condition_recovery`: калиброванный outcome risk для объявленного envelope ниже утверждённого порога и выполняются все применимые условия на тот же интервал.

G1 возвращает только первое. G2 может возвращать второе в validated domain. Thresholds, persistence duration и effective time step входят в `event_definition_version`; пользователь их не задаёт.

Для каждой совместной trajectory считаем первое **завершение/подтверждение** непрерывного интервала `persistence_hours`; `event_time_convention=confirmation_end`. Начало улучшения — отдельное derived time, не дата события. Если интервал не успел завершиться до конца общей пригодной траектории, подтверждённого события в этом горизонте нет. CDF/квантили определены до общего `horizon_end` подтверждения, а не до непроверяемых поздних начал. Все trajectories, не достигшие события, остаются right-censored и не удаляются перед p50. В G1 CDF — сценарная доля, не проверенная частота реального recovery; полные определения — `docs/08-BASELINE-TIME-ENSEMBLE.md`.

Выход exact variant: unconditional scenario CDF, достигнутая доля к horizon, доступные квантили с null там, где CDF не достигает уровня, horizon и uncertainty scope. Partial variant: time-varying CDF bounds и horizon bounds, без выдуманной point probability/quantiles; unavailable — без чисел, если ансамбль не строился. Веса относятся к event ascertainment по каждому h: уже подтверждённый first passage сохраняется после позднего сбоя, поздний candidate при полной trajectory — NO confirmation-by-H. Номинальные trajectory weights и неизвестные vehicle-configuration weights различны. Условные квантили среди восстановившихся не подменяют основной прогноз. Нет события в горизонте не означает «никогда»; unknown отличается от censored.

При полевых наблюдениях два редких осмотра не доказывают первое устойчивое recovery: между ними могли быть улучшение и повторный дождь, а один благоприятный визит не подтверждает persistence. Храним instantaneous evidence и observation support; sustained-event label допускается только по согласованному протоколу покрытия интервала. В остальных случаях — partially identified/unknown label. Отсутствие поездки не является отказом. Maintenance intervention создаёт новый regime и treatment flag. Просыхание не обязано восстанавливать разрушенную трубу, колею или дорожную одежду: repair-required — отдельное состояние, а не слишком долгий decay timer.

## 6. Агрегация доступа к объекту

Для каждого заранее известного approved approach есть упорядоченный набор обязательных сегментов и инженерных ограничений. Статистика average risk по длине не определяет доступность. При наличии калиброванной joint trajectory путь оценивается внутри каждой общей траектории; затем считаются события/вероятности. Произведение вероятностей соседних сегментов запрещено без независимости, поскольку дождь, грунтовая карта и тепловое состояние общие.

Если joint dependence неизвестна, показываем worst critical segment и диапазон/unknown, а не выдуманную «вероятность проезда ко всем объектам». Min/max вероятностей не называем точной route probability. Неизвестный bridge/culvert/legal access блокирует механический вывод о полном доступе. Не строим новый маршрут, обход закрытий или лесной corridor discovery.

## 7. Архитектура реализации

### 7.1 Выбранный стек

| Слой | Выбор | Не добавляем до доказанной необходимости |
|---|---|---|
| UI | Vue 3, TypeScript, Vite, Vue Router, Pinia; semantically accessible native/компактные headless components | Next/Nuxt SSR для закрытого GIS, тяжёлый UI framework ради marketing page |
| Map | MapLibre GL JS, собственный style, MVT/COG-backed layers | Cesium/3D globe, deck.gl без измеренной нужды |
| Charts | Apache ECharts с accessible table | несколько chart libraries |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | микросервис для каждого Engine из презентации |
| Science | NumPy, SciPy, xarray, rasterio/GDAL, pyproj, GeoPandas/pyogrio | GPU/LLM-inference, распределённый Dask cluster до профилирования |
| DB | PostgreSQL 17/18 + совместимая поддерживаемая PostGIS 3.x; точный patch pin на implementation freeze | PostGIS raster как склад всех исходных кубов |
| Pipelines | Prefect 3 self-hosted, отдельная DB/schema/control plane, process/container workers | Celery+Airflow+Prefect одновременно |
| Cache | Valkey при появлении повторяемого cache/lock workload; DB uniqueness финальна | очередь как единственный источник job status |
| Storage | Managed S3-compatible или локальный immutable filesystem для G0 с ObjectStorePort | MinIO как молчаливый дефолт, Ceph без storage команды |
| Tiles | TiTiler для raster, один authenticated PostGIS/MVT adapter для результатов; PMTiles для public baseline | три альтернативных tile server одновременно |
| Delivery | Docker Compose, CI, managed DB/object store по требованиям; OIDC existing IdP | Kubernetes и service mesh до HA/workload trigger |

Vue поддерживает Composition API + SFC для полноценных приложений; MapLibre работает с интерактивными tiles; async API не выполняет scientific CPU work в request process.[38][39][40] Выбор Vue не является утверждением научного превосходства над React; существующая команда React могла бы изменить ADR без изменения доменных контрактов.

COG применяется к готовым 2D layers, Zarr к кубам с compatibility spike выбранной версии, GeoParquet к векторным analytical artifacts.[43][44][45]

MinIO upstream на дату проверки архивирован и распространяется под AGPLv3; это основание не выбирать его дефолтом, а не утверждение, что любое применение AGPL запрещено.[47][67]

### 7.2 Единый модульный backend

`api`, `domain`, `adapters`, `science`, `pipelines`, `serving`, `validation` — границы Python packages внутри одного репозитория. Workers запускают тот же versioned scientific package отдельным image/process. Отдельный сервис оправдан только независимым scaling/security profile: API, downloader/science worker, tile serving. Soil/Recovery/Confidence Engine не требуют шести сетевых сервисов.

```text
apps/web/                    Vue GIS
apps/api/                    auth, query, jobs, assets, evidence
packages/domain/             schemas, units, reason codes, policies
packages/science/            water/thermal, outcome, recovery
packages/adapters/           sources, object store, tile ports
pipelines/                   ingestion, normalization, backtest, publish
contracts/                   OpenAPI, schemas, examples
infra/                       compose, migrations, observability, restore
 tests/                      unit, property, contracts, integration, scientific, UI
 docs/                       ADR, dataset cards, model cards, runbooks
```

### 7.3 Два контура вычислений

Фоновые ingestion/normalization независимо от кликов обновляют input snapshots. Environmental state/trajectories вычисляются один раз на допустимую совокупность входов, model version и time horizon. Vehicle-dependent evaluation использует готовые trajectories и envelope, а не заново качает Sentinel на каждый mass slider. API принимает задание и возвращает immutable result или `202`; схема карты не зависит от длительности raw ETL.

Semantic input digest включает tenant scope для закрытых данных, AOI version, requested date/day semantics, input manifest digests, model/code/parameters/event/envelope versions и knowledge cutoff. Один Idempotency-Key повторно возвращает тот же request; другой payload с тем же ключом — conflict. «Latest» — указатель, а не mutable result ID.

### 7.4 Время и воспроизводимость

Каждый source asset содержит `valid_time`, `acquired_at/forecast_issue_time`, `provider_available_at`, `ingested_at`, `revision_at`, `content_sha256`, units/CRS/support/QC/license. Указанное источником acquisition time не считается временем доступности. Для повторения именно решения GroundSense требуется `ingested_at<=knowledge_cutoff`; для внешнего hindcast допустимо separately labelled availability reconstruction, но не утверждение, что система тогда это знала.

Реанализ в режиме retrospective reconstruction допускается с датой его сегодняшней версии. В operational backtest будущие observations/reanalysis недоступны; source revisions после cutoff исключаются. Отсутствие архива issue-time weather может блокировать честный forecast skill test; это не исправляется подстановкой фактической погоды.

Два уровня воспроизводимости: exact artifact digest при сохранённых байтах; численная повторяемость scientific recompute с declared tolerance при разных CPU/GDAL. Бит-в-бит scientific results не обещаются по умолчанию. Код image digest, параметры, seeds, library lock и input objects обязательны.

### 7.5 Публикация

1. Run имеет `queued→running→validating→ready_to_publish` либо terminal `failed/cancelled`.
2. Все output objects записаны под неизменяемыми release keys, проверены SHA/size/schema/availability; они не доступны пользователю напрямую.
3. Подготовленный canonical manifest хранится как immutable bytes с digest и точными object version IDs; object lifecycle не удаляет referenced keys. Staging-to-final copy завершена до публикации.
4. Одна SQL transaction фиксирует manifest, `published` result pointer, eligibility/expiry, audit и outbox. Проверяет lease/fencing token, модельный gate и статус cancellation.
5. Readers используют только опубликованный SQL record; user получает scope-filtered ManifestView, не internal locators/чужие site metadata. Артефакт авторизуется заново. Сбой event delivery не показывает половину run; outbox повторяется. GC использует SQL reservation/reference graph и delete claims ADR-05, не object listing или один grace period.

SQL+S3 не объявляются общей ACID-транзакцией. Serializable conflicts требуют retry; объектная доступность и retention проверяются до commit.[56] Запрещены: publication до готовности объектов, удаляемые staging keys в published manifest, cache key без tenant/access scope, mutation старого run после новых наблюдений.

Scientific artifact содержит заранее выделенные run/release IDs, не digest содержащего его manifest. Manifest digest хранится снаружи canonical bytes; выбран RFC8785-JCS/UTF8 SHA256. POSIX filesystem использует conditional no-overwrite link+fsync, а не заменяющий destination rename. Полный LatestPointer key/order с отдельным model epoch, reservations и SQL GC задан ADR-05. Эти решения должны быть реализованы и испытаны, а не считаются проверенными наличием JSON fixtures.

## 8. Безопасность и эксплуатация

OIDC Authorization Code + PKCE через существующий enterprise IdP; отдельный Keycloak только если IdP нет.[59] Выбран same-origin BFF: HttpOnly/Secure cookie, OAuth tokens только server-side, CSRF+Origin на mutations, cookie-auth tiles без URL tokens. Подробности — ADR-10. Runtime DB role не владеет таблицами и не имеет BYPASSRLS; `FORCE ROW LEVEL SECURITY`, tenant context только из verified session, составные связи исключают cross-tenant asset references.[41] Tiler не принимает произвольный URL/SQL и не использует широкие object credentials.

Private tiles/cache keys: tenant, manifest, layer, style, z/x/y, authz scope. Public baseline отделён. Presigned URL — bearer capability, не криптографически audience-bound токен; для немедленного отзыва нужен authenticated proxy, иначе живёт до TTL/credential revocation.[57] Нельзя обещать отзыв уже скачанной offline копии.

Uploads: quarantine, размер/количество/expansion limits, magic+decode, generated keys, archive traversal/symlink/zip-bomb controls, malware scan, revoke/retention procedure. Downloader использует approved registry с SSRF protection, DNS/redirect check, egress allowlist; произвольные URL по умолчанию не принимаются.[52][53]

Фото могут раскрывать людей, номера и промышленную инфраструктуру. Оригинал приватный, ограниченный retention; derivative с удалённым EXIF не заменяет исходный SHA. Evidence QA и согласие/основание обработки хранятся; автоматической передачи фото во внешние LLM нет. Удаление оригинала не совместимо с вечной exact воспроизводимостью — manifest сохраняет tombstone и причину, affected models проходят impact review; нельзя заявлять cryptographic deletion при неучтённых backup keys.

SLO — проектные цели, не измеренные результаты: read API pilot 99.5%/month, cached tile p95<1s, request acceptance p95<2s. Scientific quality, upstream freshness и API availability — отдельные отчёты. Система может быть доступна, но выдавать unknown. Backups включают Postgres/PITR и referenced private objects, configs и encryption material с контролем доступа. Пилотные RPO24h/RTO8h подтверждаются restore drill; production цели уточняются по бюджету и последствиям потери данных.

Restore не открывает старые grants/approvals автоматически: fail-closed reconciliation с IdP/audit/withdrawal/deletion tombstones, новый policy epoch, инвалидированные sessions/cursors/worker leases и повторная аттестация scopes по ADR-11. Неизвестная полнота audit оставляет private serving закрытым, даже при превышении RTO.

## 9. Приёмка до эксплуатации

Инженерно корректный frontend не доказывает физику. Release gate включает:

- Контракты units/time/CRS/QC, restart/idempotency/publication isolation, tenant leakage и stale/unknown.
- Пространственные holdouts целыми дорогами/объектами и temporal holdout целыми wet/thaw events.
- Отдельную проверку на новый объект и будущий сезон; соседние сегменты одного дождя не увеличивают эффективный sample count как независимые испытания.
- Baselines: последние проверенные условия; rainfall-only триаж; hydrothermal без EO; +structure; +field; +SAR/optical. Дорогой EO-adapter остаётся только при измеримой добавочной ценности.
- Error costs и outcome definition до просмотра test results; false-favourable ceiling, calibration и minimum useful coverage согласуются владельцем и геотехником.
- Recovery evaluation учитывает censoring, persistence и missing inspections; quantiles без достижения CDF не публикуются.
- Проспективный shadow pilot до рекомендаций в validated domain. Ни один опасный проезд не проводится ради метки обучения.

Если подтверждённых испытаний нет, risk metrics отображаются как «валидация не завершена». Числа из макетов не попадают в release report.

## 10. Финансовая и временная оценка

Смета строится из work packages и сценарных ставок, не из обещания «за $20k будет промышленная точность». Отдельно учитываются разработка, scientific review, field campaign/датчики, вычисления/архив, юридическая проверка и поддержка. Бесплатные источники — только одна часть затрат. Расчёт с допущениями и диапазонами находится в `07-DELIVERY-VALIDATION.md`.

До beta нужны G0a feasibility spike и G0b authenticated forcing-only slice (ADR-08). G0a не проверяет private serving/RLS. G0b получает ограниченный реальный forcing, нормализует units/time, публикует snapshot и показывает его на карте/графике при abstained water/recovery. Его 38–62 person-days входят в общий G1 объём, не прибавляются сверху; расчётный диапазон при условной ставке150–350 USD/day — 5,700–21,700 USD, без полевой кампании. Scientific increment после этого требует card/initialization/thermal screen и собственной приёмки. Масштаб на область, field strata и эксплуатационная надёжность финансируются по результатам. Сезонная валидация может занять дольше разработки.

## Sources

[2] https://www.fhwa.dot.gov/engineering/geotech/pubs/05037/05b.cfm — Geotechnical Engineering Circular No. 5, Chapter 5
    > "CBR is not a fundamental material property and thus is unsuitable for direct use in mechanistic and mechanistic-empirical design procedures."
[7] https://www.erdc.usace.army.mil/Media/News-Stories/Article/2821041/erdc-researchers-support-army-and-marine-corps-with-vehicle-cone-index-testing — ERDC researchers support Army and Marine Corps with Vehicle Cone Index testing
    > "VCI testing measures the soil strength needed for a vehicle to make one pass over a specific area of terrain."
[13] https://www.fhwa.dot.gov/reports/tswstudy/vol3-chapter5.pdf — Comprehensive Truck Size and Weight Study Volume 3 Chapter 5
    > "The gross vehicle weight (GVW) of a vehicle is not the prime determinant of a vehicle’s impact on pavements."
[17] https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/S1GRD.html — Sentinel-1 GRD — CDSE documentation
    > "Calibration to the chosen backscatter coefficient and thermal noise removal applied."
[18] https://documentation.dataspace.copernicus.eu/Data/SentinelMissions/Sentinel2.html — Sentinel-2 — CDSE documentation
    > "The satellites carry a single payload: the optical Multi-Spectral Instrument (MSI) that samples 13 spectral bands: four bands at 10 m, six bands at 20 m and three bands at 60 m spatial resolution."
    > "Level 2A product provides atmospherically corrected Surface Reflectance (SR) images"
[20] https://land.copernicus.eu/en/products/soil-moisture/daily-soil-water-index-europe-1km-v2 — CLMS Daily Soil Water Index Europe 1 km v2
    > "Within 2 days after observation"
[22] https://docs.isric.org/globaldata/soilgrids — ISRIC SoilGrids documentation
    > "The outputs of SoilGrids are global soil property maps at six standard depth intervals"
    > "we are currently experiencing issues with the REST API for SoilGrids, and have decided to temporarily pause the service."
[24] https://openknowledge.fao.org/server/api/core/bitstreams/149f1562-bf6a-439f-9d3a-eb93940f39cf/content — FAO/IIASA HWSD v2.0 technical report
    > "Some rights reserved. This work is made available under the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 IGO licence (CC BY-NC-SA 3.0 IGO; https://creativecommons.org/licenses/by-nc-sa/3.0/igo/legalcode)."
[25] https://esdac.jrc.ec.europa.eu/content/title-russia-soil-map-ukraine — ESDAC Soil Map of Ukraine
    > "Title in Russia. (Soil Map of Ukraine). - ESDAC - European Commission"
[26] https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM — Copernicus DEM collection description
    > "Digital Surface Model (DSM) provided in 3 different resolutions (90m, 30m, 10m) with varying geographical extent (EEA: European and GLO: global) and varying format (INSPIRE, DGED, DTED)."
[28] https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land — ERA5-Land hourly data from 1950 to present
    > "Native resolution is 9 km."
    > "The ERA5-Land dataset, as any other simulation, provides estimates which have some degree of uncertainty."
[32] https://open-meteo.com/en/terms — Open-Meteo terms
    > "You may only use the free API services for non-commercial purposes."
[33] https://www.openstreetmap.org/copyright — OpenStreetMap copyright and license
    > "Although OpenStreetMap is open data, we cannot provide a free-of-charge map API or map tiles for third-parties."
[36] https://land.copernicus.eu/en/technical-library/validation-report-tree-cover-and-forests-2018-and-2021/@@download/file — CLMS HRL Tree Cover and Forests validation report
    > "Tree Cover Density (TCD): the proportional tree cover density at pixel level (in %)."
[37] https://confluence.ecmwf.int/spaces/CKB/pages/197702790/Conversion+table+for+accumulated+variables+total+precipitation+fluxes — ECMWF conversion table for accumulated variables
    > "Accumulated variables are those which are aggregated over a particular time periods."
    > "Accumulations are from 00 UTC to the hour ending at the forecast step"
[38] https://vuejs.org/guide/introduction.html — Introduction | Vue.js
    > "For production use: Go with Composition API + Single-File Components if you plan to build full applications with Vue."
[39] https://maplibre.org/maplibre-gl-js/docs — Introduction - MapLibre GL JS
    > "MapLibre GL JS is a TypeScript library that uses WebGL to render interactive maps from vector tiles in a browser."
[40] https://fastapi.tiangolo.com/async — Concurrency and async / await - FastAPI
    > "As the execution time is consumed mostly by waiting for I/O operations, they call them "I/O bound" operations."
[41] https://www.postgresql.org/docs/current/ddl-rowsecurity.html — PostgreSQL Row Security Policies
    > "If no policy exists for the table, a default-deny policy is used, meaning that no rows are visible or can be modified."
[43] https://gdal.org/en/stable/drivers/raster/cog.html — GDAL COG driver
    > "During the writing process, if overviews are generated, they will be created in a temporary dataset, requiring storage capacity of roughly one third of the final file size"
[44] https://zarr-specs.readthedocs.io/en/latest/v3/core/index.html — Zarr core specification
    > "The primary motivation for the development of Zarr is to address this challenge by enabling the storage of large multidimensional arrays in a way that is compatible with parallel and/or distributed computing applications."
[45] https://geoparquet.org/releases/v1.1.0 — GeoParquet Specification 1.1.0
    > "A GeoParquet file MUST include a `geo` key in the Parquet metadata"
[47] https://github.com/minio/minio/blob/master/LICENSE — minio LICENSE
    > "This repository was archived by the owner on Apr 25, 2026. It is now read-only."
[52] https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html — OWASP File Upload Cheat Sheet
    > "Validate the file type, don't trust the Content-Type header as it can be spoofed"
[53] https://owasp.org/www-community/attacks/Server_Side_Request_Forgery — OWASP SSRF
    > "the attacker may be able to read server configuration such as AWS metadata, connect to internal services"
[56] https://www.postgresql.org/docs/current/transaction-iso.html — PostgreSQL Transaction Isolation
    > "any concurrent execution of a set of Serializable transactions is guaranteed to produce the same effect as running them one at a time in some order."
[57] https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html — Amazon S3 presigned URLs
    > "You can use presigned URLs to grant time-limited access to objects in Amazon S3 without updating your bucket policy."
[59] https://www.keycloak.org/documentation — Keycloak Documentation
    > "Authorization Services | Centrally manage fine-grained permissions for applications and services."
[61] https://www.kesslerdcp.com/wp-content/uploads/2020/09/SAPPER_with_WiFi_Manual_18MAY2020.pdf — PowerPoint Presentation
    > "Selection of the appropriate correlation is a matter of professional judgment."
[62] https://www.ars.usda.gov/pacific-west-area/boise-id/northwest-watershed-research-center/docs/shaw-model — SHAW Model : USDA ARS
    > "The SHAW model simulates heat, water and solute transfer in a one-dimensional profile extending from the top of a plant canopy or the snow, residue or soil surface to a specified depth within the soil."
[63] https://www.fao.org/4/x0490e/x0490e06.htm — Chapter 2 - FAO Penman-Monteith equation
    > "Procedures for estimating missing climatic data are outlined in Chapter 3."
[64] https://github.com/NCAR/noahmp — GitHub - NCAR/noahmp: Noah-MP Community Repository · GitHub
    > "This GitHub repository only provides the Noah-MP source code and driver/interface code. To run Noah-MP in either offline or online mode, users need to have the host model system/framework coupled with Noah-MP."
[65] https://docs.isric.org/globaldata/soilgrids/SoilGrids_faqs_01.html — SoilGrids layers – SoilGrids Documentation
    > "SoilGrids predictions are made for the six standard depth intervals specified in the GlobalSoilMap IUSS working group and its specifications:"
[66] https://esa-worldcover.org/en/data-access — DATA | WORLDCOVER
    > "The ESA WorldCover product is provided free of charge, without restriction of use."
[67] https://github.com/minio/minio — MinIO upstream archive status
    > "This repository was archived by the owner on Apr 25, 2026. It is now read-only."
