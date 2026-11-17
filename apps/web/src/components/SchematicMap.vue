<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import 'maplibre-gl/dist/maplibre-gl.css'
maplibregl.setWorkerUrl(mapWorkerUrl)
const props = defineProps<{ map: Record<string, any> | null; assets: any[]; segments: any[]; selectedId: string }>()
const emit = defineEmits<{ select: [id: string]; status: [message: string] }>(); const root = ref<HTMLDivElement>(); const layers = ref({ fields: true, forests: true, river: true, roads: true, assets: true }); let instance: maplibregl.Map | undefined;let rendered=false
const fc = (items: any[]) => ({ type: 'FeatureCollection', features: items.filter(x => x.geometry).map(x => ({ type: 'Feature', properties: { ...x.properties, id: x.id, condition: x.condition || 'unknown', name: x.name || x.id }, geometry: x.geometry })) })
function visible() {
 if (!instance?.isStyleLoaded()) return
 for (const layer of instance.getStyle().layers || []) {
  const sourceLayer='source-layer' in layer?layer['source-layer']:''
  const key=layer.id==='assets'||layer.id==='asset-labels'?'assets':layer.id==='segments'||sourceLayer==='transportation'||sourceLayer==='transportation_name'?'roads':sourceLayer==='water'||sourceLayer==='waterway'||sourceLayer==='water_name'?'river':layer.id==='landcover_wood'?'forests':layer.id==='landcover_grass'||sourceLayer==='landuse'?'fields':null
  if(key)instance.setLayoutProperty(layer.id,'visibility',layers.value[key]?'visible':'none')
 }
 for(const id of ['assets','asset-labels','segments'])if(instance.getLayer(id))instance.setLayoutProperty(id,'visibility',layers.value[id==='segments'?'roads':'assets']?'visible':'none')
}
function update() { if (!instance?.isStyleLoaded()) return; (instance.getSource('assets') as maplibregl.GeoJSONSource)?.setData(fc(props.assets) as any); (instance.getSource('segments') as maplibregl.GeoJSONSource)?.setData(fc(props.segments) as any); if(instance.getLayer('assets'))instance.setPaintProperty('assets','circle-radius',['case',['==',['get','id'],props.selectedId],10,7]);visible() }
function focusSelected(){const point=props.assets.find(x=>x.id===props.selectedId)?.geometry;if(point?.type==='Point'&&point.coordinates?.length>=2&&point.coordinates.slice(0,2).every((x:any)=>typeof x==='number'&&Number.isFinite(x)))instance?.jumpTo({center:point.coordinates.slice(0,2),zoom:13})}
onMounted(()=>{
 if(!root.value)return
 instance=new maplibregl.Map({container:root.value,style:'https://tiles.openfreemap.org/styles/liberty',center:[15,50],zoom:4,attributionControl:{compact:true,customAttribution:'<a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a> · <a href="https://openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap</a>'}})
 instance.addControl(new maplibregl.NavigationControl(),'top-right')
 instance.on('idle',()=>{
  if(!root.value||!instance?.getLayer('assets'))return
  const features=instance.queryRenderedFeatures()
  root.value.dataset.renderedAssetCount=String(features.filter(f=>f.source==='assets').length)
  root.value.dataset.renderedBasemapFeatureCount=String(features.filter(f=>f.source!=='assets'&&f.source!=='segments').length)
 })
 instance.on('error',()=>emit('status',rendered?'Частину картографічних тайлів не завантажено.':'Карта недоступна: картографічне джерело не завантажено. Синтетичної підміни немає.'))
 instance.on('load',()=>{
  instance!.addSource('segments',{type:'geojson',data:fc(props.segments) as any})
  instance!.addLayer({id:'segments',type:'line',source:'segments',paint:{'line-color':'#202923','line-width':4,'line-dasharray':[2,1]}})
  instance!.addSource('assets',{type:'geojson',data:fc(props.assets) as any})
  instance!.addLayer({id:'assets',type:'circle',source:'assets',paint:{'circle-radius':7,'circle-color':'#7a8388','circle-stroke-color':'#fff','circle-stroke-width':2}})
  instance!.addLayer({id:'asset-labels',type:'symbol',source:'assets',layout:{'text-field':['get','id'],'text-size':10,'text-offset':[0,1.4]}} as any)
  instance!.on('click','assets',e=>{const id=e.features?.[0]?.properties?.id;if(id)emit('select',id)})
  instance!.on('mouseenter','assets',()=>instance!.getCanvas().style.cursor='pointer');instance!.on('mouseleave','assets',()=>instance!.getCanvas().style.cursor='')
  update();focusSelected();rendered=true;emit('status','')
 })
})
watch(() => [props.assets,props.segments], update,{deep:true});watch(()=>props.selectedId,()=>{update();focusSelected()});watch(layers,visible,{deep:true});onBeforeUnmount(()=>instance?.remove())
</script><template><div class="layer-toggle" aria-label="Шари карти"><label v-for="(_, key) in layers" :key="key"><input type="checkbox" v-model="layers[key as keyof typeof layers]"> {{({fields:'Поля',forests:'Ліси',river:'Річка',roads:'Дороги',assets:'Об’єкти'} as any)[key]}}</label></div><div ref="root" class="map" aria-label="Карта OpenStreetMap: поля, ліси, річки, дороги та користувацькі об’єкти"></div></template><style scoped>.map{width:100%;height:100%}.layer-toggle{position:absolute;z-index:2;right:8px;bottom:8px;background:#fffffff2;padding:6px;display:grid;gap:3px;font-size:12px}</style>
