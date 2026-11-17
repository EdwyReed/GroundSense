import { ApiClient, ApiError } from './api'

export type LiveAsset={id:string;version:number;name:string;latitude:number;longitude:number;geometry:{type:'Point';coordinates:[number,number]};source_ref:string;synthetic:false;data_origin:'user_supplied';condition:'unknown'}
export type WeatherDTO={mode:'live';synthetic:false;assessment_date:string;requested_point:{latitude:number;longitude:number};grid_point:{latitude:number;longitude:number;elevation_m:number|null};source:{id:'open-meteo-icon-global';provider:string;product:string;model:string;request_url:string;retrieved_at:string;issue_time:null;license:string;service_usage:'non_commercial_prototype';attribution_url:string;content_sha256:string;cached:boolean};units:Record<string,string>;series:Array<{time:string;temperature_2m:number|null;precipitation:number|null;soil_moisture_0_to_1cm:number|null;soil_moisture_1_to_3cm:number|null;soil_temperature_0cm:number|null;precipitation_interval_start:string;precipitation_interval_end:string}>;qc:{status:'available'|'partial';missing_variables:string[];is_observation:false;spatial_support:'model_grid_not_road'};mobility:{kind:'unavailable';reason:string}}
export type LiveBootstrap={workspace:{id:string;mode:'public_data';synthetic:false;private_data_allowed:false};csrf_token:string;user:{role:string};assets:LiveAsset[];sources:unknown[];today:string}

export async function getLiveBootstrap(fetcher:typeof fetch=globalThis.fetch.bind(globalThis)):Promise<LiveBootstrap>{
 const response=await fetcher('/api/v1/live/bootstrap',{credentials:'same-origin'}); const payload=await response.json().catch(()=>({})); if(!response.ok)throw new ApiError(response.status,payload.detail||payload.message||`Помилка сервера (${response.status})`); return payload as LiveBootstrap
}
export class LiveDataClient {
 constructor(private api:ApiClient){}
 createAsset(payload:Pick<LiveAsset,'name'|'latitude'|'longitude'|'source_ref'>){return this.api.post<LiveAsset>('/live/assets',payload)}
 importAssets(format:'csv'|'geojson',data:string){return this.api.post<{items:LiveAsset[];imported:number}>('/live/assets/import',{format,data})}
 async weather(latitude:number,longitude:number,assessmentDate:string,signal?:AbortSignal){const query=new URLSearchParams({latitude:String(latitude),longitude:String(longitude),assessment_date:assessmentDate}); const response=await fetch(`/api/v1/live/weather?${query.toString()}`,{credentials:'same-origin',signal});const payload=await response.json().catch(()=>({}));if(!response.ok)throw new ApiError(response.status,payload.detail||payload.message||`Помилка сервера (${response.status})`);return payload as WeatherDTO}
}
export const snapshotUrl=(digest:string)=>`/api/v1/live/weather/snapshots/${encodeURIComponent(digest.replace(/^sha256:/,''))}`
