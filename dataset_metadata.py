"""Capture publisher metadata only: no features, geometry queries or file exports."""
import concurrent.futures
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def write_metadata(metadata, path):
    Path(path).write_text('{"schemaVersion":1,"checked":'+json.dumps(metadata['checked'])+',"records":{\n'+
                         ',\n'.join(json.dumps(k)+':'+json.dumps(v,ensure_ascii=False,separators=(',',':')) for k,v in sorted(metadata['records'].items()))+'\n}}\n',encoding='utf-8',newline='\n')


def timestamp(value):
    """Retain precision and explicit time zones; never invent a missing date."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if isinstance(value, str) and value.strip():
        value = value.strip()
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return value  # Publisher ISO dates may deliberately have no time zone.
        except ValueError:
            pass
    return None


def date_value(value, basis, source):
    stamp = timestamp(value)
    return dict(value=stamp, basis=basis, source=source) if stamp else None


def read_json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'UK-Boundary-Atlas metadata index'})
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)
    if 'error' in data:
        raise RuntimeError(str(data['error']))
    return data


def normalize_layer(layer, url, hub=None):
    """Hub dates include publisher overrides; layer edit dates have separate provenance."""
    hub = hub or {}
    metadata = (hub.get('metadata') or {}).get('metadata') or {}
    citation = ((metadata.get('dataIdInfo') or {}).get('idCitation') or {}).get('date') or {}
    if not isinstance(citation, dict):
        citation = {}
    hub_url = 'https://hub.arcgis.com/api/v3/datasets/'+hub['id'] if hub.get('id') else url
    publication = date_value(citation.get('pubDate'), 'Publisher metadata: published date', hub_url)
    publication = publication or date_value(citation.get('createDate'), 'Publisher metadata: created date', hub_url)
    edit = layer.get('editingInfo') or {}
    updated = date_value(citation.get('reviseDate'), 'Publisher metadata: revision date', hub_url)
    updated = updated or date_value(edit.get('dataLastEditDate'), 'Service data last edited', url)
    # Hub's item-modified fallback is an information update, not evidence of a data edit.
    if not updated and hub.get('modifiedProvenance') and 'dataLastEditDate' in hub['modifiedProvenance']:
        updated = date_value(hub.get('modified'), 'Hub data date: '+hub['modifiedProvenance'], hub_url)
    fields = [{k: f[k] for k in ('name', 'alias', 'type', 'length', 'nullable') if k in f}
              for f in layer.get('fields', hub.get('fields', [])) if f.get('name')]
    result = dict(id=layer['id'], name=layer.get('name', str(layer['id'])), source=url,
                  geometryType=layer.get('geometryType'),
                  spatialReference=layer.get('spatialReference') or (layer.get('extent') or {}).get('spatialReference'),
                  fields=fields, downloadable=hub.get('downloadable') if isinstance(hub.get('downloadable'), bool) else None,
                  downloadSource='https://hub.arcgis.com/api/v3/datasets/'+hub['id'] if hub.get('id') else None,
                  downloadPage='https://geoportal.statistics.gov.uk/datasets/'+hub['id']+'/about' if hub.get('orgId')=='ESMARspQHYMw9BZ9' and hub.get('id') else None,
                  serviceExportFormats=[x.strip() for x in layer.get('supportedExportFormats', '').split(',') if x.strip()],
                  recordCount=hub.get('recordCount'), publication=publication, dataUpdated=updated)
    return result


def capture_service(row):
    service = row['service'].rstrip('/')
    match = re.fullmatch(r'(https://[^?#]+/(?:FeatureServer|MapServer))(?:/(\d+))?', service, re.I)
    if not match:
        return None
    checked = datetime.now(timezone.utc).date().isoformat()
    result = dict(service=row['service'], checked=checked, layers=[], errors=[])
    try:
        root = read_json(match[1]+'?f=json')
        summaries = root.get('layers', []) + root.get('tables', [])
        if match[2] is not None:
            summaries = [dict(id=int(match[2]))]
        item_id = row['id'][4:] if row['id'].startswith('ons:') else root.get('serviceItemId')
        for summary in summaries:
            if summary.get('subLayerIds'):
                continue
            url = match[1]+'/'+str(summary['id'])
            try:
                layer = read_json(url+'?f=json')
                hub = {}
                if item_id:
                    try:
                        response = read_json('https://hub.arcgis.com/api/v3/datasets/'+item_id+'_'+str(summary['id']))
                        hub = response['data']['attributes']
                    except Exception as exc:
                        result['errors'].append('Hub layer '+str(summary['id'])+': '+str(exc))
                result['layers'].append(normalize_layer(layer, url, hub))
            except Exception as exc:
                result['errors'].append('Layer '+str(summary['id'])+': '+str(exc))
    except Exception as exc:
        result['errors'].append('Service: '+str(exc))
    if not result['layers'] and not result['errors']: result['errors'].append('Service returned no readable layer or table metadata')
    result['status'] = 'partial' if result['errors'] and result['layers'] else 'unavailable' if result['errors'] else 'captured'
    return result


def refresh_metadata(rows, previous=None):
    previous = previous or {'records': {}}
    active = {r['id'] for r in rows}
    records = {key:value for key,value in previous['records'].items() if key in active}
    eligible = [r for r in rows if re.fullmatch(r'https://[^?#]+/(?:FeatureServer|MapServer)(?:/\d+)?/?', r.get('service', ''), re.I)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for index, (row, entry) in enumerate(zip(eligible, pool.map(capture_service, eligible)), 1):
            old = records.get(row['id'])
            if entry['status'] in ('unavailable','partial') and old and old['service'] == row['service'] and old.get('layers') and (entry['status']=='unavailable' or old['status']=='captured'):
                entry = dict(old, lastAttempt=entry['checked'], lastAttemptErrors=entry['errors'])
            records[row['id']] = entry
            if index % 100 == 0 or index == len(eligible):
                print(f'Captured publisher metadata: {index}/{len(eligible)}', flush=True)
    return dict(schemaVersion=1, checked=datetime.now(timezone.utc).date().isoformat(), records=records)


def apply_metadata(row, entry=None):
    """Small card metadata stays in the index; full field schemas load on demand."""
    dates = dict(uploaded=date_value(row.get('uploaded') or row.get('published'), 'Source item created / uploaded', row.get('itemUrl') or row['source']),
                 infoUpdated=date_value(row.get('infoUpdated') or row.get('modified'), 'Source item metadata modified', row.get('itemUrl') or row['source']),
                 published=None, dataUpdated=None)
    status = 'direct' if row['downloads'] else 'unknown'
    download = dict(status=status, basis='Indexed direct file link' if row['downloads'] else 'Download availability not confirmed', source=row['source'])
    if entry and entry['service'] == row.get('service'):
        layers = entry.get('layers', [])
        available = [l for l in layers if l.get('downloadable') is True]
        if not row['downloads'] and available:
            download = dict(status='publisher', basis='Publisher Hub metadata reports downloadable layers', source=available[0]['downloadSource'],
                            pages=[l['downloadPage'] for l in available if l.get('downloadPage')])
        elif not row['downloads'] and layers and entry['status']=='captured' and all(l.get('downloadable') is False for l in layers):
            download = dict(status='not-offered', basis='Publisher Hub metadata reports downloads disabled', source=layers[0]['downloadSource'])
        for key, layer_key in [('published', 'publication'), ('dataUpdated', 'dataUpdated')]:
            known = [l[layer_key] for l in layers if l.get(layer_key)]
            # Mixed/partial dates stay per layer rather than becoming a false dataset-wide date.
            if known and len(known)==len(layers) and len({d['value'] for d in known})==1:
                dates[key] = known[0]
        row['attributes'] = dict(key=row['id'], status=entry['status'], checked=entry['checked'],
                                 layers=len(layers), fields=sum(len(l['fields']) for l in layers))
    download['checked'] = entry['checked'] if entry and entry['service']==row.get('service') and status!='direct' else row.get('checked')
    row['downloadAvailability'] = download
    row['dates'] = dates
    return row
