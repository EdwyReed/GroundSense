import { describe, expect, it } from 'vitest'
import { forecastQuery, formatTime, importFormat, localized } from './presentation'
import * as presentation from './presentation'

describe('presentation helpers', () => {
  it('shows actual source values and native semantics in the existing source notes', () => {
    const summarize = (presentation as any).sourceSummary
    expect(typeof summarize).toBe('function')
    const context = {terrain:{elevation_m:91.8441},satellites:{sentinel_1:{vv:{linear:1.1480093,db:.59945},vh:{linear:.0695913,db:-11.57445},scene_age_days:1,qc:{missing_masks:['water']}}}}
    expect(summarize({id:'copernicus-glo-30'},context)).toContain('91,84 м')
    const sar = summarize({id:'sentinel-1-grd'},context)
    expect(sar).toContain('VV: 1,148')
    expect(sar).toContain('VH: 0,07')
    expect(sar).toContain('gamma0')
    expect(sar).toContain('QC-маски')
    expect(summarize({id:'corine-land-cover',data:{class_code:123,reference_year:2018}},{})).toContain('Клас покриву: 123')
    expect(summarize({id:'ecmwf-ifs',data:{series:[{temperature_2m:3.5,precipitation:0,soil_moisture_0_to_1cm:.3}]}},{})).toContain('0 мм')
  })
  it('keeps true zero canopy separate from missing canopy data', () => {
    const summarize = (presentation as any).sourceSummary
    expect(typeof summarize).toBe('function')
    expect(summarize({id:'clms-tree-cover-density',data:{percent:0,reference_year:2018}},{})).toContain('Полог: 0%')
    expect(summarize({id:'clms-tree-cover-density',data:{percent:null,reference_year:2018}},{})).not.toContain('Полог: 0%')
  })
  it('shows the real HWSD map-unit and never calls a static reference a UTC observation',()=>{
    const summarize = (presentation as any).sourceSummary
    expect(summarize({id:'hwsd-v2',observed_at:'static reference',data:{point:{map_unit_id:10128}}},{})).toContain('10128')
    expect(summarize({id:'hwsd-v2',observed_at:'static reference'},{})).not.toContain('Час даних:')
  })
  it('shows native HWSD classification attributes without inventing units or legend labels',()=>{
    const text = presentation.sourceSummary({id:'hwsd-v2',data:{point:{map_unit_id:10128,attributes:{rows:[{WRB4:'RTgl',FAO90:'PDg',TEXTURE_USDA:'7',BULK_DENSITY:'1.48'}]}}}})
    expect(text).toContain('WRB4: RTgl')
    expect(text).toContain('FAO90: PDg')
    expect(text).toContain('USDA (код): 7')
    expect(text).toContain('Записів MDB: 1')
    expect(text).not.toContain('1.48 г/см')
  })
  it('does not guess the statistic of soil fraction estimates',()=>{
    expect((presentation as any).sourceSummary({id:'soilgrids'},{soil:{composition:{sand:42.6,silt:33.7,clay:7.9},composition_depth_cm:[0,5]}})).toContain('Оцінки')
  })
  it('never displays results belonging to another date, asset, mass or withdrawal', () => {
    const f = (presentation as any).selectedSeries
    expect(typeof f).toBe('function')
    const assessment={asset_id:'GS-014',assessment_date:'2026-10-25',gross_mass_t:20,series:[{moisture_p50:.235241}]}
    expect(f({assessment,eligibility:'current'},null,'GS-014','2026-10-26',20)).toEqual([])
    expect(f({assessment,eligibility:'current'},null,'GS-001','2026-10-25',20)).toEqual([])
    expect(f({assessment,eligibility:'withdrawn'},assessment,'GS-014','2026-10-25',20)).toEqual([])
    expect(f(null,assessment,'GS-014','2026-10-25',20)).toEqual(assessment.series)
  })
  it('formats data without false precision and encodes explicit UTC field time', () => {
    expect(typeof (presentation as any).formatNumber).toBe('function')
    expect((presentation as any).formatNumber(.235241142)).toBe('0,235')
    expect((presentation as any).formatNumber(0)).toBe('0')
    expect((presentation as any).formatNumber(null)).toBe('—')
    expect((presentation as any).observationTimeUTC('2026-10-24T12:30')).toBe('2026-10-24T12:30:00.000Z')
  })

  it('encodes the complete forecast selection in the API query', () => {
    expect(forecastQuery('GS-014', '2026-10-25', 20.5)).toBe('/forecast?asset_id=GS-014&assessment_date=2026-10-25&gross_mass_t=20.5')
  })

  it('preserves six-hour local time in chart labels', () => {
    expect(formatTime('2026-10-25T06:00:00Z')).toMatch(/25\.10\.2026.*06:00/)
  })

  it('recognizes CSV imports and translates raw display states', () => {
    expect(importFormat('observations.CSV')).toBe('csv')
    expect(localized('unknown')).toBe('Невідомо')
    expect(localized('requested')).toBe('Запит створено')
    expect(localized('available')).toBe('Дані отримано')
    expect(localized('unavailable')).toBe('Дані недоступні')
    expect(localized('forcing_only')).toBe('Лише природні умови')
    expect(localized('auth_required')).toBe('Потрібна автентифікація')
  })
})
