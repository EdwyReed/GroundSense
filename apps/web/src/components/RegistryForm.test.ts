// @vitest-environment jsdom
import { createApp, h, nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import RegistryForm from './RegistryForm.vue'
import { buildRegistryPayload, draftForRegistry } from '../lib/registryForms'

describe('registry form payloads', () => {
  it('preserves unknown nested fields on an asset edit while omitting server fields', () => {
    const record={id:'GS-1',version:4,name:'Криниця',type:'well',condition:'unknown',geometry:{type:'Point',coordinates:[1,2]},source_ref:'seed',synthetic:true,entered_at:'server',custom:{keep:true}}
    const result=buildRegistryPayload('assets',{...draftForRegistry('assets',record),name:'Нова назва'},record)
    expect(result).toEqual({ok:true,payload:{name:'Нова назва',type:'well',condition:'unknown',geometry:{type:'Point',coordinates:[1,2]},source_ref:'seed',synthetic:true,custom:{keep:true}}})
  })

  it('rejects invalid numeric and structured advanced input instead of coercing it', () => {
    expect(buildRegistryPayload('segments',{...draftForRegistry('segments'),asset_id:'GS-1',length_m:'not-a-number',geometryText:'{}'}).ok).toBe(false)
    expect(buildRegistryPayload('assets',{...draftForRegistry('assets'),name:'A',geometryText:'not json'})).toMatchObject({ok:false,errors:{geometryText:expect.any(String)}})
  })
})

describe('RegistryForm DOM', () => {
  it('keeps public reference points nonsynthetic and their condition unknown',()=>{
    const root=document.createElement('div');const app=createApp(RegistryForm,{kind:'assets',publicData:true,assets:[],segments:[],busy:false});app.mount(root)
    try{const selects=[...root.querySelectorAll<HTMLSelectElement>('select')];expect(selects.map(e=>e.value)).toEqual(['other','unknown','false']);expect(selects[1].disabled).toBe(true);expect(selects[2].disabled).toBe(true)}finally{app.unmount()}
  })
  it('submits an edited protocol without requiring raw JSON', async () => {
    const emitted=ref<any[]>([])
    const root=document.createElement('div'); document.body.append(root)
    const app=createApp({render:()=>h(RegistryForm,{kind:'protocols',record:{id:'p-1',version:2,name:'Старий',method:'dcp',unit:'mm/blow',required_fields:['depth_mm']},assets:[],segments:[],busy:false,onSubmit:(payload:any)=>emitted.value.push(payload)})})
    app.mount(root)
    const name=root.querySelector<HTMLInputElement>('input[name="name"]')!
    name.value='Новий протокол'; name.dispatchEvent(new Event('input',{bubbles:true}))
    ;(root.querySelector('form') as HTMLFormElement).dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
    await nextTick()
    expect(emitted.value).toEqual([{name:'Новий протокол',method:'dcp',unit:'mm/blow',required_fields:['depth_mm']}])
    expect(root.querySelector('textarea')).toBeNull()
    app.unmount(); root.remove()
  })
})
