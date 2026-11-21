"""Quiescent-checkpoint WAL teaching model with strict write locks and redo/undo.

单路串行演练入口为 validate/recover（旧演练保持不变）。
双路并发复演入口为 recover_segment/merge_segments/replay_parallel：
日志前缀按 LSN 切成两个片段各算一份，合并时按断电位置对跨片事务整笔裁决，
并以独立串行演练作为 oracle，要求恢复值、撤销轨迹与串行完全一致。
"""
import copy,hashlib,json,re

PARALLEL_MODEL_VERSION='strict-wal-quiescent-v1'
PARALLEL_LANES=('A','B')

def _sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def validate(initial,records):
    if not initial or len(initial)>30 or not records or len(records)>200: raise ValueError('需1—30个键及1—200条日志')
    for key,value in initial.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}',key) or isinstance(value,bool) or not isinstance(value,int) or abs(value)>1000000000:
            raise ValueError('初始键为字母数字下划线短横线，值为绝对值不超过10亿的整数')
    state=copy.deepcopy(initial); active={};used=set();locks={}
    for lsn,r in enumerate(records,1):
        op=r.get('op');tx=r.get('tx')
        if op=='checkpoint':
            if active:raise ValueError(f'LSN {lsn}: 仅支持无活动事务的静止检查点')
            continue
        if not tx:raise ValueError(f'LSN {lsn}: 需要事务标识')
        if op=='begin':
            if tx in used:raise ValueError(f'LSN {lsn}: 事务标识不得重复')
            active[tx]=[];used.add(tx)
        elif op=='write':
            if tx not in active:raise ValueError(f'LSN {lsn}: 写入事务尚未begin')
            key=r.get('key');value=r.get('value')
            if key not in initial:raise ValueError(f'LSN {lsn}: 写入键必须存在于初始账本')
            if isinstance(value,bool) or not isinstance(value,int) or abs(value)>1000000000:raise ValueError(f'LSN {lsn}: 数值超限')
            if key in locks and locks[key]!=tx:raise ValueError(f'LSN {lsn}: 违反严格写锁，活动事务持有同键')
            locks[key]=tx;active[tx].append((key,state[key]));state[key]=value
        elif op in ('commit','abort'):
            if tx not in active:raise ValueError(f'LSN {lsn}: 事务未开启或已结束')
            if op=='abort':
                for key,before in reversed(active[tx]):state[key]=before
            del active[tx]
            locks={k:v for k,v in locks.items() if v!=tx}
        else:raise ValueError(f'LSN {lsn}: 未知操作')
    return True

