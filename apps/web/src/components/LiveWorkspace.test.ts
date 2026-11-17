// @vitest-environment jsdom
import { createApp, h, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import LiveWorkspace from './LiveWorkspace.vue'

const liveAsset={id:'point-1',version:1,name:'Точка Осло',latitude:59.91,longitude:10.75,geometry:{type:'Point',coordinates:[10.75,59.91]},source_ref:'користувач',synthetic:false,data_origin:'user_supplied',condition:'unknown'}
const weather=(latitude:number, temperature:number)=>({mode:'live',synthetic:false,assessment_date:'2026-10-25',requested_point:{latitude,longitude:10.75},grid_point:{latitude,longitude:10.75,elevation_m:23},source:{id:'open-meteo-icon-global',provider:'Open-Meteo',product:'DWD ICON Global via Open-Meteo',model:'icon_global',request_url:'https://api.open-meteo.com/',retrieved_at:'2026-10-25T12:00:00Z',issue_time:null,license:'CC BY 4.0',service_usage:'non_commercial_prototype',attribution_url:'https://open-meteo.com/',content_sha256:'sha256:abc',cached:false},units:{temperature_2m:'°C',precipitation:'mm',soil_moisture_0_to_1cm:'m³/m³',soil_moisture_1_to_3cm:'m³/m³',soil_temperature_0cm:'°C'},series:[{time:'2026-10-25T12:00:00Z',temperature_2m:temperature,precipitation:0.2,soil_moisture_0_to_1cm:0.31,soil_moisture_1_to_3cm:0.29,soil_temperature_0cm:8,precipitation_interval_start:'2026-10-25T11:00:00Z',precipitation_interval_end:'2026-10-25T12:00:00Z'}],qc:{status:'available',missing_variables:[],is_observation:false,spatial_support:'model_grid_not_road'},mobility:{kind:'unavailable',reason:'Немає виробничого допуску'}})
const json=(data:any,status=200)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}))
const flush=async()=>{ await new Promise(resolve=>setTimeout(resolve,0)); await nextTick() }

afterEach(()=>vi.unstubAllGlobals())

describe('LiveWorkspace',()=>{
  it('does not turn empty coordinate fields into a point at zero zero',async()=>{
    vi.stubGlobal('fetch',vi.fn(()=>json({workspace:{id:'live',mode:'public_data',synthetic:false,private_data_allowed:false},csrf_token:'csrf',user:{role:'engineer'},assets:[],sources:[],today:'2026-10-25'})))
    const root=document.createElement('div');document.body.append(root);const app=createApp(LiveWorkspace);app.mount(root);await flush()
    expect(root.querySelector<HTMLButtonElement>('[data-testid="load-weather"]')!.disabled).toBe(true)
    app.unmount();root.remove()
  })
  it('submits a user point and presents actual weather data',async()=>{
    const requests:string[]=[]
    vi.stubGlobal('fetch',vi.fn((url:string, init?:RequestInit)=>{requests.push(url); if(url==='/api/v1/live/bootstrap')return json({workspace:{id:'live',mode:'public_data',synthetic:false,private_data_allowed:false},csrf_token:'csrf',user:{role:'viewer'},assets:[],sources:[],today:'2026-10-25'}); if(url==='/api/v1/live/assets')return json(liveAsset,201); if(url.startsWith('/api/v1/live/weather'))return json(weather(59.91,7)); return json({detail:'немає'},404)}))
    const root=document.createElement('div'); document.body.append(root); const app=createApp({render:()=>h(LiveWorkspace) }); app.mount(root); await flush()
    expect(root.textContent).toContain('Реєстр точок порожній')
    const fields=root.querySelectorAll<HTMLInputElement>('input'); fields[0].value='Точка Осло'; fields[0].dispatchEvent(new Event('input',{bubbles:true})); fields[1].value='59.91'; fields[1].dispatchEvent(new Event('input',{bubbles:true})); fields[2].value='10.75'; fields[2].dispatchEvent(new Event('input',{bubbles:true})); fields[3].value='користувач'; fields[3].dispatchEvent(new Event('input',{bubbles:true})); root.querySelector('form')!.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})); await flush()
    expect(requests).toContain('/api/v1/live/assets'); expect(root.textContent).toContain('7 °C'); expect(root.textContent).toContain('Модельні оцінки ґрунту')
    app.unmount(); root.remove()
  })

  it('shows a retryable API error',async()=>{
    vi.stubGlobal('fetch',vi.fn((url:string)=>url==='/api/v1/live/bootstrap'?json({detail:'Сервіс недоступний'},503):json({detail:'немає'},404)))
    const root=document.createElement('div'); document.body.append(root); const app=createApp({render:()=>h(LiveWorkspace)}); app.mount(root); await flush()
    expect(root.textContent).toContain('Сервіс недоступний'); expect([...root.querySelectorAll('button')].some(button=>button.textContent?.includes('Повторити'))).toBe(true)
    app.unmount(); root.remove()
  })

  it('does not display a late response for an older selected point',async()=>{
    let first:(value:Response)=>void=()=>{}; const late=new Promise<Response>(resolve=>{first=resolve})
    vi.stubGlobal('fetch',vi.fn((url:string)=>{if(url==='/api/v1/live/bootstrap')return json({workspace:{id:'live',mode:'public_data',synthetic:false,private_data_allowed:false},csrf_token:'csrf',user:{role:'viewer'},assets:[liveAsset],sources:[],today:'2026-10-25'}); if(url.includes('latitude=59.91'))return late; if(url.includes('latitude=60'))return json(weather(60,11)); return json({detail:'немає'},404)}))
    const root=document.createElement('div'); document.body.append(root); const app=createApp({render:()=>h(LiveWorkspace)}); app.mount(root); await flush()
    const latitude=root.querySelectorAll<HTMLInputElement>('input')[1]; latitude.value='60.00'; latitude.dispatchEvent(new Event('input',{bubbles:true})); await nextTick(); root.querySelector<HTMLButtonElement>('[data-testid="load-weather"]')!.click(); await flush(); first(await json(weather(59.91,1))); await flush()
    expect(root.textContent).toContain('11 °C'); expect(root.textContent).not.toMatch(/(?:^|[^0-9])1 °C/)
    app.unmount(); root.remove()
  })
})
