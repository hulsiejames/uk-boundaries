// Pure catalogue queries shared by the browser and regression checks.
export const CORE_GROUPS = ['Census','Administration','Regions & countries'];
export const WEIGHTS = {population:'Population weighted',employment:'Employment / workplace weighted',address:'Address weighted',geometric:'Geometric', 'not-specified':'Not specified'};
export const BOUNDARY_DETAILS = {
  BFC:'BFC · Full resolution, coastline clipped', BFE:'BFE · Full resolution, extent of realm',
  BGC:'BGC · Generalised (20m), coastline clipped', BSC:'BSC · Super generalised (200m), coastline clipped',
  BUC:'BUC · Ultra generalised (500m), coastline clipped', BGG:'BGG · Generalised grid',
  BGE:'BGE · See publisher specification', BUE:'BUE · Ultra generalised (500m), extent of realm',
  Unspecified:'Not specified by publisher'
};
export function boundaryVariants(items) {
  const present=new Set(items.filter(x=>x.kind==='boundary').map(x=>x.variant));
  const codes=[...Object.keys(BOUNDARY_DETAILS).filter(v=>v!=='Unspecified'),...Array.from(present).filter(v=>!(v in BOUNDARY_DETAILS)).sort(),'Unspecified'];
  return codes.filter(v=>present.has(v)).map(value=>({value,label:BOUNDARY_DETAILS[value]||value+' · See publisher specification'}));
}
export function countryMatches(item, country) {
  if (!country) return true;
  if (country === 'Unknown') return !item.countries.length;
  if (country === 'UK') return item.countries.length === 4;
  if (country === 'Great Britain') return ['England','Wales','Scotland'].every(c=>item.countries.includes(c));
  return item.countries.includes(country);
}
export function searchable(item, levels, providers) {
  const countryAliases={England:'EN English',Wales:'WA Welsh',Scotland:'SC Scottish','Northern Ireland':'NI Northern Irish'};
  return [item.title,item.vintage,item.kind,item.variant,item.method,...item.countries,...item.formats,
    WEIGHTS[item.centroidWeight]||'',item.centroidWeight==='employment'?'workers workforce employment weighted workplace population':'',
    ...(item.areas||[]).flatMap(a=>[a.name,a.code]),
    ...item.countries.map(c=>countryAliases[c]||''),
    providers.find(p=>p.id===item.provider)?.name,
    ...levels.filter(l=>item.levels.includes(l.id)).flatMap(l=>[l.label,...l.aliases])]
    .join(' ').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
}
export function queryMatches(text, query) {
  const words=query.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim().split(/\s+/).filter(Boolean);
  const acronyms=new Set(['oa','lsoa','msoa','lad','ua','ca','cca','mca','mcca','msa','gla','dz','iz','sa','soa','sdz','ttwa','itl','nuts','wz','icb','ccg','lhb']);
  return words.every(word=>acronyms.has(word) ? new RegExp('\\b'+word+'\\b').test(text) : text.includes(word));
}
export function filterItems(items, f, levels, providers) {
  const normal=value=>value.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const query=normal(f.query||'');
  const knownNames=[...new Set(items.flatMap(x=>(x.areas||[]).map(a=>normal(a.name))))];
  const mentioned=knownNames.filter(name=>query.includes(name));
  const namedAreas=mentioned.filter(name=>!mentioned.some(longer=>longer!==name&&longer.includes(name)));
  return items.filter(x=>(f.older || !x.years.length || Math.max(...x.years)>=2010)
    && (!f.level || x.levels.includes(f.level))
    && (!f.group || levels.some(l=>x.levels.includes(l.id)&&l.group===f.group))
    && (!f.year || (f.year==='Unknown' ? !x.years.length : f.year==='older' ? x.years.length&&Math.max(...x.years)<2010 : x.years.includes(Number(f.year))))
    && countryMatches(x,f.country)
    && (!f.kind || x.kind===f.kind)
    && (!f.centroidWeight || (x.kind==='centroid'&&x.centroidWeight===f.centroidWeight))
    && (!f.variant || (x.kind==='boundary'&&x.variant===f.variant))
    && (!f.provider || x.provider===f.provider)
    && (!f.format || x.formats.includes(f.format))
    && (!f.delivery || (f.delivery==='file' ? x.downloads.length>0 : f.delivery==='service' ? !!x.service : !x.downloads.length&&!x.service))
    && (!f.method || (f.method==='weighted' ? /population|area.*match|weighted/i.test(x.method) : x.method===f.method))
    && (!namedAreas.length || !x.areas || namedAreas.every(name=>x.areas.some(a=>normal(a.name)===name)))
    && queryMatches(x.searchText ?? searchable(x,levels,providers),f.query||''));
}
export function coverageRows(items, levels, countries, group, kind, centroidWeight='', variant='') {
  return countries.flatMap(country=>levels.filter(l=>l.countries.includes(country)
    && (!group || (group==='Core' ? CORE_GROUPS.includes(l.group)||l.id==='workplace' : l.group===group)))
    .map(level=>({country,level,items:items.filter(x=>x.kind===kind&&x.levels.includes(level.id)&&x.countries.includes(country)&&(!centroidWeight||(x.kind==='centroid'&&x.centroidWeight===centroidWeight))&&(!variant||(x.kind==='boundary'&&x.variant===variant)))})));
}
export function coverageCell(row, year) {
  if (year==='older') return row.items.filter(x=>x.years.length && Math.max(...x.years)<2010);
  if (year==='Unknown') return row.items.filter(x=>!x.years.length);
  return row.items.filter(x=>x.kind==='lookup' ? x.years.includes(year) : x.year===year);
}
export function partitionCoverageRows(rows, columns) {
  const indexed=[],missing=[];
  for(const row of rows)(columns.some(year=>coverageCell(row,year).length)?indexed:missing).push(row);
  return {indexed,missing};
}
export function csvCell(value) {
  let text=String(value??'');
  if (/^[=+@-]/.test(text)) text="'"+text;
  return '"'+text.replace(/"/g,'""')+'"';
}
export function csv(rows, fields) {
  return '\uFEFF'+[fields.map(csvCell).join(','),...rows.map(r=>fields.map(f=>csvCell(Array.isArray(r[f])?r[f].join(' | '):r[f])).join(','))].join('\r\n');
}
