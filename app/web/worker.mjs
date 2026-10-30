import {createField,snapPoint,radialDirections,searchRoutes} from './core/tracker-core.mjs';
import {scanBoard,routeIdentity} from './core/auto-scan-core.mjs';
import {protectPinRows} from './core/pin-row-core.mjs';
import {traceSettings,traceAnchors} from './traces.mjs';
let field,candidates;
const read=async(url,binary=false)=>{const response=await fetch(url);if(!response.ok)throw Error('Source absente : '+url);return binary?response.arrayBuffer():response.json();};
self.onmessage=async({data})=>{
  try{
    const settings=traceSettings(data.settings);
    if(data.type==='init'){
      const query=data.result?'?result='+encodeURIComponent(data.result):'';
      const meta=await read('/data/image.json'+query);
      candidates=(await read('/data/candidates.json'+query)).candidates;
      const alpha=data.alpha??new Uint8Array(await read('/data/alpha.bin'+query,true));
      if(!alpha.some(v=>v>=128))throw Error('Masque vide : appliquer une préparation avant de détecter les pistes.');
      field=createField({...meta,alpha,photo:new Uint8Array(await read('/data/photo.bin'+query,true)),detectGaps:settings.allow_photo_gaps});
      self.postMessage({type:'ready'});return;
    }
    if(!field)throw Error('Masque non préparé.');
    const anchors=traceAnchors(data.candidates??candidates,data.reviews,data.manualPads,field.width,field.height);
    const snap=a=>{if(!a)return null;const p=snapPoint(field,a,{box:a.box});return p?{...a,...p}:null;};
    if(data.type==='scan'){
      const progress=p=>{const label=p.stage==='strict'?'Pistes strictes':p.stage==='photo'?'Microcoupures':p.stage==='directions'?'Directions':p.stage==='strict_complete'?'Passe stricte terminée':'Passe photo terminée';self.postMessage({type:'progress',message:label+(p.total?` · ${p.done}/${p.total}`:p.routes?` · ${p.routes.length} chemins`:p.visited?` · ${p.visited.toLocaleString('fr-FR')} pixels`:'')});};
      let scan=await scanBoard(field,anchors,{allowGaps:settings.allow_photo_gaps,maxVisited:settings.max_visited,timeLimitMs:settings.time_limit_ms,progress});
      // Always retain the reversible row evidence, including when the filter is off.
      scan=protectPinRows(scan,anchors,{enabled:settings.protect_pin_rows});
      self.postMessage({type:'scan',scan:{schema_version:1,...scan,reviews:{},input:data.input,settings,
        method:'multi_source_dijkstra_adjacent_fronts',input_anchors:anchors.length,electrical_validation:false}});return;
    }
    const seed=snap(anchors.find(a=>a.id===data.source));
    if(!seed)throw Error('Départ sans pixel dans le masque ; corriger la position ou tracer une ligne.');
    const radial=radialDirections(field,seed,{allowGaps:settings.allow_photo_gaps});
    if(data.type==='directions'){self.postMessage({type:'directions',radial});return;}
    const targets=anchors.filter(a=>a.id===data.target).map(snap).filter(Boolean);
    if(!targets.length)throw Error('Arrivée sans pixel dans le masque.');
    const result=searchRoutes(field,seed,targets,{allowGaps:settings.allow_photo_gaps,initialDirection:data.direction});
    result.routes=result.routes.map(r=>{const route={...r,from:seed.id,origin:'semi_manual'};route.id=routeIdentity(route);return route;});
    self.postMessage({type:'follow',result});
  }catch(error){self.postMessage({type:'error',message:error.message});}
};
