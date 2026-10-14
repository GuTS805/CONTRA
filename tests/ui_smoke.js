const fs=require('fs');
const vm=require('vm');
const assert=require('assert');
const base=process.env.CONTRA_BASE_URL||'http://127.0.0.1:8000';
const elements=new Map();
const listeners={};
function element(key){if(!elements.has(key))elements.set(key,{innerHTML:'',textContent:'',hidden:false,isConnected:true,onclick:null,onchange:null,value:'',attributes:{},setAttribute(name,value){this.attributes[name]=value},getAttribute(name){return this.attributes[name]},focus(){document.activeElement=this},contains(child){return key==='#drawer'&&child===element('#drawer .drawer-close')},querySelector(){return null},querySelectorAll(){return key==='#drawer'?[element('#drawer .drawer-close')]:[]}});return elements.get(key)}
const document={querySelector:element,querySelectorAll(){return []},addEventListener(type,callback){listeners[type]=callback},activeElement:null};
const context={document,window:{},history:{pushState(_,__,path){context.location.pathname=path}},location:{pathname:'/'},fetch:(path,options)=>fetch(base+path,options),console,alert:message=>{throw Error(message)}};
vm.createContext(context);
let source=fs.readFileSync('web/app.js','utf8');
source=source.replace('window.onpopstate=render;render();','window.onpopstate=render;');
vm.runInContext(source,context);
assert.equal(vm.runInContext("esc('<script>')",context),'&lt;script&gt;');
async function analysis(investor){const response=await fetch(base+'/v1/analyses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker:'ALPHA.NS',investor_id:investor})});assert.equal(response.status,201);return response.json()}
(async()=>{
 await vm.runInContext('render()',context);
 assert(element('#view').innerHTML.includes('Start an analysis'));
 const first=await analysis('demo_conservative');context.first=first;
 await vm.runInContext('loadRecent()',context);
 assert(element('#recent-runs').innerHTML.includes('saved runs'));
 vm.runInContext('state.report=first;reportView(first)',context);
 assert(element('#view').innerHTML.includes('Simulated price path'));
 assert(element('#view').innerHTML.includes('Download JSON'));
 assert(element('#view').innerHTML.includes('Show calculation and sources'));
 const second=await analysis('demo_growth');context.second=second;
 vm.runInContext('state.comparison={left:first,right:second};state.report=second;reportView(second)',context);
 assert(element('#view').innerHTML.includes('Same market, different investor'));
 document.activeElement=element('#compare');
 await vm.runInContext("openEvidence('demo_growth')",context);
 assert.equal(document.activeElement,element('#drawer .drawer-close'));
 let tabPrevented=false;
 listeners.keydown({key:'Tab',shiftKey:false,preventDefault(){tabPrevented=true}});
 assert(tabPrevented);
 listeners.keydown({key:'Escape'});
 assert.equal(document.activeElement,element('#compare'));
 await vm.runInContext('evaluation()',context);
 assert(element('#view').innerHTML.includes('Scenario matrix'));
 const liveFetch=context.fetch;
 let releaseBenchmark;
 context.fetch=(path,options)=>path==='/v1/evaluations/benchmark'
   ? new Promise(resolve=>{releaseBenchmark=()=>resolve(liveFetch(path,options))})
   : liveFetch(path,options);
 const benchmarkTask=element('#benchmark-run').onclick();
 assert.equal(typeof releaseBenchmark,'function');
 context.location.pathname='/';
 await vm.runInContext('render()',context);
 releaseBenchmark();
 await benchmarkTask;
 assert(element('#view').innerHTML.includes('Start an analysis'), 'Stale benchmark must not alter terminal');
 let releaseEvaluation;
 context.fetch=(path,options)=>path==='/v1/evaluations/summary'
   ? new Promise(resolve=>{releaseEvaluation=()=>resolve(liveFetch(path,options))})
   : liveFetch(path,options);
 context.location.pathname='/evaluation';
 await vm.runInContext('render()',context);
 assert.equal(typeof releaseEvaluation,'function');
 context.location.pathname='/';
 await vm.runInContext('render()',context);
 releaseEvaluation();
 await new Promise(resolve=>setTimeout(resolve,50));
 assert(element('#view').innerHTML.includes('Start an analysis'), 'Stale evaluation must not replace terminal');
 context.fetch=liveFetch;
 context.location.pathname='/evidence';
 await vm.runInContext('render()',context);
 assert(element('#view').innerHTML.includes('Synthetic filing excerpts'));
 vm.runInContext('portfolio()',context);
 assert(element('#view').innerHTML.includes('SECTOR CAP'));
 assert(element('#view').innerHTML.includes('Sector exposure'));
 assert(element('#view').innerHTML.includes('Edit synthetic holdings'));
 assert.equal(typeof element('#save-holdings').onclick,'function');
 console.log('UI runtime smoke: terminal, report, comparison, evaluation, evidence, portfolio passed');
})().catch(error=>{console.error(error);process.exitCode=1});
