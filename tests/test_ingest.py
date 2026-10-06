import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import normalize_ons, product_kind, levels_for_title, centroid_weight, YEAR

class VintageSemantics(unittest.TestCase):
    def item(self,title):
        return dict(id='fixture',title=title,type='Feature Service',created=1780000000000,modified=1780000000000,url='https://example.org/FeatureServer')

    def test_upload_date_does_not_replace_boundary_vintage(self):
        row=normalize_ons(self.item('Local Authority Districts (December 2011) Boundaries UK BFC'))
        self.assertEqual(row['year'],2011)
        self.assertEqual(row['modified'],'2026-05-28')
        self.assertEqual(len(row['countries']),4)

    def test_lookup_retains_source_target_and_assignment_vintages(self):
        row=normalize_ons(self.item('LSOA (2011) to LSOA (2021) to Local Authority District (2022) Exact Fit Lookup for EW (V3)'))
        self.assertEqual(row['years'],[2011,2021,2022])
        self.assertIsNone(row['year'])
        self.assertEqual(row['method'],'Exact Fit')
        self.assertIn('lsoa',row['levels']);self.assertIn('lad',row['levels'])
        self.assertNotIn('oa-ew',row['levels'])

    def test_current_undated_layer_has_no_annual_vintage(self):
        row=normalize_ons(self.item('Local Authority Districts Boundaries UK'))
        self.assertIsNone(row['year']);self.assertEqual(row['years'],[])

    def test_health_and_devolved_regions_are_not_english_regions(self):
        for title in ['NHS Regions (2018) Boundaries EN','Scottish Parliamentary Regions (2026) Boundaries SC','Senedd Cymru Electoral Regions (2022) Boundaries WA']:
            self.assertNotIn('region',levels_for_title(title))
        self.assertIn('region',levels_for_title('Regions (December 2025) Boundaries EN BFC'))

    def test_country_and_future_scope_are_not_guessed(self):
        self.assertEqual(normalize_ons(self.item('Output Areas (2011) Boundaries'))['countries'],[])
        self.assertIsNone(normalize_ons(self.item(f'Output Areas ({YEAR+1}) Boundaries EW')))
        self.assertEqual(product_kind('National Statistics Postcode Lookup (2026) User Guide'),'reference')

    def test_centroid_weighting_is_not_inferred_from_the_geography_name(self):
        self.assertEqual(centroid_weight('Workplace Zone Centroids','centroid'),'not-specified')
        self.assertEqual(centroid_weight('OA Population-Weighted Centroids','centroid'),'population')
        self.assertEqual(centroid_weight('LSOA Address Weighted Centroids','centroid'),'address')
        self.assertEqual(centroid_weight('Population Weighted Centroids Guidance','reference'),'')

class CatalogueIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((Path(__file__).resolve().parents[1]/'dist/catalogue.json').read_text(encoding='utf-8'))

    def test_registry_and_public_links(self):
        items=self.data['items']; ids={x['id'] for x in items}
        self.assertEqual(len(ids),len(items))
        levels={x['id'] for x in self.data['levels']};providers={x['id'] for x in self.data['providers']}
        for row in items:
            self.assertTrue(set(row['levels'])<=levels,row['title'])
            self.assertIn(row['provider'],providers)
            self.assertTrue(row['source'].startswith('https://'))
            self.assertNotIn('geometry',row)
            for file in row['downloads']: self.assertTrue(file['url'].startswith('https://'))

    def test_all_four_national_census_systems_have_required_reference_files(self):
        expected={'oa-ew':[2001,2011,2021],'lsoa':[2001,2011,2021],'msoa':[2001,2011,2021],
                  'oa-sc':[2001,2011,2022],'dz-sc':[2001,2011,2022],'iz-sc':[2001,2011,2022],
                  'oa-ni':[2001],'sa-ni':[2011],'soa-ni':[2011],'dz-ni':[2021],'sdz-ni':[2021]}
        for level,years in expected.items():
            found={x['year'] for x in self.data['items'] if level in x['levels'] and x['kind']=='boundary'}
            self.assertTrue(set(years)<=found,(level,found))

    def test_unlabelled_welsh_community_layer_is_not_backfilled(self):
        row=next(x for x in self.data['items'] if x['provider']=='wales' and x['title']=='Communities (Wales)')
        self.assertEqual(row['years'],[]);self.assertIsNone(row['year'])

    def test_mayoral_family_and_cca_membership_use_audited_snapshots(self):
        rows=[x for x in self.data['items'] if x['kind']=='boundary' and 'strategic' in x['levels']]
        cca=next(x for x in rows if x['vintage']=='December 2025' and 'cca' in x['levels'])
        self.assertTrue(any(a['code']=='E47000013' and a['name']=='East Midlands' for a in cca['areas']))
        self.assertFalse(any('cca' in x['levels'] for x in rows if x['year']==2023))
        gla=next(x for x in rows if 'gla' in x['levels'])
        self.assertEqual(gla['years'],[])
        orders=[x for x in self.data['items'] if x['provider']=='legislation']
        self.assertEqual(len(orders),4)
        self.assertTrue(all(x['kind']=='reference' for x in orders))

    def test_employment_centroid_has_documented_workforce_basis(self):
        row=next(x for x in self.data['items'] if x['id']=='ons:315bb1094745426c8c63651825322183')
        self.assertEqual(row['centroidWeight'],'employment')
        self.assertEqual(row['centroidWeightYear'],2011)
        self.assertIn('Census 2011 workers',row['centroidWeightBasis'])
        self.assertTrue(row['centroidMethodology'].endswith('/data'))

if __name__=='__main__': unittest.main()
