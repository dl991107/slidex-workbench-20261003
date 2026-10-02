// UI state checks only. No browser, CDP, network or challenge execution.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { randomUUID } = require('node:crypto');
const base = 'outputs/Slidex工作台.app/Contents/Resources/web/';
const html = fs.readFileSync(base + 'index.html', 'utf8');
const elements = new Map();
function element() { return { value:'', textContent:'', hidden:false, disabled:false, dataset:{},
  addEventListener(){}, appendChild(){}, replaceChildren(){}, setAttribute(){}, remove(){} }; }
for (const match of html.matchAll(/id="([^"]+)"/g)) elements.set(match[1], element());
const calls = [];
let resolveRun;
const response = (payload) => ({ok:true,status:200,json:async()=>payload});
const sandbox = { URL, Blob, AbortController, setTimeout, clearTimeout,
  crypto:{randomUUID}, location:{origin:'http://127.0.0.1:12345'}, navigator:{},
  document:{getElementById:id=>elements.get(id),querySelector:()=>({content:'TEST_TOKEN'}),
    createElement:()=>element(),body:{appendChild(){}}},
  fetch:async(url,options)=> { calls.push({url,options});
    if (url==='/api/status') return response({version:'0.6.28',backend:'test',busy:false});
    if (url==='/api/browser/cancel') return response({ok:true});
    if (url==='/api/browser/run') return new Promise(resolve=>{resolveRun=resolve;});
    throw new Error('unexpected request');
  }
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(base+'app.js','utf8'),sandbox);
(async()=>{
  await new Promise(setImmediate);
  assert.deepEqual(calls.map(call=>call.url),['/api/status']);
  for (const value of ['https://127.0.0.1:9222','http://user@localhost:9222','http://localhost:9222/path','http://example.com:9222','http://localhost:9222/?x=1']) {
    elements.get('endpointInput').value=value;
    assert.equal(vm.runInContext('endpointValue()',sandbox),'');
  }
  elements.get('endpointInput').value='http://localhost:9222/';
  assert.equal(vm.runInContext('endpointValue()',sandbox),'http://127.0.0.1:9222');
  vm.runInContext("state.connected=true; state.targetId='opaque';",sandbox);
  const running=vm.runInContext('runTask()',sandbox);
  await new Promise(setImmediate);
  assert.equal(vm.runInContext('state.running',sandbox),true);
  await vm.runInContext('cancelTask()',sandbox);
  assert.equal(vm.runInContext('state.running',sandbox),true);
  assert.equal(vm.runInContext('state.result',sandbox),null);
  resolveRun(response({ok:true,result:{status:'cancelled',provider:'geetest',elapsed_ms:1,message:'done'}}));
  await running;
  assert.equal(vm.runInContext('state.running',sandbox),false);
  assert.equal(vm.runInContext('state.result.status',sandbox),'cancelled');
  const run=calls.find(call=>call.url==='/api/browser/run');
  const cancel=calls.find(call=>call.url==='/api/browser/cancel');
  assert.equal(JSON.parse(run.options.body).request_id,JSON.parse(cancel.options.body).request_id);
  vm.runInContext("renderResult({status:'unsupported',provider:'geetest',message:'图片不可用；未执行拖动。'})",sandbox);
  assert.equal(elements.get('providerValue').textContent,'geetest');
  assert.equal(elements.get('messageValue').textContent,'图片不可用；未执行拖动。');
  assert.equal(elements.get('resultStatus').textContent,'Unsupported · 本次未执行拖动');
  console.log('UI logic passed: no auto-connect; strict endpoint; cancel waits for final result.');
})().catch(error=>{console.error(error);process.exitCode=1;});
