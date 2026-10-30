/** Bounded, deterministic image geometry. Scores are not probabilities. */
const TAU=2*Math.PI;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const angleDistance=(a,b)=>Math.abs(Math.atan2(Math.sin(a-b),Math.cos(a-b)));

export function prepareAnchors(candidates,reviews,bounds){
  const [ox,oy,x1,y1]=bounds;
  const anchors=candidates.filter(c=>reviews[c.id]?.status!=='rejected').map(c=>{
    const r=reviews[c.id]??{},x=r.x??(c.coords[0]+c.coords[2])/2,y=r.y??(c.coords[1]+c.coords[3])/2;
    return{id:c.id,x:x-ox,y:y-oy,box:[Math.max(0,c.coords[0]-ox),Math.max(0,c.coords[1]-oy),Math.min(x1-ox,c.coords[2]-ox),Math.min(y1-oy,c.coords[3]-oy)]};
  }).filter(a=>a.x>=0&&a.y>=0&&a.x<x1-ox&&a.y<y1-oy);
  return anchors.filter(a=>!anchors.some(b=>{
    if(a===b)return false;
    const p=a.box,q=b.box,area=(p[2]-p[0])*(p[3]-p[1]),large=(q[2]-q[0])*(q[3]-q[1]);
    const overlap=Math.max(0,Math.min(p[2],q[2])-Math.max(p[0],q[0]))*Math.max(0,Math.min(p[3],q[3])-Math.max(p[1],q[1]));
    return large>area&&overlap/area>=.95;
  }));
}

export function labelMask(mask,width,height){
  const labels=new Int32Array(mask.length),queue=new Int32Array(mask.length),sizes=[0];
  let count=0;
  for(let first=0;first<mask.length;first++){
    if(!mask[first]||labels[first])continue;
    const label=++count;let head=0,tail=1;queue[0]=first;labels[first]=label;
    while(head<tail){
      const p=queue[head++],x=p%width;
      for(const q of [x?p-1:-1,x+1<width?p+1:-1,p>=width?p-width:-1,p+width<mask.length?p+width:-1]){
        if(q>=0&&mask[q]&&!labels[q]){labels[q]=label;queue[tail++]=q;}
      }
    }
    sizes.push(tail);
  }
  return{labels,sizes,count};
}

export function distanceInside(mask,width,height){
  const d=new Float32Array(mask.length),diagonal=Math.SQRT2;
  for(let y=0;y<height;y++)for(let x=0;x<width;x++){
    const p=y*width+x;if(!mask[p])continue;
    d[p]=Math.min(x?d[p-1]+1:1,y?d[p-width]+1:1,x&&y?d[p-width-1]+diagonal:1e6,x+1<width&&y?d[p-width+1]+diagonal:1e6);
  }
  for(let y=height-1;y>=0;y--)for(let x=width-1;x>=0;x--){
    const p=y*width+x;if(!mask[p])continue;
    d[p]=Math.min(d[p],x+1<width?d[p+1]+1:1,y+1<height?d[p+width]+1:1,x+1<width&&y+1<height?d[p+width+1]+diagonal:1e6,x&&y+1<height?d[p+width-1]+diagonal:1e6);
  }
  return d;
}

function indexAt(x,y,width,height){x=Math.round(x);y=Math.round(y);return x>=0&&y>=0&&x<width&&y<height?y*width+x:-1;}

