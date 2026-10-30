import{routeIdentity}from'./auto-scan-core.mjs';
import{routeVisible}from'./pin-row-core.mjs';
const EPS=1e-6;
const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
export function project(point,a,b){
  const dx=b[0]-a[0],dy=b[1]-a[1],l=dx*dx+dy*dy,t=l?Math.max(0,Math.min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/l)):0;
  const p=[a[0]+t*dx,a[1]+t*dy];return{point:p,t,distance:dist(point,p)};
}
/** A selection partition only. Original samples remain intact. */
export function logicalSegments(points,tolerance=2.5){
  if(points.length<2)return[];
  const keep=new Set([0,points.length-1]),stack=[[0,points.length-1]];
  while(stack.length){
    const[a,b]=stack.pop();let far=-1,maximum=tolerance;
    for(let i=a+1;i<b;i++){const d=project(points[i],points[a],points[b]).distance;if(d>maximum){maximum=d;far=i;}}
    if(far>=0){keep.add(far);stack.push([a,far],[far,b]);}
  }
  const indices=[...keep].sort((a,b)=>a-b);return indices.slice(1).map((end,i)=>({start:indices[i],end}));
}
export const visibleRoutes=scan=>(scan?.routes??[]).filter(r=>routeVisible(scan,r));
export function nearestStroke(scan,point,tolerance=6,cache=null){
  let best=null;
  for(const route of visibleRoutes(scan)){
    const spans=cache?.get(route.id)??logicalSegments(route.points);
    for(const span of spans)for(let i=span.start;i<span.end;i++){
      const hit=project(point,route.points[i],route.points[i+1]);
      if(hit.distance<=tolerance&&(!best||hit.distance<best.distance-EPS))best={routeId:route.id,...span,distance:hit.distance,point:hit.point};
    }
  }
  return best;
}
export const strokeKey=span=>`${span.routeId}:${span.start}:${span.end}`;
/** Traverse explicit topology in both directions, stopping at solder anchors. */
export function chainedStrokes(scan,seed,cache=null){
  if(!seed)return[];
  const edges=new Map(),nodes=new Map();
  for(const route of visibleRoutes(scan)){
    const endpoint=index=>{
      const id=index===0?route.from:index===route.points.length-1?route.to:null;
      return id?.startsWith('PAD-')?'pad:'+id:id?.startsWith('V-')?'virtual:'+id:`route:${route.id}:${index}`;
    };
    for(const span of cache?.get(route.id)??logicalSegments(route.points)){
      const value={routeId:route.id,...span},key=strokeKey(value),ends=[endpoint(span.start),endpoint(span.end)];edges.set(key,{value,ends});
      for(const node of ends){if(!nodes.has(node))nodes.set(node,[]);nodes.get(node).push(key);}
    }
  }
  const queue=[strokeKey(seed)],seen=new Set(),out=[];
  for(let i=0;i<queue.length;i++){
    const key=queue[i];if(seen.has(key)||!edges.has(key))continue;seen.add(key);
    const edge=edges.get(key);out.push(edge.value);
    for(const node of edge.ends)if(!node.startsWith('pad:'))for(const next of nodes.get(node)??[])if(!seen.has(next))queue.push(next);
  }
  return out;
}
export function snapEndpoint(scan,point,tolerance=6){
  let node=null;
  for(const j of scan.junctions??[]){const d=dist(point,[j.x,j.y]);if(d<=tolerance&&(!node||d<node.distance))node={point:[j.x,j.y],id:j.id,distance:d,kind:'junction'};}
  for(const route of visibleRoutes(scan))for(const[id,p]of[[route.from,route.points[0]],[route.to,route.points.at(-1)]]){
    if(!id.startsWith('PAD-')&&!id.startsWith('V-'))continue;
    const d=dist(point,p);if(d<=tolerance&&(!node||d<node.distance-EPS))node={point:p,id,distance:d,kind:'endpoint'};
  }
  if(node)return node;
  let line=null;
  for(const route of visibleRoutes(scan))for(let i=1;i<route.points.length;i++){
    const hit=project(point,route.points[i-1],route.points[i]);
    if(hit.distance<=tolerance&&(!line||hit.distance<line.distance))line={...hit,kind:'track'};
  }
  return line??{point:[...point],kind:'free',distance:0};
}
function junction(scan,point){
  scan.junctions??=[];const found=scan.junctions.find(j=>dist([j.x,j.y],point)<EPS);if(found)return found.id;
  const id='V-'+String(scan.nextVirtualId??1).padStart(4,'0');scan.nextVirtualId=(scan.nextVirtualId??1)+1;scan.junctions.push({id,x:point[0],y:point[1],kind:'virtual'});return id;
}
function cleaned(points){return points.filter((p,i)=>!i||dist(p,points[i-1])>EPS);}
function fragment(parent,points,from,to){
  points=cleaned(points);if(points.length<2)return null;
  const gaps=parent.gaps.filter(g=>(g.pixels??[g.pixel]).some(p=>{
    // Each copied photo-gap carries its actual image width; never assume a PCB size.
    const width=g.imageWidth;
    if(p!==g.pixel&&!Number.isInteger(width))throw Error('Photo-gap image width is missing.');
    const center=p===g.pixel?[g.x+.5,g.y+.5]:[p%width+.5,Math.floor(p/width)+.5];
    return points.slice(1).some((b,i)=>project(center,points[i],b).distance<EPS);
  }));
  const route={...parent,from,to,points,gaps,length:points.slice(1).reduce((sum,p,i)=>sum+dist(p,points[i]),0),origin:'manual_edited',parentId:parent.id,
    status:parent.status==='manual_route'?'manual_route':gaps.length?'photo_gap_hypothesis':parent.broad?'broad_surface_route':'source_route'};
  route.id=routeIdentity(route);return route;
}
function replaceRoute(scan,parent,pieces){
  scan.reviews[parent.id]={status:'rejected'};
  const all=new Map(scan.routes.map(r=>[r.id,r]));for(const p of pieces.filter(Boolean)){all.set(p.id,p);delete scan.reviews[p.id];}
  scan.routes=[...all.values()];
}
function splitAt(scan,point,id){
  for(const route of visibleRoutes(scan)){
    const points=route.points;
    if(dist(points[0],point)<EPS){if(route.from!==id)replaceRoute(scan,route,[fragment(route,points,id,route.to)]);continue;}
    if(dist(points.at(-1),point)<EPS){if(route.to!==id)replaceRoute(scan,route,[fragment(route,points,route.from,id)]);continue;}
    for(let i=0;i+1<points.length;i++)if(project(point,points[i],points[i+1]).distance<EPS){
      replaceRoute(scan,route,[fragment(route,[...points.slice(0,i+1),point],route.from,id),fragment(route,[point,...points.slice(i+1)],id,route.to)]);break;
    }
  }
}
export function addManualLine(work,start,end,{tolerance=6,snap=true,snapStart=snap,snapEnd=snap}={}){
  const scan=structuredClone(work),a=snapStart?snapEndpoint(scan,start,tolerance):{point:[...start],kind:'free'},b=snapEnd?snapEndpoint(scan,end,tolerance):{point:[...end],kind:'free'};
  if(dist(a.point,b.point)<1)throw Error('Choisir deux points distincts.');
  const from=a.id??junction(scan,a.point),to=b.id??junction(scan,b.point);
  if(snapStart)splitAt(scan,a.point,from);if(snapEnd)splitAt(scan,b.point,to);
  const route={from,to,points:[a.point,b.point],length:dist(a.point,b.point),gaps:[],broad:false,status:'manual_route',origin:'manual_drawn'};route.id=routeIdentity(route);
  const all=new Map(scan.routes.map(r=>[r.id,r]));all.set(route.id,route);scan.routes=[...all.values()];delete scan.reviews[route.id];
  return{scan,route,end:b.point};
}
/** Exact collinear overlap only: parallel neighbouring tracks and crossings are preserved. */
function overlap(a,b,c,d){
  const dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy);if(length<EPS)return null;
  const cross=p=>Math.abs(dx*(p[1]-a[1])-dy*(p[0]-a[0]))/length;
  if(cross(c)>EPS||cross(d)>EPS)return null;
  const sq=length*length,t=p=>((p[0]-a[0])*dx+(p[1]-a[1])*dy)/sq;
  const low=Math.max(0,Math.min(t(c),t(d))),high=Math.min(1,Math.max(t(c),t(d)));return high-low>EPS?[low,high]:null;
}
function eraserIndex(eraser){
  const cells=new Map(),large=[],size=32;
  function keys(a,b){const x0=Math.floor((Math.min(a[0],b[0])-EPS)/size),x1=Math.floor((Math.max(a[0],b[0])+EPS)/size),y0=Math.floor((Math.min(a[1],b[1])-EPS)/size),y1=Math.floor((Math.max(a[1],b[1])+EPS)/size);if((x1-x0+1)*(y1-y0+1)>512)return null;const out=[];for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++)out.push(x+':'+y);return out;}
  for(let i=0;i<eraser.length;i++){const k=keys(...eraser[i]);if(!k){large.push(i);continue;}for(const key of k){if(!cells.has(key))cells.set(key,[]);cells.get(key).push(i);}}
  return(a,b)=>{const k=keys(a,b);if(!k)return eraser;const found=new Set(large);for(const key of k)for(const i of cells.get(key)??[])found.add(i);return[...found].map(i=>eraser[i]);};
}
function survivingPieces(points,query){
  const pieces=[];let piece=[],changed=false;
  for(let i=0;i+1<points.length;i++){
    const a=points[i],b=points[i+1],intervals=query(a,b).map(([c,d])=>overlap(a,b,c,d)).filter(Boolean).sort((a,b)=>a[0]-b[0]);
    const merged=[];for(const interval of intervals){const last=merged.at(-1);if(last&&interval[0]<=last[1]+EPS)last[1]=Math.max(last[1],interval[1]);else merged.push([...interval]);}
    const at=t=>[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];
    let t=0;
    for(const[low,high]of merged){
      changed=true;if(low>t+EPS){if(!piece.length)piece.push(at(t));piece.push(at(low));}
      if(piece.length>1)pieces.push(cleaned(piece));piece=[];t=high;
    }
    if(t<1-EPS){if(!piece.length)piece.push(at(t));piece.push(b);}
    else if(merged.length)piece=[];
  }
  if(piece.length>1)pieces.push(cleaned(piece));return{pieces,changed};
}
export function deleteStrokes(work,selections){
  const scan=structuredClone(work),eraser=[],seen=new Set();
  for(const selection of selections){
    const key=strokeKey(selection);if(seen.has(key))continue;seen.add(key);
    const route=scan.routes.find(r=>r.id===selection.routeId&&scan.reviews[r.id]?.status!=='rejected');
    if(!route||selection.start<0||selection.end>=route.points.length||selection.start>=selection.end)throw Error('Sélectionner des tronçons existants.');
    const points=route.points.slice(selection.start,selection.end+1);eraser.push(...points.slice(1).map((p,i)=>[points[i],p]));
  }
  const query=eraserIndex(eraser);let affected=0;
  for(const route of visibleRoutes(scan)){
    const cut=survivingPieces(route.points,query);if(!cut.changed)continue;affected++;
    const pieces=cut.pieces.map(points=>fragment(route,points,dist(points[0],route.points[0])<EPS?route.from:junction(scan,points[0]),dist(points.at(-1),route.points.at(-1))<EPS?route.to:junction(scan,points.at(-1))));
    replaceRoute(scan,route,pieces);
  }
  return{scan,affected};
}
export function deleteStroke(work,selection){return deleteStrokes(work,[selection]);}
