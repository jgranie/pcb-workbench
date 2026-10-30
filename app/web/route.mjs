import {readFile,writeFile} from 'node:fs/promises';
import {createField,prepareAnchors} from './core/tracker-core.mjs';
import {scanBoard} from './core/auto-scan-core.mjs';
import {protectPinRows,routeVisible} from './core/pin-row-core.mjs';
const directory=process.argv[2];
const load=async name=>JSON.parse(await readFile(`${directory}/${name}`,'utf8'));
const meta=await load('image.json'),config=await load('config.json'),detection=await load('candidates.json');
const field=createField({width:meta.width,height:meta.height,
  alpha:new Uint8Array(await readFile(`${directory}/alpha.bin`)),
  photo:new Uint8Array(await readFile(`${directory}/photo.bin`)),detectGaps:config.allow_photo_gaps});
const anchors=prepareAnchors(detection.candidates,{},[0,0,meta.width,meta.height]);
let scan=await scanBoard(field,anchors,{allowGaps:config.allow_photo_gaps,maxVisited:6000000,timeLimitMs:30000});
if(config.protect_pin_rows)scan=protectPinRows(scan,anchors);
scan={schema_version:1,...scan,reviews:{},electrical_validation:false};
let visits=0;
for(const r of scan.routes){
  const allowed=new Set(r.gaps.flatMap(g=>g.pixels));
  for(let i=1;i<r.points.length;i++){
    const [x,y]=r.points[i-1],[u,v]=r.points[i];
    if(x!==u&&y!==v)throw Error('Non-orthogonal automatic route');
    const n=Math.abs(u-x)+Math.abs(v-y);
    for(let k=0;k<=n;k++){
      const p=Math.floor(y+(v-y)*k/(n||1))*field.width+Math.floor(x+(u-x)*k/(n||1));
      if(!field.source[p]&&!allowed.has(p))throw Error('Automatic route leaves its evidence mask');
      visits++;
    }
  }
}
// Keep timing evidence separate from useful deterministic output.
const timings={elapsedMs:scan.elapsedMs,passes:scan.passes.map(p=>({stage:p.stage,elapsedMs:p.elapsedMs}))};
delete scan.elapsedMs;for(const pass of scan.passes)delete pass.elapsedMs;
await writeFile(`${directory}/scan.json`,JSON.stringify(scan,null,2)+'\n');
await writeFile(`${directory}/routing-diagnostics.json`,JSON.stringify({anchors:anchors.length,
  ...scan.summary,visible:scan.routes.filter(r=>routeVisible(scan,r)).length,complete:scan.complete,
  verified_pixel_visits:visits,source_components:field.sourceLabels.count,
  rows:scan.pinRows?.groups.length??0,electrical_validation:false},null,2)+'\n');
await writeFile(`${directory}/routing-timings.json`,JSON.stringify(timings,null,2)+'\n');
