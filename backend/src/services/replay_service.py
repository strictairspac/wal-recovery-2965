from sqlalchemy import select
from fastapi import HTTPException
from src.models.entities import Replay, ReplayShard, CrashCase, LogSet
from src.constants.enums import LANES, REPLAY_QUEUE_QUOTA
from src.utils.serialize import record

def list_replays(db):
    return [record_with_shards(x) for x in db.scalars(select(Replay).order_by(Replay.id.desc()).limit(100))]

def get_replay(db, ident):
    obj = db.get(Replay, ident)
    if obj is None:
        raise HTTPException(404, '复演记录不存在')
    return obj

def record_with_shards(obj):
    out = record(obj)
    out['shards'] = [record(s) for s in obj.shards]
    return out

def create_replay(db, data):
    case = db.get(CrashCase, data.crash_case_id)
    if case is None:
        raise HTTPException(404, '故障场景不存在')
    pending = len(db.scalars(
        select(Replay.id).where(Replay.status.in_(['queued', 'running', 'paused']))
    ).all())
    if pending >= REPLAY_QUEUE_QUOTA:
        raise HTTPException(429, '待处理配额20已满')
    logs = db.get(LogSet, case.log_set_id)
    obj = Replay(crash_case_id=case.id, label=data.label, status='queued',
                 snapshot={'log_set': record(logs), 'case': record(case)})
    db.add(obj)
    db.flush()
    # 两个片段在入队时即落库，状态 pending，等待 A/B 两条通道领取。
    from src.services.wal_engine import split_ranges
    ranges = split_ranges(case.crash_after)
    for lane, span in zip(LANES, ranges):
        db.add(ReplayShard(replay_id=obj.id, lane=lane,
                           lsn_from=span[0] if span else None,
                           lsn_to=span[1] if span else None,
                           status='pending' if span else 'ready'))
    db.flush()
    return obj

def pause_lane(db, ident, lane):
    if lane not in LANES:
        raise HTTPException(422, '通道标识必须为 A 或 B')
    obj = get_replay(db, ident)
    if obj.status == 'published':
        raise HTTPException(409, '复演已发布，不能暂停通道')
    shard = _get_shard(obj, lane)
    if shard.status == 'pending':
        # 仅拦截该路尚未领取的片段；已在演算的片段不受打断，跑完自然就绪。
        # 只暂停这一路，另一路仍可领取并推进，复演整体保持活动（running）。
        shard.status = 'paused'
        if obj.status == 'queued':
            obj.status = 'running'
    elif shard.status == 'running':
        raise HTTPException(409, f'通道{lane}正在演算，完成后可暂停后续领取')
    else:
        raise HTTPException(409, f'通道{lane}当前为{shard.status}，无需暂停')
    return obj

def resume_lane(db, ident, lane):
    if lane not in LANES:
        raise HTTPException(422, '通道标识必须为 A 或 B')
    obj = get_replay(db, ident)
    if obj.status == 'published':
        raise HTTPException(409, '复演已发布，不能恢复通道')
    shard = _get_shard(obj, lane)
    if shard.status != 'paused':
        raise HTTPException(409, f'通道{lane}未处于暂停状态')
    shard.status = 'pending'
    if obj.status == 'queued':
        obj.status = 'running'
    return obj

def retry_replay(db, ident):
    """失败后整笔重试：只重置未就绪的片段，已就绪片段结果保留，不重复计数。"""
    obj = get_replay(db, ident)
    if obj.status == 'published':
        raise HTTPException(409, '复演已发布，无需重试')
    if obj.status not in ('failed', 'paused', 'running', 'queued'):
        raise HTTPException(409, '当前状态不能重试')
    for shard in obj.shards:
        if shard.lsn_from is None:
            continue
        # 已就绪片段的结果保留、不重新计数；只重置失败/暂停/在途/待领取的片段。
        if shard.status == 'ready':
            continue
        shard.status = 'pending'
        shard.last_error = None
    obj.status = 'queued'
    obj.result = None
    obj.published_at = None
    return obj

def _get_shard(replay, lane):
    for shard in replay.shards:
        if shard.lane == lane:
            return shard
    raise HTTPException(404, f'通道{lane}不存在')
