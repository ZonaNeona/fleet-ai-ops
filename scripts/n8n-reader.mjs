// Dedicated read-only adapter: only this stand's executions, only localhost + signed requests.
import {createServer} from 'node:http';
import {createHmac,timingSafeEqual} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {DatabaseSync} from 'node:sqlite';
const env=Object.fromEntries(readFileSync(process.env.FLEET_INTEGRATIONS_ENV||'/etc/fleet-integrations.env','utf8').split('\n').filter(l=>l.includes('=')).map(l=>{const i=l.indexOf('=');return[l.slice(0,i),l.slice(i+1).trim()]}));
const secret=env.INTEGRATION_SECRET;
// Shared n8n install: its sqlite and its own copy of flatted; workflow ids carry the stand prefix.
const N8N_HOME=env.N8N_HOME||'/var/www/n8n';
const PREFIX=env.N8N_PREFIX||'fleet';
const WORKFLOWS=['1c','yandex-pro','fines','telematics'].map(s=>PREFIX+'-'+s);
const {parse}=createRequire(N8N_HOME+'/package.json')('flatted');
function equal(a,b){const aa=Buffer.from(a),bb=Buffer.from(b);return aa.length===bb.length&&timingSafeEqual(aa,bb)}
function preview(r,run){
 const item=(r.data?.main||[]).flat().filter(Boolean).map(x=>x.json).find(x=>x.context?.run===run);
 const rows=item?.rows||item?.value||[];
 const keys=['vehicle_code','mileage','charges','payments','fine','external_id','Ref_Key','Description','Distance','AccruedAmount','car_id','income','vehicle','odometer','registration','amount','resolution'];
 return rows.slice(0,2).map(row=>Object.fromEntries(Object.entries(row).filter(([key])=>keys.includes(key))));
}
function get(run){
 const d=new DatabaseSync(N8N_HOME+'/data/.n8n/database.sqlite',{readOnly:true});
 try{
  const rows=d.prepare("SELECT e.id,e.workflowId,e.status,e.startedAt,e.stoppedAt,d.data FROM execution_entity e JOIN execution_data d ON d.executionId=e.id WHERE e.workflowId IN ("+WORKFLOWS.map(()=>'?').join(',')+") ORDER BY e.id DESC LIMIT 160").all(...WORKFLOWS);
  for(const row of rows){
   const body=parse(row.data);const runs=body.resultData?.runData||{};
   const contexts=(runs['Контекст запуска']||[]).flatMap(r=>(r.data?.main||[]).flat().filter(Boolean).map(x=>x.json));
   if(!contexts.some(c=>c.run===run))continue;
   // One scheduled execution may contain multiple sessions; never export row payloads.
   const trace=Object.entries(runs).flatMap(([node,entries])=>entries.map(r=>({node,title:node,step:'n8n',ms:r.executionTime||0,status:r.error||r.executionStatus==='error'||r.data?.main?.[1]?.length?'error':'success',items:(r.data?.main||[]).flat().filter(Boolean).length,output:{node_type:'n8n',execution_index:r.executionIndex,sample:preview(r,run)},order:r.executionIndex,start:r.startTime}))).sort((a,b)=>a.order-b.order||a.start-b.start);
   return {id:String(row.id),workflow:row.workflowId,status:row.status,finished:!!row.stoppedAt,trace};
  }
  return {finished:false,trace:[]};
 }finally{d.close()}
}
createServer((req,res)=>{
 const path=req.url||'';const stamp=String(req.headers['x-fleet-time']||'');const sig=String(req.headers['x-fleet-signature']||'');
 if(req.method!=='GET'||!/^\/execution\/[a-f0-9]{32}$/.test(path)||!/^\d{10}$/.test(stamp)||Math.abs(Date.now()/1000-Number(stamp))>30||!equal(sig,createHmac('sha256',secret).update(stamp+':'+path).digest('hex'))){res.writeHead(403);res.end('{}');return}
 try{res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(get(path.split('/').pop())))}catch{res.writeHead(503);res.end('{"error":"execution reader unavailable"}')}
}).listen(3014,'127.0.0.1',()=>console.log('Restricted n8n reader listening on loopback'));
