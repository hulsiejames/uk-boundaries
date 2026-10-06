import {readFileSync} from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
import {filterItems,countryMatches,coverageRows,coverageCell,partitionCoverageRows,boundaryVariants,csv,searchable} from '../dist/catalogue-core.mjs';
const data=JSON.parse(readFileSync(new URL('../dist/catalogue.json',import.meta.url),'utf8'));
const find=f=>filterItems(data.items,f,data.levels,data.providers);
test('detail options include every indexed boundary code and preserve unfamiliar codes',()=>{
  const actual=new Set(boundaryVariants(data.items).map(x=>x.value));
  assert.deepEqual(actual,new Set(data.items.filter(x=>x.kind==='boundary').map(x=>x.variant)));
  for(const code of ['BFC','BFE','BGC','BSC','BUC','BGG','BGE','BUE','Unspecified'])assert.ok(actual.has(code),code);
  assert.equal(boundaryVariants([{kind:'boundary',variant:'BXX'},{kind:'lookup',variant:'BYY'}])[0].value,'BXX');
});
test('boundary detail filters never leak into non-boundary products',()=>{
  for(const variant of boundaryVariants(data.items).map(x=>x.value)){
    const rows=find({variant,older:true});assert.ok(rows.length,variant);
    assert.ok(rows.every(x=>x.kind==='boundary'&&x.variant===variant),variant);
  }
  assert.equal(find({kind:'lookup',variant:'Unspecified'}).length,0);
  assert.equal(find({kind:'centroid',variant:'Unspecified'}).length,0);
});
test('filtered coverage counts and file drill-through agree for every boundary detail',()=>{
  for(const country of ['England','Wales'])for(const {value:variant} of boundaryVariants(data.items)){
    const rows=coverageRows(data.items,data.levels,[country],'','boundary','',variant);
    assert.ok(rows.every(row=>row.items.every(x=>x.variant===variant)));
    const columns=['older',...Array.from({length:data.historyEnd-2009},(_,i)=>2010+i),'Unknown'];
    const {indexed,missing}=partitionCoverageRows(rows,columns);
    assert.equal(indexed.length+missing.length,rows.length);
    assert.ok(missing.every(row=>row.items.length===0));
    // Check a real source vintage per detail and country, including legacy/unlabelled routes.
    const row=indexed[0];if(!row)continue;
    const year=columns.find(y=>coverageCell(row,y).length);
    const matches=find({country,level:row.level.id,kind:'boundary',variant,year:String(year),older:year==='older'});
    assert.deepEqual(coverageCell(row,year).map(x=>x.id).sort(),matches.map(x=>x.id).sort());
  }
});
test('only all-empty reporting rows move to Not found, including Earlier and Not labelled',()=>{
  const row=(id,items)=>({country:'England',level:{id},items});
  const rows=[row('empty',[]),row('unknown',[{kind:'boundary',years:[],year:null}]),
    row('earlier',[{kind:'boundary',years:[2001],year:2001}]),row('mixed-lookup',[{kind:'lookup',years:[2011,2021],year:null}]),
    row('current',[{kind:'boundary',years:[2026],year:2026}])];
  const result=partitionCoverageRows(rows,['older',2011,2021,2026,'Unknown']);
  assert.deepEqual(result.missing.map(r=>r.level.id),['empty']);
  assert.deepEqual(result.indexed.map(r=>r.level.id),['unknown','earlier','mixed-lookup','current']);
  assert.equal(rows.length,5);assert.equal(rows[1].items.length,1);
  assert.deepEqual(partitionCoverageRows(rows,[2010]).missing,rows);
});
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

test('mayoral aliases and actual authority names/codes find the correct shared vintages',()=>{
  const mayoral=find({query:'mayoral authorities',country:'England',kind:'boundary'});
  assert.ok(mayoral.some(x=>x.levels.includes('gla')));
  assert.ok(mayoral.some(x=>x.levels.includes('cca')));
  const west=find({query:'West Yorkshire',country:'England',level:'strategic',kind:'boundary',year:'2025'});
  assert.ok(west.length);assert.ok(west.every(x=>x.areas.some(a=>a.name==='West Yorkshire')));
  assert.ok(find({query:'E47000013',kind:'boundary',level:'cca',year:'2025'}).length);
  assert.equal(find({query:'East Midlands',kind:'boundary',level:'strategic',year:'2023'}).length,0);
});

test('population and employment filters are disjoint, with reference files excluded',()=>{
  const population=find({country:'England',centroidWeight:'population'}),employment=find({country:'England',centroidWeight:'employment'});
  assert.ok(population.some(x=>x.levels.includes('msoa')));assert.ok(employment.some(x=>x.levels.includes('workplace')));
  assert.ok(population.every(x=>x.kind==='centroid'));assert.ok(employment.every(x=>x.kind==='centroid'));
  assert.ok(population.every(x=>!employment.some(e=>e.id===x.id)));
  assert.equal(find({country:'England',level:'lad',centroidWeight:'employment'}).length,0);
  assert.ok(coverageRows(data.items,data.levels,['England'],'Core','centroid','employment').some(row=>row.level.id==='workplace'&&coverageCell(row,2011).length));
});

test('weighted centroid grid cells and exports retain the same filtering semantics',()=>{
  for(const weight of ['population','employment','address','geometric','not-specified'])for(const row of coverageRows(data.items,data.levels,['England','Wales','Scotland','Northern Ireland'],'','centroid',weight))for(const year of ['older',2011,2021,2022,'Unknown']){
    assert.deepEqual(coverageCell(row,year).map(x=>x.id).sort(),find({country:row.country,level:row.level.id,kind:'centroid',centroidWeight:weight,year:String(year),older:year==='older'}).map(x=>x.id).sort());
  }
});
