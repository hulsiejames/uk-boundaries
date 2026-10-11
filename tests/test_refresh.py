import copy
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from refresh import check_url, check_links, preserve_history, validate_candidate, changes, report_markdown
from ingest import write_catalogue


class Response:
    def __init__(self,body=b'',url='https://example.org/file',content_type='application/zip'):
        self.status=200;self.headers={'Content-Type':content_type};self.body=body;self.url=url;self.read_sizes=[]
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def geturl(self): return self.url
    def read(self,n): self.read_sizes.append(n);return self.body[:n]


def record(id='ons:old',**extra):
    return dict(id=id,provider='ons' if id.startswith('ons:') else 'nrs',title=id,years=[2011],levels=['lad'],kind='boundary',
                source='https://example.org/about',service='',downloads=[],year=2011,checked='2026-10-10',**extra)


def catalogue(rows):
    return dict(checked='2026-10-10',items=rows,levels=[{'id':'lad'}],providers=[{'id':'ons'},{'id':'nrs'}])


class LinkChecks(unittest.TestCase):
    def test_head_does_not_read_or_save_a_gis_file(self):
        response=Response();methods=[]
        def open_(request,timeout): methods.append(request.get_method());return response
        result=check_url('https://example.org/file',open_)
        self.assertEqual(result['state'],'reachable');self.assertEqual(methods,['HEAD']);self.assertEqual(response.read_sizes,[])

    def test_unsupported_head_falls_back_to_a_bounded_range_request(self):
        requests=[];response=Response()
        def open_(request,timeout):
            requests.append(request)
            if request.get_method()=='HEAD': raise urllib.error.HTTPError(request.full_url,405,'Not allowed',{},None)
            return response
        self.assertEqual(check_url('https://example.org/file',open_)['state'],'reachable')
        self.assertEqual(requests[1].get_header('Range'),'bytes=0-511')
        self.assertEqual(response.read_sizes,[])

    def test_missing_restricted_and_network_failures_are_different(self):
        for code,state in [(404,'missing'),(410,'missing'),(403,'restricted'),(429,'inconclusive'),(503,'inconclusive')]:
            def open_(request,timeout): raise urllib.error.HTTPError(request.full_url,code,'Failure',{},None)
            self.assertEqual(check_url('https://example.org/file',open_)['state'],state)
        def timeout_(request,timeout): raise TimeoutError('Timed out')
        self.assertEqual(check_url('https://example.org/file',timeout_)['state'],'inconclusive')
        self.assertEqual(check_url('http://example.org/file')['state'],'invalid')

    def test_http_200_json_errors_are_not_healthy(self):
        response=Response(b'{"error":{"code":403,"message":"Restricted"}}',content_type='application/json')
        result=check_url('https://example.org/file',lambda request,timeout:response)
        self.assertEqual(result['state'],'restricted');self.assertEqual(response.read_sizes,[512])

    def test_redirect_reports_do_not_persist_signed_query_strings(self):
        response=Response(url='https://example.org/file.zip?X-Amz-Signature=temporary')
        result=check_url('https://example.org/download',lambda request,timeout:response)
        self.assertTrue(result['redirected']);self.assertEqual(result['finalUrl'],'https://example.org/file.zip')
        self.assertNotIn('temporary',json.dumps(result))

    def test_checks_deduplicate_files_and_preserve_403_vs_404(self):
        a=record();a['downloads']=[dict(url='https://example.org/file',format='CSV')]
        b=record('nrs:other');b['downloads']=copy.deepcopy(a['downloads'])
        calls=[]
        def check(url): calls.append(url);return dict(state='missing' if url.endswith('/file') else 'restricted',code=404 if url.endswith('/file') else 403)
        candidate=catalogue([a,b]);links=check_links(candidate,{'records':{}},check)
        self.assertEqual(len(calls),2);self.assertEqual(len(links),2)
        self.assertEqual(a['linkHealth']['downloadState'],'missing')
        self.assertEqual(b['_linkChecks'][0]['state'],'restricted')
        self.assertEqual(a['linkHealth']['state'],'attention')

    def test_html_response_is_not_a_confirmed_file_download(self):
        a=record();a['downloads']=[dict(url='https://example.org/file',format='CSV')]
        check_links(catalogue([a]),{'records':{}},lambda url:dict(state='reachable',code=200,contentType='text/html'))
        self.assertEqual(a['linkHealth']['downloadState'],'unconfirmed')


class RefreshSafety(unittest.TestCase):
    def test_removed_historical_record_is_retained_without_changing_its_vintage(self):
        old=catalogue([record()]);new=catalogue([record('ons:new')]);missing=preserve_history(old,new)
        self.assertEqual(missing,['ons:old']);self.assertEqual(len(new['items']),2)
        archived=next(r for r in new['items'] if r['id']=='ons:old')
        self.assertEqual(archived['sourceListing'],'not-found');self.assertEqual(archived['year'],2011)
        self.assertNotIn('sourceListing',old['items'][0])

    def test_bulk_disappearance_or_metadata_outage_rejects_the_candidate(self):
        old=catalogue([record('ons:'+str(i)) for i in range(100)])
        candidate=catalogue([record('ons:0')]);missing=preserve_history(old,candidate)
        self.assertTrue(any('5%' in e for e in validate_candidate(old,candidate,{'records':{}},missing)))
        metadata={'records':{str(i):dict(status='unavailable') for i in range(100)}}
        self.assertTrue(any('10%' in e for e in validate_candidate(old,old,metadata,[])))

    def test_duplicate_records_and_wrong_schema_associations_are_rejected(self):
        row=record();row['attributes']={'fields':1}
        candidate=catalogue([row,copy.deepcopy(row)])
        errors=validate_candidate(candidate,candidate,{'records':{'ons:old':{'service':'https://wrong.example','status':'captured'}}},[])
        self.assertTrue(any('Duplicate' in e for e in errors));self.assertTrue(any('Schema association' in e for e in errors))

    def test_previously_reviewed_archival_gaps_do_not_block_every_later_refresh(self):
        rows=[record('ons:'+str(i)) for i in range(100)]
        for row in rows[:50]: row['sourceListing']='not-found'
        old=catalogue(rows);new=catalogue(copy.deepcopy(rows[50:]));missing=preserve_history(old,new)
        self.assertEqual(validate_candidate(old,new,{'records':{}},missing),[])

    def test_change_report_ignores_check_date_churn_but_detects_changed_urls(self):
        old=catalogue([record()]);new=copy.deepcopy(old);new['items'][0]['checked']='2026-10-17'
        self.assertEqual(changes(old,new),{'added':[],'changed':[]})
        new['items'][0]['source']='https://example.org/new-about'
        # Source and service URLs must be in the semantic comparison.
        new['items'][0]['service']='https://example.org/FeatureServer'
        self.assertEqual(changes(old,new)['changed'],['ons:old'])

    def test_serialized_candidate_round_trips_without_geometry(self):
        candidate=catalogue([record()])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'catalogue.json';write_catalogue(candidate,path)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8')),candidate)


if __name__=='__main__': unittest.main()