/** Short source gaps. Every absent pixel needs actual-position photo evidence. */
export function detectPhotoGaps(mask,photo,width,height,sourceLabels,{maxGaps=40}={}){
  const {labels,sizes}=sourceLabels,luma=new Float32Array(mask.length);
  for(let p=0;p<mask.length;p++)luma[p]=.2126*photo[p*4]+.7152*photo[p*4+1]+.0722*photo[p*4+2];
  const bestByPair=new Map(),rejectedByPair=new Map(),axes=[[1,0],[0,1],[1,1],[1,-1]],evidenceCache=new Map();
  let examined=0;
  function evidence(p,baseAngle){
    const key=p+':'+baseAngle;if(evidenceCache.has(key))return evidenceCache.get(key);
    const x=p%width,y=Math.floor(p/width);
    if(x<20||y<20||x>=width-20||y>=height-20)return null;
    let best=null;
    for(const delta of[-Math.PI/6,-Math.PI/12,0,Math.PI/12,Math.PI/6]){
      const angle=baseAngle+delta,dx=Math.cos(angle),dy=Math.sin(angle);
      const sample=(t,s)=>indexAt(x+t*dx-s*dy,y+t*dy+s*dx,width,height);
      for(const radius of[6,9,12,16]){
        let center=0,flankA=0,flankB=0;
        for(const t of[-3,0,3]){center+=luma[sample(t,0)]/3;flankA+=luma[sample(t,-radius)]/3;flankB+=luma[sample(t,radius)]/3;}
        const contrast=Math.min(flankA,flankB)-center,pointContrast=Math.min(flankA,flankB)-luma[p];
        if(contrast<14||pointContrast<10)continue;
        const score=contrast+pointContrast*.5;
        if(!best||score>best.score)best={angle,radius,contrast,pointContrast,score};
      }
    }
    evidenceCache.set(key,best);return best;
  }
  for(let y=20;y<height-20;y++)for(let x=20;x<width-20;x++){
    const p=y*width+x,la=labels[p];if(!la||sizes[la]<40)continue;
    for(const [dx,dy] of axes){
      const first=(y+dy)*width+x+dx;if(labels[first]===la)continue;
      let previous=p,path=[],absent=[],endLabel=0;
      for(let step=1;step<=9;step++){
        const nx=x+dx*step,ny=y+dy*step;
        if(nx<20||ny<20||nx>=width-20||ny>=height-20)break;
        const q=ny*width+nx;
        if(dx&&dy){
          const alternatives=[previous+dx,previous+dy*width];
          alternatives.sort((a,b)=>(mask[b]-mask[a])||(luma[a]-luma[b]));
          path.push(alternatives[0]);
        }
        path.push(q);previous=q;
        if(labels[q]&&sizes[labels[q]]>=40){endLabel=labels[q];break;}
      }
      if(!endLabel||endLabel===la)continue;
      absent=[...new Set(path.filter(q=>!mask[q]))];
      if(!absent.length||absent.length>8)continue;
      examined++;
      const angle=Math.atan2(dy,dx),samples=absent.map(q=>evidence(q,angle));
      const pair=[Math.min(la,endLabel),Math.max(la,endLabel)],key=pair.join(':'),middle=absent[Math.floor(absent.length/2)];
      if(samples.some(s=>!s)){
        const rejected={pixel:middle,x:middle%width,y:Math.floor(middle/width),pair,missingPixels:absent.length,status:'insufficient_photo_support'};
        if(!rejectedByPair.has(key)||absent.length<rejectedByPair.get(key).missingPixels)rejectedByPair.set(key,rejected);
        continue;
      }
      const score=Math.min(...samples.map(s=>s.score))+.2*samples.reduce((a,b)=>a+b.score,0)/samples.length-absent.length*1.2;
      const proposal={pixel:middle,pixels:absent,imageWidth:width,x:middle%width,y:Math.floor(middle/width),angle,score,pair,status:'photo_gap_hypothesis',photoEvidence:samples};
      if(!bestByPair.has(key)||proposal.score>bestByPair.get(key).score)bestByPair.set(key,proposal);
    }
  }
  return{gaps:[...bestByPair.values()].sort((a,b)=>b.score-a.score).slice(0,maxGaps).sort((a,b)=>a.pixel-b.pixel),
    rejected:[...rejectedByPair].filter(([key])=>!bestByPair.has(key)).map(([,value])=>value),examined,truncated:bestByPair.size>maxGaps};
}

