import {filterItems,searchable,coverageRows,coverageCell,csv,WEIGHTS} from './catalogue-core.mjs';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=value=>{try{const u=new URL(value);return ['https:','http:'].includes(u.protocol)?u.href:'';}catch{return '';}};
const link=(url,label)=>safeURL(url)?`<a href="${esc(safeURL(url))}" target="_blank" rel="noopener">${esc(label)}</a>`:'';
const detail={BFE:'Full · extent of realm',BFC:'Full · coastline clipped',BGC:'Generalised · clipped',BSC:'Super generalised · clipped',Unspecified:'See source specification',BUC:'BUC · see source',BNC:'BNC · see source'};
const names={boundary:'boundaries',lookup:'lookups / linkage',centroid:'centroids',reference:'names, codes & directories'};
let data,items=[],filtered=[],limit=30,rows=[];
const countries=['England','Wales','Scotland','Northern Ireland'];
const fields=['level','country','year','kind','provider','variant','group','format','delivery','method','centroidWeight'];
function showTab(name){
 for(const b of document.querySelectorAll('.tab')){const on=b.dataset.tab===name;b.classList.toggle('active',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');}
 for(const section of document.querySelectorAll('.view'))section.hidden=section.id!==name;
 history.replaceState(null,'','#'+name);
}
for(const b of document.querySelectorAll('.tab'))b.onclick=()=>showTab(b.dataset.tab);
function options(id,values,label){$(id).innerHTML=`<option value="">${esc(label)}</option>`+values.map(v=>`<option value="${esc(v.value??v)}">${esc(v.label??v)}</option>`).join('');}
function filters(){return Object.fromEntries([...fields.map(k=>[k,$(k).value]),['query',$('search').value],['older',$('older').checked]]);}
function reset(render=true){for(const f of fields)$(f).value='';$('country').value='England';$('kind').value='boundary';$('search').value='';$('older').checked=false;limit=30;if(render)renderResults();}
function renderResults(){
 if(!data)return;
 const centroidView=['centroid',''].includes($('kind').value);$('centroid-options').hidden=!centroidView;if(!centroidView)$('centroidWeight').value='';
 filtered=filterItems(items,filters(),data.levels,data.providers);
 $('result-count').textContent=`${filtered.length.toLocaleString('en-GB')} official source ${filtered.length===1?'record':'records'}`;
 const level=data.levels.find(l=>l.id===$('level').value);
 $('level-note').textContent=level?.note||'Search finds datasets and download bundles. Audited combined-authority names and codes are searchable; other individual polygon names are not indexed.';
 $('results').innerHTML=filtered.slice(0,limit).map(x=>{
  const provider=data.providers.find(p=>p.id===x.provider)?.name||x.provider;
  const labels=data.levels.filter(l=>x.levels.includes(l.id)).map(l=>l.label).join(' · ');
  const downloads=x.downloads.map(d=>link(d.url,'Download '+d.format)).join('');
  return `<article class="result"><div class="result-main"><span class="eyebrow">${esc(provider)} · ${esc(names[x.kind])}</span><h3>${esc(x.title)}</h3><span class="source-title">${esc(labels)}</span><div class="tags"><span class="tag">${esc(x.countries.join(' & ')||'Scope not labelled')}</span><span class="tag">${esc(x.vintage)}</span>${x.formats.map(f=>`<span class="tag">${esc(f)}</span>`).join('')}</div></div><div class="result-meta"><span class="data-label">${x.kind==='boundary'?'Boundary detail':'Reference vintages'}</span><span class="data-value">${esc(x.kind==='boundary'?(detail[x.variant]||x.variant):(x.years.join(', ')||'Not labelled'))}</span>${x.kind==='centroid'?`<span class="data-label updated">Centroid weighting</span><span class="data-value">${esc(WEIGHTS[x.centroidWeight]||'Not specified')}</span>`:''}${x.kind==='lookup'?`<span class="source-title">${esc(x.method||'Method: see publisher')}</span>`:''}<span class="data-label updated">Source item updated</span><span class="data-value">${esc(x.modified||'See publisher')}</span></div><div class="result-actions">${link(x.source,'Official source & licence')}${downloads}${x.service?link(x.service,'Open geography service'):''}</div><details class="record-details"><summary>Metadata & translation notes</summary><dl><dt>Vintage basis</dt><dd>${esc(x.dateBasis)}</dd><dt>Reference years</dt><dd>${esc(x.years.join(', ')||'Not explicitly labelled')}</dd><dt>First published / uploaded</dt><dd>${esc(x.published||'See official source')} · not a legal effective date</dd><dt>Source checked</dt><dd>${esc(x.checked)}</dd><dt>Catalogue ID</dt><dd>${esc(x.id)}</dd></dl>${x.kind==='centroid'?`<p><strong>Weighting basis:</strong> ${esc(x.centroidWeightBasis||'Not specified by the indexed source')}</p>${x.centroidAlgorithm?`<p>${esc(x.centroidAlgorithm)}</p>`:''}${x.centroidMethodology?link(x.centroidMethodology,'Centroid methodology'):''}`:''}${x.areas?.length?`<p><strong>Indexed areas:</strong> ${esc(x.areas.map(a=>a.name+(a.code?' · '+a.code:'')).join('; '))}</p>${x.areaNamesSource?link(x.areaNamesSource,'Names/code audit source'):''}`:''}${x.notes?`<p>${esc(x.notes)}</p>`:''}${x.kind==='lookup'?'<p>Check the source’s fit method and weighting definitions before translating statistics.</p>':''}${!x.downloads.length?'<p>Use the publisher page or service to choose its supported download format. The index contains metadata only.</p>':''}${x.itemUrl?link(x.itemUrl,'ArcGIS item metadata'):''}</details></article>`;
 }).join('');
 if(!filtered.length)$('results').innerHTML='<div class="empty"><h3>No matching source in this index.</h3><p>Try another reference year, enable pre-2010 vintages or remove a filter. Current, unlabelled layers appear under “Not labelled”. A missing record does not establish a boundary change.</p><p>The search covers dataset titles and reporting levels. Individual place names such as Kirklees are explained under Coverage &amp; sources.</p><button id="empty-coverage" class="secondary">Inspect UK coverage</button></div>';
 if($('empty-coverage'))$('empty-coverage').onclick=()=>showTab('coverage');
 $('more').hidden=limit>=filtered.length;
}
for(const f of [...fields,'older'])$(f).onchange=()=>{limit=30;renderResults();};
$('search').oninput=()=>{limit=30;renderResults();};
$('reset').onclick=()=>reset();$('more').onclick=()=>{limit+=30;renderResults();};
for(const button of document.querySelectorAll('[data-preset]'))button.onclick=()=>{
 reset(false);const p=button.dataset.preset;
 if(p==='england'||p==='wales')$('country').value=p==='england'?'England':'Wales';
 else if(p==='scotland'||p==='ni'){$('country').value=p==='scotland'?'Scotland':'Northern Ireland';$('group').value='Census';}
 else if(p==='population'||p==='employment'){$('kind').value='centroid';$('centroidWeight').value=p;}
 else if(p==='history'){$('kind').value='reference';$('search').value='code history';}
 else $('level').value=p;
 renderResults();
};
function download(text,filename,mime){const url=URL.createObjectURL(new Blob([text],{type:mime}));const a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function exportable(x){const {searchText,...record}=x;return record;}
$('export-index').onclick=()=>{
 const records=filtered.map(x=>({...exportable(x),levels:x.levels.map(id=>data.levels.find(l=>l.id===id)?.label||id),downloads:x.downloads.map(d=>d.format+': '+d.url).join(' | '),areas:(x.areas||[]).map(a=>a.name+(a.code?' ['+a.code+']':'')).join(' | ')}));
 download(csv(records,['id','title','levels','kind','vintage','years','countries','provider','variant','formats','source','downloads','service','method','centroidWeight','centroidWeightBasis','centroidWeightYear','centroidAlgorithm','centroidMethodology','areas','areaNamesSource','dateBasis','published','modified','checked','notes']),'uk-boundary-catalogue.csv','text/csv;charset=utf-8');
};
$('export-manifest').onclick=()=>download(JSON.stringify({schemaVersion:data.schemaVersion,checked:data.checked,filters:filters(),levels:data.levels,providers:data.providers,items:filtered.map(exportable)},null,2),'uk-boundary-manifest.json','application/json');
function drill(level,country,year){reset(false);$('level').value=level;$('country').value=country;
 if(year==='older'){$('older').checked=true;$('year').value='older';}else if(year)$('year').value=year;
 renderResults();showTab('catalogue');window.scrollTo({top:0,behavior:'instant'});
}
function renderCoverage(){
 if(!data)return;
 const isCentroid=$('coverage-kind').value==='centroid';$('coverage-centroid-options').hidden=!isCentroid;if(!isCentroid)$('coverage-weight').value='';
 rows=coverageRows(items,data.levels,$('coverage-country').value?[$('coverage-country').value]:countries,$('coverage-group').value,$('coverage-kind').value,$('coverage-weight').value);
 const years=Array.from({length:data.historyEnd-2010+1},(_,i)=>2010+i),columns=['older',...years,'Unknown'];
 const cells=row=>columns.map(y=>{const matches=coverageCell(row,y);return `<td>${matches.length?`<button class="coverage-cell" data-level="${row.level.id}" data-country="${esc(row.country)}" data-year="${y}" aria-label="${esc(row.country+' · '+row.level.label+' · '+(y==='Unknown'?'unlabelled':y==='older'?'pre-2010':y)+' · '+matches.length+' source records')}">${matches.length}</button>`:'<span title="No indexed source snapshot">—</span>'}</td>`;}).join('');
 $('parity').innerHTML=`<table><caption>Indexed ${esc($('coverage-weight').value?(WEIGHTS[$('coverage-weight').value]+' centroids'):names[$('coverage-kind').value])} by reference vintage</caption><thead><tr><th scope="col">Country / reporting level</th>${columns.map(y=>`<th scope="col">${y==='older'?'Earlier':y==='Unknown'?'Not labelled':y}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr><th scope="row"><button class="row-link" data-level="${row.level.id}" data-country="${esc(row.country)}">${esc(row.level.label)}</button><span class="source-title">${esc(row.country)} · ${esc(row.level.group)}</span></th>${cells(row)}</tr>`).join('')}</tbody></table>`;
 $('coverage-explanation').textContent=$('coverage-kind').value==='lookup'?'Numbers count source records referencing that year. A mixed-vintage lookup can appear in several columns. Select a cell to find its files. A dash means no matching indexed record.':'Numbers count indexed source records, not polygons. Select a cell to find its files. A dash is an index gap, not evidence of abolition or a boundary change. “Earlier” includes support vintages for reporting around 2010.';
}
$('parity').onclick=e=>{const b=e.target.closest('button[data-level]');if(!b)return;drill(b.dataset.level,b.dataset.country,b.dataset.year);$('kind').value=$('coverage-kind').value;$('centroidWeight').value=$('coverage-weight').value;renderResults();};
for(const id of ['coverage-country','coverage-group','coverage-kind','coverage-weight'])$(id).onchange=renderCoverage;
$('export-coverage').onclick=()=>{
 const flat=[];for(const row of rows)for(const year of ['older',...Array.from({length:data.historyEnd-2010+1},(_,i)=>i+2010),'Unknown'])flat.push({country:row.country,level:row.level.label,product:$('coverage-kind').value,centroid_weight:$('coverage-weight').value,reference_year:year,record_count:coverageCell(row,year).length,status:coverageCell(row,year).length?'indexed':'no indexed record',basis:'Source vintages; not certified legal annual validity'});
 download(csv(flat,['country','level','product','centroid_weight','reference_year','record_count','status','basis']),'uk-boundary-coverage.csv','text/csv;charset=utf-8');
};
async function init(){try{
 const response=await fetch('catalogue.json');if(!response.ok)throw Error('Catalogue could not be loaded.');data=await response.json();if(data.schemaVersion!==2)throw Error('Unsupported catalogue format.');
 items=data.items.map(x=>({...x,searchText:searchable(x,data.levels,data.providers)}));
 $('checked').textContent=new Date(data.checked+'T12:00:00Z').toLocaleDateString('en-GB',{day:'numeric',month:'long',year:'numeric'});
 const groups=[...new Set(data.levels.map(l=>l.group))];
 $('level').innerHTML='<option value="">All reporting levels</option>'+groups.map(group=>`<optgroup label="${esc(group)}">${data.levels.filter(l=>l.group===group).map(l=>`<option value="${l.id}">${esc(l.label)}</option>`).join('')}</optgroup>`).join('');
 options('year',[...new Set(items.flatMap(x=>x.years))].sort((a,b)=>b-a).concat([{value:'older',label:'Pre-2010 only'},{value:'Unknown',label:'Not labelled'}]),'All reference years');
 options('provider',data.providers.map(p=>({value:p.id,label:p.name})),'All publishers');
 options('group',groups,'All reporting groups');
 options('format',[...new Set(items.flatMap(x=>x.formats))].sort(),'Any format');
 options('coverage-group',[{value:'Core',label:'Core reporting levels'},...groups],'All reporting groups');$('coverage-group').value='Core';$('coverage-country').value='England';
 const boundaries=items.filter(x=>x.kind==='boundary');
 $('coverage-summary').innerHTML=`<div><strong>${items.length.toLocaleString('en-GB')}</strong><span>source records</span></div><div><strong>${data.levels.length}</strong><span>reporting levels</span></div><div><strong>${data.providers.filter(p=>items.some(x=>x.provider===p.id)).length}</strong><span>official publishers</span></div>${countries.map(c=>`<div><strong>${boundaries.filter(x=>x.countries.includes(c)).length.toLocaleString('en-GB')}</strong><span>${esc(c)} boundary records</span></div>`).join('')}`;
 $('sources').innerHTML=data.providers.map(p=>`<article><span class="eyebrow">${items.filter(x=>x.provider===p.id).length} indexed records</span><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p>${link(p.url,'Open official source')}</article>`).join('');
 $('audit').innerHTML=`<p>${data.sourceAudit.onsItemsScanned.toLocaleString('en-GB')} ONS metadata items were scanned. ${data.sourceAudit.curatedRecords} additional national source records were curated and checked on ${esc(data.curatedChecked)}. ${items.filter(x=>!x.countries.length).length} records have no explicitly labelled national scope.</p><p>This is a source inventory, not a certified register of legal changes. Boundary, lookup, centroid and reference records remain separate.</p>`;
 $('export-index').disabled=false;$('export-manifest').disabled=false;reset();renderCoverage();
 if(location.hash==='#coverage')showTab('coverage');
}catch(error){$('result-count').textContent='Catalogue unavailable';$('results').innerHTML=`<div class="empty"><h3>The catalogue could not be loaded.</h3><p>${esc(error.message)} Reload this page to try again.</p></div>`;$('export-coverage').disabled=true;}}
init();
