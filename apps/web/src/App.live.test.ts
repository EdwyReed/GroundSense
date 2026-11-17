// @vitest-environment jsdom
import {createApp} from 'vue'
import {afterEach,expect,it,vi} from 'vitest'
import App from './App.vue'
vi.mock('./components/SchematicMap.vue',()=>({default:{template:'<div>Картографічні дані</div>'}}))
vi.mock('./components/ForecastChart.vue',()=>({default:{template:'<div>Тестовий графік</div>'}}))
afterEach(()=>vi.unstubAllGlobals())
it('keeps the original six-tab layout and two-field querybar with real data by default',async()=>{
 const paths:string[]=[]
 vi.stubGlobal('fetch',vi.fn(async(input:any)=>{paths.push(String(input));return new Response(JSON.stringify({workspace:{mode:'public_data',synthetic:false,private_data_allowed:false},assets:[],segments:[],sources:[],features:[],models:[],observations:[],inspections:[],context:{assessment_date:'2026-10-25',gross_mass_t:20},today:'2026-10-25',user:{role:'engineer'},csrf_token:'test-only',map:{}}),{status:200})}))
 const root=document.createElement('div');document.body.append(root);const app=createApp(App)
 // This test checks shell/data routing; real WebGL rendering is browser QA.
 app.config.errorHandler=()=>{}
 app.mount(root)
 try{
  await vi.waitFor(()=>expect(paths).toContain('/api/v1/bootstrap'))
  expect(paths).not.toContain('/api/v1/live/bootstrap')
  expect(root.querySelector('.live-workspace')).toBeNull()
  expect([...root.querySelectorAll('.masthead nav button')].map(x=>x.textContent)).toEqual(['Карта','Об’єкти','Прогноз','Спостереження','Джерела','Перевірки'])
  expect([...root.querySelectorAll<HTMLInputElement>('.querybar input')].map(x=>x.type)).toEqual(['date','number'])
  await vi.waitFor(()=>{for(const selector of ['.masthead','.querybar','.map-layout','.list-panel','.map-wrap'])expect(root.querySelector(selector)).not.toBeNull()})
  expect(root.textContent).not.toContain('Окремий тестовий')
  expect(root.textContent).not.toContain('Схематична карта · вигадані геометрії')
  expect(root.textContent).not.toContain('Демонстраційні дані · вигадані координати')
 }finally{app.unmount();root.remove()}
})
