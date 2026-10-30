import{MinHeap,snapPoint,radialDirections}from'./tracker-core.mjs';
const pause=()=>new Promise(resolve=>setTimeout(resolve,0));
const difference=(a,b)=>Math.abs(Math.atan2(Math.sin(a-b),Math.cos(a-b)));
const pairKey=(a,b)=>[a,b].sort().join('|');
export function routeIdentity(route){
  let hash=2166136261;
  for(const [x,y]of route.points)for(const v of [Math.round(x*2),Math.round(y*2)])hash=Math.imul(hash^v,16777619)>>>0;
  return pairKey(route.from,route.to)+'|'+hash.toString(16);
}

function makeRoute(field,pixels,a,b,allowGaps){
  const points=[],boxes=[a.box,b.box].filter(Boolean),gaps=new Set();let broad=false;
  const distance=allowGaps?field.candidateDistance:field.sourceDistance;
  for(let i=0;i<pixels.length;i++){
    const p=pixels[i],x=p%field.width,y=Math.floor(p/field.width);
    if(!field.source[p]){const gap=field.gapAt.get(p);if(!gap)throw Error('Unproven gap in scan route.');gaps.add(gap);}
    if(distance[p]>14&&!boxes.some(box=>x>=box[0]&&x<box[2]&&y>=box[1]&&y<box[3]))broad=true;
    if(!i||i+1===pixels.length||p-pixels[i-1]!==pixels[i+1]-p)points.push([x+.5,y+.5]);
  }
  const route={from:a.id,to:b.id,points,length:pixels.length-1,gaps:[...gaps],broad,status:gaps.size?'photo_gap_hypothesis':broad?'broad_surface_route':'source_route',origin:'automatic'};
  route.id=routeIdentity(route);return route;
}

/** Neighbouring anchor fronts meet on actual traversable pixels. No spanning-tree pruning. */
async function fronts(field,anchors,{allowGaps,progress,cancelled,maxVisited,timeLimitMs,maxRoutes,maxPoints}){
  const mask=allowGaps?field.candidate:field.source,distance=allowGaps?field.candidateDistance:field.sourceDistance,labels=allowGaps?field.candidateLabels.labels:field.sourceLabels.labels;
  const n=mask.length,w=field.width,costs=new Float64Array(n),owner=new Int32Array(n),parent=new Int32Array(n),settled=new Uint8Array(n);
  costs.fill(Infinity);parent.fill(-1);const heap=new MinHeap(),componentCounts=new Map(),duplicates=[];
  for(const a of anchors)componentCounts.set(labels[a.pixel],(componentCounts.get(labels[a.pixel])??0)+1);
  for(let i=0;i<anchors.length;i++){
    const a=anchors[i];if(componentCounts.get(labels[a.pixel])<2)continue;
    if(owner[a.pixel]){duplicates.push(a.id);continue;}
    owner[a.pixel]=i+1;costs[a.pixel]=0;heap.push(a.pixel,0);
  }
  const started=performance.now();let visited=0,stopped=null;
  while(heap.length){
    const[p,cost]=heap.pop();if(settled[p]||cost!==costs[p])continue;
    if(visited>=maxVisited){stopped='budget';break;}
    settled[p]=1;visited++;
    if(visited%32768===0){
      progress({visited,stage:allowGaps?'photo':'strict'});await pause();
      if(cancelled()){stopped='cancelled';break;}
      if(performance.now()-started>timeLimitMs){stopped='budget';break;}
    }
    const x=p%w;
    for(const q of[x?p-1:-1,x+1<w?p+1:-1,p>=w?p-w:-1,p+w<n?p+w:-1]){
      if(q<0||!mask[q]||settled[q])continue;
      const next=cost+1+2/(distance[p]+.5)+2/(distance[q]+.5)+(!field.source[q]?35:0);
      if(next<costs[q]){costs[q]=next;parent[q]=p;owner[q]=owner[p];heap.push(q,next);}
    }
  }
  if(cancelled())stopped='cancelled';
  const borders=new Map();
  for(let p=0;p<n;p++){
    if(!settled[p])continue;
    for(const q of[p%w+1<w?p+1:-1,p+w<n?p+w:-1]){
      if(q<0||!settled[q]||owner[p]===owner[q])continue;
      const a=owner[p]-1,b=owner[q]-1;if(a<0||b<0)continue;
      const key=a<b?a+':'+b:b+':'+a,cost=costs[p]+costs[q]+1;
      if(!borders.has(key)||cost<borders.get(key).cost)borders.set(key,{p,q,a,b,cost});
    }
  }
  const routes=[];let points=0,truncated=false;
  function climb(p,root){const path=[p];while(p!==root){p=parent[p];if(p<0||path.length>n)throw Error('Invalid scan predecessor chain.');path.push(p);}return path;}
  for(const edge of [...borders.values()].sort((a,b)=>a.cost-b.cost)){
    const a=anchors[edge.a],b=anchors[edge.b];
    const pixels=[...climb(edge.p,a.pixel).reverse(),...climb(edge.q,b.pixel)];
    if(allowGaps&&!pixels.some(p=>!field.source[p]))continue;
    const route=makeRoute(field,pixels,a,b,allowGaps);
    if(routes.length>=maxRoutes||points+route.points.length>maxPoints){truncated=true;break;}
    routes.push(route);points+=route.points.length;
  }
  return{routes,visited,stopped,truncated,duplicates,elapsedMs:performance.now()-started};
}