export function createField({width,height,alpha,photo,detectGaps=true}){
  if(!Number.isInteger(width)||!Number.isInteger(height)||width<3||height<3||width*height>6000000)throw Error('Image dimensions exceed the bounded full-card CPU limit.');
  if(alpha.length!==width*height||photo.length!==width*height*4)throw Error('Image buffer dimensions do not match.');
  const source=Uint8Array.from(alpha,v=>v>=128?1:0),sourceLabels=labelMask(source,width,height);
  const detected=detectGaps?detectPhotoGaps(source,photo,width,height,sourceLabels,{maxGaps:40*Math.ceil(width*height/500000)}):{gaps:[],rejected:[],examined:0};
  const candidate=source.slice(),gapAt=new Map();
  for(const gap of detected.gaps)for(const pixel of gap.pixels){candidate[pixel]=1;gapAt.set(pixel,gap);}
  const candidateLabels=labelMask(candidate,width,height),sourceToCandidate=new Int32Array(sourceLabels.count+1);
  for(let p=0;p<source.length;p++)if(sourceLabels.labels[p])sourceToCandidate[sourceLabels.labels[p]]=candidateLabels.labels[p];
  return{width,height,source,candidate,gaps:detected.gaps,rejected:detected.rejected,gapAt,examined:detected.examined,
    sourceLabels,candidateLabels,sourceToCandidate,gapsTruncated:detected.truncated??false,
    sourceDistance:distanceInside(source,width,height),candidateDistance:distanceInside(candidate,width,height)};
}

export function snapPoint(field,point,{box=null,maxDistance=8}={}){
  const {width,height,source}=field;
  const x0=Math.max(0,Math.floor(box?.[0]??point.x-maxDistance)),x1=Math.min(width,Math.ceil(box?.[2]??point.x+maxDistance+1));
  const y0=Math.max(0,Math.floor(box?.[1]??point.y-maxDistance)),y1=Math.min(height,Math.ceil(box?.[3]??point.y+maxDistance+1));
  let best=null;
  for(let y=y0;y<y1;y++)for(let x=x0;x<x1;x++){
    if(!source[y*width+x])continue;
    const distance=Math.hypot(x+.5-point.x,y+.5-point.y);
    if(distance<=maxDistance&&(!best||distance<best.snapDistance))best={x:x+.5,y:y+.5,pixel:y*width+x,snapDistance:distance,box};
  }
  return best;
}

function activeData(field,allowGaps){return allowGaps?{mask:field.candidate,labels:field.candidateLabels.labels,distance:field.candidateDistance}:{mask:field.source,labels:field.sourceLabels.labels,distance:field.sourceDistance};}

export function radialDirections(field,seed,{allowGaps=false,previousAngle=null,workspace=null}={}){
  const {width,height}=field,{mask,distance}=activeData(field,allowGaps);
  const sx=seed.x-.5,sy=seed.y-.5;
  const box=seed.box;
  const radius=clamp(box?Math.max(...[[box[0],box[1]],[box[0],box[3]],[box[2],box[1]],[box[2],box[3]]].map(([x,y])=>Math.hypot(x-seed.x,y-seed.y)))+5:distance[seed.pixel]*3+6,14,80);
  const radii=[radius,radius+5,radius+10],limit=radius+13;
  const queueSize=Math.min(mask.length,Math.ceil((2*limit+3)**2));
  if(workspace){
    if(workspace.reached?.length!==mask.length){workspace.reached=new Uint8Array(mask.length);workspace.count=0;}
    else for(let i=0;i<(workspace.count??0);i++)workspace.reached[workspace.queue[i]]=0;
    if(!workspace.queue||workspace.queue.length<queueSize)workspace.queue=new Int32Array(queueSize);
  }
  const reached=workspace?.reached??new Uint8Array(mask.length),queue=workspace?.queue??new Int32Array(queueSize);
  let head=0,tail=1;queue[0]=seed.pixel;reached[seed.pixel]=1;
  while(head<tail){
    const p=queue[head++],x=p%width,y=Math.floor(p/width);
    for(const q of [x?p-1:-1,x+1<width?p+1:-1,y?p-width:-1,y+1<height?p+width:-1]){
      if(q<0||!mask[q]||reached[q])continue;
      if(Math.hypot(q%width-sx,Math.floor(q/width)-sy)>limit)continue;
      reached[q]=1;queue[tail++]=q;
    }
  }
  if(workspace)workspace.count=tail;
  const bins=180,response=new Float32Array(bins),outer=new Uint8Array(bins);
  let samples=0,occupied=0;
  for(let i=0;i<bins;i++){
    const a=i*TAU/bins;
    for(let k=0;k<radii.length;k++){
      const p=indexAt(sx+Math.cos(a)*radii[k],sy+Math.sin(a)*radii[k],width,height);
      if(p<0)continue;samples++;
      if(reached[p]){response[i]+=1/3;occupied++;if(k===1)outer[i]=1;}
    }
  }
  const smooth=Float32Array.from(response,(_,i)=>{let sum=0;for(let d=-2;d<=2;d++)sum+=response[(i+d+bins)%bins];return sum/5;});
  const coverage=samples?occupied/samples:0;
  const surface=coverage>.43||(!box&&distance[seed.pixel]>20);
  const runs=[];
  const on=Array.from(smooth,v=>v>=.23);
  const start=on.findIndex(v=>!v);
  if(start>=0){
    let run=[];
    for(let j=1;j<=bins;j++){
      const i=(start+j)%bins;
      if(on[i])run.push(i);
      else if(run.length){runs.push(run);run=[];}
    }
    if(run.length)runs.push(run);
  }
  const directions=[];
  if(!surface)for(const run of runs){
    let vx=0,vy=0,weight=0;
    for(const i of run){const a=i*TAU/bins;vx+=Math.cos(a)*smooth[i];vy+=Math.sin(a)*smooth[i];weight+=smooth[i];}
    const angle=(Math.atan2(vy,vx)+TAU)%TAU;
    if(previousAngle!==null&&angleDistance(angle,previousAngle+Math.PI)<Math.PI/3)continue;
    const candidates=run.map(i=>({i,p:indexAt(sx+Math.cos(i*TAU/bins)*(radius+5),sy+Math.sin(i*TAU/bins)*(radius+5),width,height)})).filter(v=>v.p>=0&&reached[v.p]);
    candidates.sort((a,b)=>angleDistance(a.i*TAU/bins,angle)-angleDistance(b.i*TAU/bins,angle));
    const exit=candidates[0]?.p;if(exit===undefined)continue;
    directions.push({angle,degrees:Math.round(angle*180/Math.PI),width:Math.round(run.length*TAU/bins*(radius+5)),score:weight/run.length,
      exit:{x:exit%width+.5,y:Math.floor(exit/width)+.5,pixel:exit},radius:radius+5});
  }
  return{directions:directions.sort((a,b)=>b.score-a.score),radius,coverage,surface,nearBoundary:sx<radius||sy<radius||width-sx<radius||height-sy<radius};
}

