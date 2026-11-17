export function forecastQuery(assetId: string, assessmentDate: string, grossMassT: number) {
  return `/forecast?${new URLSearchParams({ asset_id: assetId, assessment_date: assessmentDate, gross_mass_t: String(grossMassT) })}`
}

export function formatTime(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }).format(date)
}

export function importFormat(filename: string): 'csv' | 'geojson' | 'json' {
  const name = filename.toLowerCase()
  return name.endsWith('.csv') ? 'csv' : name.endsWith('.geojson') || name.endsWith('.json.geo') ? 'geojson' : 'json'
}

const labels: Record<string, string> = {
  research_water_balance:'Дослідницький водний баланс',
  available:'Дані отримано',unavailable:'Дані недоступні',forcing_only:'Лише природні умови',auth_required:'Потрібна автентифікація',on_request:'Очікує запиту',point:'Користувацька точка',other:'Інше',site:'Майданчик',
  'Потрібні CDS credentials / імпорт':'Потрібен ключ CDS або імпорт даних',
  well: 'Свердловина', unknown: 'Невідомо', requested: 'Запит створено', screening: 'Попередня оцінка',
  accepted: 'Прийнято', rejected: 'Відхилено', queued: 'У черзі', running: 'Виконується', published: 'Опубліковано',
  cancelled: 'Скасовано', failed: 'Не виконано', less_adverse: 'Менш несприятливі', adverse: 'Несприятливі',
  severe: 'Суттєве перезволоження', ground: 'Ґрунтове', gravel: 'Гравійне', current: 'Чинний', withdrawn: 'Відкликано',
  research: 'Дослідницька', blocked: 'Заблоковано', preview: 'Попередній перегляд', committed: 'Імпортовано',
  dispatcher: 'Диспетчер', engineer: 'Інженер', field: 'Польова група', admin: 'Адміністратор',
  modelled: 'Модельна оцінка', forecast: 'Синтетичний сценарій', partial: 'Часткова',
  reconstruction:'Реконструкція (демо)', climatology:'Кліматологічний режим (без даних)',
  not_checked:'Не перевірено',not_connected:'Не підключено',coverage_unknown:'Покриття не підтверджено',
  qc_rejected:'Відхилено контролем якості',static:'Статичний приклад',license_pending:'Права не підтверджено',
  stored:'Збережено',validated:'Перевірено',research_only:'Лише дослідження',abstained:'Оцінка недоступна',
  insufficient_evidence:'Недостатньо доказів',historical_only:'Лише історичний перегляд',expired:'Строк дії минув',
  create:'Створено',revise:'Нова редакція',adjudicate:'Рецензування',export:'Експорт',upload:'Завантаження фото',
  create_analysis:'Запит розрахунку',demo_role:'Зміна деморолі',preview_import:'Перегляд імпорту',commit_import:'Підтвердження імпорту',

}
export const localized = (value: unknown) => labels[String(value)] || String(value ?? '—')

export function selectedSeries(result: any, forecast: any, asset: string, day: string, mass: number): any[] {
  const matches = (a: any) => a?.asset_id === asset && a?.assessment_date === day && Number(a?.gross_mass_t) === Number(mass)
  if (matches(result?.assessment) && result?.eligibility === 'withdrawn') return []
  if (matches(result?.assessment)) return result.assessment.series || []
  return matches(forecast) ? forecast.series || [] : []
}
export function formatNumber(value: unknown, precision = 3): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return new Intl.NumberFormat('uk-UA', {maximumFractionDigits: precision}).format(value)
}
export function observationTimeUTC(value: string): string {
  return new Date(value + 'Z').toISOString()
}

