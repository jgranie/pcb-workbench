import test from 'node:test';
import assert from 'node:assert/strict';
import {traceSettings,traceAnchors,mergeTraceScan,filteredTraces} from '../web/traces.mjs';
import {createField,snapPoint} from '../web/core/tracker-core.mjs';
import {scanBoard} from '../web/core/auto-scan-core.mjs';

test('trace inputs retain every active corrected anchor, including contained points',()=>{
 const auto=[{id:'auto',coords:[10,10,50,50]},{id:'inside',coords:[20,20,30,30]},{id:'rejected',coords:[40,40,60,60]}];
 const reviews={auto:{x:70,y:70},rejected:{status:'rejected'},manual:{x:90,y:50}},manual=[{type:'pad',id:'manual',x:20,y:20}];
 const anchors=traceAnchors(auto,reviews,manual,100,100);
 assert.deepEqual(anchors.map(p=>p.id),['auto','inside','manual']);
 assert.deepEqual(anchors[0],{id:'auto',x:70,y:70,box:[50,50,90,90]});
 assert.deepEqual(anchors[2].box,[78,38,100,62]);
 const alpha=new Uint8Array(10000);alpha[70*100+70]=255;
 const field=createField({width:100,height:100,alpha,photo:new Uint8Array(40000),detectGaps:false});
 assert.equal(snapPoint(field,anchors[0],{box:anchors[0].box}).pixel,7070);
});
test('rerun preserves manual cuts, rejections, acceptance and virtual junctions',()=>{
 const route=(id,origin='automatic')=>({id,origin,points:[[1,1],[2,2]],gaps:[]});
 const old={routes:[route('untouched'),route('rejected'),route('accepted'),route('drawn','manual_drawn'),route('cut','manual_edited')],
 reviews:{rejected:{status:'rejected'},accepted:{status:'accepted'},removed:{status:'rejected'}},junctions:[{id:'V-1',x:1,y:1}],nextVirtualId:2};
 const before=structuredClone(old),fresh={routes:[route('fresh'),route('rejected')],issues:[],complete:true};
 const merged=mergeTraceScan(old,fresh);
 assert.deepEqual(merged.routes.map(r=>r.id),['fresh','rejected','accepted','drawn','cut']);
 assert.equal(merged.reviews.rejected.status,'rejected');assert.equal(merged.reviews.accepted.status,'accepted');assert.equal(merged.reviews.removed,undefined);
 assert.deepEqual(merged.junctions,old.junctions);assert.equal(merged.nextVirtualId,2);assert.deepEqual(old,before);
 assert.deepEqual(mergeTraceScan(merged,fresh),merged);
});
test('review filters make hidden row links and rejected paths recoverable',()=>{
 const routes=[{id:'fine',gaps:[],origin:'automatic'},{id:'photo',gaps:[{}]},{id:'wide',gaps:[],broad:true},{id:'row',gaps:[],origin:'automatic'},{id:'rejected',gaps:[]}];
 const scan={routes,reviews:{rejected:{status:'rejected'}},pinRows:{enabled:true,blocked:{row:'H1'}}};
 assert.deepEqual(filteredTraces(scan,'all').map(r=>r.id),['fine','photo','wide']);
 assert.deepEqual(filteredTraces(scan,'rows').map(r=>r.id),['row']);
 assert.deepEqual(filteredTraces(scan,'rejected').map(r=>r.id),['rejected']);
 assert.deepEqual(filteredTraces(scan,'photo').map(r=>r.id),['photo']);
 scan.reviews.row={status:'accepted'};assert.equal(filteredTraces(scan,'rows').length,0);assert.equal(filteredTraces(scan,'all').length,4);
});
test('scan preserves four sides of a loop rather than reducing it to a spanning tree',async()=>{
 const width=80,height=80,alpha=new Uint8Array(width*height),photo=new Uint8Array(width*height*4);
 for(let y=20;y<=60;y++)for(let x=20;x<=60;x++)if(x===20||x===60||y===20||y===60)alpha[y*width+x]=255;
 const field=createField({width,height,alpha,photo,detectGaps:false});
 const scan=await scanBoard(field,[[20.5,20.5],[60.5,20.5],[60.5,60.5],[20.5,60.5]].map(([x,y],i)=>({id:'PAD-'+i,x,y})),{allowGaps:false});
 assert.equal(scan.routes.length,4);assert.equal(scan.complete,true);
});
test('settings reject unbounded budgets, truthy booleans and unknown keys',()=>{
 assert.equal(traceSettings().max_visited,3000000);
 for(const value of [{max_visited:6000001},{max_visited:true},{time_limit_ms:NaN},{allow_photo_gaps:1},{model:'llm'}])assert.throws(()=>traceSettings(value));
});
