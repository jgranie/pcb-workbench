import test from 'node:test';
import assert from 'node:assert/strict';
import {createField} from '../web/core/tracker-core.mjs';
import {scanBoard} from '../web/core/auto-scan-core.mjs';
import {addManualLine,deleteStrokes,nearestStroke,visibleRoutes} from '../web/core/trace-edit-core.mjs';
test('parallel copper cannot connect across an empty column',async()=>{
  const width=100,height=100,alpha=new Uint8Array(width*height),photo=new Uint8Array(width*height*4);
  for(let y=10;y<90;y++)for(const x of [30,60])alpha[y*width+x]=255;
  const before=alpha.slice(),field=createField({width,height,alpha,photo,detectGaps:false});
  const scan=await scanBoard(field,[{id:'a',x:30.5,y:20.5},{id:'b',x:30.5,y:70.5},{id:'c',x:60.5,y:20.5},{id:'d',x:60.5,y:70.5}],{allowGaps:false});
  assert.equal(scan.routes.length,2);assert.deepEqual(alpha,before);
  assert.ok(scan.routes.every(r=>['a|b','c|d'].includes([r.from,r.to].sort().join('|'))));
});
test('a manual T junction splits an existing route; deleting one arm preserves the others',()=>{
  const empty={routes:[],reviews:{},issues:[]};
  const first=addManualLine(empty,[10,20],[90,20],{snap:false}).scan;
  const next=addManualLine(first,[50,20],[50,70],{tolerance:2}).scan;
  assert.equal(visibleRoutes(next).length,3);assert.equal(empty.routes.length,0);
  const span=nearestStroke(next,[50,50],1),deleted=deleteStrokes(next,[span]).scan;
  assert.equal(visibleRoutes(deleted).length,2);assert.equal(visibleRoutes(next).length,3);
});