export function sourceSummary(source: any, context: any = {}, forecast: any = null): string {
  const data = source?.data || {}, parts: string[] = []
  const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
  if (source.id === 'soilgrids') {
    const soil = context.soil || {}, composition = soil.composition || {}
    const values = [['sand', 'пісок'], ['silt', 'пил'], ['clay', 'глина']].filter(([key]) => number(composition[key!])).map(([key, label]) => `${label} ${formatNumber(composition[key!], 1)}%`)
    if (values.length) parts.push(`Оцінки ${soil.composition_depth_cm?.join('–') || 'невідомої глибини'} см: ${values.join(', ')}`)
    const interval = soil.depths?.[0]?.sand_uncertainty_90
    if (interval && number(interval.lower) && number(interval.upper)) parts.push(`Пісок, Q0.05–Q0.95: ${formatNumber(interval.lower, 1)}–${formatNumber(interval.upper, 1)} ${interval.unit}`)
  }
  if (source.id === 'copernicus-glo-30' && number(context.terrain?.elevation_m)) parts.push(`Висота поверхні: ${formatNumber(context.terrain.elevation_m, 2)} м (DSM)`)
  const classCode = data.class_code ?? (source.id === 'esa-worldcover' ? context.land_cover?.class : null)
  if (number(classCode)) parts.push(`Клас покриву: ${classCode}`)
  if (number(data.percent)) parts.push(`Полог: ${formatNumber(data.percent, 1)}%`)
  if (source.id === 'hwsd-v2' && number(data.point?.map_unit_id)) {
    parts.push(`Картографічна одиниця: ${data.point.map_unit_id}`)
    const rows = data.point.attributes?.rows
    if (Array.isArray(rows) && rows.length) {
      parts.push(`Записів MDB: ${rows.length}`)
      for (const [key, label] of [['WRB4', 'WRB4'], ['FAO90', 'FAO90'], ['TEXTURE_USDA', 'USDA (код)']]) {
        if (typeof rows[0]?.[key!] === 'string' && rows[0][key!] !== '') parts.push(`${label}: ${rows[0][key!]}`)
      }
    }
  }
  const year = data.reference_year ?? data.static_reference_year
  if (year != null) parts.push(`Опорний рік: ${year}`)
  const sar = context.satellites?.sentinel_1
  if (source.id === 'sentinel-1-grd' && sar) {
    for (const key of ['vv', 'vh']) if (number(sar[key]?.linear)) parts.push(`${key.toUpperCase()}: ${formatNumber(sar[key].linear)} gamma0 (${formatNumber(sar[key].db, 2)} dB)`)
    if (number(sar.scene_age_days)) parts.push(`Давність сцени: ${sar.scene_age_days} дн.`)
    if (sar.qc?.missing_masks?.length) parts.push('Додаткові QC-маски не отримано')
  }
  if (source.id === 'sentinel-2-l2a' && data.pixel) {
    if (number(data.pixel.scl?.value)) parts.push(`SCL: ${data.pixel.scl.value}`)
    for (const key of ['red', 'nir']) if (number(data.pixel.bands?.[key]?.value)) parts.push(`${key === 'red' ? 'Червоний' : 'Ближній ІЧ'}: ${formatNumber(data.pixel.bands[key].value, 4)} reflectance`)
  }
  if (data.point && number(data.point.value)) parts.push(`${data.point.depth_index || 'Вологість'}: ${formatNumber(data.point.value, 2)} ${data.point.unit || 'одиниці не встановлено'}`)
  if (number(data.mapped_way_count)) parts.push(`Нанесених ділянок поруч: ${data.mapped_way_count}; повнота невідома`)
  let rows = data.series
  if (source.id === 'era5-land') rows = context.history?.series
  if (source.id === 'open-meteo-icon-global') rows = forecast?.series
  const row = Array.isArray(rows) ? rows.find((value: any) => ['temperature_2m','temperature_c','precipitation','precipitation_mm','soil_moisture_0_to_1cm','soil_moisture_0_to_7cm','moisture_p50'].some(key => number(value[key]))) : null
  if (row) {
    const temperature = row.temperature_c ?? row.temperature_2m, precipitation = row.precipitation_mm ?? row.precipitation
    const moisture = row.moisture_p50 ?? row.soil_moisture_0_to_1cm ?? row.soil_moisture_0_to_7cm
    if (number(temperature)) parts.push(`Температура: ${formatNumber(temperature, 1)} °C`)
    if (number(precipitation)) parts.push(`Опади: ${formatNumber(precipitation, 1)} мм`)
    if (number(moisture)) parts.push(`Модельна вологість ${source.id === 'era5-land' ? '0–7' : '0–1'} см: ${formatNumber(moisture)} м³/м³`)
    if (typeof row.time === 'string') parts.push(`Ряд: ${formatTime(row.time)} UTC`)
    parts.push(`Рядів: ${rows.length}`)
  }
  if (source.note) parts.push(source.note)
  const timestamp = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value) && Number.isFinite(Date.parse(value))
  if (timestamp(source.observed_at)) parts.push(`Час даних: ${formatTime(source.observed_at)} UTC`)
  if (timestamp(source.retrieved_at)) parts.push(`Отримано: ${formatTime(source.retrieved_at)} UTC`)
  return parts.join(' · ')
}

