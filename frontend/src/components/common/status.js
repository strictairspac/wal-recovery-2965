import {DRILL_STATUSES,REPLAY_STATUSES,SHARD_STATUSES} from '../../constants/enums.js';
import {esc} from '../../utils/html.js';
export const badge=(status)=>`<span class="badge ${esc(status)}">${esc(DRILL_STATUSES[status]||status)}</span>`;
export const replayBadge=(status)=>`<span class="badge replay-${esc(status)}">${esc(REPLAY_STATUSES[status]||status)}</span>`;
export const shardBadge=(status)=>`<span class="badge shard-${esc(status)}">${esc(SHARD_STATUSES[status]||status)}</span>`;
