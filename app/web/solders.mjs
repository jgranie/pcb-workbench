/** Match Python's tile boundaries, including ties rounded to even. */
export function solderSectionCore(width,height,section){
  if(section==null)return null;
  if(!Number.isInteger(section)||section<0||section>=24)throw Error('Section invalide.');
  const round=value=>{const floor=Math.floor(value);return value-floor===.5?floor+floor%2:Math.round(value);};
  const row=Math.floor(section/4),column=section%4;
  return [round(column*width/4),round(row*height/6),round((column+1)*width/4),round((row+1)*height/6)];
}
export function inSolderCore(point,core){
  if(!core)return true;
  const x=point.x??(point.coords[0]+point.coords[2])/2,y=point.y??(point.coords[1]+point.coords[3])/2;
  return core[0]<=x&&x<core[2]&&core[1]<=y&&y<core[3];
}
export function solderResultText(detection){
  if(detection.section==null)return `${detection.candidates.length} points sur la carte`;
  const core=detection.tiles?.[0]?.core;
  const local=detection.candidates.filter(p=>inSolderCore(p,core)).length;
  const outside=detection.candidates.length-local;
  const halo=detection.application?.ignored_context??outside;
  return `Section ${detection.section+1} : ${local} point${local>1?'s':''}`+(detection.application||detection.retained_outside_section!=null?` · ${outside} ailleurs`:(halo?` · ${halo} hors section ignorés`:''));
}

/** Replace automatic proposals while preserving explicit human corrections. */
export function replaceSolders(workspace, previous, detection){
  const next=structuredClone(workspace),reviews=next.detectionReviews??{};
  const core=detection.section!=null?detection.tiles?.[0]?.core:null;
  if(detection.section!=null&&(!Array.isArray(core)||core.length!==4||!core.every(Number.isFinite)||core[0]>=core[2]||core[1]>=core[3]))throw Error('Limites de section absentes ou invalides ; aucun résultat appliqué.');
  const inCore=p=>!core||(core[0]<=(p.coords[0]+p.coords[2])/2&&(p.coords[0]+p.coords[2])/2<core[2]&&core[1]<=(p.coords[1]+p.coords[3])/2&&(p.coords[1]+p.coords[3])/2<core[3]);
  const untouched=previous.filter(p=>!inCore(p));
  const protectedPads=previous.filter(p=>inCore(p)).filter(p=>Object.keys(reviews[p.id]??{}).length);
  const manual=next.objects.filter(p=>p.type==='pad');
  const center=p=>[(p.coords[0]+p.coords[2])/2,(p.coords[1]+p.coords[3])/2];
  const near=(p,q,r)=>Math.hypot(p[0]-q[0],p[1]-q[1])<=r;
  const fresh=detection.candidates.filter(inCore).filter(p=>{
    const c=center(p);
    return !manual.some(m=>near(c,[m.x,m.y],8)||near(c,[reviews[m.id]?.x??m.x,reviews[m.id]?.y??m.y],8))&&!protectedPads.some(old=>{
      const original=center(old),review=reviews[old.id],r=Math.max(4,Math.min(10,(old.coords[2]-old.coords[0])/3,(old.coords[3]-old.coords[1])/3));
      return old.id===p.id||near(c,original,r)||near(c,[review.x??original[0],review.y??original[1]],r);
    });
  });
  const limit=Math.max(0,3000-protectedPads.length-untouched.length);
  next.solderDetection={...detection,candidates:[...fresh.slice(0,limit),...untouched,...protectedPads],retained_outside_section:untouched.length,protected_count:protectedPads.length,replacement_truncated:fresh.length>limit};
  next.solderDetection.application={replaced_automatic:previous.length-untouched.length-protectedPads.length,received_in_section:detection.candidates.filter(inCore).length,ignored_context:detection.candidates.filter(p=>!inCore(p)).length,applied_automatic:Math.min(fresh.length,limit)};
  const ids=new Set([...next.solderDetection.candidates,...manual].map(p=>p.id));
  next.detectionReviews=Object.fromEntries(Object.entries(reviews).filter(([id])=>ids.has(id)));
  next.scanStale=true;
  return next;
}

