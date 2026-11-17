# Завершення інтеграцій у наявному прототипі

Доповнює DATA-SWAP-CONTRACT.md; не змінює верстку, CSS, навігацію чи основні URL. Мета — реальні reads, не зелений каталог. Публічні контрольні точки, жодних виробничих маршрутів.

## Незалежні адаптери цього пакета

Конструктори без мережі. Усі класи приймають cache_dir: Path; необов'язковий transport для детермінованих HTTP-тестів. Власні фіксовані endpoints, обмежені вікна/відповіді/таймаути й bounded cache; жодних довільних URL від користувача. Виклики read(latitude, longitude, assessment_date: str).

Кожний запис джерела: id, name, product, version, status, qc, note, retrieved_at, observed_at, content_sha256, data. Статуси available/partial/unavailable/auth_required. Українські пояснення. available лише для фактично отриманих даних, відповідних запитаній точці/даті. Немає даних/поза покриттям/потрібен доступ — явний стан, не нуль і не синтетика. Відсутність історичного геоприв'язаного растра не виправляється LLM-класифікацією скану.

1. apps/api/clms_sources.py: CLMSSources.read -> {soil_moisture: {swi: object|null, ssm: object|null}, sources: [...]}. Канонічні id clms-swi-1km-v2, clms-ssm-1km. Реальний точковий read CLMS SWI/SSM, якщо існує законний публічний шлях; query/dataset metadata не є числовим read. Units/scales/NoData/QC/version/date/depth-index semantics з фактичного продукту. Не підміняти точний європейський продукт глобальним SWI іншого масштабу без окремого явного маркування.
2. apps/api/context_sources.py: ContextSources.read -> {context: object, sources: [...]}. Канонічні id hwsd-v2, esdac-ukraine-soil-map, corine-land-cover, clms-tree-cover-density. Отримати доступний справжній raster value/attribute або історичний скан з provenance. Статичні reference years і coverage обов'язкові; ESDAC scan != автоматична точкова класифікація. Правові обмеження не приховувати, жодного заявленого дозволу на комерційне використання без джерела.
3. apps/api/sentinel1_sources.py: Sentinel1Sources.read -> {satellite: object, source: object}. Канонічна категорія id sentinel-1-grd; фактичний product може бути GRD-derived RTC, але назва, processing chain, provider/version і units повинні точно це показувати. Обчислений calibrated gamma0/sigma0 та необроблені DN не змішуються. Лише сцени не пізніше кінця обраної UTC-дати; минуле вікно до 10 діб, явна давність. Реальні VV/VH point/window, orbit/incidence/QC, де вони доступні. Не стверджувати власну SAR preprocessing для готового RTC mirror.

Батьківський агент інтегрує ці класи у main.py, прибирає дубльовані placeholder rows під час злиття та відповідає за UI/розгортання. Власники модулів НЕ змінюють main.py, remote_sources.py, static_sources.py, frontend, залежності, credentials чи файли інших власників. Не створювати акаунти, не виконувати платні операції, не комітити. Відсутність необхідної залежності повернути батьківському агенту.

## Перевірка

SoilGrids Q0.5 — незалежні оцінки фракцій; їх не нормалізуємо до 100%. Публікуємо фактичну суму і QC partial, якщо відхилення перевищує 1 відсотковий пункт. Це прозорий поріг перевірки узгодженості відображення, не заявлена норма ISRIC, не помилка завантаження й не науковий/транспортний допуск.

CLMS: каталог не більше 1 MiB, streamed download не більше 64 MiB; ZIP до 64 елементів, 128 MiB на елемент, 256 MiB загалом, співвідношення розпакованого/стисненого розміру до 1000. Відхилений за лімітом продукт не вважаємо прочитаним; ці межі не доводять, що будь-який офіційний продукт поміститься. Sentinel-1 signer може додати query лише до того самого дозволеного HTTPS asset; інший host/path/credentials/fragment відхиляється, signed URLs не публікуються.

TDD на фактичну поведінку: несправний provider, null/NoData, selected date, coverage, одиниці, відсутність secret/signed URLs у DTO. Справжній малий read із raw evidence/hash у qa/<adapter>-real-proof.json. У proof чітко відокремити справжній read від unit fixtures. Якщо немає легального доступу — зберегти справжню відповідь/документований endpoint і конкретний блокер; не вигадувати успіх. Повернути коротко змінені файли, команду focused tests, реальні значення/блокери.
