# 初始化结构
SQLAlchemy metadata.create_all首次建users、log_sets、crash_cases、recoveries、replays、replay_shards、audits。log_sets.name、crash_cases.name唯一，关联使用外键，入队冻结日志和崩溃点快照。暂无在线schema升级器。

## 双路并发复演（replays / replay_shards）
- replays 保存整笔复演：queued/running/paused/failed/published，片段全部核对通过后 result 与 published 状态在同一事务一起发布；attempts_total 累计尝试次数，重试不重复计数（同一片段只在真正被领取时 +1）。
- replay_shards 每笔固定两行，对应 A/B 两条通道与各自 LSN 片段；(replay_id, lane) 唯一。待合并结果每路只保留最新一份（result 覆盖写），整笔复演最多两份。
- 崩溃点为 0 时没有可切片段，两路分片直接 ready，合并结果即初始账本并通过串行等价核对。
- 旧 recoveries 表与单路 worker 保持不变，旧演练照常运行。
