// @vitest-environment jsdom
import { createApp, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.vue'

vi.mock('./components/SchematicMap.vue',()=>({default:{template:'<div>Схематична карта</div>'}}))
vi.mock('./components/ForecastChart.vue',()=>({default:{template:'<div>Графік</div>'}}))
afterEach(()=>vi.unstubAllGlobals())

async function mountRegistry(){
  const state={assets:[],segments:[],protocols:[] as any[],observations:[],inspections:[],models:[],envelopes:[],constraints:[],tickets:[],subscriptions:[],features:[],user:{role:'engineer'},context:{assessment_date:'2026-10-25',gross_mass_t:20},csrf_token:'test-csrf',map:{}}
  const requests:any[]=[]
  vi.stubGlobal('fetch',vi.fn(async(input:any,init?:RequestInit)=>{
    if(['/api/v1/bootstrap','/api/v1/live/bootstrap'].includes(String(input))) return new Response(JSON.stringify({...state,today:'2026-10-25'}),{status:200})
    const body=JSON.parse(String(init?.body));requests.push({path:input,body})
    const row={...body,id:'protocol-test',version:1};state.protocols.push(row)
    return new Response(JSON.stringify(row),{status:201})
  }))
  const root=document.createElement('div');document.body.append(root)
  const app=createApp(App);app.mount(root)

  await vi.waitFor(()=>expect(root.querySelector('.menu')).not.toBeNull())
  ;(root.querySelector('.menu') as HTMLButtonElement).click()
  await vi.waitFor(()=>expect(root.querySelector('.registry-form')).not.toBeNull())
  return {root,requests,close(){app.unmount();root.remove()}}
}
function enter(input:HTMLInputElement,text:string){input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}))}

describe('registry draft lifecycle',()=>{
  it('cancel clears a new unsaved draft, not just an existing edit',async()=>{
    const view=await mountRegistry()
    try{
      enter(view.root.querySelector('.registry-form input[name="name"]')!,'Чернетка');await nextTick()
      ;([...view.root.querySelectorAll<HTMLButtonElement>('.registry-form button')].find(b=>b.textContent==='Скасувати')!).click();await nextTick()
      expect((view.root.querySelector('.registry-form input[name="name"]') as HTMLInputElement).value).toBe('')
      expect(view.requests).toHaveLength(0)
    }finally{view.close()}
  })
  it('successful create resets the form and preserves date and mass',async()=>{
    const view=await mountRegistry()
    try{
      const inputs=view.root.querySelectorAll<HTMLInputElement>('.registry-form input')
      enter(inputs[0]!,'Протокол QA');enter(inputs[1]!,'dcp');enter(inputs[2]!,'mm/blow');await nextTick()
      view.root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))
      await vi.waitFor(()=>expect(view.requests).toHaveLength(1))
      await vi.waitFor(()=>expect((view.root.querySelector('.registry-form input[name="name"]') as HTMLInputElement).value).toBe(''))
      expect(view.requests[0].path).toBe('/api/v1/protocols')
      expect(view.requests[0].body).toMatchObject({name:'Протокол QA',method:'dcp',unit:'mm/blow'})
      expect((view.root.querySelector('.querybar input[type="date"]') as HTMLInputElement).value).toBe('2026-10-25')
      expect((view.root.querySelector('.querybar input[type="number"]') as HTMLInputElement).value).toBe('20')
    }finally{view.close()}
  })
})
