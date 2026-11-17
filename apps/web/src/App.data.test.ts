// @vitest-environment jsdom
import {createApp,nextTick} from 'vue'
import {afterEach,expect,it,vi} from 'vitest'
import App from './App.vue'
vi.mock('./components/SchematicMap.vue',()=>({default:{template:'<div>Картографія</div>'}}))
vi.mock('./components/ForecastChart.vue',()=>({default:{template:'<div>Графік</div>'}}))
afterEach(()=>vi.unstubAllGlobals())
const soil=()=>({composition:null,support_m:null,depths:[]})
const base=()=>({workspace:{mode:'public_data',synthetic:false},context:{assessment_date:'2026-10-25',gross_mass_t:20},user:{role:'engineer'},csrf_token:'test-only',assets:[{id:'real-1',name:'Тестова користувацька точка',type:'point',condition:'unknown',synthetic:false,geometry:{type:'Point',coordinates:[10.75,59.91]}}],segments:[],sources:[],features:[],observations:[],inspections:[],models:[],protocols:[],soil:soil(),map:{mode:'public_data',type:'FeatureCollection',features:[]}})
const json=(x:any)=>new Response(JSON.stringify(x),{status:200})
function selectTab(root:HTMLElement,label:string){[...root.querySelectorAll<HTMLButtonElement>('.masthead nav button')].find(x=>x.textContent===label)!.click()}
it('shows actual model and terrain data on the first map without pretending road admission exists',async()=>{
 const paths:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:any)=>{
  const path=String(url);paths.push(path)
  if(path==='/api/v1/bootstrap')return json(base())
  if(path.startsWith('/api/v1/forecast?'))return json({asset_id:'real-1',assessment_date:'2026-10-25',gross_mass_t:20,mode:'forcing_only',synthetic:false,series:[{time:'2026-10-25T00:00:00Z',temperature_c:9.7,precipitation_mm:0,moisture_p50:.338}],source_supports:[{id:'open-meteo-icon-global',product:'ICON Global',model:'icon_global'}]})
  return json({asset_id:'real-1',assessment_date:'2026-10-25',soil:soil(),terrain:{elevation_m:91.84,surface_kind:'DSM'},sources:[]})
 }))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{
  await vi.waitFor(()=>expect(root.querySelector('.inspector')?.textContent).toContain('9,7 °C'))
  const text=root.querySelector('.inspector')!.textContent!
  expect(text).toContain('Проїзд не оцінено')
  expect(text).not.toContain('Недостатньо даних')
  expect(text).toContain('0 мм')
  expect(text).toContain('0,338 м³/м³')
  expect(text).toContain('00:00')
  await vi.waitFor(()=>expect(root.querySelector('.inspector')?.textContent).toContain('91,84 м'))
  expect(root.querySelector('.inspector')?.textContent).toContain('DSM')
  expect(paths.some(x=>x.startsWith('/api/v1/forecast?'))).toBe(true)
  expect(paths.filter(x=>x.startsWith('/api/v1/forecast?'))).toHaveLength(1)
  expect(root.querySelectorAll('.masthead nav button')).toHaveLength(6)
  expect(root.querySelectorAll('.querybar input')).toHaveLength(2)
 }finally{app.unmount();root.remove()}
})
it('does not turn null model values into zero in the map inspector',async()=>{
 vi.stubGlobal('fetch',vi.fn(async(url:any)=>{
  if(String(url)==='/api/v1/bootstrap')return json(base())
  if(String(url).startsWith('/api/v1/forecast?'))return json({asset_id:'real-1',assessment_date:'2026-10-25',gross_mass_t:20,series:[{time:'2026-10-25T00:00:00Z',temperature_c:null,precipitation_mm:null,moisture_p50:null}]})
  return json({asset_id:'real-1',assessment_date:'2026-10-25',soil:soil(),sources:[]})
 }))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{await vi.waitFor(()=>expect(root.querySelector('[data-testid=point-conditions]')?.textContent).toContain('Числовий прогноз недоступний'));expect(root.querySelector('[data-testid=point-conditions]')?.textContent).not.toContain('0 мм')}finally{app.unmount();root.remove()}
})
it('ignores late weather for the previous date while the map is open',async()=>{
 let resolveOld:(response:Response)=>void=()=>{};const old=new Promise<Response>(resolve=>resolveOld=resolve);let oldRequested=false
 const forecast=(day:string,value:number)=>({asset_id:'real-1',assessment_date:day,gross_mass_t:20,series:[{time:day+'T00:00:00Z',temperature_c:value,precipitation_mm:0,moisture_p50:.3}]})
 vi.stubGlobal('fetch',vi.fn(async(url:any)=>{
  const path=String(url);if(path==='/api/v1/bootstrap')return json(base())
  const day=new URL(path,'https://test.invalid').searchParams.get('assessment_date')!
  if(path.startsWith('/api/v1/forecast?')){if(day==='2026-10-25'){oldRequested=true;return old}return json(forecast(day,12.2))}
  return json({asset_id:'real-1',assessment_date:day,soil:soil(),sources:[]})
 }))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{
  await vi.waitFor(()=>expect(oldRequested).toBe(true))
  const date=root.querySelector<HTMLInputElement>('input[type=date]')!;date.value='2026-10-26';date.dispatchEvent(new Event('input',{bubbles:true}))
  await vi.waitFor(()=>expect(root.querySelector('.inspector')?.textContent).toContain('12,2 °C'))
  resolveOld(json(forecast('2026-10-25',9.7)));await new Promise(resolve=>setTimeout(resolve,0))
  expect(root.querySelector('.inspector')?.textContent).toContain('12,2 °C');expect(root.querySelector('.inspector')?.textContent).not.toContain('9,7 °C')
 }finally{app.unmount();root.remove()}
})
it('opens an explicitly labelled public reference through the original asset API',async()=>{
 let created=false;let payload:any=null
 vi.stubGlobal('fetch',vi.fn(async(url:any,options:any)=>{
  if(String(url)==='/api/v1/assets'&&options?.method==='POST'){payload=JSON.parse(options.body);created=true;return json({id:'real-1',status:'created'})}
  if(String(url)==='/api/v1/bootstrap'){const value=base();if(!created)value.assets=[];return json(value)}
  return json({asset_id:'real-1',assessment_date:'2026-10-25',soil:soil(),sources:[]})
 }))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{await vi.waitFor(()=>expect(root.querySelector('.map-layout')).not.toBeNull());const button=[...root.querySelectorAll<HTMLButtonElement>('.list-panel button')].find(x=>x.textContent?.includes('Публічний приклад'));expect(button).toBeDefined();button!.click();await vi.waitFor(()=>expect(payload).not.toBeNull());expect(payload.type).toBe('other');expect(payload.geometry.coordinates).toEqual([10.78,59.66]);expect(payload.source_ref).toContain('public-reference');expect(root.querySelectorAll('.querybar input')).toHaveLength(2)}finally{app.unmount();root.remove()}
})
it('fills the original soil and source tables from asset-context rather than seed data',async()=>{
 const paths:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(url:any)=>{paths.push(String(url));if(String(url)==='/api/v1/bootstrap')return json(base());if(String(url).startsWith('/api/v1/asset-context?'))return json({asset_id:'real-1',assessment_date:'2026-10-25',synthetic:false,soil:{composition:{sand:61,silt:25,clay:14},composition_depth_cm:[0,5],support_m:250,depths:[{top_cm:0,bottom_cm:5,texture:'Дані SoilGrids',estimate_kind:'modelled'}]},sources:[{id:'soilgrids',name:'ISRIC SoilGrids',product:'SoilGrids 250m',qc:'available',status:'available',note:'Витягнуто значення растра'}]});return json({})}))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{await vi.waitFor(()=>expect(paths.some(x=>x.startsWith('/api/v1/asset-context?'))).toBe(true));selectTab(root,'Об’єкти');await vi.waitFor(()=>expect(root.textContent).toContain('61%'));expect(root.textContent).not.toContain('40%');selectTab(root,'Джерела');await nextTick();expect(root.textContent).toContain('ISRIC SoilGrids');expect(root.querySelector('.querybar')).not.toBeNull()}finally{app.unmount();root.remove()}
})
it('clears old soil immediately and ignores context from an old date',async()=>{
 let reply:(x:Response)=>void=()=>{};const old=new Promise<Response>(r=>reply=r)
 vi.stubGlobal('fetch',vi.fn(async(url:any)=>{if(String(url)==='/api/v1/bootstrap')return json(base());if(String(url).includes('assessment_date=2026-10-25'))return old;return json({asset_id:'real-1',assessment_date:'2026-10-26',synthetic:false,soil:{...soil(),composition:{sand:72,silt:20,clay:8}},sources:[]})}))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App);app.mount(root)
 try{await vi.waitFor(()=>expect(root.querySelector('.map-layout')).not.toBeNull());await new Promise(r=>setTimeout(r,400));const date=root.querySelector<HTMLInputElement>('.querybar input[type=date]')!;date.value='2026-10-26';date.dispatchEvent(new Event('input',{bubbles:true}));selectTab(root,'Об’єкти');await vi.waitFor(()=>expect(root.textContent).toContain('72%'));reply(json({asset_id:'real-1',assessment_date:'2026-10-25',soil:{...soil(),composition:{sand:99,silt:1,clay:0}},sources:[]}));await new Promise(r=>setTimeout(r,0));expect(root.textContent).not.toContain('99%')}finally{app.unmount();root.remove()}
})
