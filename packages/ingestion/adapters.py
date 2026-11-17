"""Strict normalizers for declared data imports, not claims of live ingestion."""
from __future__ import annotations
import math


def number(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name}: потрібне скінченне число")
    if low is not None and value < low or high is not None and value > high:
        raise ValueError(f"{name}: поза допустимими межами")
    return float(value)


def soilgrids_profile(payload):
    version = payload.get("source_version")
    if not version:
        raise ValueError("Потрібна версія джерела")
    support = number(payload.get("support_m"), "support_m", .01)
    if not isinstance(payload.get("depths"), list) or not payload["depths"]:
        raise ValueError("Потрібні інтервали глибин")
    rows, last = [], -1.
    for raw in payload["depths"]:
        top = number(raw.get("top_cm"), "top_cm", 0)
        bottom = number(raw.get("bottom_cm"), "bottom_cm", top)
        if bottom <= top or top < last:
            raise ValueError("Глибини мають бути впорядковані та не перетинатися")
        last = bottom
        composition = {k: raw.get(k + "_g_kg") for k in ("sand", "silt", "clay")}
        if any(v is None for v in composition.values()):
            composition, status = None, "nodata"
        else:
            composition = {k:number(v,k,0,1000)/10 for k,v in composition.items()}
            if abs(sum(composition.values()) - 100) > 1:
                raise ValueError("Компоненти ґрунту мають давати 100 ± 1 %")
            status = "modelled"
        rows.append({"top_cm":top,"bottom_cm":bottom,"composition_percent":composition,"status":status})
    return {"source_version":version,"support_m":support,"depths":rows,"taxonomy":payload.get("taxonomy"),
            "road_material_observed":False,"native_units":"g/kg","output_units":"%", "transform_version":"soilgrids-gkg/v1"}


def satellite_evidence(payload):
    """Preserve declared QC, never turn SAR backscatter into water by fiat."""
    product=payload.get('product')
    if product not in ('sentinel-1','sentinel-2','clms-swi'):
        raise ValueError('Невідомий супутниковий продукт')
    if not payload.get('source_version'):
        raise ValueError('Потрібна версія продукту')
    required={'sentinel-1':('orbit','incidence_angle','radiometric_calibration','speckle_filter','terrain_mask','vegetation_mask','freeze_mask','water_mask'),
              'sentinel-2':('cloud_mask','snow_mask','water_mask','canopy_mask'),
              'clms-swi':('coverage_confirmed','quality_mask','depth_definition')}[product]
    qc=payload.get('qc',{})
    missing=[key for key in required if qc.get(key) is None]
    rejected=[key for key in ('terrain_mask','freeze_mask','water_mask','cloud_mask') if qc.get(key)=='rejected']
    # Complete metadata only makes evidence reviewable, not assimilated or calibrated.
    reasons=[]
    if missing: reasons.append('SAR_QC_INCOMPLETE' if product=='sentinel-1' else 'PRODUCT_QC_INCOMPLETE')
    if rejected: reasons.append('QC_REJECTED')
    if not payload.get('approved_observation_operator'): reasons.append('OBSERVATION_OPERATOR_UNAVAILABLE')
    return {'product':product,'source_version':payload['source_version'],'native_support_m':payload.get('native_support_m'),
            'observed_at':payload.get('observed_at'),'recorded_at':payload.get('recorded_at'), 'qc':qc,
            'missing_qc':missing,'reason_codes':reasons,'evidence_status':'quarantined' if missing or rejected else 'review_required',
            'eligible_for_assimilation':False, 'soil_water_state':None,'raw_value':payload.get('value'),
            'transform_version':'satellite-evidence-gate/v1'}


def terrain_features(payload):
    if not payload.get('source_version'):
        raise ValueError('Потрібна версія DEM')
    cell=number(payload.get('cell_size_m'),'cell_size_m',.001)
    z=payload.get('elevations_m')
    if not isinstance(z,list) or len(z)!=3 or any(not isinstance(row,list) or len(row)!=3 for row in z):
        raise ValueError('Потрібне ядро DEM 3 × 3')
    slope=None
    if all(v is not None for row in z for v in row):
        z=[[number(v,'elevation_m') for v in row] for row in z]
        dx=((z[0][2]+2*z[1][2]+z[2][2])-(z[0][0]+2*z[1][0]+z[2][0]))/(8*cell)
        dy=((z[2][0]+2*z[2][1]+z[2][2])-(z[0][0]+2*z[0][1]+z[0][2]))/(8*cell)
        slope=math.degrees(math.atan(math.hypot(dx,dy)))
    return {'source_version':payload['source_version'],'native_support_m':cell,'surface_kind':payload.get('surface_kind','unknown'),
            'slope_degrees':slope,'culvert_status':'unknown','drainage_status':'unknown',
            'bare_earth_confirmed':payload.get('surface_kind')=='DTM' and payload.get('bare_earth_evidence') is not None,
            'local_road_grade_confirmed':False,'transform_version':'horn3x3/v1','status':'nodata' if slope is None else 'derived'}

