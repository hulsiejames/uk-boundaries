"""Refresh a source-linked inventory; never infer legal effective dates from publication dates."""
import json, re, urllib.parse, urllib.request
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
FAMILIES = {
    'Counties and Unitary Authorities inc Metropolitan Counties': 'Upper tiers + metropolitan counties',
    'Local Authority Districts': 'Local authorities',
    'Counties and Unitary Authorities': 'Counties / upper tier',
    'Middle Layer Super Output Areas': 'MSOA',
    'Lower Layer Super Output Areas': 'LSOA',
    'Output Areas': 'Output areas',
    'Wards': 'Wards',
    'Westminster Parliamentary Constituencies': 'Constituencies',
    'Code History Database': 'Code history',
    'Register of Geographic Codes': 'Code register',
    'Regions': 'English regions',
    'Countries': 'Countries',
    'Combined Authorities': 'Combined authorities',
    'Combined County Authorities': 'Combined county authorities',
    'Metropolitan Counties': 'Metropolitan counties',
    'International Territorial Level 1': 'ITL 1 regions',
    'International Territorial Level 2': 'ITL 2 regions',
    'International Territorial Level 3': 'ITL 3 regions',
    'NUTS Level 1': 'NUTS 1 regions (historic)',
    'NUTS Level 2': 'NUTS 2 regions (historic)',
    'NUTS Level 3': 'NUTS 3 regions (historic)',
    'NUTS, level 1': 'NUTS 1 regions (historic)',
    'NUTS, level 2': 'NUTS 2 regions (historic)',
    'NUTS, level 3': 'NUTS 3 regions (historic)',
    'Data Zones': 'Data Zones',
    'Intermediate Zones': 'Intermediate Zones',
    'Super Data Zones': 'Super Data Zones',
    'Small Areas': 'Small Areas',
    'Super Output Areas': 'Super Output Areas',
}
def get(url):
    with urllib.request.urlopen(url, timeout=60) as f:
        return json.load(f)

query = 'orgid:ESMARspQHYMw9BZ9 AND (' + ' OR '.join('title:"'+k+'"' for k in FAMILIES) + ') AND (type:"Feature Service" OR type:"Shapefile" OR type:"CSV Collection" OR type:"Microsoft Excel")'
items, start = [], 1
while start != -1:
    result = get('https://www.arcgis.com/sharing/rest/search?' + urllib.parse.urlencode(dict(f='json',q=query,num=100,start=start,sortField='title',sortOrder='asc')))
    if 'error' in result: raise RuntimeError(result['error'])
    items.extend(result['results'])
    start = result['nextStart']
    print('Read', len(items), 'of',result['total'], flush=True)

out=[]
for item in items:
    title=item['title']
    family=next((v for k,v in FAMILIES.items() if title.lower().startswith(k.lower()+' (')),None)
    if family is None: continue
    kind='boundary' if 'boundaries' in title.lower() else 'reference' if family in ('Code history','Code register') else 'lookup' if 'lookup' in title.lower() else None
    if kind is None: continue
    date=re.search(r'\(([^)]*?(?:19|20)\d{2}[^)]*)\)', title)
    if not date: continue
    vintage=date.group(1)
    year=int(re.search(r'(?:19|20)\d{2}',vintage).group())
    if year<2001 or year>2026: continue
    coverage='Unknown'
    for pattern,value in [(r'\b(UK|United Kingdom)\b','UK'),(r'\b(GB|Great Britain)\b','Great Britain'),(r'\b(EW|England and Wales)\b','England & Wales'),(r'\b(EN|England)\b','England'),(r'\b(WA|Wales)\b','Wales'),(r'\b(SC|Scotland)\b','Scotland'),(r'\b(NI|Northern Ireland)\b','Northern Ireland')]:
        if re.search(pattern,title,re.I): coverage=value; break
    variant=next((v for v in ['BFE','BFC','BGC','BSC','BUC','BNC'] if re.search(r'\b'+v+r'\b',title)),None)
    if not variant:
        variant=next((v for k,v in [('Full Clipped','BFC'),('Full Extent','BFE'),('Super Generalised','BSC'),('Generalised','BGC')] if k.lower() in title.lower()),'Unspecified')
    out.append(dict(id=item['id'],title=title,family=family,kind=kind,vintage=vintage,year=year,coverage=coverage,variant=variant,type=item['type'],service=item.get('url'),source='https://geoportal.statistics.gov.uk/datasets/'+item['id']+'/about',itemUrl='https://ons.maps.arcgis.com/home/item.html?id='+item['id'],owner=item['owner'],published=datetime.fromtimestamp(item['created']/1000,timezone.utc).date().isoformat(),modified=datetime.fromtimestamp(item['modified']/1000,timezone.utc).date().isoformat()))

# Official change lookups are indexed separately: they start with the source geography.
q='orgid:ESMARspQHYMw9BZ9 AND (title:"MSOA (2011) to MSOA (2021)" OR title:"LSOA (2011) to LSOA (2021)" OR title:"Local Authority District (2011) to Local Authority District (2021)" OR title:"Local Authority District (2022) to Local Authority District (2023)") AND type:"Feature Service"'
result=get('https://www.arcgis.com/sharing/rest/search?'+urllib.parse.urlencode(dict(f='json',q=q,num=100)))
for item in result['results']:
    title=item['title']
    if not re.search(r'^(MSOA|LSOA|Local Authority District) \(\d{4}\) to (MSOA|LSOA|Local Authority District) \(\d{4}\)',title):continue
    years=re.findall(r'\((\d{4})\)',title)
    out.append(dict(id=item['id'],title=title,family='Change lookups',kind='lookup',vintage=' → '.join(years[:2]),year=int(years[1]),coverage='UK' if 'UK' in title else 'England & Wales',variant='Unspecified',type=item['type'],service=item.get('url'),source='https://geoportal.statistics.gov.uk/datasets/'+item['id']+'/about',itemUrl='https://ons.maps.arcgis.com/home/item.html?id='+item['id'],owner=item['owner'],published=datetime.fromtimestamp(item['created']/1000,timezone.utc).date().isoformat(),modified=datetime.fromtimestamp(item['modified']/1000,timezone.utc).date().isoformat()))

out=list({x['id']:x for x in out}.values())
out.sort(key=lambda x:(-x['year'],x['family'],x['title'],x['type']))
payload=dict(checked='2026-10-06',organisation='Office for National Statistics',organisationId='ESMARspQHYMw9BZ9',items=out)
(ROOT/'dist'/'catalogue.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved',len(out),'records; boundary years:',sorted({x['year'] for x in out if x['kind']=='boundary'}))
print('Local authority boundary years:',sorted({x['year'] for x in out if x['family']=='Local authorities' and x['kind']=='boundary'}))
