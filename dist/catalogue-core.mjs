// Pure catalogue queries shared by the browser and regression checks.
export const CORE_GROUPS = ['Census','Administration','Regions & countries'];
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
    ...item.countries.map(c=>countryAliases[c]||''),
    providers.find(p=>p.id===item.provider)?.name,
    ...levels.filter(l=>item.levels.includes(l.id)).flatMap(l=>[l.label,...l.aliases])]
    .join(' ').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
}
export function queryMatches(text, query) {
  const words=query.normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim().split(/\s+/).filter(Boolean);
  const acronyms=new Set(['oa','lsoa','msoa','lad','ua','ca','cca','dz','iz','sa','soa','sdz','ttwa','itl','nuts','wz','icb','ccg','lhb']);
  return words.every(word=>acronyms.has(word) ? new RegExp('\\b'+word+'\\b').test(text) : text.includes(word));
}
export function filterItems(items, f, levels, providers) {
  return items.filter(x=>(f.older || !x.years.length || Math.max(...x.years)>=2010)
    && (!f.level || x.levels.includes(f.level))
    && (!f.group || levels.some(l=>x.levels.includes(l.id)&&l.group===f.group))
    && (!f.year || (f.year==='Unknown' ? !x.years.length : f.year==='older' ? x.years.length&&Math.max(...x.years)<2010 : x.years.includes(Number(f.year))))
    && countryMatches(x,f.country)
    && (!f.kind || x.kind===f.kind)
    && (!f.variant || x.variant===f.variant)
    && (!f.provider || x.provider===f.provider)
    && (!f.format || x.formats.includes(f.format))
    && (!f.delivery || (f.delivery==='file' ? x.downloads.length>0 : f.delivery==='service' ? !!x.service : !x.downloads.length&&!x.service))
    && (!f.method || (f.method==='weighted' ? /population|area.*match|weighted/i.test(x.method) : x.method===f.method))
    && queryMatches(x.searchText ?? searchable(x,levels,providers),f.query||''));
}
export function coverageRows(items, levels, countries, group, kind) {
  return countries.flatMap(country=>levels.filter(l=>l.countries.includes(country)
    && (!group || (group==='Core' ? CORE_GROUPS.includes(l.group) : l.group===group)))
    .map(level=>({country,level,items:items.filter(x=>x.kind===kind&&x.levels.includes(level.id)&&x.countries.includes(country))})));
}
export function coverageCell(row, year) {
  if (year==='older') return row.items.filter(x=>x.years.length && Math.max(...x.years)<2010);
  if (year==='Unknown') return row.items.filter(x=>!x.years.length);
  return row.items.filter(x=>x.kind==='lookup' ? x.years.includes(year) : x.year===year);
}
export function csvCell(value) {
  let text=String(value??'');
  if (/^[=+@-]/.test(text)) text="'"+text;
  return '"'+text.replace(/"/g,'""')+'"';
}
export function csv(rows, fields) {
  return '\uFEFF'+[fields.map(csvCell).join(','),...rows.map(r=>fields.map(f=>csvCell(Array.isArray(r[f])?r[f].join(' | '):r[f])).join(','))].join('\r\n');
}
