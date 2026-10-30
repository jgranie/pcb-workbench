/** Model inference is explicit. Apply composes a crop only; never detects. */
export async function mountWevisone({onPreview,onStatus,onApply,getCrop,sourceResult,sourceSha,hasBoard,isBusy,onWorking,getSettings,onSettings}){
  const $=id=>document.getElementById(id);
  let job=null,available=false,timer=null,preview=null,working=false,parameterDefaults=null,editingKind=null,modelChoices=[];
  const resultQuery=sourceResult?'?result='+encodeURIComponent(sourceResult):'';
  async function api(path,body){
    const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw Error(result.error??'Erreur WeVisOne.');return result;
  }
  async function refreshSession(){
    try{const session=await api('/api/wevisone/session');
      $('modelSession').textContent=session.running?'WeVisOne '+session.model_size+(session.loaded?' · en mémoire':' · chargement à la demande'):'WeVisOne · non chargé';
      $('modelRelease').disabled=!session.running;
      $('modelRelease').title=session.reason??'Libérer la mémoire du modèle';
    }catch{$('modelSession').textContent='Session indisponible';}
  }
  $('modelRelease').onclick=async()=>{try{await api('/api/wevisone/session/release',{});await refreshSession();}catch(error){onStatus(error.message);}};
  await refreshSession();
  setInterval(refreshSession,2000);
  function render(){
    const running=['running','cancelling','deriving'].includes(job?.status),ready=['ready','derived'].includes(job?.status),applied=getCrop()?.job===job?.id&&!!job;
    $('epoxyStart').disabled=!available||running||working||isBusy()||!hasBoard();
    $('epoxySection').disabled=running||working;
    $('boardSettings').disabled=!parameterDefaults||working;
    $('epoxySettings').disabled=!parameterDefaults||working;
    $('modelStart').disabled=!available||running||working||isBusy();
    $('modelCancel').disabled=!['running','deriving'].includes(job?.status);
    $('modelPreview').disabled=!ready||working;
    $('modelApply').disabled=!ready||applied||running||working||isBusy();
    let text=job?.status==='failed'?'Échec · '+job.message:running?job.phase:ready?((job.kind??'board')==='epoxy'?'Époxy proposé':'Contour proposé'):'Prêt';
    if(!job&&hasBoard())text='Préparation appliquée';
    if(job?.status==='cancelled'||job?.status==='interrupted')text='Arrêté';
    if(applied)text=(job.kind==='epoxy'?'Époxy':'Contour')+' appliqué';
    if(job)text=(job.model_size??job.provenance?.model_size??'2B')+' · '+text;
    if(job?.simulation)text='TEST · '+text;
    $('modelStatus').textContent=working?'Application…':text;
  }
  function stopPolling(){if(timer)clearTimeout(timer);timer=null;}
  async function refresh(){try{job=await api('/api/wevisone/jobs/'+job.id);render();if(['running','cancelling','deriving'].includes(job.status))timer=setTimeout(refresh,1000);else stopPolling();}catch(error){stopPolling();$('modelStatus').textContent=error.message;}}
  function resetPreview(){preview=null;$('modelPreview').checked=false;onPreview(null);}
  async function start(kind){
    if(isBusy())return;
    try{working=true;onWorking(true);render();resetPreview();stopPolling();job=await api('/api/wevisone/jobs',{kind,source_result:sourceResult,source_crop:getCrop()?.id??null,settings:getSettings(kind)??parameterDefaults?.[kind],section:kind==='epoxy'&&$('epoxySection').value!==''?Number($('epoxySection').value):null});timer=setTimeout(refresh,400);}
    catch(error){$('modelStatus').textContent=error.message;onStatus(error.message);}finally{working=false;onWorking(false);render();}
  }
  const fields={
    model_size:['Taille du modèle','select'],
    query:['Description recherchée','text'],mask_threshold:['Seuil du masque (1–254)','number',1,254,1],
    lab_a_threshold:['Seuil couleur Lab a* (vide = automatique)','number',0,255,1],
    vision_max_pixels:['Pixels vision maximum','number',16384,524288,1],max_new_tokens:['Jetons maximum','number',1,512,1],
    temperature:['Température','number',0,2,.01],top_p:['Top P','number',.01,1,.01],top_k:['Top K','number',0,100,1],
    repetition_penalty:['Pénalité de répétition','number',.5,2,.01],bilateral_diameter:['Diamètre bilatéral (impair)','number',3,15,2],
    bilateral_sigma_color:['Lissage couleur','number',1,50,.1],bilateral_sigma_space:['Lissage spatial','number',1,20,.1]
  };
  function fillSettings(values){for(const [key,value] of Object.entries(values)){const input=$('param-'+key);if(input)input.value=value??'';}}
  function editSettings(kind){
    if(!parameterDefaults)return;editingKind=kind;
    $('settingsTitle').textContent=kind==='board'?'Contour du PCB':'Retrait de l’époxy';
    $('settingsMain').replaceChildren();$('settingsAdvanced').replaceChildren();$('settingsAdvanced').parentElement.open=false;$('settingsStatus').textContent='';
    for(const key of Object.keys(parameterDefaults[kind])){
      const [name,type,min,max,step]=fields[key],label=document.createElement('label'),input=document.createElement(type==='select'?'select':'input');
      label.textContent=name;input.id='param-'+key;input.name=key;if(type!=='select')input.type=type;
      if(type==='select')for(const model of modelChoices){const option=document.createElement('option');option.value=model.size;option.textContent=model.size+(model.available?'':' · indisponible');option.disabled=!model.available;input.append(option);}
      input.required=key!=='lab_a_threshold';if(type==='number'){input.min=min;input.max=max;input.step=step;}else input.maxLength=200;
      if(key==='mask_threshold')input.title=kind==='board'?'Augmenter réduit la carte conservée.':'Augmenter réduit le retrait proposé par le modèle.';
      label.append(input);(['model_size','query','mask_threshold','lab_a_threshold'].includes(key)?$('settingsMain'):$('settingsAdvanced')).append(label);
    }
    fillSettings({...parameterDefaults[kind],...getSettings(kind)});$('settingsDialog').showModal();
  }
  $('boardSettings').onclick=()=>editSettings('board');$('epoxySettings').onclick=()=>editSettings('epoxy');
  $('settingsCancel').onclick=()=>$('settingsDialog').close();
  $('settingsReset').onclick=()=>{fillSettings(parameterDefaults[editingKind]);$('settingsStatus').textContent='';};
  $('settingsForm').onsubmit=async event=>{
    event.preventDefault();if(!$('settingsForm').reportValidity())return;
    const settings={};for(const key of Object.keys(parameterDefaults[editingKind])){const value=$('param-'+key).value;settings[key]=['query','model_size'].includes(key)?value:key==='lab_a_threshold'&&value===''?null:Number(value);}
    $('settingsUse').disabled=true;
    try{const normalized=await api('/api/wevisone/parameters/validate',{kind:editingKind,settings});onSettings(editingKind,normalized);$('settingsDialog').close();onStatus('Paramètres mémorisés pour la prochaine proposition.');}
    catch(error){$('settingsStatus').textContent=error.message;}finally{$('settingsUse').disabled=false;}
  };
  $('modelStart').onclick=()=>start('board');$('epoxyStart').onclick=()=>start('epoxy');
  $('modelInfoToggle').onclick=event=>{event.preventDefault();event.stopPropagation();const open=$('modelHelp').hidden;$('modelHelp').hidden=!open;$('modelInfoToggle').setAttribute('aria-expanded',String(open));};
  $('modelCancel').onclick=async()=>{try{job=await api('/api/wevisone/jobs/'+job.id+'/cancel',{});render();}catch(error){onStatus(error.message);}};
  $('modelPreview').onchange=async()=>{
    if(!$('modelPreview').checked){onPreview(null);return;}
    try{
      if(!preview){const image=await new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error('Masque indisponible.'));im.src='/api/wevisone/jobs/'+job.id+'/alpha.png';});
        preview=document.createElement('canvas');preview.width=image.width;preview.height=image.height;const context=preview.getContext('2d');context.drawImage(image,0,0);const pixels=context.getImageData(0,0,image.width,image.height);
        for(let i=0;i<pixels.data.length;i+=4){const excluded=pixels.data[i]<128;pixels.data[i]=255;pixels.data[i+1]=55;pixels.data[i+2]=75;pixels.data[i+3]=excluded?170:0;}context.putImageData(pixels,0,0);}
      onPreview(preview);
    }catch(error){$('modelPreview').checked=false;onStatus(error.message);}
  };
  $('modelApply').onclick=async()=>{
    if(isBusy())return;
    try{working=true;onWorking(true);render();const crop=await api('/api/wevisone/jobs/'+job.id+'/apply',{source_result:sourceResult,previous:getCrop()?.id??null});await onApply(crop);resetPreview();onStatus('Crop appliqué · aucune détection lancée.');}
    catch(error){onStatus('Échec · '+error.message);}finally{working=false;onWorking(false);render();}
  };
  try{const capability=await api('/api/wevisone');modelChoices=capability.models??[];parameterDefaults=capability.parameter_defaults??null;available=capability.available&&!!parameterDefaults&&!!modelChoices.length;
    $('modelInfo').textContent=(capability.simulation?'TEST · aucune inférence réelle. ':capability.model+'. ')+capability.message+'. '+capability.limits;
    if(!parameterDefaults)$('modelInfo').textContent='Redémarrer le serveur pour charger les paramètres.';
    job=capability.jobs.filter(j=>j.kind!=='solders'&&j.source_sha256===sourceSha).at(-1)??null;render();if(['running','cancelling','deriving'].includes(job?.status))timer=setTimeout(refresh,500);
  }catch(error){$('modelInfo').textContent='Relancer le serveur pour charger cette version.';render();}
  return {refresh:render,running:()=>['running','cancelling','deriving'].includes(job?.status)};
}
