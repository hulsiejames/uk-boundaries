import json
import unittest
from pathlib import Path
from unittest.mock import patch
from dataset_metadata import timestamp, normalize_layer, apply_metadata, capture_service, refresh_metadata


class PublisherMetadata(unittest.TestCase):
    def row(self):
        return dict(id='ons:example', service='https://example.org/FeatureServer', source='https://example.org/about', downloads=[], published='2020-01-01', modified='2026-04-29', year=2011)

    def layer(self):
        return dict(id=7, name='Boundaries', fields=[dict(name='CODE', alias='Area code', type='esriFieldTypeString', length=9, nullable=False)], editingInfo=dict(dataLastEditDate=1777039481609))

    def test_timestamps_do_not_invent_dates_or_time_zones(self):
        for value in [None, '', 0, -1, True, 'yesterday']:
            self.assertIsNone(timestamp(value))
        self.assertEqual(timestamp(1777451050000), '2026-04-29T08:24:10.000Z')
        self.assertEqual(timestamp('2026-04-24T15:35:20'), '2026-04-24T15:35:20')

    def test_publisher_dates_override_service_edits_without_overwriting_vintage(self):
        hub=dict(id='example_7', downloadable=True, metadata=dict(metadata=dict(dataIdInfo=dict(idCitation=dict(date=dict(pubDate='2026-04-24T15:35:20',reviseDate='2026-03-10T00:00:00'))))))
        layer=normalize_layer(self.layer(), 'https://example.org/FeatureServer/7', hub)
        entry=dict(service=self.row()['service'],checked='2026-10-09',status='captured',layers=[layer])
        row=apply_metadata(self.row(),entry)
        self.assertEqual(row['year'],2011)
        self.assertEqual(row['dates']['uploaded']['value'],'2020-01-01')
        self.assertEqual(row['dates']['published']['value'],'2026-04-24T15:35:20')
        self.assertEqual(row['dates']['dataUpdated']['value'],'2026-03-10T00:00:00')
        self.assertIn('/api/v3/datasets/',row['dates']['published']['source'])
        self.assertEqual(row['downloadAvailability']['status'],'publisher')
        self.assertEqual(layer['fields'][0]['length'],9)
        self.assertFalse(layer['fields'][0]['nullable'])

    def test_query_or_export_capability_alone_does_not_confirm_downloads(self):
        layer=self.layer();layer['supportedExportFormats']='csv,geojson';layer['capabilities']='Query,Extract'
        normalized=normalize_layer(layer,'https://example.org/FeatureServer/7',dict(modified=1777451050000,modifiedProvenance='item.modified'))
        row=apply_metadata(self.row(),dict(service=self.row()['service'],checked='2026-10-09',status='captured',layers=[normalized]))
        self.assertEqual(row['downloadAvailability']['status'],'unknown')
        self.assertEqual(normalized['serviceExportFormats'],['csv','geojson'])
        layer.pop('editingInfo')
        self.assertIsNone(normalize_layer(layer,'https://example.org/7',dict(modified=1777451050000,modifiedProvenance='item.modified'))['dataUpdated'])

    def test_direct_links_and_explicit_disabled_downloads_are_distinct(self):
        row=self.row();row['downloads']=[dict(url='https://example.org/file.zip',format='Shapefile')]
        self.assertEqual(apply_metadata(row)['downloadAvailability']['status'],'direct')
        layer=normalize_layer(self.layer(),'https://example.org/7',dict(id='example_7',downloadable=False))
        entry=dict(service=self.row()['service'],checked='2026-10-09',status='captured',layers=[layer])
        self.assertEqual(apply_metadata(self.row(),entry)['downloadAvailability']['status'],'not-offered')
        entry['status']='partial'
        self.assertEqual(apply_metadata(self.row(),entry)['downloadAvailability']['status'],'unknown')

    def test_mixed_layer_dates_remain_per_layer(self):
        first=normalize_layer(self.layer(),'https://example.org/7')
        second=normalize_layer(dict(self.layer(),id=8,editingInfo=dict(dataLastEditDate=1777451050000)),'https://example.org/8')
        row=apply_metadata(self.row(),dict(service=self.row()['service'],checked='2026-10-09',status='captured',layers=[first,second]))
        self.assertIsNone(row['dates']['dataUpdated'])
        self.assertEqual(row['attributes']['layers'],2)
        self.assertNotEqual(first['dataUpdated'],second['dataUpdated'])

    def test_null_publisher_metadata_does_not_discard_schema(self):
        layer=normalize_layer(self.layer(),'https://example.org/7',dict(metadata=None,downloadable=True))
        self.assertEqual(layer['fields'][0]['name'],'CODE')
        self.assertTrue(layer['downloadable'])
        self.assertIsNone(layer['publication'])

    def test_capture_uses_real_layer_ids_and_never_queries_features(self):
        calls=[]
        def read(url):
            calls.append(url)
            if url.endswith('FeatureServer?f=json'): return dict(layers=[dict(id=7)],tables=[])
            if '/7?f=json' in url: return self.layer()
            return dict(data=dict(attributes=dict(id='example_7',downloadable=True)))
        with patch('dataset_metadata.read_json',side_effect=read): result=capture_service(self.row())
        self.assertEqual(result['status'],'captured')
        self.assertEqual(result['layers'][0]['id'],7)
        self.assertTrue(any('example_7' in url for url in calls))
        self.assertFalse(any('/query' in url or '/export' in url or '/0?' in url for url in calls))

    def test_failed_refresh_retains_last_success_with_its_original_check_date(self):
        old=dict(service=self.row()['service'],checked='2026-10-06',status='captured',layers=[normalize_layer(self.layer(),'https://example.org/7')],errors=[])
        failure=dict(service=self.row()['service'],checked='2026-10-09',status='unavailable',layers=[],errors=['Service timeout'])
        with patch('dataset_metadata.capture_service',return_value=failure):
            cache=refresh_metadata([self.row()],dict(records={'ons:example':old,'removed':old}))
        entry=cache['records']['ons:example']
        self.assertEqual(entry['checked'],'2026-10-06')
        self.assertEqual(entry['lastAttempt'],'2026-10-09')
        self.assertEqual(entry['lastAttemptErrors'],['Service timeout'])
        self.assertEqual(entry['layers'],old['layers'])
        self.assertNotIn('removed',cache['records'])

    def test_changed_service_does_not_reuse_old_schema(self):
        row=apply_metadata(self.row(),dict(service='https://elsewhere.org/FeatureServer',layers=[self.layer()]))
        self.assertNotIn('attributes',row)
        self.assertEqual(row['downloadAvailability']['status'],'unknown')

    def test_partial_hub_outage_does_not_erase_a_previously_complete_snapshot(self):
        old=dict(service=self.row()['service'],checked='2026-10-06',status='captured',layers=[normalize_layer(self.layer(),'https://example.org/7',dict(downloadable=True))],errors=[])
        partial=dict(service=self.row()['service'],checked='2026-10-10',status='partial',layers=[normalize_layer(self.layer(),'https://example.org/7')],errors=['Hub layer 7: temporary failure'])
        with patch('dataset_metadata.capture_service',return_value=partial): cache=refresh_metadata([self.row()],dict(records={'ons:example':old}))
        entry=cache['records']['ons:example']
        self.assertEqual(entry['checked'],'2026-10-06');self.assertTrue(entry['layers'][0]['downloadable'])
        self.assertEqual(entry['lastAttempt'],'2026-10-10');self.assertIn('temporary failure',entry['lastAttemptErrors'][0])


