import {api} from './client.js';
export const logSetsAPI={list:()=>api('/log-sets'),create:data=>api('/log-sets',{method:'POST',body:JSON.stringify(data)})};
export const crashCasesAPI={list:()=>api('/crash-cases'),create:data=>api('/crash-cases',{method:'POST',body:JSON.stringify(data)})};
export const recoveriesAPI={list:()=>api('/recoveries'),get:id=>api('/recoveries/'+id),create:data=>api('/recoveries',{method:'POST',body:JSON.stringify(data)})};
export const replaysAPI={
 list:()=>api('/replays'),
 get:id=>api('/replays/'+id),
 create:data=>api('/replays',{method:'POST',body:JSON.stringify(data)}),
 pause:(id,lane)=>api(`/replays/${id}/lanes/${lane}/pause`,{method:'POST'}),
 resume:(id,lane)=>api(`/replays/${id}/lanes/${lane}/resume`,{method:'POST'}),
 retry:id=>api(`/replays/${id}/retry`,{method:'POST'}),
};