export async function mountSolders({getSettings,onSettings,getInput,onInput,hasCrop,isBusy,onResult,onWorking,getCrop,sourceResult,sourceSha,getAppliedJob,getDetection,onView,onStatus}){
  const $=id=>document.getElementById(id);let defaults=null,models=[],job=null,timer=null,submitting=false,available=false;
  async function api(path,body){const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error??'Erreur soudures.');return v;}
  const fields={
    model_size:['Taille du modèle','select'],query:['Description recherchée','text'],
    vision_max_pixels:['Pixels vision maximum','number',16384,524288,1],max_new_tokens:['Jetons par section','number',1,2048,1],
    temperature:['Température','number',0,2,.01],top_p:['Top P','number',.01,1,.01],top_k:['Top K','number',0,100,1],repetition_penalty:['Pénalité de répétition','number',.5,2,.01]
  };
  const running=()=>submitting||['running','cancelling'].includes(job?.status);
  function fill(values){for(const [key,value] of Object.entries(values))$('solder-param-'+key).value=value;}
  function refresh(){
    const active=running();$('solderStart').disabled=!available||active||isBusy();$('solderSettings').disabled=!defaults||active||isBusy();$('solderSource').disabled=active||isBusy();$('solderSection').disabled=active||isBusy();
    $('solderSource').options[0].disabled=!hasCrop();$('solderSource').value=getInput()??(hasCrop()?'cropped':'original');
    $('solderSectionOnly').disabled=active||isBusy()||$('solderSection').value==='';
    $('solderCancel').hidden=!['running','cancelling'].includes(job?.status);$('solderCancel').disabled=!['running'].includes(job?.status);$('solderLoad').hidden=job?.status!=='ready'||getAppliedJob()===job.id;$('solderLoad').disabled=isBusy();$('solderCancel').parentElement.hidden=$('solderCancel').hidden&&$('solderLoad').hidden;
    if(submitting){$('solderStatus').textContent='Préparation du calcul…';return;}
    if(job){let text=job.status==='ready'?(getAppliedJob()===job.id?solderResultText(getDetection()):`${job.candidates} propositions brutes · ${job.completed_tiles}/${job.total_tiles}`):job.status==='failed'?'Échec · '+job.message:job.status==='cancelled'?'Arrêté':job.phase;
      if(getAppliedJob()===job.id&&job.input==='cropped'&&job.source_crop!==(getCrop()?.id??null))text='Préparation modifiée · relancer';
      $('solderStatus').textContent=(job.simulation?'TEST · ':'')+'WeVisOne '+(job.model_size??'2B')+' · '+text;}else if(defaults)$('solderStatus').textContent='WeVisOne '+(getSettings()?.model_size??defaults.model_size)+' · Prêt';
  }
  async function load(){
    if(job.source_sha256!==sourceSha)throw Error('Résultat d’une autre image.');
    if(job.input==='cropped'&&job.source_crop!==(getCrop()?.id??null))throw Error('Résultat d’une autre préparation ; restaurer le crop correspondant.');
    const result=await api('/api/solders/jobs/'+job.id+'/detection.json');onResult(result);refresh();
  }
  async function poll(autoApply=false){
    try{job=await api('/api/solders/jobs/'+job.id);refresh();
      if(['running','cancelling'].includes(job.status))timer=setTimeout(()=>poll(autoApply),1200);
      else{onWorking(false);if(job.status==='ready'&&autoApply)await load();else if(job.status==='failed')onStatus(job.message);refresh();}
    }catch(error){onWorking(false);onStatus(error.message);refresh();}
  }
  $('solderInfoToggle').onclick=event=>{event.preventDefault();event.stopPropagation();$('solderHelp').hidden=!$('solderHelp').hidden;$('solderInfoToggle').setAttribute('aria-expanded',String(!$('solderHelp').hidden));};
  $('solderSource').onchange=()=>onInput($('solderSource').value);
  const updateView=()=>{onView({section:$('solderSection').value===''?null:Number($('solderSection').value),only:$('solderSectionOnly').checked});refresh();};
  $('solderSection').onchange=()=>{$('solderSectionOnly').checked=$('solderSection').value!=='';updateView();};
  $('solderSectionOnly').onchange=updateView;
  $('solderSettings').onclick=()=>{
    $('solderSettingsMain').replaceChildren();$('solderSettingsAdvanced').replaceChildren();$('solderSettingsAdvanced').parentElement.open=false;$('solderSettingsStatus').textContent='';
    for(const [key,[name,type,min,max,step]] of Object.entries(fields)){
      const label=document.createElement('label'),input=document.createElement(type==='select'?'select':'input');input.id='solder-param-'+key;input.setAttribute('aria-label',name);label.textContent=name;input.required=true;
      if(type==='select')for(const model of models){const option=document.createElement('option');option.value=model.size;option.textContent=model.size+(model.available?'':' · indisponible');option.disabled=!model.available;input.append(option);}
      else{input.type=type;if(type==='number'){input.min=min;input.max=max;input.step=step;}else input.maxLength=1000;}
      label.append(input);(['model_size','query'].includes(key)?$('solderSettingsMain'):$('solderSettingsAdvanced')).append(label);
    }
    fill({...defaults,...getSettings()});$('solderSettingsDialog').showModal();
  };
  $('solderSettingsCancel').onclick=()=>$('solderSettingsDialog').close();$('solderSettingsReset').onclick=()=>{fill(defaults);$('solderSettingsStatus').textContent='';};
  $('solderSettingsForm').onsubmit=async event=>{
    event.preventDefault();if(!$('solderSettingsForm').reportValidity())return;
    const settings=Object.fromEntries(Object.keys(fields).map(key=>[key,['model_size','query'].includes(key)?$('solder-param-'+key).value:Number($('solder-param-'+key).value)]));
    $('solderSettingsUse').disabled=true;
    try{onSettings(await api('/api/solders/parameters/validate',{settings}));$('solderSettingsDialog').close();}
    catch(error){$('solderSettingsStatus').textContent=error.message;}finally{$('solderSettingsUse').disabled=false;}
  };
  $('solderStart').onclick=async()=>{
    if(running()||isBusy())return;
    submitting=true;onWorking(true);refresh();
    try{job=await api('/api/solders/jobs',{input:$('solderSource').value,settings:{...defaults,...getSettings()},source_result:sourceResult,source_crop:getCrop()?.id??null,section:$('solderSection').value===''?null:Number($('solderSection').value)});timer=setTimeout(()=>poll(true),500);}
    catch(error){onWorking(false);onStatus('Détection refusée · '+error.message);}finally{submitting=false;refresh();}
  };
  $('solderCancel').onclick=async()=>{try{job=await api('/api/solders/jobs/'+job.id+'/cancel',{});refresh();}catch(error){onStatus(error.message);}};
  $('solderLoad').onclick=async()=>{try{await load();}catch(error){onStatus(error.message);}};
  try{const cap=await api('/api/solders');if(!cap.defaults?.model_size||!Array.isArray(cap.models))throw Error('Ancien serveur');defaults=cap.defaults;models=cap.models??[];available=cap.available&&models.some(m=>m.available);job=(cap.jobs??[]).filter(j=>j.source_sha256===sourceSha&&j.source_result===sourceResult).at(-1)??null;if(job)$('solderSection').value=job.section??'';
    if(running()){onWorking(true);timer=setTimeout(()=>poll(true),500);}
  }catch{$('solderStatus').textContent='Redémarrer le serveur pour activer WeVisOne.';}
  $('solderSectionOnly').checked=$('solderSection').value!=='';updateView();return {refresh,running};
}
