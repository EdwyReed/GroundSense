import { describe, expect, it } from 'vitest'
import { buildRegistryPayload, draftForRegistry, type RegistryKind } from './registryForms'

describe('registry PATCH integrity', () => {
  it.each(['models','envelopes'] as const)('only resubmits declared metadata fields for %s', kind => {
    const original={id:'metadata-1',version:1,name:'Синтетичні метадані',approval:{approved:true},metadata_only:true,custom:{hidden:true}}
    const result=buildRegistryPayload(kind,draftForRegistry(kind,original),original)
    expect(result.ok).toBe(true)
    if(result.ok){expect(result.payload).not.toHaveProperty('approval');expect(result.payload).not.toHaveProperty('metadata_only');expect(result.payload).not.toHaveProperty('custom')}
  })
  it('sends null when an existing geometry is deliberately cleared', () => {
    const original={name:'Синтетичний об’єкт',geometry:{type:'Point',coordinates:[.03,.04]}}
    const result=buildRegistryPayload('assets',{...draftForRegistry('assets',original),geometryText:''},original)
    expect(result).toMatchObject({ok:true,payload:{geometry:null}})
  })

  it.each([
    ['assets','{}'],
    ['assets','{"type":"Point","coordinates":[200,0]}'],
    ['assets','{"type":"Point","coordinates":[true,0]}'],
    ['assets','{"type":"Point","coordinates":[1e999,0]}'],
    ['assets','{"type":"LineString","coordinates":[[0,0],[1,1]]}'],
    ['segments','{"type":"LineString","coordinates":[[0,0]]}'],
    ['segments','{"type":"LineString","coordinates":[[0,0],[0,95]]}'],
    ['segments','{"type":"Point","coordinates":[0,0]}'],
  ])('rejects invalid or wrong-kind geometry for %s: %s', (rawKind,geometryText) => {
    const kind=rawKind as RegistryKind
    const result=buildRegistryPayload(kind,{...draftForRegistry(kind),name:'Синтетичний об’єкт',asset_id:'GS-014',length_m:'800',geometryText})
    expect(result).toMatchObject({ok:false,errors:{geometryText:expect.any(String)}})
  })

  it.each([['tickets','due_at'],['inspections','scheduled_at']])('uses explicit UTC and clears %s timestamps through PATCH', (rawKind,key) => {
    const kind=rawKind as RegistryKind
    const original={[key]:'2026-10-25T14:30:00.000Z',custom:{keep:true}}
    const draft=draftForRegistry(kind,original)
    expect(draft[key]).toBe('2026-10-25T14:30:00')
    expect(buildRegistryPayload(kind,{...draft,[key]:'2026-10-25T15:30'},original)).toMatchObject({ok:true,payload:{[key]:'2026-10-25T15:30:00.000Z',custom:{keep:true}}})
    expect(buildRegistryPayload(kind,{...draft,[key]:''},original)).toMatchObject({ok:true,payload:{[key]:null}})
    expect(buildRegistryPayload(kind,{...draft,[key]:'not-a-date'},original)).toMatchObject({ok:false,errors:{[key]:expect.any(String)}})
  })
})
