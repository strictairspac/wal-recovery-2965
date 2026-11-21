import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import select, case, func
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.entities import Replay, ReplayShard
from src.services.wal_engine import recover_segment, merge_segments, recover_empty_prefix

logging.basicConfig(level=logging.INFO)
redis = Redis.from_url(REDIS_URL)

# 每个通道一把 Redis 锁：A 路卡住（锁占用/计算慢）不阻塞 B 路领取自己的片段。
LANE_LOCKS = {'A': 'wal-replay-lane-A', 'B': 'wal-replay-lane-B'}
# 收尾合并单独一把锁：两个通道进程只有一个能执行发布，避免重复合并。
SETTLE_LOCK = 'wal-replay-settle'


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _claim_shard(db, lane):
    """领取一条该通道下待执行的片段，行级跳过已锁定行，保证同一片段不会被重复计算。

    复演被暂停（一路暂停）后不再发放新片段；已经在算的片段不受影响，跑完即就绪。
    """
    shard = db.scalar(
        select(ReplayShard)
        .join(Replay, ReplayShard.replay_id == Replay.id)
        .where(ReplayShard.lane == lane,
               ReplayShard.status == 'pending',
               Replay.status.in_(['queued', 'running']))
        .order_by(ReplayShard.replay_id, ReplayShard.id)
        .with_for_update(skip_locked=True)
    )
    if shard is None:
        return None
    shard.status = 'running'
    replay = db.get(Replay, shard.replay_id)
    if replay.status == 'queued':
        replay.status = 'running'
    db.flush()
    return shard


def _run_shard(db, shard):
    replay = db.get(Replay, shard.replay_id)
    snapshot = replay.snapshot
    logs, case = snapshot['log_set'], snapshot['case']
    shard.attempts += 1
    replay.attempts_total += 1
    try:
        result = recover_segment(logs['initial'], logs['records'], case['crash_after'],
                                 shard.lsn_from, shard.lsn_to, shard.lane)
        # 待合并结果每路只保留最新一份：直接覆盖，整笔复演最多两份片段结果。
        shard.result = result
        shard.last_error = None
        shard.status = 'ready'
    except ValueError as exc:
        shard.status = 'failed'
        shard.last_error = str(exc)[:500]
        replay.status = 'failed'
    db.flush()
    return replay


def _try_finalize(db, replay):
    """所有片段核对完才合并：账本与完成状态在同一事务内一起发布。"""
    shards = list(replay.shards)
    if any(s.status == 'failed' for s in shards):
        replay.status = 'failed'
        return
    if not all(s.status == 'ready' for s in shards):
        # 一路被暂停（shard=paused）时另一路仍可领取推进；未全部就绪不发布。
        if replay.status == 'queued':
            replay.status = 'running'
        return
    segments = [s.result for s in shards if s.lsn_from is not None]
    logs, case = replay.snapshot['log_set'], replay.snapshot['case']
    try:
        if not segments:
            # 崩溃点 0：两路均为空片段，直接按空前缀恢复并与串行 oracle 核对。
            merged = recover_empty_prefix(logs['initial'], logs['records'])
        else:
            merged = merge_segments(logs['initial'], logs['records'], case['crash_after'], segments)
    except ValueError as exc:
        replay.status = 'failed'
        replay.result = {'error': str(exc), 'simulation': True}
        for s in shards:
            if s.status == 'ready' and s.lsn_from is not None:
                s.status = 'failed'
                s.last_error = str(exc)[:500]
        return
    if not merged.get('serial_equivalent'):
        replay.status = 'failed'
        replay.result = {'error': '串行等价核对未通过，拒绝发布',
                         'detail': merged.get('equivalence_checks'), 'simulation': True}
        return
    replay.result = merged
    replay.status = 'published'
    replay.published_at = _now()


def process_lane(lane):
    lock = redis.lock(LANE_LOCKS[lane], timeout=30, blocking_timeout=1)
    try:
        with lock:
            with Session() as db:
                shard = _claim_shard(db, lane)
                if shard is None:
                    return
                replay = _run_shard(db, shard)
                db.refresh(replay)
                _try_finalize(db, replay)
                db.commit()
                logging.info('replay %s lane %s shard %s -> replay %s',
                             shard.replay_id, lane, shard.id, replay.status)
    except Exception:
        logging.exception('lane %s worker retry', lane)


def _settle_ready_replays(db):
    """收尾没有可领取片段的复演（如崩溃点0的空片段两路直接就绪），执行合并发布。"""
    ready_flag = case((ReplayShard.status == 'ready', 1), else_=0)
    replay_ids = db.scalars(
        select(ReplayShard.replay_id)
        .join(Replay, ReplayShard.replay_id == Replay.id)
        .where(Replay.status.in_(['queued', 'running']))
        .group_by(ReplayShard.replay_id)
        .having(func.count(ReplayShard.id) == func.sum(ready_flag))
    ).all()
    for rid in replay_ids:
        replay = db.get(Replay, rid)
        if replay is None:
            continue
        _try_finalize(db, replay)


def settle_once():
    """一轮收尾：独立锁保护，两个通道进程不会重复合并同一笔复演。"""
    lock = redis.lock(SETTLE_LOCK, timeout=30, blocking_timeout=1)
    try:
        with lock:
            with Session() as db:
                _settle_ready_replays(db)
                db.commit()
    except Exception:
        logging.exception('settle replay retry')


def main(lane=None):
    # REPLAY_LANE 指定本进程负责的通道；未指定则本进程轮询两路（本地/单机模式）。
    lanes = (lane,) if lane else ('A', 'B')
    heartbeat = f'/tmp/heartbeat-replay-{lane or "all"}'
    while True:
        Path(heartbeat).touch()
        for current in lanes:
            process_lane(current)
        settle_once()
        time.sleep(1)


if __name__ == '__main__':
    main(os.getenv('REPLAY_LANE') or None)
