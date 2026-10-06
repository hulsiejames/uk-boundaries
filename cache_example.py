import json, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone
def get(url):
    with urllib.request.urlopen(url,timeout=60) as response:
        return json.load(response)

root=Path(__file__).resolve().parent
items=json.loads((root/'dist/catalogue.json').read_text(encoding='utf-8'))['items']
out={}
for side,item_id in [('a','1b4fb79cc4974048919daf6e1fde5073'),('b','43eddab36751466db7bb4006b242243c')]:
    item=next(x for x in items if x['id']==item_id)
    layer=item['service']+'/0'
    meta=get(layer+'?f=json')
    field=next(x['name'] for x in meta['fields'] if x['name'].lower().endswith('cd'))
    geo=get(layer+'/query?'+urllib.parse.urlencode(dict(f='geojson',where=field+" = 'E08000034'",outFields='*',outSR=4326,returnGeometry='true')))
    source=get('https://www.arcgis.com/sharing/rest/content/items/'+item_id+'?f=json')
    assert geo['type']=='FeatureCollection' and len(geo['features'])==1
    out[side]=dict(item=item,term='Kirklees',geo=geo,layerUrl=layer,licence=source.get('licenseInfo','See source licence.'),copyright=meta.get('copyrightText',''),fetched=datetime.now(timezone.utc).isoformat(),cached=True)
(root/'dist/kirklees-example.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf-8')
print('Cached two verified Kirklees snapshots.')
