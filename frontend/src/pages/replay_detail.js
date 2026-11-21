import {table} from '../components/common/table.js';
import {replayBadge,shardBadge} from '../components/common/status.js';
import {esc} from '../utils/html.js';
import {downloadReplay} from '../api/client.js';
import {replaysAPI} from '../api/entities.js';
import {session} from '../stores/session.js';
import {message} from '../hooks/action.js';

const writable=()=>session.role!=='viewer';

function shardPanel(r){
 return table(['通道','LSN 片段','状态','尝试次数','片段校验和','错误'],r.shards.map(s=>[
   esc(s.lane),
   s.lsn_from==null?'空片段（崩溃点0）':`${s.lsn_from} → ${s.lsn_to}`,
   shardBadge(s.status),
   s.attempts,
   esc(s.result?.segment_sha256?.slice(0,16)||'—'),
   s.last_error?esc(s.last_error):'',
 ]));
}

function mergedPanel(r){
 const m=r.result;
 if(!m)return '<p class="notice">两路片段尚未全部就绪，账本与完成状态会在核对通过后一起发布。</p>';
 if(m.error)return `<p class="notice error">${esc(m.error)}</p>`;
 const checks=m.equivalence_checks||{};
 return `<section class="verdict"><div><p>串行等价核对（双路合并 vs 串行演练）</p><h2>${m.serial_equivalent?'恢复值与撤销顺序一致':'核对未通过'}</h2></div>
 <p>检查点LSN ${m.checkpoint_lsn??'—'} · 崩溃点 ${m.crash_after??'—'}<br>重做 ${m.redo_count??0} 次 / 撤销 ${m.undo_count??0} 次<br>跨片事务 ${esc((m.cross_shard_transactions||[]).join(', ')||'无')}<br>已提交 ${esc((m.committed||[]).join(', ')||'无')} · 未提交撤销 ${esc((m.losers||[]).join(', ')||'无')}</p></section>
 ${table(['核对项','结果'],Object.entries(checks).map(([k,v])=>[esc(k),v?'通过':'未通过']))}
 <h2>合并后账本</h2>
 ${table(['账本键','检查点值','重做后','恢复后','独立提交结果(oracle)'],Object.keys(m.recovered||{}).map(k=>[esc(k),m.durable_checkpoint[k],m.after_redo[k],m.recovered[k],m.oracle[k]]))}
 <h2>恢复轨迹（按全局 LSN，撤销为倒序）</h2>
 ${table(['LSN','事务','阶段','键','before → after'],(m.trace||[]).map(t=>[t.lsn,esc(t.tx),esc(t.phase),esc(t.key),t.phase==='undo_loser'||t.phase==='redo_abort_undo'?`${t.after} → ${t.before}`:`${t.before} → ${t.after}`]))}
 <p class="checksum">输入摘要 ${esc(m.input_sha256||'无')}<br>结果摘要 ${esc(m.result_sha256||'无')}<br>片段校验和 ${esc(JSON.stringify(m.shard_checksums||{}))}</p>`;
}

export function replayDetailPage(r){
 if(!r)return '<section class="empty"><h2>还没有双路复演记录</h2><p>先在双路并发复演页提交任务。</p><a href="#replays">进入复演队列 →</a></section>';
 const can=writable()&&r.status!=='published';
 const laneBtn=lane=>{
  const s=r.shards.find(x=>x.lane===lane);
  if(!s)return '';
  if(s.status==='paused')return `<button class="secondary" data-ctl="resume" data-lane="${lane}">恢复 ${lane} 路</button>`;
  if(s.status==='pending')return `<button class="secondary" data-ctl="pause" data-lane="${lane}">暂停 ${lane} 路</button>`;
  return '';
 };
 return `<div class="section-title"><h2>${esc(r.label)} <small>#${r.id}</small></h2>${replayBadge(r.status)}</div>
 <div class="toolbar">
  ${can?`${laneBtn('A')}${laneBtn('B')}`:''}
  ${can?`<button data-ctl="retry">整笔重试（不重复计数已就绪片段）</button>`:''}
  <button class="secondary" id="replay-export">导出复演证据</button>
  <button class="secondary" id="replay-refresh">刷新状态</button>
 </div>
 <h2>两路片段（待合并结果最多两份）</h2>
 ${shardPanel(r)}
 ${mergedPanel(r)}
 <details><summary>查看冻结输入</summary><pre>${esc(JSON.stringify(r.snapshot,null,2))}</pre></details>`;
}

export function bindReplayDetail(r,render){
 document.querySelector('#replay-refresh')?.addEventListener('click',render);
 document.querySelector('#replay-export')?.addEventListener('click',()=>downloadReplay(r.id).catch(e=>message(e.message,true)));
 document.querySelectorAll('[data-ctl]').forEach(btn=>{
  btn.onclick=async()=>{
   try{
    if(btn.dataset.ctl==='pause')await replaysAPI.pause(r.id,btn.dataset.lane);
    else if(btn.dataset.ctl==='resume')await replaysAPI.resume(r.id,btn.dataset.lane);
    else if(btn.dataset.ctl==='retry')await replaysAPI.retry(r.id);
    message('操作已提交');await render();
   }catch(e){message(e.message,true);}
  };
 });
}
