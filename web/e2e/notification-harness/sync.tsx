// Synthetic sync transport only; actual notification/account/conflict components.
import { createRoot } from 'react-dom/client';
import { useState, useSyncExternalStore } from 'react';
import { AccountControl } from '../../src/components/AccountControl';
import { AccountSyncControl } from '../../src/components/AccountSyncControl';
import { TransientMessage } from '../../src/components/TransientMessage';
import { useNotificationState } from '../../src/useNotificationState';
import type { AccountSyncControl as Control, SyncStatus } from '../../src/accountSync';
import '../../src/styles.css';
let state:SyncStatus={conflicts:[],imports:[],undo:[],generation:0};
let fail=true;
const listeners=new Set<()=>void>();
const publish=(next:SyncStatus)=>{state=next;listeners.forEach(fn=>fn())};
const sync:Control={getState:()=>state,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},
 resolve:async()=>'',importLatest:async()=>{},undo:async id=>{if(fail)throw new Error(`Test: undo ${id} failed`);}};
function Test(){
 const status=useSyncExternalStore(sync.subscribe,sync.getState);
 const [error,setError,revision]=useNotificationState();
 const [errors,setErrors]=useState<string[]>([]);
 return <>
 <header className="app-header"><AccountControl busy={false} networkAvailability={()=>'online'} syncMessages={[status.notice,...errors].filter((v):v is string=>!!v)}/></header>
 <main style={{paddingTop:70,minHeight:1200}}>
 <button onClick={()=>{publish({...state,notice:'Test: sync offline',undo:[{id:'A',name:'A',until:Date.now()+10000},{id:'B',name:'B',until:Date.now()+10000}]});setTimeout(()=>publish({...state,undo:[]}),10000)}}>Test: notify</button>
 <button onClick={()=>{fail=false}}>Test: allow retry</button>
 <button onClick={()=>publish({...state,notice:undefined})}>Test: sync recovered</button>
 </main>
 <AccountSyncControl sync={sync} notificationsManaged onErrorChange={setError} onErrorsChange={setErrors} onChange={()=>{}} onResolved={async()=>{}}/>
 <div className="app-notification-region"><TransientMessage message={status.notice}/><TransientMessage message={error} revision={revision}/></div>
 </>;
}
createRoot(document.getElementById('root')!).render(<Test/>);
