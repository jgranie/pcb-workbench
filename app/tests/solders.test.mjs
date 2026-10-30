import test from 'node:test';
import assert from 'node:assert/strict';
import {replaceSolders,solderSectionCore,inSolderCore,solderResultText} from '../web/solders.mjs';
const pad=(id,x)=>({id,coords:[x-5,10,x+5,20]});
test('replacement preserves moved, rejected and manual points without stacking',()=>{
  const old=[pad('moved',20),pad('rejected',50),pad('untouched',80)];
  const workspace={objects:[{type:'pad',id:'manual',x:110,y:15}],detectionReviews:{moved:{x:25,y:15},rejected:{status:'rejected'}},traceScan:{routes:[{id:'kept-manual-route',origin:'manual'}]}};
  const snapshot=structuredClone(workspace);
  const detection={candidates:[pad('new1',20),pad('new2',50),pad('new3',80),pad('new4',110)],stats:{candidates:4}};
  const first=replaceSolders(workspace,old,detection);
  assert.deepEqual(first.solderDetection.candidates.map(p=>p.id),['new3','moved','rejected']);
  assert.deepEqual(first.objects,workspace.objects);assert.deepEqual(first.traceScan,workspace.traceScan);
  assert.equal(first.detectionReviews.moved.x,25);assert.equal(first.detectionReviews.rejected.status,'rejected');
  assert.equal(first.scanStale,true);assert.deepEqual(workspace,snapshot);
  const second=replaceSolders(first,first.solderDetection.candidates,detection);
  assert.deepEqual(second.solderDetection.candidates,first.solderDetection.candidates);
});
test('rerunning with no detections replaces unreviewed points with an empty set',()=>{
  const w={objects:[],detectionReviews:{},traceScan:{routes:[]}};
  const first=replaceSolders(w,[pad('old',10)],{candidates:[],stats:{candidates:0}});
  assert.equal(first.solderDetection.candidates.length,0);
});

test('a moved manual point suppresses duplicate detections at its original and reviewed positions',()=>{
  const w={objects:[{type:'pad',id:'manual',x:100,y:15}],detectionReviews:{manual:{x:150,y:15}},traceScan:{routes:[]}};
  const next=replaceSolders(w,[],{candidates:[pad('old-location',100),pad('new-location',150)],stats:{candidates:2}});
  assert.deepEqual(next.solderDetection.candidates,[]);assert.equal(next.detectionReviews.manual.x,150);
});
test('a section replaces only its core and leaves proposals in other sections intact',()=>{
 const w={objects:[],detectionReviews:{},traceScan:{routes:[]}};
 const next=replaceSolders(w,[pad('old-in',20),pad('old-out',150)],{section:0,tiles:[{core:[0,0,100,100]}],candidates:[pad('new-in',30),pad('halo-out',140)],stats:{candidates:2}});
 assert.deepEqual(next.solderDetection.candidates.map(p=>p.id),['new-in','old-out']);
 assert.equal(next.solderDetection.retained_outside_section,1);
});
test('retesting a section twice removes its old proposals, ignores halo and preserves other sections',()=>{
 const w={objects:[],detectionReviews:{},traceScan:{routes:[]}};
 const detection={section:0,tiles:[{core:[0,0,100,100]}],candidates:[pad('new-in',30),pad('halo-out',140)],stats:{candidates:2}};
 const first=replaceSolders(w,[pad('old-in',20),pad('old-out',150)],detection);
 const second=replaceSolders(first,first.solderDetection.candidates,{...detection,candidates:[pad('retry-in',40)]});
 assert.deepEqual(second.solderDetection.candidates.map(p=>p.id),['retry-in','old-out']);
 assert.equal(solderResultText(first.solderDetection),'Section 1 : 1 point · 1 ailleurs');
 assert.equal(solderResultText(detection),'Section 1 : 1 point · 1 hors section ignorés');
 assert.equal(first.solderDetection.application.ignored_context,1);
 const cleared=replaceSolders(second,second.solderDetection.candidates,{...detection,candidates:[]});
 assert.deepEqual(cleared.solderDetection.candidates.map(p=>p.id),['old-out']);
});
test('section display uses exact half-open tile boundaries and the reviewed point position',()=>{
 assert.deepEqual(solderSectionCore(1984,2782,4),[0,464,496,927]);
 assert.deepEqual(solderSectionCore(1986,2781,0),[0,0,496,464]);
 const core=solderSectionCore(1984,2782,4);
 assert.equal(inSolderCore({x:0,y:464},core),true);
 assert.equal(inSolderCore({x:496,y:500},core),false);
 assert.equal(inSolderCore({x:100,y:927},core),false);
 assert.equal(inSolderCore({coords:[20,300,40,340],x:30,y:500},core),true);
 assert.equal(inSolderCore({x:1000,y:1000},null),true);
});
test('counts distinguish a legacy merged section from raw halo observations',()=>{
 const d={section:0,tiles:[{core:[0,0,100,100]}],candidates:[pad('in',20),pad('out',150)],retained_outside_section:1};
 assert.equal(solderResultText(d),'Section 1 : 1 point · 1 ailleurs');
});
test('a section without valid bounds never falls back to replacing the whole card',()=>{
 const w={objects:[],detectionReviews:{}};const old=[pad('old',20)];
 for(const tiles of [undefined,[],[{core:[0,0,0,100]}],[{core:[0,0,NaN,100]}]]){
  assert.throws(()=>replaceSolders(w,old,{section:0,tiles,candidates:[]}),/Limites de section/);
 }
 assert.deepEqual(old,[pad('old',20)]);assert.equal(w.solderDetection,undefined);
});
