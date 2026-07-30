"""Minimal same-origin chat page for quick end-to-end testing in a browser.

Served at GET / by the copilot backend. Talks to the same-origin
/api/v1/copilot endpoints — no CORS, no Superset needed. This is the dev harness
for verifying "open the copilot, say hi, the LangGraph agent responds"; the real
UI is the Superset chat extension.
"""
from __future__ import annotations

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Copilot</title>
<style>
  body{font-family:system-ui,sans-serif;margin:0;background:#f7f9fb;color:#111}
  #wrap{max-width:720px;margin:0 auto;height:100vh;display:flex;flex-direction:column}
  header{padding:14px 16px;border-bottom:1px solid #e5e9ee;background:#fff;font-weight:600}
  #log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
  .row{display:flex}
  .b{max-width:76%;padding:9px 13px;border-radius:14px;white-space:pre-wrap;word-break:break-word;font-size:15px;line-height:1.4}
  .user{margin-left:auto;background:#20a7c9;color:#fff;border-bottom-right-radius:3px}
  .asst{background:#fff;border:1px solid #e5e9ee;border-bottom-left-radius:3px}
  .thoughts{font:12px/1.4 monospace;color:#8a94a0;margin:2px 0 4px}
  #bar{display:flex;gap:8px;padding:12px 16px;border-top:1px solid #e5e9ee;background:#fff}
  #msg{flex:1;padding:10px;border:1px solid #d4dae1;border-radius:8px;font-size:15px}
  #send{padding:10px 18px;background:#20a7c9;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:15px}
  #send:disabled{opacity:.5}
</style></head>
<body><div id="wrap">
  <header>Copilot <span id="status" style="font-weight:400;color:#8a94a0;font-size:13px"></span></header>
  <div id="log"></div>
  <div id="bar">
    <input id="msg" placeholder="Say hi…" autocomplete="off"/>
    <button id="send">Send</button>
  </div>
</div>
<script>
const API='/api/v1/copilot';
let convId=null;
const log=document.getElementById('log'), msg=document.getElementById('msg'),
      send=document.getElementById('send'), status=document.getElementById('status');

function bubble(cls){const r=document.createElement('div');r.className='row';
  const b=document.createElement('div');b.className='b '+cls;r.appendChild(b);log.appendChild(r);
  log.scrollTop=log.scrollHeight;return b;}

async function init(){
  try{const r=await fetch(API+'/conversations',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({agent_type:'DEFAULT'})});
    const c=await r.json();convId=c.id;status.textContent='conversation '+c.id.slice(0,8);}
  catch(e){status.textContent='backend unreachable';}
}
init();

async function stream(text){
  const b=bubble('asst');b.textContent='…';let acc='';let thoughtsEl=null;
  const res=await fetch(API+'/completions',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({conversation_id:convId,message:text})});
  const reader=res.body.getReader();const dec=new TextDecoder();let buf='';
  const handle=(ev,d)=>{
    if(ev==='token'){acc+=d.text;b.textContent=acc;}
    else if(ev==='final'){if(!acc){b.textContent=d.content;}}
    else if(ev==='tool_call'){if(!thoughtsEl){thoughtsEl=document.createElement('div');thoughtsEl.className='thoughts';b.parentNode.insertBefore(thoughtsEl,b.parentNode.firstChild);}thoughtsEl.textContent+='\\u2192 '+d.name+'('+JSON.stringify(d.arguments)+')\\n';}
    else if(ev==='tool_result'){if(thoughtsEl)thoughtsEl.textContent+='\\u2190 '+String(d.content).slice(0,120)+'\\n';}
    else if(ev==='error'){b.textContent='[error] '+d.message;}
    log.scrollTop=log.scrollHeight;
  };
  while(true){const{value,done}=await reader.read();if(done)break;buf+=dec.decode(value,{stream:true});
    let i;while((i=buf.indexOf('\\n\\n'))!==-1){const rec=buf.slice(0,i);buf=buf.slice(i+2);
      let ev='message',data=[];for(const line of rec.split('\\n')){if(line.startsWith('event:'))ev=line.slice(6).trim();else if(line.startsWith('data:'))data.push(line.slice(5).trim());}
      if(data.length){try{handle(ev,JSON.parse(data.join('\\n')));}catch(e){}}}}
}

async function go(){const t=msg.value.trim();if(!t||!convId)return;msg.value='';
  bubble('user').textContent=t;send.disabled=true;
  try{await stream(t);}finally{send.disabled=false;msg.focus();}}
send.onclick=go;
msg.addEventListener('keydown',e=>{if(e.key==='Enter')go();});
</script>
</body></html>"""
