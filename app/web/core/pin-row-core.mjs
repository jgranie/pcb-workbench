/** Layout prior only: regular pin rows are not proof of electrical isolation. */
export const PIN_ROW_VERSION='regular-pin-rows-v1';
export function detectPinRows(anchors,{minPins=6,minPitch=20,maxPitch=95}={}){
  const found=[];
  for(const axis of ['horizontal','vertical']){
    const u=p=>axis==='horizontal'?p.x:p.y,v=p=>axis==='horizontal'?p.y:p.x;
    for(const a of anchors)for(const b of anchors){
      const du=u(b)-u(a),dv=v(b)-v(a);
      if(du<minPitch||du>maxPitch||Math.abs(dv)>du*.12)continue;
      const tol=Math.min(11,du*.27),slots=new Map();
      for(const c of anchors){
        const t=(u(c)-u(a))/du,k=Math.round(t),error=Math.hypot((t-k)*du,v(c)-v(a)-k*dv);
        if(error<=tol&&(!slots.has(k)||error<slots.get(k).error))slots.set(k,{anchor:c,error});
      }
      let run=[];
      const flush=()=>{
        if(run.length>=minPins&&run.length/(run.at(-1)-run[0]+1)>=.8){
          const members=run.map(k=>({...slots.get(k).anchor,slot:k-run[0]}));
          found.push({axis,members,pitch:du,error:run.reduce((n,k)=>n+slots.get(k).error,0)/run.length});
        }
        run=[];
      };
      for(const k of [...slots.keys()].sort((a,b)=>a-b)){if(run.length&&k-run.at(-1)>2)flush();run.push(k);}flush();
    }
  }
  // Keep the strongest row where duplicate lattices or a chance crossing compete.
  found.sort((a,b)=>b.members.length-a.members.length||a.error-b.error||a.members[0].id.localeCompare(b.members[0].id));
  const chosen=[];
  for(const row of found){
    const ids=new Set(row.members.map(a=>a.id));
    if(new Set(chosen.filter(q=>q.axis!==row.axis).flatMap(q=>q.members.filter(a=>ids.has(a.id)).map(a=>a.id))).size>=2)continue;
    if(chosen.some(q=>{const overlap=q.members.filter(a=>ids.has(a.id)).length;return q.axis===row.axis?overlap>=Math.min(row.members.length,q.members.length)*.6:overlap>=2;}))continue;
    chosen.push(row);
  }
  // Tolerate a noisy BB centre in an already established row; do not invent missing pins.
  for(const row of chosen){
    const u=p=>row.axis==='horizontal'?p.x:p.y,v=p=>row.axis==='horizontal'?p.y:p.x;
    const first=row.members[0],last=row.members.at(-1),pitch=(u(last)-u(first))/(last.slot-first.slot),slope=(v(last)-v(first))/(u(last)-u(first));
    const members=new Map(row.members.map(a=>[a.id,a]));
    for(const a of anchors){const t=(u(a)-u(first))/pitch,k=Math.round(t);
      if(t>=-.28&&t<=last.slot+.28&&Math.abs(t-k)<=.28&&Math.abs(v(a)-v(first)-slope*(u(a)-u(first)))<=Math.min(20,pitch*.55))members.set(a.id,{...a,slot:k});
    }
    row.members=[...members.values()].sort((a,b)=>u(a)-u(b)||a.id.localeCompare(b.id));row.pitch=pitch;
  }
  chosen.sort((a,b)=>a.axis.localeCompare(b.axis)||a.members[0].y-b.members[0].y||a.members[0].x-b.members[0].x);
  const counts={horizontal:0,vertical:0};
  return chosen.map(row=>{
    const xs=row.members.map(a=>a.x),ys=row.members.map(a=>a.y);
    return{id:(row.axis==='horizontal'?'H':'V')+(++counts[row.axis]),axis:row.axis,pitch:row.pitch,error:row.error,
      members:row.members.map(({id,x,y,slot})=>({id,x,y,slot})),bounds:[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)]};
  });
}
function directRowLink(route,row){
  const a=row.members.find(a=>a.id===route.from),b=row.members.find(a=>a.id===route.to);
  if(!a||!b||a.slot===b.slot)return false;
  const u=p=>row.axis==='horizontal'?p[0]:p[1],v=p=>row.axis==='horizontal'?p[1]:p[0],start=[a.x,a.y],end=[b.x,b.y];
  const lo=Math.min(u(start),u(end)),hi=Math.max(u(start),u(end)),slope=(v(end)-v(start))/(u(end)-u(start)),margin=Math.max(8,row.pitch*.6);
  let length=0;
  for(let i=0;i<route.points.length;i++){
    const p=route.points[i];if(u(p)<lo-margin||u(p)>hi+margin||Math.abs(v(p)-v(start)-slope*(u(p)-u(start)))>margin)return false;
    if(i)length+=Math.hypot(p[0]-route.points[i-1][0],p[1]-route.points[i-1][1]);
  }
  return length<=1.8*Math.hypot(a.x-b.x,a.y-b.y)+margin;
}
export function protectPinRows(scan,anchors,{enabled=scan.pinRows?.enabled??true}={}){
  const groups=detectPinRows(anchors),blocked={};
  for(const route of scan.routes)if(route.origin==='automatic'){
    const row=groups.find(row=>directRowLink(route,row));if(row)blocked[route.id]=row.id;
  }
  return{...scan,pinRows:{version:PIN_ROW_VERSION,enabled,groups,blocked}};
}
export function pinRowSuppressed(scan,route){
  return !!scan?.pinRows?.enabled&&route.origin==='automatic'&&!!scan.pinRows.blocked[route.id]&&scan.reviews?.[route.id]?.status!=='accepted';
}
export function routeVisible(scan,route){return scan.reviews?.[route.id]?.status!=='rejected'&&!pinRowSuppressed(scan,route);}
export function validatePinRows(scan,{width,height}){
  const p=scan.pinRows;if(p===undefined)return;
  if(!p||p.version!==PIN_ROW_VERSION||typeof p.enabled!=='boolean'||!Array.isArray(p.groups)||p.groups.length>200||!p.blocked||typeof p.blocked!=='object'||Array.isArray(p.blocked))throw Error('Protection des rangées invalide.');
  const ids=new Set();
  for(const g of p.groups){
    if(typeof g.id!=='string'||!/^[HV][0-9]{1,3}$/.test(g.id)||ids.has(g.id)||!['horizontal','vertical'].includes(g.axis)||!Number.isFinite(g.pitch)||g.pitch<=0||!Array.isArray(g.members)||g.members.length<6||g.members.length>1000||new Set(g.members.map(a=>a.id)).size!==g.members.length||!Array.isArray(g.bounds)||g.bounds.length!==4||!g.bounds.every(Number.isFinite))throw Error('Rangée enregistrée invalide.');
    ids.add(g.id);
    for(const a of g.members)if(typeof a.id!=='string'||a.id.length>100||!Number.isInteger(a.slot)||!Number.isFinite(a.x)||!Number.isFinite(a.y)||a.x<0||a.y<0||a.x>=width||a.y>=height)throw Error('Broche de rangée invalide.');
  }
  const routes=new Map(scan.routes.map(r=>[r.id,r]));
  if(Object.keys(p.blocked).length>3000)throw Error('Trop de liaisons de rangées.');
  for(const[id,row]of Object.entries(p.blocked))if(!routes.has(id)||routes.get(id).origin!=='automatic'||!ids.has(row))throw Error('Liaison de rangée invalide.');
}