class ShippedMetadata(unittest.TestCase):
    def test_screenshot_example_and_cache_match_the_index(self):
        root=Path(__file__).resolve().parents[1]
        catalogue=json.loads((root/'dist/catalogue.json').read_text(encoding='utf-8'))
        cache=json.loads((root/'dist/dataset-metadata.json').read_text(encoding='utf-8'))
        for row in catalogue['items']:
            if not row.get('attributes'): continue
            entry=cache['records'][row['id']]
            self.assertEqual(row['service'],entry['service'])
            self.assertEqual(row['attributes']['checked'],entry['checked'])
            self.assertEqual(row['attributes']['fields'],sum(len(l['fields']) for l in entry['layers']))
            for layer in entry['layers']:
                self.assertNotIn('features',layer)
                self.assertNotIn('geometry',layer)
        row=next(x for x in catalogue['items'] if x['id']=='ons:46d178d0a81241a0ae8637b9eddf2378')
        self.assertEqual(row['downloadAvailability']['status'],'publisher')
        self.assertEqual(row['dates']['published']['value'],'2026-04-24T15:35:20')
        self.assertEqual(row['dates']['dataUpdated']['value'],'2026-03-10T00:00:00')
        self.assertEqual(row['dates']['infoUpdated']['value'],'2026-04-29T08:24:10.000Z')
        self.assertIn('CAUTH25CD',[f['name'] for f in cache['records'][row['id']]['layers'][0]['fields']])


if __name__=='__main__': unittest.main()
