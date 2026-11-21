ROLES = ('admin', 'operator', 'viewer')
# 旧版单路恢复演练状态，保持兼容。
DRILL_STATUSES = ('queued', 'running', 'completed', 'failed')
# 双路并发复演状态：片段全部核对并通过后才会进入 published，失败可重试回到 running。
REPLAY_STATUSES = ('queued', 'running', 'paused', 'failed', 'published')
# 单个分片（一路）的状态。
SHARD_STATUSES = ('pending', 'running', 'ready', 'paused', 'failed')
# 固定两条复演通道，一路卡住不影响另一路领取任务。
LANES = ('A', 'B')
# 待合并的片段结果最多保留两份（每条复演每路一份）。
MAX_MERGE_BUFFER_PER_REPLAY = 2
# 待执行配额沿用旧演练口径。
REPLAY_QUEUE_QUOTA = 20
