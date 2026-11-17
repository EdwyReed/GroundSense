"""Declared product normalization; no live-source availability claims."""
import unittest
try:
    from packages.ingestion.adapters import soilgrids_profile
except ModuleNotFoundError:
    soilgrids_profile = None

class SoilAdapterTest(unittest.TestCase):
    def test_native_units_depths_and_nodata_survive(self):
        self.assertIsNotNone(soilgrids_profile, 'SoilGrids normalization is not implemented')
        raw={'source_version':'sg2-fixture','support_m':250,'depths':[
            {'top_cm':0,'bottom_cm':5,'sand_g_kg':400,'silt_g_kg':380,'clay_g_kg':220},
            {'top_cm':5,'bottom_cm':15,'sand_g_kg':None,'silt_g_kg':None,'clay_g_kg':None}]}
        result=soilgrids_profile(raw)
        self.assertEqual(result['depths'][0]['composition_percent'], {'sand':40.,'silt':38.,'clay':22.})
        self.assertEqual(result['depths'][1]['status'],'nodata')
        self.assertIsNone(result['taxonomy'])
        self.assertEqual(result['support_m'],250)
        self.assertFalse(result['road_material_observed'])

class EvidenceAdaptersTest(unittest.TestCase):
    def test_missing_sar_qc_does_not_become_valid_measurement(self):
        from packages.ingestion import adapters
        fn=getattr(adapters,'satellite_evidence',None)
        self.assertIsNotNone(fn,'Satellite QC adapter is missing')
        row=fn({'product':'sentinel-1','source_version':'s1-test','native_support_m':20,'value':.37})
        self.assertFalse(row['eligible_for_assimilation'])
        self.assertIn('SAR_QC_INCOMPLETE',row['reason_codes'])
        self.assertIsNone(row['soil_water_state'])

    def test_bare_earth_and_culvert_are_not_invented_from_dsm(self):
        from packages.ingestion import adapters
        fn=getattr(adapters,'terrain_features',None)
        self.assertIsNotNone(fn,'Terrain adapter is missing')
        row=fn({'elevations_m':[[0,1,2],[0,1,2],[0,1,2]],'cell_size_m':10,'surface_kind':'DSM','source_version':'dem-test'})
        self.assertAlmostEqual(row['slope_degrees'],5.7105931375,places=8)
        self.assertEqual(row['culvert_status'],'unknown')
        self.assertFalse(row['bare_earth_confirmed'])
        row=fn({'elevations_m':[[0,1,2],[0,None,2],[0,1,2]],'cell_size_m':10,'surface_kind':'DSM','source_version':'dem-test'})
        self.assertIsNone(row['slope_degrees'])

if __name__=='__main__': unittest.main()
