// @vitest-environment jsdom
import {createApp,h,nextTick,ref} from 'vue'
import {afterEach,expect,it,vi} from 'vitest'
import SchematicMap from './SchematicMap.vue'
const state=vi.hoisted(()=>({options:{} as any,events:{} as Record<string,Function>,sources:{} as Record<string,any>,layers:{} as Record<string,any>,visibility:vi.fn(),jump:vi.fn(),remove:vi.fn()}))
vi.mock('maplibre-gl',()=>({setWorkerUrl:vi.fn(),NavigationControl:class{},Map:class{
 constructor(options:any){state.options=options}
 on(name:string,layerOrCb:any,cb?:any){state.events[cb?`${name}:${layerOrCb}`:name]=cb||layerOrCb;return this}
 addControl(){} addSource(id:string,source:any){state.sources[id]={...source,setData(data:any){this.data=data}}} addLayer(layer:any){state.layers[layer.id]=layer}
 getSource(id:string){return state.sources[id]} getLayer(id:string){return state.layers[id]||['landcover_wood','waterway_river','road_primary','landuse'].includes(id)}
 getStyle(){return {layers:[{id:'landcover_wood','source-layer':'landcover'},{id:'waterway_river','source-layer':'waterway'},{id:'road_primary','source-layer':'transportation'},{id:'landuse','source-layer':'landuse'}]}}
 queryRenderedFeatures(){return [{source:'openmaptiles'},{source:'assets'}]}
 isStyleLoaded(){return true} setLayoutProperty(...args:any[]){state.visibility(...args)} setPaintProperty(){} jumpTo(...args:any[]){state.jump(...args)} getCanvas(){return {style:{cursor:''}}} remove(){state.remove()}
}}))
afterEach(()=>{state.options={};state.events={};state.sources={};state.layers={};state.visibility.mockClear();state.jump.mockClear();state.remove.mockClear()})
it('uses a real basemap inside the original map and layer controls without seed geometry',async()=>{
 const root=document.createElement('div');const app=createApp(SchematicMap,{map:{features:[{properties:{kind:'field'},geometry:{type:'Polygon',coordinates:[]}}]},assets:[],segments:[],selectedId:''});app.mount(root)
 try{expect(state.options.style).toBe('https://tiles.openfreemap.org/styles/liberty');state.events.load();expect(Object.keys(state.sources)).toEqual(['segments','assets']);expect(root.querySelectorAll('.layer-toggle input')).toHaveLength(5);expect(root.querySelector('.map')?.getAttribute('aria-label')).not.toContain('Схематична');const forests=root.querySelectorAll<HTMLInputElement>('.layer-toggle input')[1];forests.checked=false;forests.dispatchEvent(new Event('change',{bubbles:true}));await nextTick();expect(state.visibility).toHaveBeenCalledWith('landcover_wood','visibility','none')}finally{app.unmount()}
})
it('centres on the real selected point and emits asset selection',async()=>{
 const selected=ref('a'),picked=vi.fn(),assets=[{id:'a',geometry:{type:'Point',coordinates:[10.75,59.91]}},{id:'b',geometry:{type:'Point',coordinates:[10.76,59.92]}}];const root=document.createElement('div');const app=createApp({render:()=>h(SchematicMap,{map:null,assets,segments:[],selectedId:selected.value,onSelect:picked})});app.mount(root)
 try{state.events.load();expect(state.jump).toHaveBeenCalledWith(expect.objectContaining({center:[10.75,59.91]}));state.events['click:assets']({features:[{properties:{id:'b'}}]});expect(picked).toHaveBeenCalledWith('b');selected.value='b';await nextTick();expect(state.jump).toHaveBeenLastCalledWith(expect.objectContaining({center:[10.76,59.92]}))}finally{app.unmount()}
})
it('reports actual rendered vector features instead of equating a canvas with a loaded map',()=>{
 const root=document.createElement('div');const app=createApp(SchematicMap,{map:null,assets:[{id:'a',geometry:{type:'Point',coordinates:[10.78,59.66]}}],segments:[],selectedId:'a'});app.mount(root)
 try{state.events.load();expect(state.events.idle).toBeTypeOf('function');state.events.idle();expect((root.querySelector('.map') as HTMLElement).dataset).toMatchObject({renderedAssetCount:'1',renderedBasemapFeatureCount:'1'})}finally{app.unmount()}
})
