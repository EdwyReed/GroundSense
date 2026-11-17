<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as maplibregl from 'maplibre-gl'
import mapWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { LiveAsset } from '../lib/liveData'
maplibregl.setWorkerUrl(mapWorkerUrl)
const props=defineProps<{assets:LiveAsset[];latitude?:number;longitude?:number}>()
const emit=defineEmits<{point:[latitude:number,longitude:number]}>()
const root=ref<HTMLDivElement>();const mapError=ref('');let map:maplibregl.Map|undefined;let selected:maplibregl.Marker|undefined
function showSelection(){if(!map)return;const lat=props.latitude,lon=props.longitude;if(lat===undefined||lon===undefined||!Number.isFinite(lat)||!Number.isFinite(lon)){selected?.remove();selected=undefined;return}if(!selected)selected=new maplibregl.Marker({color:'#215f4b'}).setLngLat([lon,lat]).addTo(map);else selected.setLngLat([lon,lat]);map.jumpTo({center:[lon,lat],zoom:Math.max(8,map.getZoom())})}
const points=()=>({type:'FeatureCollection' as const,features:props.assets.map(asset=>({type:'Feature' as const,properties:{name:asset.name},geometry:asset.geometry}))})
function update(){if(!map?.isStyleLoaded())return; (map.getSource('live-assets') as maplibregl.GeoJSONSource|undefined)?.setData(points() as any)}
onMounted(()=>{if(!root.value||typeof ResizeObserver==='undefined')return;try{map=new maplibregl.Map({container:root.value,style:'https://tiles.openfreemap.org/styles/liberty',center:[10,52],zoom:3,attributionControl:false});map.addControl(new maplibregl.NavigationControl(),'top-right');map.on('error',()=>{mapError.value='Карта недоступна: не вдалося завантажити картографічні дані.'});map.on('load',()=>{map?.addSource('live-assets',{type:'geojson',data:points() as any});map?.addLayer({id:'live-assets',type:'circle',source:'live-assets',paint:{'circle-radius':7,'circle-color':'#426a53','circle-stroke-width':2,'circle-stroke-color':'#fff'}});update();showSelection()});map.on('click',event=>emit('point',Number(event.lngLat.lat.toFixed(6)),Number(event.lngLat.lng.toFixed(6))))}catch{mapError.value='Карта недоступна: браузер не підтримує потрібний графічний режим.'}})
watch(()=>props.assets,update,{deep:true});watch(()=>[props.latitude,props.longitude],showSelection);onBeforeUnmount(()=>{selected?.remove();map?.remove()})
</script>
<template><div class="map-shell"><p v-if="mapError" class="map-error" role="alert">{{mapError}}</p><div ref="root" class="map" aria-label="Карта OpenFreeMap. Натисніть, щоб вибрати координати"></div><p class="attribution">© <a href="https://openfreemap.org/" target="_blank" rel="noopener">OpenFreeMap</a> · © <a href="https://openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> · © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a></p></div></template>
<style scoped>.map-error{position:absolute;z-index:2;background:#fff4e5;color:#7b3e13;padding:8px;max-width:85%}.map-shell{height:100%;min-height:300px;position:relative}.map{height:100%;min-height:300px;width:100%;background:#dfe6dc}.attribution{position:absolute;bottom:0;left:0;margin:0;padding:4px 7px;background:#fffffff0;font-size:11px}.attribution a{color:#21563e}</style>
