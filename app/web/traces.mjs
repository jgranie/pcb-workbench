/** Trace settings and composition. The geometric engines stay shared with the previous workshop. */
export const traceDefaults=()=>({allow_photo_gaps:false,protect_pin_rows:true,max_visited:3000000,time_limit_ms:10000});
export function traceSettings(value={}){
  const defaults=traceDefaults();if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).some(k=>!(k in defaults)))throw Error('Paramètres pistes inconnus.');
  const next={...defaults,...value};
  for(const key of ['allow_photo_gaps','protect_pin_rows'])if(typeof next[key]!=='boolean')throw Error('Paramètre pistes invalide : '+key);
  for(const [key,low,high]of [['max_visited',10000,6000000],['time_limit_ms',1000,30000]])if(!Number.isInteger(next[key])||next[key]<low||next[key]>high)throw Error('Paramètre pistes invalide : '+key);
  return next;
}
export function traceAnchors(candidates,reviews={},manual=[],width,height){
  const raw=[...candidates,...manual.filter(p=>p.type==='pad').map(p=>({id:p.id,coords:[p.x-12,p.y-12,p.x+12,p.y+12]}))];
  return raw.filter(p=>reviews[p.id]?.status!=='rejected').map(p=>{
    const r=reviews[p.id]??{},[a,b,c,d]=p.coords,cx=(a+c)/2,cy=(b+d)/2,x=r.x??cx,y=r.y??cy,dx=x-cx,dy=y-cy;
    return{id:p.id,x,y,box:[Math.max(0,a+dx),Math.max(0,b+dy),Math.min(width,c+dx),Math.min(height,d+dy)]};
  }).filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0&&p.x<width&&p.y<height);
}
export function mergeTraceScan(old,scan){
  const routes=new Map(scan.routes.map(r=>[r.id,r]));
  for(const r of old.routes??[])if(r.origin!=='automatic'||['accepted','rejected'].includes(old.reviews?.[r.id]?.status))routes.set(r.id,r);
  const ids=new Set(routes.keys()),reviews=Object.fromEntries(Object.entries(old.reviews??{}).filter(([id])=>ids.has(id)));
  return{...scan,routes:[...routes.values()],reviews,junctions:old.junctions??[],nextVirtualId:old.nextVirtualId??1};
}
export function filteredTraces(scan,filter='all'){
  return (scan.routes??[]).filter(r=>{
    const review=scan.reviews?.[r.id]?.status,blocked=scan.pinRows?.enabled&&r.origin==='automatic'&&scan.pinRows.blocked[r.id]&&review!=='accepted';
    if(filter==='rejected')return review==='rejected';
    if(filter==='rows')return blocked&&review!=='rejected';
    if(review==='rejected'||blocked)return false;
    if(filter==='photo')return !!r.gaps?.length;
    if(filter==='broad')return !!r.broad;
    if(filter==='pending')return review!=='accepted';
    return true;
  });
}
export function mountTraceSettings({getSettings,onSettings,onStatus}){
  const $=id=>document.getElementById(id);
  const fill=settings=>{for(const[k,v]of Object.entries(settings)){const input=$('trace-param-'+k);if(typeof v==='boolean')input.checked=v;else input.value=v;}};
  $('traceSettings').onclick=()=>{fill(traceSettings(getSettings()));$('traceSettingsStatus').textContent='';$('traceSettingsDialog').showModal();};
  $('traceSettingsCancel').onclick=()=>$('traceSettingsDialog').close();
  $('traceSettingsReset').onclick=()=>fill(traceDefaults());
  $('traceSettingsForm').onsubmit=event=>{event.preventDefault();if(!$('traceSettingsForm').reportValidity())return;
    try{const values={};for(const[k,v]of Object.entries(traceDefaults())){const input=$('trace-param-'+k);values[k]=typeof v==='boolean'?input.checked:Number(input.value);}
      onSettings(traceSettings(values));$('traceSettingsDialog').close();onStatus('Paramètres pour le prochain calcul de pistes.');
    }catch(error){$('traceSettingsStatus').textContent=error.message;}
  };
  $('traceInfoToggle').onclick=event=>{event.preventDefault();event.stopPropagation();const open=$('traceHelp').hidden;$('traceHelp').hidden=!open;$('traceInfoToggle').setAttribute('aria-expanded',String(open));};
}
