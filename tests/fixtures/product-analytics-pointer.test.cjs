// Execute the actual fixture click handler and send gate without a browser or network.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(__dirname+'/product-analytics.html','utf8');
const handler=html.slice(html.indexOf('root.addEventListener("click", event => {'),html.indexOf('document.addEventListener("visibilitychange"'));
const sender=html.slice(html.indexOf('async function send('),html.indexOf('function watch()'));
// Native Chrome observations (Playwright build1248): click records from the separately leased local DOM probe.
const mouse={pointerType:'mouse',isPrimary:false,isTrusted:true,button:0,detail:1};
const touch={pointerType:'touch',isPrimary:false,isTrusted:true,button:0,detail:1};
const keyboard={pointerType:'',isPrimary:false,isTrusted:true,button:0,detail:0};
function fixture(change={}){
 const deliveries=[];let callback;
 class PointerEvent{constructor(fields){Object.assign(this,fields);}}
 const section={dataset:{section:'hero'},getBoundingClientRect:()=>({left:0,top:0,width:100,height:100})};
 const root={addEventListener:(name,fn)=>{assert.equal(name,'click');callback=fn;},contains:node=>node===section};
 const box={PointerEvent,root,document:{hidden:false},allowed:true,saved:()=>true,endpoint:()=> 'http://127.0.0.1:8000/api/v1/analytics/events',AbortController,requests:new Set(),generation:0,crypto:{randomUUID:()=> '12345678-1234-4234-8234-123456789abc'},route:{value:'/'},viewport:()=> 'desktop',received:0,note:()=>{},fetch:async(url,options)=>{deliveries.push(JSON.parse(options.body));return {status:204};},...change};
 vm.runInNewContext(sender+'\n'+handler,box);
 return {box,deliveries,section,click:fields=>callback(new PointerEvent({target:{closest:()=>section},clientX:50,clientY:50,...fields})),plain:fields=>callback(fields)};
}
for(const [name,event] of [['observed native mouse',mouse],['observed native touch',touch],['pen',{...mouse,pointerType:'pen'}]])test(name+' accepted with isPrimary=false',()=>{const f=fixture();f.click(event);assert.equal(f.deliveries.length,1);assert.equal(f.deliveries[0].event_name,'public_click');assert.equal(f.deliveries[0].cell_x,4);assert.equal(f.deliveries[0].cell_y,4);});
for(const [name,event] of [['observed keyboard',keyboard],['untrusted',{...mouse,isTrusted:false}],['right button',{...mouse,button:2}],['middle button',{...mouse,button:1}]])test(name+' refused',()=>{const f=fixture();f.click(event);assert.equal(f.deliveries.length,0);});
for(const [name,change] of [['no local choice',{allowed:false}],['withdrawn saved choice',{saved:()=>false}],['hidden document',{document:{hidden:true}}]])test(name+' refused by actual send gate',()=>{const f=fixture(change);f.click(mouse);assert.equal(f.deliveries.length,0);});
test('non PointerEvent refused',()=>{const f=fixture();f.plain({...mouse,target:{closest:()=>f.section}});assert.equal(f.deliveries.length,0);});
test('foreign surface refused',()=>{const f=fixture();f.box.root.contains=()=>false;f.click(mouse);assert.equal(f.deliveries.length,0);});
test('zero-size surface refused',()=>{const f=fixture();f.section.getBoundingClientRect=()=>({left:0,top:0,width:0,height:100});f.click(mouse);assert.equal(f.deliveries.length,0);});
test('coordinates stay bounded integer cells',()=>{const f=fixture();f.click({...mouse,clientX:1000,clientY:-1000});assert.equal(f.deliveries[0].cell_x,7);assert.equal(f.deliveries[0].cell_y,0);});
