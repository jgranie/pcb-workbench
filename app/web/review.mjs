import {traceSettings,traceAnchors,mergeTraceScan,filteredTraces,mountTraceSettings} from './traces.mjs';
import {visibleRoutes,nearestStroke,strokeKey,chainedStrokes,addManualLine,deleteStrokes,logicalSegments} from './core/trace-edit-core.mjs';
import {mountWevisone} from './wevisone.mjs';
import {mountSolders,replaceSolders,solderSectionCore,inSolderCore,solderResultText} from './solders.mjs';
const $=id=>document.getElementById(id),clone=structuredClone;
const resultId=new URLSearchParams(location.search).get('result'),resultQuery=resultId?'?result='+encodeURIComponent(resultId):'';
const get=async name=>{const r=await fetch('/data/'+name+resultQuery);if(!r.ok)throw Error('Fichier absent : '+name);return r.json();};
let workspace=await get('workspace.json'),meta=await get('image.json'),candidates=(await get('candidates.json')).candidates;
const receipt=await get('result.json');
const provenance=await get('provenance.json');
const sourceLabel=[provenance.filename,provenance.xcf_layer?.name].filter(Boolean).join(' · ');
if(sourceLabel){document.title=sourceLabel+' — Atelier PCB';$('showOriginal').closest('label').title=sourceLabel;}
$('pipelineInfo').textContent=provenance.standalone_from_original===false?(provenance.material_mask?'Parcours assisté : contour PCB et retrait d’époxy expérimental':'Parcours assisté par un masque de fond')+(provenance.background_mask?.evidence?.execution==='simulation'?' simulé — TEST UNIQUEMENT':' revu')+' ; provenance conservée.':'Parcours CPU depuis Original.';
$('parentResult').hidden=!resultId;
for(const link of document.querySelectorAll('a[href^="/data/"]'))link.href+=resultQuery;
const image=await loadImage('/data/original.png'+resultQuery);
let modelPreview=null,cropImage=null,legacyCrop=null,cropSerial=0,modelControls=null,solderControls=null;
if(provenance.standalone_from_original===false){
  const alpha=await loadImage('/data/'+(provenance.material_mask?'external-material-mask.png':'board.png')+resultQuery);
  legacyCrop=document.createElement('canvas');legacyCrop.width=meta.width;legacyCrop.height=meta.height;
  const c=legacyCrop.getContext('2d');c.drawImage(image,0,0);const pixels=c.getImageData(0,0,meta.width,meta.height);
  c.drawImage(alpha,0,0);const a=c.getImageData(0,0,meta.width,meta.height);
  for(let i=0;i<pixels.data.length;i+=4)pixels.data[i+3]=a.data[i]>=128?255:0;c.putImageData(pixels,0,0);
}
async function syncCrop(){
  const serial=++cropSerial,id=workspace.preprocessing?.id;
  const next=id?await loadImage('/api/preprocessing/'+id+'/original-cropped.png'+resultQuery):legacyCrop;
  if(serial!==cropSerial)return;
  cropImage=next;
  const layers=workspace.layerVisibility??{original:!cropImage,crop:!!cropImage,pads:true,routes:true};
  for(const [id,key] of [['showOriginal','original'],['showCrop','crop'],['showPads','pads'],['showRoutes','routes']])$(id).checked=!!layers[key];
  $('showCrop').disabled=!cropImage;
  modelControls?.refresh();
}
function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;});}
const canvas=$('canvas'),ctx=canvas.getContext('2d'),container=$('view');
let zoom=1,offset=[0,0],pointer=null,pending=null,selections=new Map(),padSelection=new Set(),undo=[],redo=[],worker,ready=false,busy=false,modelBlocking=false,solderBlocking=false,source=null,target=null,direction=null,proposed=[],dirty=false,scanStale=false;
let solderView={section:null,only:false},toolMode='pan',activeDomain='solders',workerKey=null,queuedRequest=null,workerTimer=null,tracePhase='',traceNotice='',lastReviewKey='';
const getTraceSettings=()=>traceSettings(workspace.traceSettings);
function setTool(mode,domain='traces'){toolMode=mode;activeDomain=domain;pending=null;selections.clear();padSelection.clear();if(mode==='follow')$('traceFollowPanel').open=true;render();}