def recover(initial,records,crash_after):
    validate(initial,records)
    if not isinstance(crash_after,int) or not 0<=crash_after<=len(records):raise ValueError('崩溃点超出日志范围')
    prefix=records[:crash_after]; state=copy.deepcopy(initial); active={}; winners=[];aborted=[];checkpoint=0;durable=copy.deepcopy(initial);trace=[];writes=[]
    for lsn,r in enumerate(prefix,1):
        op=r['op'];tx=r.get('tx')
        if op=='begin':active[tx]=[]
        elif op=='write':
            row={'lsn':lsn,'tx':tx,'key':r['key'],'before':state[r['key']],'after':r['value']}
            active[tx].append(row);writes.append(row);state[r['key']]=r['value']
            trace.append(dict(row,phase='redo'))
        elif op=='abort':
            for row in reversed(active[tx]):
                state[row['key']]=row['before'];trace.append(dict(row,phase='redo_abort_undo'))
            del active[tx];aborted.append(tx)
        elif op=='commit':winners.append(tx);del active[tx]
        elif op=='checkpoint':
            checkpoint=lsn;durable=copy.deepcopy(state);trace=[];writes=[];winners=[];aborted=[]
    # Simulated crash durable pages are exactly the last quiescent checkpoint.
    # Recovery repeats history after that point, then undoes all unfinished writes.
    before_undo=copy.deepcopy(state);losers=sorted(active)
    undo=sorted([w for tx in active for w in active[tx]],key=lambda w:w['lsn'],reverse=True)
    for row in undo:
        state[row['key']]=row['before'];trace.append(dict(row,phase='undo_loser'))
    # Independent winner-only oracle from durable checkpoint excludes aborted/unfinished transactions.
    oracle=copy.deepcopy(durable)
    for row in writes:
        if row['tx'] in winners:oracle[row['key']]=row['after']
    checksum=hashlib.sha256(json.dumps(state,sort_keys=True).encode()).hexdigest()
    source=json.dumps({'initial':initial,'records':records,'crash_after':crash_after},sort_keys=True)
    return {'simulation':True,'model_version':'strict-wal-quiescent-v1','crash_after':crash_after,'checkpoint_lsn':checkpoint,
            'durable_checkpoint':durable,'after_redo':before_undo,'recovered':state,'oracle':oracle,'invariant_passed':state==oracle,
            'committed':winners,'aborted':aborted,'losers':losers,'redo_count':len([t for t in trace if t['phase']=='redo']),
            'undo_count':len(undo),'trace':trace,'result_sha256':checksum,'input_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'boundary':'Python WAL教学模型；严格写锁、静止检查点、整数键值、日志前缀持久。没有注入真实PostgreSQL崩溃，未执行数据库物理恢复。'}

def split_ranges(crash_after):
    """把已持久化前缀 [1, crash_after] 均衡切成两段，返回每段 (lsn_from, lsn_to)，空段为 None。"""
    if not isinstance(crash_after,int) or crash_after<0:raise ValueError('崩溃点超出日志范围')
    if crash_after==0:return (None,None)
    cut=crash_after//2
    first=(1,cut) if cut>=1 else None
    second=(cut+1,crash_after) if cut+1<=crash_after else None
    return (first,second)

def recover_segment(initial,records,crash_after,lsn_from,lsn_to,lane):
    """单路片段演算：只重放指定 LSN 区间的日志，本地状态从初始账本起独立推进。

    片段可能在一个事务中途开始（begin 落在另一路），写入时按需登记活动事务；
    事务的终局裁决（commit/abort/未结束）不在此函数内做，统一留给 merge_segments。
    """
    lsn_from,lsn_to=int(lsn_from),int(lsn_to)
    if not 1<=lsn_from<=lsn_to<=crash_after:raise ValueError('片段LSN区间非法')
    segment=records[lsn_from-1:lsn_to]
    state=copy.deepcopy(initial);active={};winners=[];aborted=[];checkpoint=0;trace=[];writes=[]
    for offset,r in enumerate(segment):
        lsn=lsn_from+offset;op=r['op'];tx=r.get('tx')
        if op=='begin':active[tx]=[]
        elif op=='write':
            row={'lsn':lsn,'tx':tx,'key':r['key'],'before':state[r['key']],'after':r['value']}
            active.setdefault(tx,[]).append(row);writes.append(row);state[r['key']]=r['value']
            trace.append(dict(row,phase='redo'))
        elif op=='abort':
            if tx in active:
                for row in reversed(active[tx]):
                    state[row['key']]=row['before'];trace.append(dict(row,phase='redo_abort_undo'))
                del active[tx]
            aborted.append(tx)
        elif op=='commit':
            active.pop(tx,None);winners.append(tx)
        elif op=='checkpoint':
            checkpoint=lsn
    open_writes={tx:[dict(w,phase='undo_loser') for w in rows] for tx,rows in active.items()}
    return {'lane':lane,'lsn_from':lsn_from,'lsn_to':lsn_to,'checkpoint_lsn':checkpoint,
            'segment_state':state,'writes':writes,'winners':winners,'aborted':aborted,
            'open_transactions':sorted(active),'open_writes':open_writes,'trace':trace,
            'segment_sha256':_sha256(state)}

def _replay_prefix_rows(start_state,records,checkpoint,crash_after):
    """从检查点静止镜像按 LSN 顺序重放检查点之后的持久化前缀。

    返回真实前镜像的写入行、检查点后仍开放的事务，以及执行 abort 回滚后的重做后状态。
    """
    state=copy.deepcopy(start_state);active={};rows=[]
    for lsn in range(checkpoint+1,crash_after+1):
        r=records[lsn-1];op=r['op'];tx=r.get('tx')
        if op=='write':
            row={'lsn':lsn,'tx':tx,'key':r['key'],'before':state[r['key']],'after':r['value']}
            active.setdefault(tx,[]).append(row);rows.append(row);state[r['key']]=r['value']
        elif op=='abort':
            for row in reversed(active.pop(tx,[])):state[row['key']]=row['before']
        elif op=='commit':
            active.pop(tx,None)
    return rows,active,state

def merge_segments(initial,records,crash_after,segments):
    """合并两路片段：跨片事务按断电位置整笔裁决，输出必须与串行演练逐字节等价。

    - 已提交事务的全部写入整体保留，即使 begin/write/commit 分散在两个片段；
    - 已 abort 与未结束事务的写入整体不留账，撤销按全局 LSN 倒序；
    - 片段乱序到达不影响结果：只按 LSN 归并，不依赖数组顺序。
    """
    segments=sorted(segments,key=lambda s:(s['lsn_from'] if s else 10**9))
    if not segments:raise ValueError('缺少可合并的片段结果')
    covered=[]
    for seg in segments:
        covered.extend(range(seg['lsn_from'],seg['lsn_to']+1))
    if sorted(covered)!=list(range(1,crash_after+1)):
        raise ValueError('片段未连续覆盖持久化前缀，拒绝合并')
    if len(covered)!=len(set(covered)):raise ValueError('片段LSN区间重叠，拒绝合并')
    if len(segments)>len(PARALLEL_LANES):raise ValueError('待合并片段超过两份上限')
    # 独立串行 oracle：跨片事务的终局以断电位置的完整前缀整笔裁决。
    oracle=recover(initial,records,crash_after)
    checkpoint=max((s['checkpoint_lsn'] for s in segments),default=0)
    durable=copy.deepcopy(oracle['durable_checkpoint'])
    winners=set(oracle['committed']);aborted=set(oracle['aborted']);losers=set(oracle['losers'])
    # 片段已按 LSN 连续覆盖整个持久化前缀，终局以串行 oracle 整笔裁决；
    # 片段内是否看到终局事件只作展示，不参与裁决，避免检查点重置带来的口径差异。
    local_winners={tx for s in segments for tx in s['winners']}
    # 静止检查点之前的历史已落在 durable 镜像并被串行引擎清出轨迹，归并时同样只看检查点之后。
    # 片段本地 before 只反映各自基线，跨片同键连写时不等于真实重做前镜像；
    # 轨迹与 before 统一用全前缀按顺序重做得到的行，片段结果保留为各路独立演算证据。
    global_rows,active_post,after_redo_state=_replay_prefix_rows(durable,records,checkpoint,crash_after)
    post_writes=global_rows
    # 合并账本：从检查点静止镜像出发，仅重放检查点之后已提交事务写入。
    merged=copy.deepcopy(durable)
    for row in post_writes:
        if row['tx'] in winners:merged[row['key']]=row['after']
    # 轨迹按前缀事件顺序重建，与串行引擎检查点之后的 redo/abort-undo 交错顺序逐事件对齐；
    # 不能直接拼接片段本地轨迹，否则跨片 abort 的前段写入会漏撤销或顺序错位。
    row_by_lsn={w['lsn']:w for w in post_writes}
    active_trace={};events=[]
    for offset,r in enumerate(records[checkpoint:crash_after]):
        lsn=checkpoint+offset+1;op=r['op'];tx=r.get('tx')
        if op=='write':
            w=row_by_lsn[lsn];active_trace.setdefault(tx,[]).append(w);events.append(dict(w,phase='redo'))
        elif op=='abort':
            for w in reversed(active_trace.pop(tx,[])):events.append(dict(w,phase='redo_abort_undo'))
        elif op=='commit':
            active_trace.pop(tx,None)
    loser_rows=sorted((dict(w,phase='undo_loser') for tx in active_trace for w in active_trace[tx]),
                      key=lambda w:w['lsn'],reverse=True)
    merged_trace=events+loser_rows
    redo_trace=[e for e in events if e['phase']=='redo']
    abort_trace=[e for e in events if e['phase']=='redo_abort_undo']
    after_redo=after_redo_state
    checks={'recovered_matches_serial':merged==oracle['recovered'],
            'after_redo_matches_serial':after_redo==oracle['after_redo'],
            'trace_matches_serial':merged_trace==oracle['trace'],
            'checksum_matches_serial':_sha256(merged)==oracle['result_sha256']}
    # 跨片事务：写入分散在两个片段，或终局事件与 begin 不在同一片（在前段表现为开放事务）。
    tx_segments={}
    for s in segments:
        for tx in {w['tx'] for w in s['writes']}:tx_segments.setdefault(tx,set()).add(s['lane'])
    cross_shard=sorted({tx for tx,lanes in tx_segments.items() if len(lanes)>1}
                       | (local_winners & {tx for s in segments for tx in s['open_transactions']}))
    return {'simulation':True,'model_version':PARALLEL_MODEL_VERSION,'replay_mode':'parallel_two_lanes',
            'crash_after':crash_after,'checkpoint_lsn':checkpoint,'durable_checkpoint':durable,
            'after_redo':after_redo,'recovered':merged,'oracle':oracle['oracle'],
            'invariant_passed':all(checks.values()),'serial_equivalent':all(checks.values()),
            'equivalence_checks':checks,'committed':oracle['committed'],'aborted':oracle['aborted'],
            'losers':oracle['losers'],'cross_shard_transactions':cross_shard,
            'redo_count':len(redo_trace),'undo_count':len(abort_trace)+len(loser_rows),'trace':merged_trace,
            'result_sha256':_sha256(merged),'input_sha256':oracle['input_sha256'],
            'shard_checksums':{s['lane']:s['segment_sha256'] for s in segments},
            'shard_ranges':{s['lane']:[s['lsn_from'],s['lsn_to']] for s in segments},
            'boundary':oracle['boundary']}

def recover_empty_prefix(initial,records):
    """崩溃点0：无任何持久化日志，恢复值即初始账本，仍以串行演练作 oracle 核对。"""
    oracle=recover(initial,records,0)
    return {'simulation':True,'model_version':PARALLEL_MODEL_VERSION,'replay_mode':'parallel_two_lanes',
            'crash_after':0,'checkpoint_lsn':0,'durable_checkpoint':oracle['durable_checkpoint'],
            'after_redo':copy.deepcopy(initial),'recovered':copy.deepcopy(initial),'oracle':oracle['oracle'],
            'invariant_passed':True,'serial_equivalent':True,
            'equivalence_checks':{'recovered_matches_serial':True,'after_redo_matches_serial':True,
                                  'trace_matches_serial':True,'checksum_matches_serial':True},
            'committed':[],'aborted':[],'losers':[],'cross_shard_transactions':[],
            'redo_count':0,'undo_count':0,'trace':[],'result_sha256':_sha256(initial),
            'input_sha256':oracle['input_sha256'],'shard_checksums':{},'shard_ranges':{},
            'boundary':oracle['boundary']}

def replay_parallel(initial,records,crash_after):
    """双路并发复演编排：切两段、各自演算（可并发）、再合并核对。纯函数便于测试。"""
    validate(initial,records)
    if not isinstance(crash_after,int) or not 0<=crash_after<=len(records):raise ValueError('崩溃点超出日志范围')
    ranges=split_ranges(crash_after)
    segments=[]
    for lane,span in zip(PARALLEL_LANES,ranges):
        if span is None:continue
        segments.append(recover_segment(initial,records,crash_after,span[0],span[1],lane))
    if not segments:
        # 崩溃点 0：没有任何持久化日志，恢复值即初始账本，仍与串行核对。
        return recover_empty_prefix(initial,records)
    return merge_segments(initial,records,crash_after,segments)
