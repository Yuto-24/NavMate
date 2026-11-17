// Test-only AuthProvider. No account/network operations or personal data.
import { createRoot } from 'react-dom/client';
import { AccountControl, AccountNotice } from '../../src/components/AccountControl';
import type { AuthProvider, AuthState } from '../../src/auth';
import '../../src/styles.css';
let state: AuthState = {account:null,available:true};
const listeners = new Set<()=>void>();
function publish(next:AuthState) {state=next; listeners.forEach(fn=>fn());}
let retries=0;
const auth:AuthProvider={getState:()=>state,subscribe:fn=>{listeners.add(fn);return()=>listeners.delete(fn)},
 signIn:async()=>{
  if (new URLSearchParams(location.search).has('pending-login')) await new Promise<void>((resolve,reject)=>{
   (window as any).completeLogin = (failure:boolean)=>failure ? reject(new Error('Test: login failed')) : resolve();
  });
 },signOut:async()=>{retries++;publish({account:null,available:true});}};
function Test(){return <>
 <header className="app-header"><AccountControl auth={auth} busy={false} networkAvailability={()=>'online'}/></header>
 <main style={{paddingTop:70,minHeight:1200}}>
  <button onClick={()=>publish({account:null,available:true,signOutPending:true,notice:'Test: sign-out failed'})}>Test: notify</button>
  <button onClick={()=>publish({...state,notice:'Test: newer failure'})}>Test: newer notice</button>
  <output id="retries">{retries}</output>
 </main>
 <div id="app-notification-region" className="app-notification-region"><AccountNotice auth={auth}/></div>
 </>}
createRoot(document.getElementById('root')!).render(<Test/>);
