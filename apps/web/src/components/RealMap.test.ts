// @vitest-environment jsdom
import {createApp,h,nextTick,ref} from 'vue'
import {afterEach,expect,it,vi} from 'vitest'
import RealMap from './RealMap.vue'
const state=vi.hoisted(()=>({events:{} as Record<string,(event?:any)=>void>,setLngLat:vi.fn()}))
vi.mock('maplibre-gl',()=>({setWorkerUrl:vi.fn(),NavigationControl:class{},Map:class{
 on(n:string,cb:any){state.events[n]=cb;return this} addControl(){} addSource(){} addLayer(){} isStyleLoaded(){return true} getSource(){return {setData(){}}} getZoom(){return 3} jumpTo(){} remove(){}
},Marker:class{setLngLat(p:any){state.setLngLat(p);return this} addTo(){if(!state.setLngLat.mock.calls.length)throw new Error('MapLibre requires coordinates before addTo');return this} remove(){}}}))
afterEach(()=>{vi.unstubAllGlobals();state.events={};state.setLngLat.mockClear()})
it('shows the selected coordinates on the real map without creating an asset',async()=>{
 vi.stubGlobal('ResizeObserver',class{})
 const point=ref<any>({}),root=document.createElement('div');document.body.append(root)
 const app=createApp({render:()=>h(RealMap,{assets:[],latitude:point.value.lat,longitude:point.value.lon})});app.mount(root)
 try{state.events.load();point.value={lat:59.91,lon:10.75};await nextTick();expect(state.setLngLat).toHaveBeenLastCalledWith([10.75,59.91])}finally{app.unmount();root.remove()}
})
it('makes a basemap failure visible without synthetic fallback',async()=>{
 vi.stubGlobal('ResizeObserver',class{})
 const root=document.createElement('div'),app=createApp(RealMap,{assets:[]});app.mount(root)
 try{state.events.error?.({error:new Error('Style offline')});await nextTick();expect(root.textContent).toContain('Карта недоступна')}finally{app.unmount()}
})
