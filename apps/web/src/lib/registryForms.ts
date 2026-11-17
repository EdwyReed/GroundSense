export type RegistryKind = 'assets'|'segments'|'observations'|'protocols'|'models'|'envelopes'|'constraints'|'tickets'|'subscriptions'|'inspections'
export type RegistryDraft = Record<string, string>
export type PayloadResult = {ok:true; payload:Record<string, unknown>} | {ok:false; errors:Record<string,string>}

const controlled=new Set(['id','version','workspace_id','entered_at','adjudication','calibrated','model_approval','production_eligible','metadata_only','tombstoned'])
const metadataFields=new Set(['name','description','status','scope','card_ref','source_ref','reason','synthetic'])
const editable:Record<RegistryKind,string[]>={
  assets:['name','type','condition','source_ref','synthetic','geometryText'],
  segments:['asset_id','length_m','surface','construction','drainage','culvert_status','geometryText'],
  observations:[], protocols:['name','method','unit','requiredFieldsText'],
  models:['name','status','scope','card_ref','reason'], envelopes:['name','scope','reason'],
  constraints:['asset_id','segment_id','kind','status','reason'],
  tickets:['asset_id','segment_id','title','status','reason','due_at'],
  subscriptions:['asset_id','segment_id','channel','status','note'],
  inspections:['asset_id','segment_id','status','reason','scheduled_at']
}
const knownDefaults:Record<RegistryKind,Record<string,unknown>>={
  assets:{name:'',type:'well',condition:'unknown',source_ref:'',synthetic:true},
  segments:{asset_id:'',length_m:'',surface:'unknown',construction:'unknown',drainage:'unknown',culvert_status:'unknown'},
  observations:{}, protocols:{name:'',method:'',unit:'',required_fields:[]},
  models:{name:'',status:'research',scope:'',card_ref:'',reason:''}, envelopes:{name:'',scope:'',reason:''},
  constraints:{asset_id:'',segment_id:'',kind:'culvert',status:'unknown',reason:''},
  tickets:{asset_id:'',segment_id:'',title:'',status:'open',reason:'',due_at:''},
  subscriptions:{asset_id:'',segment_id:'',channel:'in_app',status:'active',note:''},
  inspections:{asset_id:'',segment_id:'',status:'requested',reason:'',scheduled_at:''}
}
export const registryKinds=Object.keys(knownDefaults) as RegistryKind[]
export function draftForRegistry(kind:RegistryKind, record?:Record<string,any>):RegistryDraft {
  const value={...knownDefaults[kind],...(record||{})}; const draft:RegistryDraft={}
  for(const key of editable[kind]) {
    if(key==='geometryText') draft[key]=record?.geometry ? JSON.stringify(record.geometry,null,2) : ''
    else if(key==='requiredFieldsText') draft[key]=Array.isArray(value.required_fields)?value.required_fields.join(', '):''
    else if(key==='due_at'||key==='scheduled_at') draft[key]=timestampDraft(value[key])
    else draft[key]=value[key]===undefined||value[key]===null?'':String(value[key])
  }
  return draft
}
function timestampDraft(value:unknown):string {
  if(typeof value!=='string'||!value) return ''
  if(!/(Z|[+-]\d{2}:\d{2})$/.test(value)) return value
  const parsed=new Date(value)
  return Number.isNaN(parsed.getTime())?value:parsed.toISOString().replace(/(?:\.000)?Z$/,'')
}
function timestampValue(value:string,field:string,errors:Record<string,string>):string|undefined {
  const parsed=new Date(value+'Z')
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,3})?)?$/.test(value)||Number.isNaN(parsed.getTime())||parsed.toISOString().slice(0,value.length)!==value) {
    errors[field]='Вкажіть коректний час UTC.';return undefined
  }
  return parsed.toISOString()
}
function structured(value:string, field:string, errors:Record<string,string>){
  if(!value.trim()) return undefined
  try{return JSON.parse(value)}catch{errors[field]='Вкажіть коректний JSON у розширеному полі.'; return undefined}
}
function geometryValue(kind:RegistryKind,value:string,errors:Record<string,string>){
  const geometry=structured(value,'geometryText',errors)
  if(geometry===undefined||geometry===null) return geometry
  const point=(p:unknown)=>Array.isArray(p)&&p.length===2&&p.every(v=>typeof v==='number'&&Number.isFinite(v))&&Math.abs(p[0])<=180&&Math.abs(p[1])<=90
  const valid=typeof geometry==='object'&&!Array.isArray(geometry)&&(kind==='assets'
    ?geometry.type==='Point'&&point(geometry.coordinates)
    :geometry.type==='LineString'&&Array.isArray(geometry.coordinates)&&geometry.coordinates.length>=2&&geometry.coordinates.every(point))
  if(!valid){errors.geometryText='Потрібна WGS84 геометрія Point для об’єкта або LineString для ділянки з коректними координатами.';return undefined}
  return geometry
}
function numberValue(value:string, field:string, errors:Record<string,string>){
  if(value.trim()==='') {errors[field]='Поле обов’язкове.'; return undefined}
  const parsed=Number(value); if(!Number.isFinite(parsed)||parsed<0){errors[field]='Вкажіть невід’ємне число.'; return undefined}; return parsed
}
export function buildRegistryPayload(kind:RegistryKind,draft:RegistryDraft,original?:Record<string,any>):PayloadResult {
  const payload:Record<string,unknown>={}
  for(const [key,value] of Object.entries(original||{})) if(!controlled.has(key)&&(!['models','envelopes'].includes(kind)||metadataFields.has(key))) payload[key]=value
  const errors:Record<string,string>={}
  if(kind==='observations') return {ok:false,errors:{form:'Спостереження вносяться лише на окремій сторінці та проходять рецензування.'}}
  for(const key of editable[kind]) {
    if(key==='geometryText') {const geometry=geometryValue(kind,draft[key]||'',errors); if(geometry!==undefined) payload.geometry=geometry; else if(!draft[key]?.trim()&&original&&Object.hasOwn(original,'geometry')) payload.geometry=null}
    else if(key==='requiredFieldsText') payload.required_fields=(draft[key]||'').split(',').map(x=>x.trim()).filter(Boolean)
    else if(key==='synthetic') payload.synthetic=draft[key]==='true'
    else if(key==='length_m') {const n=numberValue(draft[key]||'',key,errors); if(n!==undefined)payload[key]=n}
    else if(key==='due_at'||key==='scheduled_at') {
      if(!draft[key]) {if(original&&Object.hasOwn(original,key))payload[key]=null;else delete payload[key]}
      else if(original&&draft[key]===timestampDraft(original[key]))payload[key]=original[key]
      else {const time=timestampValue(draft[key],key,errors);if(time!==undefined)payload[key]=time}
    }
    else payload[key]=draft[key]||''
  }
  for(const key of controlled) delete payload[key]
  return Object.keys(errors).length?{ok:false,errors}:{ok:true,payload}
}