function routeHeading(points,anchor,radius,reverse=false){
  const list=reverse?[...points].reverse():points;
  for(let i=1;i<list.length;i++){
    const[x,y]=list[i];if(Math.hypot(x-anchor.x,y-anchor.y)>=radius)return Math.atan2(y-anchor.y,x-anchor.x);
  }
  return null;
}
function covers(direction,heading){return heading!==null&&difference(direction.angle,heading)<=Math.min(Math.PI/3,Math.max(Math.PI/6,direction.width/(2*direction.radius)+Math.PI/12));}

export async function scanBoard(field,rawAnchors,{allowGaps=true,progress=()=>{},cancelled=()=>false,maxVisited=3000000,timeLimitMs=10000,maxRoutes=2500,maxPoints=250000}={}){
  const started=performance.now(),anchors=[],issues=[];
  for(const a of rawAnchors){const point=snapPoint(field,a,{box:a.box});if(point)anchors.push({...a,...point});else issues.push({id:'snap:'+a.id,type:'no_copper',anchor:a.id,x:a.x,y:a.y});}
  const scans=[],routes=[],seenPairs=new Set();let stopped=null,truncated=false;
  for(const allowPhoto of allowGaps?[false,true]:[false]){
    if(cancelled()){stopped='cancelled';break;}
    const pass=await fronts(field,anchors,{allowGaps:allowPhoto,progress,cancelled,maxVisited,timeLimitMs,maxRoutes:maxRoutes-routes.length,maxPoints:maxPoints-routes.reduce((v,r)=>v+r.points.length,0)});
    scans.push({stage:allowPhoto?'photo':'strict',visited:pass.visited,elapsedMs:pass.elapsedMs,stopped:pass.stopped});
    for(const id of pass.duplicates)if(!issues.some(i=>i.id==='overlap:'+id))issues.push({id:'overlap:'+id,type:'overlapping_anchor',anchor:id});
    for(const route of pass.routes){const key=pairKey(route.from,route.to);if(!seenPairs.has(key)){seenPairs.add(key);routes.push(route);}}
    stopped=pass.stopped;truncated||=pass.truncated;
    progress({stage:allowPhoto?'photo_complete':'strict_complete',routes:[...routes],visited:pass.visited,stopped});await pause();
    if(stopped)break;
  }
  const incident=new Map(anchors.map(a=>[a.id,[]]));
  for(const r of routes){incident.get(r.from).push(r);incident.get(r.to).push(r);}
  const directional=[],workspace={};
  for(let i=0;i<anchors.length;i++){
    const a=anchors[i],radial=radialDirections(field,a,{allowGaps,workspace}),links=incident.get(a.id);
    directional.push({id:a.id,x:a.x,y:a.y,radius:radial.radius,surface:radial.surface,directions:radial.directions});
    if(!links.length)issues.push({id:'isolated:'+a.id,type:'isolated_anchor',anchor:a.id,x:a.x,y:a.y});
    for(const d of radial.directions){
      if(!links.some(r=>covers(d,routeHeading(r.points,a,radial.radius,r.to===a.id))))issues.push({id:'branch:'+a.id+':'+d.degrees,type:'unresolved_direction',anchor:a.id,degrees:d.degrees,x:d.exit.x,y:d.exit.y});
    }
    if(i%32===0){progress({stage:'directions',done:i,total:anchors.length});await pause();if(cancelled()){stopped='cancelled';break;}}
  }
  // Annotate photo paths with independently computed outgoing sectors at both endpoints.
  const radialById=new Map(directional.map(a=>[a.id,a]));
  for(const r of routes)if(r.gaps.length){
    r.directionEvidence=[r.from,r.to].map(id=>{const a=radialById.get(id);if(!a)return{anchor:id,status:'not_examined'};
      if(a.surface)return{anchor:id,status:'broad_surface'};
      const angle=routeHeading(r.points,a,a.radius,r.to===id);return{anchor:id,status:angle===null?'short_path':a.directions.some(d=>covers(d,angle))?'supported':'ambiguous'};});
  }
  const relevantComponents=new Set(anchors.map(a=>field.sourceLabels.labels[a.pixel]));
  for(const gap of field.rejected)if(gap.pair.some(c=>relevantComponents.has(c)))issues.push({id:'gap:'+gap.pixel,type:'unsupported_gap',x:gap.x,y:gap.y});
  return{routes,issues:issues.slice(0,2000),directions:directional,complete:!stopped&&!truncated,stopped,truncated,allowGaps,passes:scans,elapsedMs:performance.now()-started,
    summary:{anchors:anchors.length,strict:routes.filter(r=>!r.gaps.length).length,photo:routes.filter(r=>r.gaps.length).length,broad:routes.filter(r=>r.broad).length,issues:issues.length},
    topology:'adjacent anchor fronts on the source graph; no spanning-tree pruning; not an exhaustive circuit or cycle reconstruction'};
}
