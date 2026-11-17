// @vitest-environment jsdom
import {createApp} from 'vue'
import {afterEach,expect,it,vi} from 'vitest'
import LiveWeatherChart from './LiveWeatherChart.vue'
const mocks=vi.hoisted(()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn()}))
vi.mock('echarts',()=>({init:()=>mocks}))
afterEach(()=>vi.restoreAllMocks())
it('uses separate physical axes for temperature moisture and precipitation',()=>{
 vi.spyOn(HTMLElement.prototype,'clientWidth','get').mockReturnValue(800)
 const root=document.createElement('div');document.body.append(root)
 const app=createApp(LiveWeatherChart,{weather:{series:[]} as any});app.mount(root)
 try{
  const option=mocks.setOption.mock.calls.at(-1)![0]
  expect(option.yAxis.map((axis:any)=>axis.name)).toEqual(['°C','м³/м³','мм'])
  expect(option.series.map((series:any)=>series.yAxisIndex??0)).toEqual([0,1,1,2])
 }finally{app.unmount();root.remove()}
})
