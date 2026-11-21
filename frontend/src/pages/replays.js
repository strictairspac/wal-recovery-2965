import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {replaysAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {replayBadge,shardBadge} from '../components/common/status.js';
import {esc,formObject} from '../utils/html.js';
import {action,message} from '../hooks/action.js';

const canWrite=()=>session.role!=='viewer';
const backlogOf=r=>r.shards.filter(s=>['pending','running','paused','failed'].includes(s.status)).length;
const laneCell=(r,lane)=>{
 const s=r.shards.find(x=>x.lane===lane);
 if(!s)return '—';
 const range=s.lsn_from==null?'空片段':`LSN ${s.lsn_from}–${s.lsn_to}`;
 const err=s.last_error?`<br><small class="err">${esc(s.last_error)}</small>`:'';
 return `<div class="lane-cell">${shardBadge(s.status)}<small>${range} · 尝试${s.attempts}</small>${err}</div>`;
};
const laneActions=(r,lane)=>{
 if(!canWrite()||r.status==='published')return '';
 const s=r.shards.find(x=>x.lane===lane);
 if(!s)return '';
 if(s.status==='paused')return `<button class="secondary mini" data-act="resume" data-id="${r.id}" data-lane="${lane}">恢复${lane}路</button>`;
 if(s.status==='pending')return `<button class="secondary mini" data-act="pause" data-id="${r.id}" data-lane="${lane}">暂停${lane}路</button>`;
 return '';
};

export function replaysPage(){
 const writable=canWrite();
 return `<section class="split compact"><div><h2>发起双路并发复演</h2><p>持久化前缀按 LSN 均衡切成两个片段，A/B 两路各自演算。一路卡住或暂停时另一路照常推进；待合并结果每路只留最新一份，全笔最多两份。片段全部核对且与串行演练等价后，账本与完成状态才一起发布。</p></div>${writable?`<form id="replay-form"><label>故障场景<select name="crash_case_id">${store.cases.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label><label>记录标签<input name="label" value="晚班双路并发复演" required></label><button type="submit">冻结日志并双路复演 →</button></form>`:'<p class="readonly">观察员可查看两路状态、积压与发布结果。</p>'}</section>
 <div class="section-title"><h2>复演队列（双路）</h2><button class="secondary" id="replay-refresh">刷新状态</button></div>
 ${table(['编号','复演记录','整体状态','A 路','B 路','积压片段','核对/结果','操作'],store.replays.map(r=>[
   r.id,esc(r.label),replayBadge(r.status),
   `${laneCell(r,'A')}${laneActions(r,'A')}`,
   `${laneCell(r,'B')}${laneActions(r,'B')}`,
   `<span class="backlog">${backlogOf(r)} / 2</span>`,
   r.result?.serial_equivalent?'与串行演练一致':r.result?.error?esc(r.result.error):'待合并发布',
   `<a href="#replay-detail/${r.id}">查看两路结果 →</a>${writable&&r.status!=='published'?` <button class="secondary mini" data-act="retry" data-id="${r.id}">整笔重试</button>`:''}`,
 ]))}`;
}

export function bindReplays(render){
 document.querySelector('#replay-refresh').onclick=render;
 action(document.querySelector('#replay-form'),async f=>{
  const d=formObject(f);d.crash_case_id=Number(d.crash_case);
  await replaysAPI.create(d);await render();
 });
 document.querySelectorAll('[data-act]').forEach(btn=>{
  btn.onclick=async()=>{
   const id=Number(btn.dataset.id);
   try{
    if(btn.dataset.act==='pause')await replaysAPI.pause(id,btn.dataset.lane);
    else if(btn.dataset.act==='resume')await replaysAPI.resume(id,btn.dataset.lane);
    else if(btn.dataset.act==='retry')await replaysAPI.retry(id);
    message('操作已提交，刷新查看最新状态');await render();
   }catch(e){message(e.message,true);}
  };
 });
}