function solderViewCore(){return activeDomain!=='traces'&&solderView.only?solderSectionCore(meta.width,meta.height,solderView.section):null;}
function message(text){$('status').textContent=text;}
function history(){workspace.scanStale=scanStale;undo.push(clone(workspace));if(undo.length>40)undo.shift();redo=[];dirty=true;$('saveState').textContent='Modifié';}
function invalidate(){scanStale=true;workspace.scanStale=true;proposed=[];message(workspace.traceScan.routes.length?'Soudures modifiées · pistes à recalculer.':'Soudures modifiées.');}
function currentCandidates(){return workspace.solderDetection?.candidates??candidates;}
function allPads(){return [...currentCandidates(),...workspace.objects.filter(o=>o.type==='pad').map(p=>({id:p.id,coords:[p.x-12,p.y-12,p.x+12,p.y+12],origin:'manual'}))].filter(c=>workspace.detectionReviews[c.id]?.status!=='rejected').map(c=>{const r=workspace.detectionReviews[c.id]??{};return {...c,x:r.x??(c.coords[0]+c.coords[2])/2,y:r.y??(c.coords[1]+c.coords[3])/2};});}
function pads(){const core=solderViewCore();return allPads().filter(p=>inSolderCore(p,core));}
function displayScan(){return scanStale?{...workspace.traceScan,routes:workspace.traceScan.routes.filter(r=>r.origin!=='automatic')}:workspace.traceScan;}
function nearestPad(p){let best=null;for(const a of pads()){const d=Math.hypot(a.x-p[0],a.y-p[1]);if(d<Math.max(12,8/zoom)&&(!best||d<best.d))best={...a,d};}return best;}
function world(event){const r=canvas.getBoundingClientRect();return[(event.clientX-r.left-offset[0])/zoom,(event.clientY-r.top-offset[1])/zoom].map((v,i)=>Math.max(0,Math.min((i?meta.height:meta.width)-.001,v)));}
function fit(){zoom=Math.min(container.clientWidth/meta.width,container.clientHeight/meta.height)*.96;offset=[(container.clientWidth-meta.width*zoom)/2,(container.clientHeight-meta.height*zoom)/2];render();}
function render(){
  const dpr=devicePixelRatio;canvas.width=container.clientWidth*dpr;canvas.height=container.clientHeight*dpr;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,canvas.width,canvas.height);ctx.translate(...offset);ctx.scale(zoom,zoom);
  if(modelPreview||$('showOriginal').checked)ctx.drawImage(image,0,0);
  if($('showCrop').checked&&cropImage&&!modelPreview)ctx.drawImage(cropImage,0,0);
  if(modelPreview)ctx.drawImage(modelPreview,0,0);
  const scope=solderViewCore();
  if(scope&&!modelPreview){ctx.save();ctx.strokeStyle='#a3dcc7';ctx.lineWidth=1.5/zoom;ctx.setLineDash([6/zoom,4/zoom]);ctx.strokeRect(scope[0],scope[1],scope[2]-scope[0],scope[3]-scope[1]);ctx.restore();}
  if($('showRoutes').checked&&!modelPreview){for(const r of [...visibleRoutes(displayScan()),...proposed]){
    ctx.strokeStyle=r.origin!=='automatic'?'#3687ff':r.gaps.length?'#ffad22':r.broad?'#ce79ee':'#ffdc4d';ctx.lineWidth=2/zoom;ctx.setLineDash(r.gaps.length?[5/zoom,4/zoom]:[]);ctx.beginPath();r.points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();ctx.setLineDash([]);
  }}
  if(!modelPreview)for(const span of selections.values()){const r=workspace.traceScan.routes.find(r=>r.id===span.routeId);if(!r)continue;ctx.strokeStyle='#ff623a';ctx.lineWidth=5/zoom;ctx.beginPath();r.points.slice(span.start,span.end+1).forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();}
  if($('showPads').checked&&!modelPreview)for(const [padIndex,a] of pads().entries()){ctx.strokeStyle=padSelection.has(a.id)||a.id===source?'#ff7849':a.id===target?'#fbe454':'#39e5d4';ctx.lineWidth=1.2/zoom;ctx.beginPath();ctx.arc(a.x,a.y,Math.max(4,3/zoom),0,2*Math.PI);if(a.origin==='manual'){ctx.fillStyle=padSelection.has(a.id)?'#ff7849':'#3687ff';ctx.fill();}ctx.stroke();if(zoom>.65){ctx.font=`${10/zoom}px system-ui`;ctx.fillStyle=ctx.strokeStyle;ctx.fillText(a.origin==='manual'?a.id.slice(4):String(padIndex+1),a.x+6/zoom,a.y-4/zoom);}}
  if(pending){ctx.fillStyle='#388dff';ctx.beginPath();ctx.arc(...pending,5/zoom,0,2*Math.PI);ctx.fill();}
  const visible=$('showRoutes').checked?visibleRoutes(displayScan()).length:0;
  $('summary').textContent=(scope?`${pads().length} points dans la section · ${allPads().length} au total`:`${allPads().length} candidats`)+` · ${visible} tracés visibles · ${workspace.traceScan.issues.length} diagnostics${scanStale&&workspace.traceScan.routes.length?' · tracés périmés':''}${receipt.status==='partial_proposals'?' · ESSAI PARTIEL':''}`;
  $('selection').textContent=selections.size?`${selections.size} tronçon(s) sélectionné(s)`:'Aucune sélection';
  renderTracePanel();
  $('save').dataset.dirty=String(dirty);$('save').title=dirty?'Enregistrer · modifications en attente':'Enregistrer';
  for(const id of ['reject','accept','candidate','addPad','rescan','open'])$(id).disabled=busy||modelBlocking||solderBlocking;
  $('save').disabled=busy||modelBlocking;$('export').disabled=busy||modelBlocking;
  $('selectPads').disabled=busy||modelBlocking||solderBlocking;$('deletePads').disabled=busy||modelBlocking||solderBlocking||!padSelection.size;
  $('selectPads').setAttribute('aria-pressed',String(toolMode==='pads'));$('addPad').setAttribute('aria-pressed',String(toolMode==='pad-add'));
  $('solderSelection').textContent=padSelection.size?`${padSelection.size} sélectionnée(s)`:'Aucune sélection';
  if(workspace.solderDetection&&!workspace.solderDetection.job_id){const d=workspace.solderDetection,stale=d.input==='cropped'&&d.source_crop!==(workspace.preprocessing?.id??null);$('solderStatus').textContent=stale?'Recadrage modifié · relancer la détection':`${pads().length} points${d.stats.candidates_truncated||d.replacement_truncated?' · résultat partiel':''}`;}
  solderControls?.refresh();
  canvas.style.cursor=['pad-add','line','follow'].includes(toolMode)?'crosshair':toolMode==='pan'?'grab':'default';
  $('undo').disabled=busy||modelBlocking||solderBlocking||!undo.length;$('redo').disabled=busy||modelBlocking||solderBlocking||!redo.length;
  modelControls?.refresh();
}
function traceFieldKey(){return JSON.stringify([workspace.preprocessing?.id??'initial',getTraceSettings().allow_photo_gaps]);}
function sendTraceRequest(data){worker.postMessage(data);}
function request(type,extra={}){
  if(busy||modelBlocking||solderBlocking){message('Moteur occupé.');return;}
  activeDomain='traces';busy=true;traceNotice='';tracePhase='Préparation du masque…';render();
  const data={type,candidates:currentCandidates(),reviews:workspace.detectionReviews,manualPads:workspace.objects.filter(p=>p.type==='pad'),source,target,direction,settings:getTraceSettings(),input:{source_rgba_sha256:workspace.source_rgba_sha256,source_crop:workspace.preprocessing?.id??null},...extra};
  clearTimeout(workerTimer);workerTimer=setTimeout(()=>stopTrace('Calcul arrêté après 90 s ; résultat précédent conservé.'),90000);
  if(workerKey!==traceFieldKey()||!worker||!ready){
    queuedRequest=data;initWorker();
  }else sendTraceRequest(data);
}
function stopTrace(text='Calcul arrêté ; résultat précédent conservé.'){
  worker?.terminate();worker=null;ready=false;busy=false;workerKey=null;queuedRequest=null;clearTimeout(workerTimer);tracePhase='';proposed=[];message(text);render();
}
function initWorker(){
  worker?.terminate();worker=new Worker('/worker.mjs',{type:'module'});ready=false;workerKey=traceFieldKey();
  worker.onmessage=({data})=>{
    if(data.type==='ready'){ready=true;const next=queuedRequest;queuedRequest=null;if(next)sendTraceRequest(next);return;}
    if(data.type==='progress'){tracePhase=data.message;render();return;}
    busy=false;clearTimeout(workerTimer);tracePhase='';
    if(data.type==='error'){traceNotice=data.message;message(data.message);}
    if(data.type==='directions'){
      $('directions').replaceChildren();for(const d of data.radial.directions){const button=document.createElement('button');button.textContent=d.degrees+'°';button.setAttribute('aria-pressed',String(direction?.degrees===d.degrees));button.onclick=()=>{direction=d;for(const b of $('directions').children)b.setAttribute('aria-pressed',String(b===button));message('Direction '+d.degrees+'° choisie.');if(target)request('follow');};$('directions').append(button);}
      $('followInfo').textContent=followText()+(data.radial.surface?' · surface large':` · ${data.radial.directions.length} direction(s)`);
      message('Choisir une direction et une arrivée sur la carte.');if(target)request('follow');
    }
    if(data.type==='follow'){proposed=data.result.routes;message(proposed.length?'Chemin proposé ; conserver après examen.':`Aucun chemin trouvé (${data.result.stopped??'masque déconnecté'}).`);}
    if(data.type==='scan'){
      history();workspace.traceScan=mergeTraceScan(workspace.traceScan,data.scan);
      scanStale=false;workspace.scanStale=false;selections.clear();proposed=[];
      workspace.layerVisibility??={original:!cropImage,crop:!!cropImage,pads:true,routes:true};workspace.layerVisibility.routes=true;$('showRoutes').checked=true;
      message(`Détection ${data.scan.complete?'terminée':'partielle'} · corrections conservées. Enregistrer pour garder.`);
    }render();
  };
  worker.onerror=event=>stopTrace('Erreur du moteur : '+event.message);
  let alpha=null;
  if(cropImage){const c=document.createElement('canvas');c.width=meta.width;c.height=meta.height;const context=c.getContext('2d');context.drawImage(cropImage,0,0);const rgba=context.getImageData(0,0,c.width,c.height).data;alpha=new Uint8Array(c.width*c.height);for(let i=0;i<alpha.length;i++)alpha[i]=rgba[i*4+3];}
  worker.postMessage({type:'init',result:resultId,alpha,settings:getTraceSettings()},alpha?[alpha.buffer]:[]);
}
canvas.addEventListener('wheel',event=>{event.preventDefault();const r=canvas.getBoundingClientRect(),x=event.clientX-r.left,y=event.clientY-r.top,z=Math.max(.1,Math.min(5,zoom*Math.exp(-event.deltaY*.0015))),ratio=z/zoom;offset=[x-(x-offset[0])*ratio,y-(y-offset[1])*ratio];zoom=z;render();},{passive:false});
canvas.onpointerdown=event=>{
  const p=world(event),mode=toolMode,a=['pads','follow'].includes(mode)?nearestPad(p):null;
  pointer={client:[event.clientX,event.clientY],offset:[...offset],p,moved:false,pad:mode==='pads'?a:null};canvas.setPointerCapture(event.pointerId);
};
canvas.onpointermove=event=>{
  if(!pointer)return;const dx=event.clientX-pointer.client[0],dy=event.clientY-pointer.client[1];if(Math.hypot(dx,dy)>4)pointer.moved=true;
  if(pointer.moved&&!pointer.pad){offset=[pointer.offset[0]+dx,pointer.offset[1]+dy];render();}
};
canvas.onpointerup=event=>{
  if(!pointer)return;const gesture=pointer;pointer=null;const p=world(event),mode=toolMode,multi=event.metaKey||event.ctrlKey||event.shiftKey;
  if(modelPreview&&mode!=='pan'){message('Quitter l’aperçu du contour pour modifier le travail.');return;}
  if((busy||modelBlocking||solderBlocking)&&mode!=='pan'){message('Calcul en cours : attendre ou arrêter avant de modifier les données.');return;}
  if(gesture.moved){if(gesture.pad){history();workspace.detectionReviews[gesture.pad.id]={...workspace.detectionReviews[gesture.pad.id],x:p[0],y:p[1]};invalidate();render();}return;}
  if(mode==='pad-add'){addPad(p);}
  if(mode==='pads'){const a=nearestPad(p);if(!multi)padSelection.clear();if(a){if(multi&&padSelection.has(a.id))padSelection.delete(a.id);else padSelection.add(a.id);}selections.clear();}
  if(mode==='follow'){
    const a=nearestPad(p);if(!a){message('Choisir une soudure visible ou ajouter une pastille.');return;}
    if(!source){source=a.id;target=null;direction=null;request('directions');}else{target=a.id;request('follow');}
    $('followInfo').textContent=followText();
  }
  if(mode==='line'){
    let end=p;if(pending&&event.shiftKey){const dx=p[0]-pending[0],dy=p[1]-pending[1],angle=Math.round(Math.atan2(dy,dx)/(Math.PI/4))*Math.PI/4,length=Math.hypot(dx,dy);end=[pending[0]+length*Math.cos(angle),pending[1]+length*Math.sin(angle)].map((v,i)=>Math.max(0,Math.min((i?meta.height:meta.width)-.001,v)));}
    if(pending){try{const result=addManualLine(workspace.traceScan,pending,end,{tolerance:8/zoom,snap:!event.altKey});history();workspace.traceScan=result.scan;pending=result.end;workspace.layerVisibility??={original:!cropImage,crop:!!cropImage,pads:true,routes:true};workspace.layerVisibility.routes=true;$('showRoutes').checked=true;message('Ligne ajoutée ; cliquer pour continuer ou Terminer.');}catch(error){message(error.message);}}else pending=end;
  }
  if(mode==='stroke'){
    const hit=nearestStroke(displayScan(),p,8/zoom);padSelection.clear();if(!multi)selections.clear();if(hit){const key=strokeKey(hit);if(multi&&selections.has(key))selections.delete(key);else selections.set(key,hit);}
  }render();
};
canvas.ondblclick=event=>{if(toolMode!=='stroke'||busy||modelBlocking||solderBlocking||modelPreview)return;const hit=nearestStroke(displayScan(),world(event),8/zoom);if(!hit)return;if(!event.metaKey&&!event.ctrlKey)selections.clear();const chain=chainedStrokes(workspace.traceScan,hit),remove=(event.metaKey||event.ctrlKey)&&chain.every(span=>selections.has(strokeKey(span)));for(const span of chain)if(remove)selections.delete(strokeKey(span));else selections.set(strokeKey(span),span);render();};
function review(status){if(!selections.size)return;history();for(const span of selections.values())workspace.traceScan.reviews[span.routeId]={status};render();}
$('reject').onclick=()=>{
  if(padSelection.size){history();for(const id of padSelection)workspace.detectionReviews[id]={...workspace.detectionReviews[id],status:'rejected'};padSelection.clear();invalidate();}
  else if(selections.size){try{const result=deleteStrokes(workspace.traceScan,[...selections.values()]);history();workspace.traceScan=result.scan;selections.clear();}catch(error){message(error.message);}}render();
};
$('accept').onclick=()=>review('accepted');$('candidate').onclick=()=>review('candidate');
function addPad(p){history();workspace.objects.push({type:'pad',id:'PAD-M'+String(workspace.nextId++).padStart(4,'0'),x:p[0],y:p[1]});invalidate();workspace.layerVisibility??={original:!cropImage,crop:!!cropImage,pads:true,routes:false};workspace.layerVisibility.pads=true;$('showPads').checked=true;}
$('addPad').onclick=()=>{activeDomain='solders';toolMode='pad-add';pending=null;padSelection.clear();selections.clear();message('Cliquer sur la carte pour ajouter une soudure.');render();};
$('selectPads').onclick=()=>{activeDomain='solders';toolMode='pads';pending=null;selections.clear();message('Cliquer pour sélectionner ; glisser pour déplacer.');render();};
$('deletePads').onclick=()=>{if(padSelection.size)$('reject').click();};
$('finish').onclick=()=>{pending=null;render();};
$('undo').onclick=async()=>{if(!undo.length)return;const rev=workspace._revision;redo.push(clone(workspace));workspace=undo.pop();workspace._revision=rev;dirty=true;$('saveState').textContent='Modifié';selections.clear();padSelection.clear();pending=null;proposed=[];source=null;target=null;direction=null;traceNotice='';scanStale=workspace.scanStale??false;await syncCrop();message('Modification annulée.');render();};
$('redo').onclick=async()=>{if(!redo.length)return;const rev=workspace._revision;undo.push(clone(workspace));workspace=redo.pop();workspace._revision=rev;dirty=true;$('saveState').textContent='Modifié';selections.clear();padSelection.clear();pending=null;proposed=[];source=null;target=null;direction=null;traceNotice='';scanStale=workspace.scanStale??false;await syncCrop();message('Modification rétablie.');render();};
$('rescan').onclick=()=>request('scan');
$('keep').onclick=()=>{if(!proposed.length)return;history();const map=new Map(workspace.traceScan.routes.map(r=>[r.id,r]));for(const r of proposed)map.set(r.id,r);workspace.traceScan.routes=[...map.values()];proposed=[];message('Chemin conservé ; enregistrer.');render();};
$('resetFollow').onclick=()=>{source=null;target=null;direction=null;proposed=[];$('directions').replaceChildren();$('followInfo').textContent='Choisir le départ sur une soudure.';render();};
$('stop').onclick=()=>stopTrace();
async function saveWork(){try{message('Enregistrement…');$('saveState').textContent='Enregistrement…';workspace.scanStale=scanStale;const response=await fetch('/workspace'+resultQuery,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(workspace)});const result=await response.json();if(!response.ok)throw Error(result.error);workspace._revision=result.revision;dirty=false;$('saveState').textContent='Enregistré · '+new Date().toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'});message('');render();return true;}catch(error){$('saveState').textContent='Échec';message('Échec : '+error.message);return false;}}
$('save').onclick=saveWork;
$('export').onclick=()=>{const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(workspace,null,2)],{type:'application/json'}));a.href=url;a.download='pcb-workspace.json';a.click();URL.revokeObjectURL(url);};
let pendingImport=null;
$('layerDialog').onclose=()=>{pendingImport=null;};
const oldServerMessage='Ancien serveur : enregistre ton travail, puis Ctrl-C dans le Terminal et relance la commande workshop serve.';
async function checkImageImport(){
  const response=await fetch('/api/app');
  if(!response.ok)throw Error(oldServerMessage);
  const capabilities=await response.json();
  if(!capabilities.features?.includes('image_import'))throw Error(oldServerMessage);
}
async function importResponse(response){
  if(response.status===404)throw Error(oldServerMessage);
  let value;try{value=await response.json();}catch{throw Error('Réponse serveur illisible · HTTP '+response.status);}
  if(!response.ok)throw Error(value.error??('Import refusé · HTTP '+response.status));return value;
}
$('layerOpen').onclick=async()=>{
  const identity=pendingImport;$('layerOpen').disabled=true;
  try{$('layerStatus').textContent='Extraction du calque…';
    const value=await importResponse(await fetch('/api/images/'+identity+'/select',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({native_path:JSON.parse($('layerChoice').value)})}));
    if(pendingImport===identity)location.assign(value.url);
  }catch(error){if(pendingImport===identity)$('layerStatus').textContent=error.message;}finally{$('layerOpen').disabled=false;}
};
$('open').onclick=()=>$('openFile').click();
$('openFile').onchange=async()=>{
  const file=$('openFile').files[0];if(!file)return;
  try{
    if(!file.name.toLowerCase().endsWith('.json')){
      if(!/\.(png|xcf)$/i.test(file.name))throw Error('Choisir un PNG, un XCF ou un JSON.');
      if(file.size>256*1024*1024)throw Error('Fichier limité à 256 Mio.');
      await checkImageImport();
      if(dirty&&!await saveWork())return;
      modelBlocking=true;render();message(file.name.toLowerCase().endsWith('.xcf')?'Lecture des calques XCF…':'Ouverture du PNG…');
      const value=await importResponse(await fetch('/api/images/upload?name='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file}));
      if(value.status==='choose_layer'){
        pendingImport=value.id;$('layerChoice').replaceChildren();
        for(const layer of value.layers){const option=document.createElement('option');option.value=JSON.stringify(layer.native_path);option.textContent=layer.name+' · '+layer.size.join(' × ');option.disabled=!!layer.is_group;option.selected=layer.name==='Original'&&!layer.is_group;$('layerChoice').append(option);}
        if(!$('layerChoice').selectedOptions[0]||$('layerChoice').selectedOptions[0].disabled){const first=[...$('layerChoice').options].find(o=>!o.disabled);if(first)first.selected=true;}
        $('layerOpen').disabled=![...$('layerChoice').options].some(o=>!o.disabled);$('layerStatus').textContent=file.name;$('layerDialog').showModal();message('Choisir un calque.');
      }else location.assign(value.url);
      return;
    }
    if(file.size>20000000)throw Error('Fichier trop volumineux.');const value=JSON.parse(await file.text());
    const response=await fetch('/api/workspace/validate'+resultQuery,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
    const check=await response.json();if(!response.ok)throw Error(check.error);
    const id=value.preprocessing?.id;if(id)await loadImage('/api/preprocessing/'+id+'/original-cropped.png'+resultQuery);
    history();const revision=workspace._revision;workspace=value;workspace._revision=revision;scanStale=workspace.scanStale??false;selections.clear();padSelection.clear();pending=null;
    await syncCrop();message('Travail ouvert · '+file.name);render();
  }catch(error){message('Ouverture refusée · '+error.message);}finally{$('openFile').value='';modelBlocking=false;render();}
};
$('fit').onclick=fit;
for(const [id,key] of [['showOriginal','original'],['showCrop','crop'],['showPads','pads'],['showRoutes','routes']])$(id).onchange=()=>{
  history();workspace.layerVisibility??={original:!cropImage,crop:!!cropImage,pads:true,routes:true};workspace.layerVisibility[key]=$(id).checked;render();
};
window.onkeydown=event=>{if(document.querySelector('dialog[open]'))return;if(['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName))return;if(event.key==='Escape'){pending=null;selections.clear();padSelection.clear();toolMode='pan';render();}if(event.key==='Delete'||event.key==='Backspace'){event.preventDefault();$('reject').click();}if((event.metaKey||event.ctrlKey)&&event.key==='z'){event.preventDefault();$(event.shiftKey?'redo':'undo').click();}};
window.onbeforeunload=event=>{if(dirty){event.preventDefault();event.returnValue='';}};
scanStale=workspace.scanStale??false;await syncCrop();new ResizeObserver(render).observe(container);fit();
modelControls=await mountWevisone({onPreview:preview=>{modelPreview=preview;render();},onStatus:message,
  getSettings:kind=>workspace.wevisoneSettings?.[kind],onSettings:(kind,settings)=>{history();workspace.wevisoneSettings??={};workspace.wevisoneSettings[kind]=settings;render();},
  sourceSha:receipt.useful_sha256['original.png'],sourceResult:resultId,getCrop:()=>workspace.preprocessing,hasBoard:()=>!!workspace.preprocessing||!!legacyCrop,isBusy:()=>busy||modelBlocking||solderBlocking,onWorking:value=>{modelBlocking=value;render();},
  onApply:async crop=>{
    await loadImage('/api/preprocessing/'+crop.id+'/original-cropped.png'+resultQuery);
    history();workspace.preprocessing=crop;workspace.layerVisibility={original:false,crop:true,pads:false,routes:false};
    scanStale=true;workspace.scanStale=true;proposed=[];selections.clear();padSelection.clear();
    await syncCrop();render();
  }});
solderControls=await mountSolders({getSettings:()=>workspace.solderModelSettings,getInput:()=>workspace.solderInput,hasCrop:()=>!!workspace.preprocessing||!!legacyCrop,
  isBusy:()=>busy||modelBlocking||!!modelControls?.running(),getCrop:()=>workspace.preprocessing,sourceResult:resultId,sourceSha:receipt.useful_sha256['original.png'],
  getAppliedJob:()=>workspace.solderDetection?.job_id,onWorking:value=>{solderBlocking=value;render();},onStatus:message,
  getDetection:()=>workspace.solderDetection,onView:value=>{activeDomain='solders';solderView=value;padSelection.clear();source=null;target=null;render();},
  onSettings:settings=>{history();workspace.solderModelSettings=settings;message('Paramètres pour la prochaine détection.');render();},
  onInput:input=>{history();workspace.solderInput=input;render();},
  onResult:result=>{
    const next=replaceSolders(workspace,currentCandidates(),result);history();workspace=next;scanStale=true;
    source=null;target=null;direction=null;proposed=[];selections.clear();padSelection.clear();modelPreview=null;$('modelPreview').checked=false;
    workspace.layerVisibility??={original:!cropImage,crop:!!cropImage,pads:true,routes:false};workspace.layerVisibility.pads=true;workspace.layerVisibility.routes=false;$('showPads').checked=true;$('showRoutes').checked=false;
    activeDomain='solders';toolMode='pads';message(solderResultText(next.solderDetection)+' · remplacement effectué.');render();
  }});
render();
for(const id of ['modelPanel','solderPanel','tracePanel','layersPanel']){
  const key='pcb-panel-'+id;const saved=localStorage.getItem(key);$(id).open=saved===null?(id!=='modelPanel'||!workspace.preprocessing):saved==='open';
  $(id).ontoggle=()=>localStorage.setItem(key,$(id).open?'open':'closed');
}

function padName(id){const list=allPads(),index=list.findIndex(p=>p.id===id);return id?.startsWith('PAD-M')?'M'+Number(id.slice(5)):index>=0?String(index+1):id?.startsWith('V-')?'Jonction '+id.slice(2):'Soudure absente';}
function followText(){return source?`Départ ${padName(source)}${target?' → arrivée '+padName(target):' · choisir l’arrivée'}`:'Choisir le départ puis l’arrivée sur la carte.';}
function selectedRoute(){return workspace.traceScan.routes.find(r=>r.id===$('traceRoute').value);}
function renderTracePanel(){
  const scan=workspace.traceScan,locked=busy||modelBlocking||solderBlocking,visible=visibleRoutes(scan).length;
  $('traceStatus').textContent=busy?tracePhase:traceNotice?traceNotice:scanStale&&scan.routes.length?'Soudures ou préparation modifiées · recalcul nécessaire':scan.routes.length?`${visible} chemins visibles · ${scan.complete?'calcul terminé':'résultat partiel'} · ${scan.issues.length} diagnostics`:`Prêt · ${allPads().length} soudures · ${cropImage?'Original-croppé':'masque CPU initial'}`;
  $('traceRunning').hidden=!busy;$('stop').disabled=!busy;
  for(const[id,mode]of [['tracePan','pan'],['traceSelect','stroke'],['traceLine','line'],['traceFollow','follow']]){$(id).disabled=locked;$(id).setAttribute('aria-pressed',String((mode==='pan'||activeDomain==='traces')&&toolMode===mode));}
  $('traceSettings').disabled=locked;$('traceSelectionActions').hidden=!selections.size;
  $('finish').hidden=toolMode!=='line'||!pending;$('finish').disabled=locked;
  $('keep').disabled=locked||!proposed.length;$('resetFollow').disabled=locked;
  const reviewKey=JSON.stringify([scan.routes.map(r=>[r.id,scan.reviews?.[r.id]?.status]),scan.pinRows?.enabled,$('traceFilter').value]);
  if(reviewKey!==lastReviewKey){lastReviewKey=reviewKey;const selected=$('traceRoute').value;$('traceRoute').replaceChildren();
    for(const r of filteredTraces(scan,$('traceFilter').value)){const option=document.createElement('option');option.value=r.id;option.textContent=`${padName(r.from)} → ${padName(r.to)}${r.gaps.length?' · microcoupure':r.broad?' · surface large':''}`;option.title=r.id;option.selected=r.id===selected;$('traceRoute').append(option);}
  }
  const route=selectedRoute();$('traceReviewStatus').textContent=$('traceRoute').options.length+' chemin(s) dans cette liste';
  for(const id of ['traceFilter','traceRoute','traceLocate','traceRestore','traceResume'])$(id).disabled=locked||scanStale||(id!=='traceFilter'&&!route);
  $('traceResume').disabled||=!allPads().some(p=>p.id===route?.from)||!allPads().some(p=>p.id===route?.to);
}
function locateTrace(route){
  if(!route)return;activeDomain='traces';toolMode='stroke';padSelection.clear();selections.clear();for(const span of logicalSegments(route.points))selections.set(strokeKey({routeId:route.id,...span}),{routeId:route.id,...span});
  const xs=route.points.map(p=>p[0]),ys=route.points.map(p=>p[1]),x=Math.min(...xs),y=Math.min(...ys),w=Math.max(...xs)-x,h=Math.max(...ys)-y;
  zoom=Math.min(3,container.clientWidth/(w+100),container.clientHeight/(h+100));offset=[container.clientWidth/2-(x+w/2)*zoom,container.clientHeight/2-(y+h/2)*zoom];render();
}
$('tracePan').onclick=()=>setTool('pan');$('traceSelect').onclick=()=>setTool('stroke');$('traceLine').onclick=()=>setTool('line');
$('traceFollow').onclick=()=>{source=null;target=null;direction=null;proposed=[];$('directions').replaceChildren();setTool('follow');$('followInfo').textContent=followText();message('Choisir le départ puis l’arrivée sur la carte.');};
$('traceFilter').onchange=()=>render();$('traceRoute').onchange=()=>render();$('traceLocate').onclick=()=>locateTrace(selectedRoute());
$('traceRestore').onclick=()=>{const route=selectedRoute();if(!route)return;history();workspace.traceScan.reviews[route.id]={status:'accepted'};message('Chemin rétabli comme exception validée.');render();};
$('traceResume').onclick=()=>{const route=selectedRoute();if(!route)return;locateTrace(route);source=route.from;target=route.to;direction=null;proposed=[];setTool('follow');$('followInfo').textContent=followText();request('directions');};
mountTraceSettings({getSettings:()=>workspace.traceSettings,onSettings:settings=>{history();workspace.traceSettings=settings;if(workspace.traceScan.pinRows)workspace.traceScan.pinRows.enabled=settings.protect_pin_rows;render();},onStatus:message});
render();

if($('status').textContent==='Chargement…')message('Prêt.');
