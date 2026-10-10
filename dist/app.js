import {filterItems,searchable,coverageRows,coverageCell,partitionCoverageRows,boundaryVariants,BOUNDARY_DETAILS,csv,WEIGHTS,DOWNLOAD_STATUS,downloadStatus,dateLabel,attachAttributes,snapshotAge} from './catalogue-core.mjs';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL=value=>{try{if(!value)return '';const u=new URL(value,location.href);return ['https:','http:'].includes(u.protocol)?u.href:'';}catch{return '';}};
const link=(url,label)=>safeURL(url)?`<a href="${esc(safeURL(url))}" target="_blank" rel="noopener">${esc(label)}</a>`:'';
const detail=BOUNDARY_DETAILS;
const names={boundary:'boundaries',lookup:'lookups / linkage',centroid:'centroids',reference:'names, codes & directories'};
let data,items=[],filtered=[],limit=30,rows=[];
const countries=['England','Wales','Scotland','Northern Ireland'];
const fields=['level','country','year','kind','provider','variant','group','format','delivery','method','centroidWeight'];
let metadataPromise;
function loadMetadata(){return metadataPromise??=fetch('dataset-metadata.json').then(r=>{if(!r.ok)throw Error('Attribute metadata could not be loaded.');return r.json();}).catch(error=>{metadataPromise=null;throw error;});}
function refreshMarkup(){
 const refresh=data.sourceAudit.refresh,checked=refresh?.finished||data.sourceAudit.onsMetadataChecked||data.checked,age=snapshotAge(checked);
 const banner=$('freshness');banner.hidden=false;banner.classList.toggle('attention',age.stale);
 banner.innerHTML=`<strong>${age.stale?'Published snapshot needs a refresh.':'Catalogue freshness'}</strong> Last ${refresh?'refresh and link check':'ONS scan'}: ${esc(dateLabel(checked))}.${refresh?` ${refresh.summary.attentionRecords} records have links or listing status needing attention. ${link('refresh-status.json','Latest published check report')}`:''} ${link('https://github.com/hulsiejames/uk-boundaries/actions/workflows/refresh.yml','Check for updates on GitHub')}. Updates reach this site after the refresh PR is merged.`;
}
function datesMarkup(x){
 return [['published','Publisher publication'],['uploaded','Uploaded / item created'],['infoUpdated','Info updated'],['dataUpdated','Data updated']].map(([key,label])=>{
  const date=x.dates?.[key];return `<dt>${label}</dt><dd>${esc(dateLabel(date?.value,true))}${date?`<span class="source-title">${esc(date.basis)}</span>`:''}</dd>`;
 }).join('');
}
function attributesMarkup(entry){
 const types={String:'Text',Integer:'Integer (32 bit)',SmallInteger:'Integer (16 bit)',Single:'Decimal (32 bit)',Double:'Decimal (64 bit)',OID:'Object identifier',GlobalID:'Global identifier',GUID:'Identifier',Date:'Date / time'};
 return `<p class="small">Publisher layer schema · checked ${esc(entry.checked)}. Download formats can rename, omit or truncate fields; inspect the chosen file before translating.</p>${entry.layers.map(layer=>`<section class="attribute-layer"><h4>${esc(layer.name)}</h4><p class="small">${esc((layer.geometryType||'Table').replace('esriGeometry',''))}${layer.spatialReference?` · CRS ${esc(layer.spatialReference.latestWkid||layer.spatialReference.wkid||layer.spatialReference.wkt||'See source')}`:''}${layer.recordCount!=null?` · ${esc(layer.recordCount)} records`:''}</p>${link(layer.source+'?f=pjson','Publisher schema')}<dl class="attribute-fields">${layer.fields.map(f=>`<dt><code>${esc(f.name)}</code></dt><dd>${esc(types[f.type?.replace('esriFieldType','')]||f.type||'Type not supplied')}${f.length!=null?` · length ${esc(f.length)}`:''}${typeof f.nullable==='boolean'?` · ${f.nullable?'allows null':'required'}`:''}${f.alias&&f.alias!==f.name?`<span class="source-title">${esc(f.alias)}</span>`:''}</dd>`).join('')}</dl>${layer.dataUpdated?`<p class="small">Data updated: ${esc(dateLabel(layer.dataUpdated.value,true))} · ${esc(layer.dataUpdated.basis)}</p>`:''}${layer.publication?`<p class="small">Published: ${esc(dateLabel(layer.publication.value,true))} · ${esc(layer.publication.basis)}</p>`:''}${layer.serviceExportFormats?.length?`<p class="small">Service-supported export formats: ${esc(layer.serviceExportFormats.join(', '))}. The publisher download page controls which are offered.</p>`:''}</section>`).join('')}${entry.status!=='captured'?'<p class="small">Some publisher metadata could not be captured. Missing fields or download status remain unconfirmed.</p>':''}${entry.lastAttempt?`<p class="small">Latest refresh attempt failed on ${esc(entry.lastAttempt)}; this is the last successful snapshot.</p>`:''}`;
}
document.addEventListener('toggle',async e=>{
 const panel=e.target;if(!panel.matches?.('.attribute-details')||!panel.open||panel.dataset.loaded)return;
 const content=panel.querySelector('.attribute-content'),row=items.find(x=>x.id===panel.dataset.record);content.textContent='Loading publisher attributes…';
 try{const metadata=await loadMetadata();const entry=attachAttributes(row,metadata);content.innerHTML=attributesMarkup(metadata.records[entry.attributes.key]);panel.dataset.loaded='true';}
 catch(error){content.replaceChildren();const message=document.createElement('p');message.textContent=error.message+' Close and reopen to retry.';content.append(message);}
},true);
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
 const boundaryView=['boundary',''].includes($('kind').value);$('boundary-options').hidden=!boundaryView;if(!boundaryView)$('variant').value='';
 filtered=filterItems(items,filters(),data.levels,data.providers);
 $('result-count').textContent=`${filtered.length.toLocaleString('en-GB')} official source ${filtered.length===1?'record':'records'}`;
 const level=data.levels.find(l=>l.id===$('level').value);
 $('level-note').textContent=level?.note||'Search finds datasets and download bundles. Audited combined-authority names and codes are searchable; other individual polygon names are not indexed.';
 $('results').innerHTML=filtered.slice(0,limit).map(x=>{
  const provider=data.providers.find(p=>p.id===x.provider)?.name||x.provider;
  const labels=data.levels.filter(l=>x.levels.includes(l.id)).map(l=>l.label).join(' · ');
  const downloads=x.downloads.map(d=>link(d.url,'Download '+d.format)).join('');
  const status=downloadStatus(x),availability=x.downloadAvailability;
  const publisherDownload=status==='publisher'?link(availability.pages?.[0]||x.source,'Choose download format'):'';
  const cardDate=x.dates?.dataUpdated||x.dates?.infoUpdated;
  return `<article class="result"><div class="result-main"><span class="eyebrow">${esc(provider)} · ${esc(names[x.kind])}</span><h3>${esc(x.title)}</h3><span class="source-title">${esc(labels)}</span><div class="tags"><span class="tag download-tag ${['direct','publisher'].includes(status)?'available':''}">${esc(DOWNLOAD_STATUS[status]||DOWNLOAD_STATUS.unknown)}</span>${x.linkHealth?.state==='attention'?'<span class="tag attention-tag">Links need attention</span>':''}${x.sourceListing==='not-found'?'<span class="tag attention-tag">Absent from current publisher listing</span>':''}<span class="tag">${esc(x.countries.join(' & ')||'Scope not labelled')}</span><span class="tag">${esc(x.vintage)}</span>${x.formats.map(f=>`<span class="tag">${esc(f)}</span>`).join('')}</div></div><div class="result-meta"><span class="data-label">${x.kind==='boundary'?'Boundary detail':'Reference vintages'}</span><span class="data-value">${esc(x.kind==='boundary'?(detail[x.variant]||x.variant):(x.years.join(', ')||'Not labelled'))}</span>${x.kind==='centroid'?`<span class="data-label updated">Centroid weighting</span><span class="data-value">${esc(WEIGHTS[x.centroidWeight]||'Not specified')}</span>`:''}${x.kind==='lookup'?`<span class="source-title">${esc(x.method||'Method: see publisher')}</span>`:''}<span class="data-label updated">${x.dates?.dataUpdated?'Data updated':'Info updated'}</span><span class="data-value">${esc(dateLabel(cardDate?.value))}</span>${x.dates?.published?`<span class="data-label updated">Published</span><span class="data-value">${esc(dateLabel(x.dates.published.value))}</span>`:''}</div><div class="result-actions">${link(x.source,'Official source & licence')}${downloads}${publisherDownload}${x.service?link(x.service,'Open geography service'):''}</div><details class="record-details"><summary>Dates, download status & translation notes</summary><dl><dt>Vintage basis</dt><dd>${esc(x.dateBasis)}</dd><dt>Reference years</dt><dd>${esc(x.years.join(', ')||'Not explicitly labelled')}</dd>${datesMarkup(x)}<dt>Source checked</dt><dd>${esc(x.checked)}</dd><dt>Download status</dt><dd>${esc(DOWNLOAD_STATUS[status]||DOWNLOAD_STATUS.unknown)}<span class="source-title">${esc(availability?.basis||'Availability not confirmed')}${availability?.checked?` · checked ${esc(availability.checked)}`:''}</span>${availability?.source?link(availability.source,'Download status source'):''}</dd>${x.linkHealth?`<dt>Link check</dt><dd>${x.linkHealth.state==='attention'?'Some links need attention':'Checked'} · ${esc(x.linkHealth.checked)}${x.sourceListing==='not-found'?'<span class="source-title">Historical record retained; absent from the latest publisher listing.</span>':''} ${link('refresh-status.json','Per-link check report')}</dd>`:''}<dt>Catalogue ID</dt><dd>${esc(x.id)}</dd></dl><p class="small">Publisher dates describe this source item; they are separate from the boundary vintage and legal effective dates.</p>${x.kind==='centroid'?`<p><strong>Weighting basis:</strong> ${esc(x.centroidWeightBasis||'Not specified by the indexed source')}</p>${x.centroidAlgorithm?`<p>${esc(x.centroidAlgorithm)}</p>`:''}${x.centroidMethodology?link(x.centroidMethodology,'Centroid methodology'):''}`:''}${x.areas?.length?`<p><strong>Indexed areas:</strong> ${esc(x.areas.map(a=>a.name+(a.code?' · '+a.code:'')).join('; '))}</p>${x.areaNamesSource?link(x.areaNamesSource,'Names/code audit source'):''}`:''}${x.notes?`<p>${esc(x.notes)}</p>`:''}${x.kind==='lookup'?'<p>Check the source’s fit method and weighting definitions before translating statistics.</p>':''}${!x.downloads.length?'<p>The publisher page supplies its download options. This index contains metadata only.</p>':''}${!x.attributes?.fields?'<p>Attribute schema has not been captured for this source. Check the publisher’s file or data dictionary.</p>':''}${x.itemUrl?link(x.itemUrl,'ArcGIS item metadata'):''}</details>${x.attributes?.fields?`<details class="record-details attribute-details" data-record="${esc(x.id)}"><summary>Attributes · ${x.attributes.fields} fields${x.attributes.layers>1?` across ${x.attributes.layers} layers`:''}</summary><div class="attribute-content"></div></details>`:''}</article>`;
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
async function exportRecords(format){
 const snapshot=filtered.map(exportable),selectedFilters=filters();
 $('export-index').disabled=true;$('export-manifest').disabled=true;$('export-status').textContent='Preparing export with publisher attributes…';
 try{
  const metadata=snapshot.some(x=>x.attributes)?await loadMetadata():null;
  const records=snapshot.map(x=>x.attributes?attachAttributes(x,metadata):x);
  if(format==='json')download(JSON.stringify({schemaVersion:data.schemaVersion,checked:data.checked,filters:selectedFilters,levels:data.levels,providers:data.providers,items:records},null,2),'uk-boundary-manifest.json','application/json');
  else{
   const flat=records.map(x=>({...x,levels:x.levels.map(id=>data.levels.find(l=>l.id===id)?.label||id),downloads:x.downloads.map(d=>d.format+': '+d.url).join(' | '),areas:(x.areas||[]).map(a=>a.name+(a.code?' ['+a.code+']':'')).join(' | '),downloadStatus:downloadStatus(x),downloadAvailability:JSON.stringify(x.downloadAvailability),linkHealth:JSON.stringify(x.linkHealth||null),dates:JSON.stringify(x.dates),attributeSchema:JSON.stringify(x.attributeSchema||null),attributes:JSON.stringify(x.attributes||null),attributeMetadataErrors:JSON.stringify(x.attributeMetadataErrors||[])}));
   download(csv(flat,['id','title','levels','kind','vintage','years','countries','provider','variant','formats','source','downloads','service','downloadStatus','downloadAvailability','sourceListing','linkHealth','dates','attributes','attributeSchema','attributeMetadataErrors','attributeLastAttempt','method','centroidWeight','centroidWeightBasis','centroidWeightYear','centroidAlgorithm','centroidMethodology','areas','areaNamesSource','dateBasis','published','modified','uploaded','infoUpdated','checked','notes']),'uk-boundary-catalogue.csv','text/csv;charset=utf-8');
  }
  $('export-status').textContent='Export ready. Attribute schemas are included where captured.';
 }catch(error){$('export-status').textContent=error.message+' Retry the export.';}
 finally{$('export-index').disabled=false;$('export-manifest').disabled=false;}
}
$('export-index').onclick=()=>exportRecords('csv');
$('export-manifest').onclick=()=>exportRecords('json');
function drill(level,country,year){reset(false);$('level').value=level;$('country').value=country;
 if(year==='older'){$('older').checked=true;$('year').value='older';}else if(year)$('year').value=year;
 $('kind').value=$('coverage-kind').value;$('centroidWeight').value=$('coverage-weight').value;$('variant').value=$('coverage-variant').value;
 renderResults();showTab('catalogue');window.scrollTo({top:0,behavior:'instant'});
}
function renderCoverage(){
 if(!data)return;
 const isCentroid=$('coverage-kind').value==='centroid';$('coverage-centroid-options').hidden=!isCentroid;if(!isCentroid)$('coverage-weight').value='';
 const isBoundary=$('coverage-kind').value==='boundary';$('coverage-boundary-options').hidden=!isBoundary;if(!isBoundary)$('coverage-variant').value='';
 rows=coverageRows(items,data.levels,$('coverage-country').value?[$('coverage-country').value]:countries,$('coverage-group').value,$('coverage-kind').value,$('coverage-weight').value,$('coverage-variant').value);
 const years=Array.from({length:data.historyEnd-2010+1},(_,i)=>2010+i),columns=['older',...years,'Unknown'];
 const {indexed,missing}=partitionCoverageRows(rows,columns);
 const yearLabel=y=>y==='older'?'Earlier':y==='Unknown'?'Not labelled':y;
 const button=(row,y,count,text)=>`<button class="coverage-cell" data-level="${row.level.id}" data-country="${esc(row.country)}" data-year="${y}" aria-label="${esc(row.country+' · '+row.level.label+' · '+(y==='Unknown'?'unlabelled':y==='older'?'pre-2010':y)+' · '+count+' source records')}">${text}</button>`;
 const cells=row=>columns.map(y=>{const count=coverageCell(row,y).length;return `<td>${count?button(row,y,count,count):'<span title="No indexed source snapshot">—</span>'}</td>`;}).join('');
 const heading=row=>`<button class="row-link" data-level="${row.level.id}" data-country="${esc(row.country)}">${esc(row.level.label)}</button><span class="source-title">${esc(row.country)} · ${esc(row.level.group)}</span>`;
 const caption='Indexed '+($('coverage-weight').value?(WEIGHTS[$('coverage-weight').value]+' centroids'):names[$('coverage-kind').value])+($('coverage-variant').value?' · '+(detail[$('coverage-variant').value]||$('coverage-variant').value):'')+' by reference vintage';
 $('parity').innerHTML=indexed.length?`<div class="parity-table coverage-desktop"><table><caption>${esc(caption)}</caption><thead><tr><th scope="col">Country / reporting level</th>${columns.map(y=>`<th scope="col">${yearLabel(y)}</th>`).join('')}</tr></thead><tbody>${indexed.map(row=>`<tr><th scope="row">${heading(row)}</th>${cells(row)}</tr>`).join('')}</tbody></table></div><div class="coverage-cards" aria-label="${esc(caption)}">${indexed.map(row=>`<article class="coverage-card"><h3>${heading(row)}</h3><div class="coverage-vintages">${columns.map(y=>{const count=coverageCell(row,y).length;return count?button(row,y,count,`${yearLabel(y)} <span class="vintage-count">${count}</span>`):'';}).join('')}</div></article>`).join('')}</div>`:'<div class="empty"><h3>No indexed files under these filters.</h3><p>Try another product, reporting group or boundary detail. The reporting rows are listed in “Not found” below.</p></div>';
 $('coverage-row-count').textContent=`${indexed.length} reporting ${indexed.length===1?'row':'rows'} with indexed files · ${missing.length} not found under these filters.`;
 $('not-found').hidden=!missing.length;
 $('not-found-summary').textContent=`Not found (${missing.length} reporting ${missing.length===1?'row':'rows'})`;
 $('not-found-list').innerHTML=missing.map(row=>`<li><strong>${esc(row.level.label)}</strong><span class="source-title">${esc(row.country)} · ${esc(row.level.group)}</span></li>`).join('');
 $('coverage-explanation').textContent=$('coverage-kind').value==='lookup'?'Numbers count source records referencing that year. A mixed-vintage lookup can appear in several columns. Select a cell to find its files. A dash means no matching indexed record.':'Numbers count indexed source records, not polygons. Select a cell to find its files. A dash is an index gap, not evidence of abolition or a boundary change. “Earlier” includes support vintages for reporting around 2010.';
}
$('parity').onclick=e=>{const b=e.target.closest('button[data-level]');if(b)drill(b.dataset.level,b.dataset.country,b.dataset.year);};
for(const id of ['coverage-country','coverage-group','coverage-kind','coverage-weight','coverage-variant'])$(id).onchange=renderCoverage;
$('export-coverage').onclick=()=>{
 const flat=[];for(const row of rows)for(const year of ['older',...Array.from({length:data.historyEnd-2010+1},(_,i)=>i+2010),'Unknown'])flat.push({country:row.country,level:row.level.label,product:$('coverage-kind').value,centroid_weight:$('coverage-weight').value,boundary_variant:$('coverage-variant').value,reference_year:year,record_count:coverageCell(row,year).length,status:coverageCell(row,year).length?'indexed':'no indexed record',basis:'Source vintages; not certified legal annual validity'});
 download(csv(flat,['country','level','product','centroid_weight','boundary_variant','reference_year','record_count','status','basis']),'uk-boundary-coverage.csv','text/csv;charset=utf-8');
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
 for(const id of ['variant','coverage-variant'])options(id,boundaryVariants(items),'Any boundary detail');
 options('coverage-group',[{value:'Core',label:'Core reporting levels'},...groups],'All reporting groups');$('coverage-group').value='Core';$('coverage-country').value='England';
 const boundaries=items.filter(x=>x.kind==='boundary');
 $('coverage-summary').innerHTML=`<div><strong>${items.length.toLocaleString('en-GB')}</strong><span>source records</span></div><div><strong>${data.levels.length}</strong><span>reporting levels</span></div><div><strong>${data.providers.filter(p=>items.some(x=>x.provider===p.id)).length}</strong><span>official publishers</span></div>${countries.map(c=>`<div><strong>${boundaries.filter(x=>x.countries.includes(c)).length.toLocaleString('en-GB')}</strong><span>${esc(c)} boundary records</span></div>`).join('')}`;
 $('sources').innerHTML=data.providers.map(p=>`<article><span class="eyebrow">${items.filter(x=>x.provider===p.id).length} indexed records</span><h3>${esc(p.name)}</h3><p>${esc(p.description)}</p>${link(p.url,'Open official source')}</article>`).join('');
 $('audit').innerHTML=`<p>${data.sourceAudit.onsItemsScanned.toLocaleString('en-GB')} ONS metadata items were scanned${data.sourceAudit.onsMetadataChecked?' on '+esc(data.sourceAudit.onsMetadataChecked):''}. ${data.sourceAudit.curatedRecords} additional national source records were curated and checked on ${esc(data.curatedChecked)}. ${items.filter(x=>!x.countries.length).length} records have no explicitly labelled national scope.</p>${data.sourceAudit.publisherMetadataChecked?`<p>Publisher download flags, dates and layer attributes were captured on ${esc(data.sourceAudit.publisherMetadataChecked)}. ${items.filter(x=>x.attributes?.fields).length.toLocaleString('en-GB')} records have a captured attribute schema. Download tags reflect indexed links or publisher metadata; individual files have not all been downloaded or tested. Missing schemas and unconfirmed download availability remain explicit.</p>`:''}<p>This is a source inventory, not a certified register of legal changes. Boundary, lookup, centroid and reference records remain separate.</p>`;
 $('export-index').disabled=false;$('export-manifest').disabled=false;refreshMarkup();reset();renderCoverage();
 if(location.hash==='#coverage')showTab('coverage');
}catch(error){$('result-count').textContent='Catalogue unavailable';$('results').innerHTML=`<div class="empty"><h3>The catalogue could not be loaded.</h3><p>${esc(error.message)} Reload this page to try again.</p></div>`;$('export-coverage').disabled=true;}}
init();