export class MinHeap{
  constructor(){this.nodes=[];this.costs=[];}
  push(node,cost){let i=this.nodes.length;this.nodes.push(node);this.costs.push(cost);while(i){const p=(i-1)>>1;if(this.costs[p]<=cost)break;this.nodes[i]=this.nodes[p];this.costs[i]=this.costs[p];i=p;}this.nodes[i]=node;this.costs[i]=cost;}
  pop(){const node=this.nodes[0],cost=this.costs[0],lastNode=this.nodes.pop(),lastCost=this.costs.pop();if(this.nodes.length){let i=0;while(true){let c=i*2+1;if(c>=this.nodes.length)break;if(c+1<this.nodes.length&&this.costs[c+1]<this.costs[c])c++;if(this.costs[c]>=lastCost)break;this.nodes[i]=this.nodes[c];this.costs[i]=this.costs[c];i=c;}this.nodes[i]=lastNode;this.costs[i]=lastCost;}return[node,cost];}
  get length(){return this.nodes.length;}
}

function extractPath(field,parent,seed,target,allowGaps,boxes){
  const reverse=[target.pixel];let p=target.pixel;
  while(p!==seed.pixel){p=parent[p];if(p<0||reverse.length>field.source.length)return null;reverse.push(p);}
  const pixels=reverse.reverse(),gapPixels=pixels.filter(p=>!field.source[p]);
  const distance=activeData(field,allowGaps).distance;
  const broad=pixels.some(p=>distance[p]>14&&!boxes.some(b=>p%field.width>=b[0]&&p%field.width<b[2]&&Math.floor(p/field.width)>=b[1]&&Math.floor(p/field.width)<b[3]));
  // Lossless horizontal/vertical run reduction; no diagonal shortcut crosses a gap.
  const points=[];
  for(let i=0;i<pixels.length;i++){
    if(i&&i+1<pixels.length&&pixels[i]-pixels[i-1]===pixels[i+1]-pixels[i])continue;
    points.push([pixels[i]%field.width+.5,Math.floor(pixels[i]/field.width)+.5]);
  }
  return{to:target.id??null,points,length:pixels.length-1,gaps:[...new Set(gapPixels.map(p=>field.gapAt.get(p)))],broad,status:gapPixels.length?'photo_gap_hypothesis':broad?'broad_surface_route':'source_route'};
}

