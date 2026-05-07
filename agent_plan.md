import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, AlertTriangle, CheckCircle2, Clock, Crosshair, FileText, KeyRound, Play, RefreshCw, Shield, TerminalSquare, Wifi } from 'lucide-react';
import './styles.css';

const API = '';
async function api(path, opts = {}) {
  const res = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
function post(path, body = {}) { return api(path, { method: 'POST', body: JSON.stringify(body) }); }

function Badge({children, tone='neutral'}) { return <span className={`badge ${tone}`}>{children}</span>; }
function Card({children, className=''}) { return <section className={`card ${className}`}>{children}</section>; }
function Empty({children}) { return <div className="empty">{children}</div>; }

function App() {
  const [targets, setTargets] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [target, setTarget] = useState(null);
  const [ip, setIp] = useState('');
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState(null);
  const [view, setView] = useState('dashboard');

  async function refresh() {
    const ts = await api('/api/targets');
    setTargets(ts);
    const id = activeId || ts[0]?.id;
    if (id) {
      setActiveId(id);
      const t = await api(`/api/targets/${id}`);
      setTarget(t);
    } else {
      setTarget(null);
    }
  }
  useEffect(() => { refresh(); const i = setInterval(refresh, 5000); return () => clearInterval(i); }, [activeId]);

  async function createTarget(e) {
    e.preventDefault();
    if (!ip.trim()) return;
    setBusy(true);
    try {
      const t = await post('/api/targets', { ip: ip.trim() });
      setActiveId(t.id);
      setIp('');
      await post(`/api/targets/${t.id}/initial-recon`);
      await refresh();
    } finally { setBusy(false); }
  }

  async function runPlan(executeSafe=false) {
    if (!target) return;
    setBusy(true);
    try {
      const p = await post(`/api/targets/${target.id}/agent/plan`, { goal: 'Continue the operation from current evidence and propose next steps.', execute_safe: executeSafe });
      setPlan(p); await refresh();
    } finally { setBusy(false); }
  }

  async function approve(id) { await post(`/api/targets/${target.id}/approvals/${id}/approve`); await refresh(); }
  async function deny(id) { await post(`/api/targets/${target.id}/approvals/${id}/deny`, {reason:'Denied from UI'}); await refresh(); }
  async function syncHosts() { await post(`/api/targets/${target.id}/hosts/sync`); await refresh(); }
  async function updateReport() { await post(`/api/targets/${target.id}/report/update`); await refresh(); }

  const pending = (target?.approvals || []).filter(a => a.status === 'pending');
  const jobs = target?.jobs || [];
  const latestJobs = jobs.slice(-8).reverse();
  const services = target?.state?.services || [];
  const findings = target?.findings || [];
  const credentials = target?.credentials || [];
  const timeline = target?.timeline || [];

  return <div className="app">
    <aside className="sidebar">
      <div className="brand"><Shield size={24}/><div><b>HTB Mission</b><span>Control MVP</span></div></div>
      <form onSubmit={createTarget} className="target-form">
        <input value={ip} onChange={e=>setIp(e.target.value)} placeholder="Target IP e.g. 10.129.30.34" />
        <button disabled={busy}><Crosshair size={16}/> Start</button>
      </form>
      <div className="target-list">
        {targets.map(t => <button key={t.id} className={activeId===t.id?'active':''} onClick={()=>setActiveId(t.id)}>
          <span>{t.name || t.ip}</span><small>{t.ip}</small>
        </button>)}
      </div>
      <nav>
        {['dashboard','approvals','jobs','findings','evidence','report'].map(v => <button key={v} onClick={()=>setView(v)} className={view===v?'active':''}>{v}</button>)}
      </nav>
    </aside>
    <main>
      <header className="topbar">
        <div>
          <h1>{target ? target.name : 'No target selected'}</h1>
          <p>{target ? `${target.ip} · ${target.state?.access_level || 'no access'} · ${services.length} services` : 'Add an HTB target IP to begin.'}</p>
        </div>
        <div className="actions">
          <button onClick={refresh}><RefreshCw size={16}/> Refresh</button>
          {target && <button onClick={()=>runPlan(false)} disabled={busy}><Activity size={16}/> Ask Agent</button>}
          {target && <button className="primary" onClick={()=>runPlan(true)} disabled={busy}><Play size={16}/> Continue Safe</button>}
        </div>
      </header>

      {!target ? <Landing/> : <>
        {view === 'dashboard' && <Dashboard target={target} pending={pending} jobs={latestJobs} services={services} findings={findings} timeline={timeline} plan={plan} approve={approve} deny={deny} syncHosts={syncHosts} updateReport={updateReport}/>} 
        {view === 'approvals' && <Approvals pending={pending} all={target.approvals || []} approve={approve} deny={deny}/>} 
        {view === 'jobs' && <Jobs target={target} refresh={refresh}/>} 
        {view === 'findings' && <Findings findings={findings} credentials={credentials}/>} 
        {view === 'evidence' && <Evidence target={target}/>} 
        {view === 'report' && <Report target={target} updateReport={updateReport}/>} 
      </>}
    </main>
  </div>
}

function Landing(){ return <div className="grid"><Card><h2>Mission Control</h2><p>Enter an HTB target IP. The app creates a persistent case folder, starts recon, saves output, extracts findings, and asks before risky actions.</p></Card></div> }

function Dashboard({target,pending,jobs,services,findings,timeline,plan,approve,deny,syncHosts,updateReport}){
  return <div className="grid dash">
    <Card className="hero">
      <div className="hero-row"><div><h2>{target.ip}</h2><p>{(target.hostnames||[]).map(h=>h.hostname).join(', ') || 'No hostnames yet'}</p></div><Badge tone={pending.length?'danger':'good'}>{pending.length} approvals</Badge></div>
      <div className="metric-row"><Metric label="Risk" value={target.state?.risk_score || 0}/><Metric label="Services" value={services.length}/><Metric label="Findings" value={findings.length}/><Metric label="Jobs" value={(target.jobs||[]).length}/></div>
      <div className="quick"><button onClick={syncHosts}><Wifi size={16}/> Sync hosts</button><button onClick={updateReport}><FileText size={16}/> Update report</button></div>
    </Card>
    <Card><h3>Pending approvals</h3>{pending.length?pending.slice(0,3).map(a=><ApprovalCard key={a.id} a={a} approve={approve} deny={deny}/>):<Empty>No risky actions waiting.</Empty>}</Card>
    <Card><h3>Services</h3>{services.length?services.map(s=><div className="row" key={s.port}><b>{s.port}/tcp</b><span>{s.service}</span><small>{s.detail}</small></div>):<Empty>No services parsed yet.</Empty>}</Card>
    <Card><h3>Latest jobs</h3>{jobs.length?jobs.map(j=><JobRow key={j.id+j.updated_at} j={j}/>):<Empty>No jobs yet.</Empty>}</Card>
    <Card><h3>Top findings</h3>{findings.length?findings.slice(-5).reverse().map(f=><FindingRow key={f.id} f={f}/>):<Empty>No findings yet.</Empty>}</Card>
    <Card><h3>Agent plan</h3>{plan?<Plan plan={plan}/>:<Empty>Ask Agent to generate next actions.</Empty>}</Card>
    <Card className="wide"><h3>Timeline</h3>{timeline.slice(-10).reverse().map(e=><div className="timeline" key={e.id}><Clock size={14}/><span>{e.type}</span><small>{JSON.stringify(e.data).slice(0,140)}</small></div>)}</Card>
  </div>
}
function Metric({label,value}){return <div className="metric"><b>{value}</b><span>{label}</span></div>}
function ApprovalCard({a,approve,deny}){return <div className="approval"><div><AlertTriangle size={18}/><b>{a.action_type}</b><Badge tone="danger">approval</Badge></div><code>{a.command}</code><p>{(a.reasons||[]).join(', ')}</p><div><button onClick={()=>deny(a.id)}>Deny</button><button className="primary" onClick={()=>approve(a.id)}><CheckCircle2 size={16}/> Approve</button></div></div>}
function JobRow({j}){return <div className="job"><span className={`dot ${j.status}`}></span><b>{j.label}</b><Badge tone={j.status==='completed'?'good':j.status==='failed'?'danger':'neutral'}>{j.status}</Badge><small>{j.command}</small></div>}
function FindingRow({f}){return <div className="finding"><b>{f.title}</b><Badge tone={f.severity==='high'?'danger':f.severity==='medium'?'warn':'neutral'}>{f.severity}</Badge><small>confidence {f.confidence}</small></div>}
function Plan({plan}){return <div><p>{plan.summary}</p>{(plan.proposed_actions||[]).map((a,i)=><div className="action" key={i}><b>{a.label}</b><Badge tone={a.risk==='approval_required'?'danger':'good'}>{a.risk}</Badge><code>{a.command}</code><p>{a.why}</p></div>)}</div>}
function Approvals({pending,all,approve,deny}){return <div className="grid"><Card className="wide"><h2>Approvals</h2>{all.length?all.slice().reverse().map(a=><ApprovalCard key={a.id} a={a} approve={approve} deny={deny}/>):<Empty>No approvals yet.</Empty>}</Card></div>}
function Jobs({target,refresh}){return <div className="grid"><Card className="wide"><h2>Jobs</h2>{(target.jobs||[]).slice().reverse().map(j=><JobRow key={j.id+j.updated_at} j={j}/>)}</Card></div>}
function Findings({findings,credentials}){return <div className="grid"><Card><h2>Findings</h2>{findings.map(f=><FindingRow key={f.id} f={f}/>)}</Card><Card><h2>Credentials</h2>{credentials.length?credentials.map(c=><div className="cred" key={c.id}><KeyRound size={16}/><b>{c.username}</b><code>{c.password || c.secret}</code><small>{c.service}</small></div>):<Empty>No creds yet.</Empty>}</Card></div>}
function Evidence({target}){return <div className="grid"><Card className="wide"><h2>Evidence</h2><p>Evidence index is updated by jobs. Raw output paths are stored in job rows and report.</p>{(target.jobs||[]).filter(j=>j.output_path).slice().reverse().map(j=><div className="row" key={j.id}><TerminalSquare size={16}/><b>{j.label}</b><code>{j.output_path}</code></div>)}</Card></div>}
function Report({target,updateReport}){return <div className="grid"><Card className="wide"><div className="hero-row"><h2>Live Report</h2><button onClick={updateReport}>Regenerate</button></div><pre className="report">{target.report}</pre></Card></div>}

createRoot(document.getElementById('root')).render(<App />);
