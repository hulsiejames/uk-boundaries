import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {filterItems,countryMatches,coverageRows,coverageCell,csv,searchable} from '../dist/catalogue-core.mjs';
const data=JSON.parse(readFileSync(new URL('../dist/catalogue.json',import.meta.url),'utf8'));
const find=f=>filterItems(data.items,f,data.levels,data.providers);
test('Scottish/NI census shortcuts include their different statistical systems',()=>{
  for(const country of ['Scotland','Northern Ireland']){
    const rows=find({country,group:'Census',kind:'boundary'});
    const wanted=country==='Scotland'?['oa-sc','dz-sc','iz-sc']:['sa-ni','soa-ni','dz-ni','sdz-ni'];
    for(const id of wanted)assert.ok(rows.some(x=>x.levels.includes(id)),id);
  }
});
test('MSOA and OA acronym searches stay distinct; NI alias resolves national files',()=>{
  const m=find({query:'MSOA 2011',kind:'boundary'});assert.ok(m.length);assert.ok(m.every(x=>x.levels.includes('msoa')));
  const oa=find({query:'OA 2011',kind:'boundary'});assert.ok(oa.length);assert.ok(oa.every(x=>x.levels.some(l=>l.startsWith('oa-'))));
  assert.ok(find({query:'NI Data Zones',kind:'boundary'}).some(x=>x.levels.includes('dz-ni')));
});
test('mixed-vintage lookup can be found from either census year',()=>{
  const before=find({level:'lsoa',kind:'lookup',year:'2011'}),after=find({level:'lsoa',kind:'lookup',year:'2021'});
  const row=before.find(x=>/LSOA \(2011\) to LSOA \(2021\)/.test(x.title));assert.ok(row);assert.ok(after.some(x=>x.id===row.id));
});
test('every coverage cell drills into exactly the matching catalogue records',()=>{
  for(const kind of ['boundary','lookup','centroid','reference'])for(const row of coverageRows(data.items,data.levels,['England','Wales','Scotland','Northern Ireland'],'',kind)){
    for(const year of ['older',2010,2011,2014,2021,2022,2026,'Unknown']){
      const cell=coverageCell(row,year);
      const records=find({kind,level:row.level.id,country:row.country,year:String(year),older:year==='older'});
      assert.deepEqual(cell.map(x=>x.id).sort(),records.map(x=>x.id).sort(),`${kind} ${row.level.id} ${year}`);
    }
  }
});
test('CSV quotes values, preserves Unicode, and neutralizes spreadsheet formulas',()=>{
  assert.equal(csv([{name:'Caerdydd, "Cymru"',value:'=1+1'}],['name','value']),'\uFEFF"name","value"\r\n"Caerdydd, ""Cymru""","\'=1+1"');
});
test('UK-wide files are available when selecting individual nations; census baseline is opt-in',()=>{
  const uk=data.items.find(x=>x.countries.length===4&&x.levels.includes('lad'));assert.ok(countryMatches(uk,'Scotland'));
  assert.equal(find({level:'dz-sc',year:'2001',kind:'boundary'}).length,0);
  assert.ok(find({level:'dz-sc',year:'2001',kind:'boundary',older:true}).length);
});
