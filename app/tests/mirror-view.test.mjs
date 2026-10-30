import test from 'node:test';
import assert from 'node:assert/strict';
import {displayX,imageX} from '../web/core/mirror-view.mjs';
test('reflection preserves coordinates through zoom and pan in either direction',()=>{
 const width=1984,zoom=1.37,offset=211;
 for(const mirrored of [false,true])for(const x of [0,17.5,496,1501.25,1984]){
  const screen=offset+zoom*displayX(x,width,mirrored);
  assert.ok(Math.abs(imageX((screen-offset)/zoom,width,mirrored)-x)<1e-9);
  assert.equal(displayX(displayX(x,width,true),width,true),x);
 }
});