export function searchRoutes(field,seed,targets,{allowGaps=false,initialDirection=null,maxVisited=300000,timeLimitMs=3000}={}){
  const {width,height}=field,{mask,labels,distance}=activeData(field,allowGaps);
  let gate=null;
  if(initialDirection){
    if(!Number.isFinite(initialDirection.angle)||!Number.isFinite(initialDirection.exit?.x)||!Number.isFinite(initialDirection.exit?.y))throw Error('Invalid initial direction.');
    const radius=Math.max(4,Math.hypot(initialDirection.exit.x-seed.x,initialDirection.exit.y-seed.y)-2);
    const tolerance=clamp((initialDirection.width??8)/(2*radius)+Math.PI/24,Math.PI/18,Math.PI/4);
    gate={angle:initialDirection.angle,radius,tolerance,degrees:Math.round(initialDirection.angle*180/Math.PI)};
  }
  const startTime=performance.now(),costs=new Float64Array(mask.length);costs.fill(Infinity);
  const parent=new Int32Array(mask.length);parent.fill(-1);
  const validTargets=targets.filter(t=>t.pixel!==seed.pixel&&labels[t.pixel]===labels[seed.pixel]);
  const targetPixels=new Set(validTargets.map(t=>t.pixel)),remaining=new Set(targetPixels);
  const heap=new MinHeap();heap.push(seed.pixel,0);costs[seed.pixel]=0;
  let visited=0,stopped=null;
  while(heap.length&&remaining.size){
    const [p,cost]=heap.pop();if(cost!==costs[p])continue;
    if(++visited>maxVisited||(visited%2048===0&&performance.now()-startTime>timeLimitMs)){stopped='budget';break;}
    remaining.delete(p);
    const x=p%width,y=Math.floor(p/width);
    for(const q of [x?p-1:-1,x+1<width?p+1:-1,y?p-width:-1,y+1<height?p+width:-1]){
      if(q<0||!mask[q])continue;
      if(gate){
        const sx=seed.x-.5,sy=seed.y-.5,qx=q%width,qy=Math.floor(q/width);
        if(Math.hypot(x-sx,y-sy)<gate.radius&&Math.hypot(qx-sx,qy-sy)>=gate.radius&&angleDistance(Math.atan2(qy-sy,qx-sx),gate.angle)>gate.tolerance)continue;
      }
      const step=1+2/(distance[p]+.5)+2/(distance[q]+.5)+(!field.source[q]?35:0);
      const next=cost+step;if(next<costs[q]){costs[q]=next;parent[q]=p;heap.push(q,next);}
    }
  }
  const boxes=[seed.box,...targets.map(t=>t.box)].filter(Boolean);
  const routes=validTargets.filter(t=>!remaining.has(t.pixel)).map(t=>extractPath(field,parent,seed,t,allowGaps,boxes)).filter(Boolean);
  const reached=new Set(routes.map(r=>r.to));
  const component=label=>allowGaps?field.sourceToCandidate[label]:label;
  const sourceComponent=labels[seed.pixel];
  const unreachedComponents=new Set(targets.filter(t=>!reached.has(t.id??null)).map(t=>labels[t.pixel]));
  const unresolved=field.rejected.filter(g=>
    (component(g.pair[0])===sourceComponent&&unreachedComponents.has(component(g.pair[1])))||
    (component(g.pair[1])===sourceComponent&&unreachedComponents.has(component(g.pair[0]))));
  return{routes,unreached:targets.filter(t=>t.pixel!==seed.pixel&&!reached.has(t.id??null)).map(t=>t.id??null),visited,stopped,elapsedMs:performance.now()-startTime,
    unresolved,initialDirection:gate,
    photoCandidatesAvailable:allowGaps?[]:targets.filter(t=>labels[t.pixel]!==labels[seed.pixel]&&field.candidateLabels.labels[t.pixel]===field.candidateLabels.labels[seed.pixel]).map(t=>t.id??null),
    topology:'source-to-anchor routes; reachable source graph retains cycles, displayed routes do not enumerate every cycle'};
}
