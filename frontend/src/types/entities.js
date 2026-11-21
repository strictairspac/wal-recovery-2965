/** @typedef {{id:number,name:string,initial:object,records:object[],description:string}} LogSet */
/** @typedef {{id:number,name:string,log_set_id:number,crash_after:number}} CrashCase */
/** @typedef {{id:number,crash_case_id:number,label:string,status:string,snapshot:object,result:object|null}} Recovery */
/** @typedef {{id:number,replay_id:number,lane:'A'|'B',lsn_from:number|null,lsn_to:number|null,status:string,attempts:number,result:object|null,last_error:string|null}} ReplayShard */
/** @typedef {{id:number,crash_case_id:number,label:string,status:string,snapshot:object,result:object|null,attempts_total:number,published_at:string|null,shards:ReplayShard[]}} Replay */
export {};
