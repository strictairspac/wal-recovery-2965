import {logSetsAPI,crashCasesAPI,recoveriesAPI,replaysAPI} from '../api/entities.js';
export const store={logs:[],cases:[],runs:[],replays:[],async refresh(){[this.logs,this.cases,this.runs,this.replays]=await Promise.all([logSetsAPI.list(),crashCasesAPI.list(),recoveriesAPI.list(),replaysAPI.list()]);}};
