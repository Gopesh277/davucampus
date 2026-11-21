// Dean's Office portal (role "dean"): department timetables · faculty meeting availability · university-wide notices.
// Loaded before app.js and only declares things; it uses app.js's $, api, esc, board, f12, D at call time, so it
// shares the same sign-in, header, tabs and cards as the student / faculty / admin views.
const DV={ov:[],fac:[],snap:null,view:'teacher',sel:new Set()},DAYS=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'];
const fdt=i=>i?new Date(i).toLocaleDateString('en-IN',{day:'numeric',month:'short'}):'';
const t12a=t=>{const[h,m]=t.split(':').map(Number);return`${(h+11)%12+1}:${String(m).padStart(2,'0')} ${h>=12?'PM':'AM'}`};
const r12=(a,b)=>`${t12a(a)} – ${t12a(b)}`,dshort=a=>(a||[]).map(d=>d.short).join(', '),dToday=()=>DAYS[(new Date().getDay()+6)%7];
const AUD={all:'Everyone',students:'Students',faculty:'Faculty',admins:'Dept. admins'};

const dStats=t=>[[`${t.with_timetable}/${t.departments}`,'Depts with timetable'],[t.faculty,'Faculty'],[t.students,'Students']];
async function dRefresh(){const[ov,fac]=await Promise.all([api('/dean/overview'),api('/dean/faculty')]);DV.ov=ov.departments;DV.fac=fac.faculty;
 const keep=new Set(DV.fac.map(f=>f.key));[...DV.sel].forEach(k=>keep.has(k)||DV.sel.delete(k));  // drop anyone a department no longer lists
 const st=$('.board-stats');if(st)st.innerHTML=dStats(ov.totals).map(([n,l])=>`<div class="stat"><div class="stat-num">${esc(n)}</div><div class="stat-label">${esc(l)}</div></div>`).join('');return ov.totals}
async function deanView(){let t;try{t=await dRefresh()}catch(e){$('#app').innerHTML=`<div class="panel-card err">${esc(e.message)}</div>`;return}
 DV.snap=null;DV.view='teacher';DV.sel.clear();
 $('#app').innerHTML=board('Dean’s portal · Read-only','All Departments at a Glance','Open any department’s published timetable, check when several faculty are free for a meeting, or post a notice that appears on every department’s board.',dStats(t))+
  `<div class="tabs" style="--n:3" role="tablist"><button class="tab on" data-t="tt" role="tab">Timetables</button><button class="tab" data-t="meet" role="tab">Availability</button><button class="tab" data-t="notes" role="tab">Notices</button></div><div id="pane"></div>`;
 document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>dShow(b.dataset.t));dTT()}
async function dShow(k){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.t==k));
 try{await dRefresh()}catch(e){$('#pane').innerHTML=`<div class="panel-card err">${esc(e.message)}</div>`;return}  // departments publish at any time: re-read on every tab switch
 ({tt:dTT,meet:dMeet,notes:dNotes})[k]()}

// ---------------------------------------------------------------- department timetables
function dTT(){const keep=DV.snap?.department?.id||'';
 $('#pane').innerHTML=`<div class="panel-card"><h2>Load a department’s timetable</h2><p class="mute">Shows exactly what the department has published to its students and faculty.</p>
  <div class="controls"><select id="dsel" aria-label="Department"><option value="" disabled ${keep?'':'selected'}>Select a department…</option>${DV.ov.map(d=>`<option value="${esc(d.id)}" ${d.id==keep?'selected':''}>${esc(d.name)} — ${d.has_timetable?'✓ '+fdt(d.synced.timetable):'no timetable yet'}</option>`).join('')}</select></div></div>
  <div id="dbody">${keep?'':'<div class="dean-empty">Choose a department above to see its timetable.</div>'}</div>`;
 $('#dsel').onchange=dLoad;if(keep)dLoad()}
async function dLoad(){const code=$('#dsel').value,body=$('#dbody');if(!code)return;body.innerHTML='<p class="mute">Loading…</p>';
 try{DV.snap=await api('/dean/timetable/'+code)}catch(e){DV.snap=null;body.innerHTML=`<div class="dean-empty">${esc(e.message)}</div>`;return}
 const st=DV.snap.stats,sy=st.synced||{};
 body.innerHTML=`<div class="dchips"><span class="pill good">Published${sy.timetable?' · '+fdt(sy.timetable):''}</span><span class="pill"><b>${st.periods}</b> periods / week</span><span class="pill"><b>${st.teachers}</b> teachers · <b>${st.sections}</b> classes · <b>${st.rooms}</b> rooms</span>
  <span class="pill"><b>${st.students}</b> students${sy.students?' · '+fdt(sy.students):''}</span><span class="pill"><b>${st.faculty}</b> faculty${sy.faculty?' · '+fdt(sy.faculty):''}</span></div>
  <div class="controls"><div class="seg" id="dseg">${[['teacher','Teacher-wise'],['room','Room-wise'],['section','Class-wise']].map(([v,l])=>`<button type="button" data-v="${v}" class="${v==DV.view?'on':''}">${l}</button>`).join('')}</div>
  <select id="dent" aria-label="Choose one"></select><span class="pill" id="dpill"></span></div><div id="dgrid"></div>`;
 document.querySelectorAll('#dseg button').forEach(b=>b.onclick=()=>{DV.view=b.dataset.v;document.querySelectorAll('#dseg button').forEach(x=>x.classList.toggle('on',x==b));dEnts()});
 $('#dent').onchange=dGrid;dEnts()}
const dKey=()=>({teacher:'faculty',room:'room',section:'section'}[DV.view]);
function dEnts(){const k=dKey(),xs=[...new Set(DV.snap.slots.map(s=>s[k]).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
 $('#dent').innerHTML=xs.map(x=>`<option>${esc(x)}</option>`).join('')||'<option>(none)</option>';dGrid()}
function dGrid(){const S=DV.snap.slots,k=dKey(),sel=$('#dent').value,mine=S.filter(s=>s[k]===sel),per={};S.forEach(s=>per[s.period]=[s.start,s.end]);
 const ps=Object.keys(per).map(Number).sort((a,b)=>a-b),days=[...new Set([0,1,2,3,4,5,...S.map(s=>s.day)])].sort(),today=(new Date().getDay()+6)%7,d0=days.includes(today)?today:days[0],v=DV.view;
 const cls=s=>s.section+(s.group?' '+s.group:''),meta=s=>(v=='teacher'?[cls(s),s.room]:v=='room'?[s.faculty,cls(s)]:[s.faculty,s.room+(s.group?' · '+s.group:'')]).filter(Boolean).map(esc).join(' · ');
 $('#dpill').textContent=`${mine.length} periods / week`;
 $('#dgrid').innerHTML=`<div class="grid-wrap"><table class="tt"><thead><tr><th class="timecol">Period</th>${days.map(d=>`<th class="${d==today?'now':''}">${D[d]}</th>`).join('')}</tr></thead><tbody>
  ${ps.map(p=>`<tr><th>P${p}<small>${f12(per[p][0])}–${f12(per[p][1])}</small></th>${days.map(d=>`<td class="cell ${d==today?'now':''}">${mine.filter(s=>s.day==d&&s.period==p).map(s=>`<div class="slot ${esc(s.kind)}"><span class="code">${esc(s.code||s.subject)}</span>${s.code?esc(s.subject):''}<span class="meta">${meta(s)}</span></div>`).join('')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
  <div class="mview"><div class="daytabs" role="tablist">${days.map(d=>`<button class="dt${d==d0?' on':''}${d==today?' today':''}" data-d="${d}" role="tab">${D[d]}</button>`).join('')}</div><div id="dlist"></div></div>`;
 const dv=d=>{const xs=[];mine.filter(s=>s.day==d).forEach(s=>{const p=xs[xs.length-1];if(p&&p.s.period+p.n==s.period&&['subject','section','group','room'].every(q=>p.s[q]==s[q])){p.n++;p.e=s.end}else xs.push({s,n:1,e:s.end})});
  $('#dlist').innerHTML=xs.length?xs.map(({s,e})=>`<div class="dc ${esc(s.kind)}"><span class="dtime">${f12(s.start)}–${f12(e)}</span><b>${esc(s.subject)}</b><span class="mute">${meta(s)}</span></div>`).join(''):`<div class="panel-card mute">No classes on ${D[d]}.</div>`};
 document.querySelectorAll('#dgrid .dt').forEach(b=>b.onclick=()=>{document.querySelectorAll('#dgrid .dt').forEach(x=>x.classList.toggle('on',x==b));dv(+b.dataset.d)});dv(d0)}

// ---------------------------------------------------------------- meeting availability
const dShown=()=>{const q=($('#fs').value||'').trim().toLowerCase(),d=$('#fd').value;return DV.fac.filter(f=>(!q||f.name.toLowerCase().includes(q))&&(!d||f.departments.some(x=>x.id==d)))};
function dFacList(){const rows=dShown();$('#fl').innerHTML=rows.length?rows.map(f=>`<label class="fac-item"><input type="checkbox" data-k="${esc(f.key)}" ${DV.sel.has(f.key)?'checked':''}><span>${esc(f.name)}</span><span class="dpt">${esc(dshort(f.departments))}</span></label>`).join(''):
 `<div class="dean-empty" style="border:0">${DV.fac.length?'No faculty match.':'No department has published faculty or a timetable yet.'}</div>`}
function dChips(){$('#fc').innerHTML=[...DV.sel].map(k=>{const f=DV.fac.find(x=>x.key==k);return f?`<span class="fchip">${esc(f.name)}<button type="button" data-rm="${esc(k)}" aria-label="Remove ${esc(f.name)}">×</button></span>`:''}).join('')}
function dMeet(){const ds=new Map();DV.fac.forEach(f=>f.departments.forEach(d=>ds.set(d.id,d.short)));const td=dToday()=='Sunday'?'Monday':dToday();
 $('#pane').innerHTML=`<div class="two"><div class="panel-card"><h2>1 · Pick faculty</h2><p class="mute">Faculty from any department, matched by name across departments.</p>
  <div class="controls"><input id="fs" placeholder="Search by name…" aria-label="Search faculty" autocomplete="off"><select id="fd" aria-label="Department"><option value="">All departments</option>${[...ds].sort((a,b)=>a[1].localeCompare(b[1])).map(([i,s])=>`<option value="${esc(i)}">${esc(s)}</option>`).join('')}</select></div>
  <div class="fac-list" id="fl"></div><div class="fac-actions"><button type="button" class="link-btn" id="fall">Select all shown</button><button type="button" class="link-btn" id="fclr">Clear</button></div><div class="chip-row" id="fc"></div></div>
  <div class="panel-card"><h2>2 · Pick the time</h2><p class="mute">Based on the published timetables only — it shows teaching commitments, not other engagements.</p>
  <div class="when-row"><div><label for="wd">Day</label><select id="wd">${DAYS.map(d=>`<option ${d==td?'selected':''}>${d}</option>`).join('')}</select></div><div><label for="ws">From</label><input id="ws" type="time" value="10:30"></div><div><label for="we">To</label><input id="we" type="time" value="11:30"></div></div>
  <div class="controls push"><button class="btn" id="chk" type="button">Check availability</button><button class="btn btn-gold" id="nowb" type="button">📍 Where are they right now?</button></div></div></div><div id="dres"></div>`;
 dFacList();dChips();
 $('#fl').onchange=e=>{const k=e.target.dataset.k;if(!k)return;e.target.checked?DV.sel.add(k):DV.sel.delete(k);dChips()};
 $('#fc').onclick=e=>{const k=e.target.dataset.rm;if(!k)return;DV.sel.delete(k);dChips();dFacList()};
 $('#fs').oninput=dFacList;$('#fd').onchange=dFacList;
 $('#fall').onclick=()=>{dShown().forEach(f=>DV.sel.add(f.key));dChips();dFacList()};$('#fclr').onclick=()=>{DV.sel.clear();dChips();dFacList()};
 $('#chk').onclick=()=>dCheck();
 $('#nowb').onclick=()=>{const n=new Date(),p=x=>String(x).padStart(2,'0');$('#wd').value=dToday()=='Sunday'?'Monday':dToday();$('#ws').value=`${p(n.getHours())}:${p(n.getMinutes())}`;$('#we').value='';dCheck(true)};
 $('#dres').onclick=e=>{const t=e.target.closest('[data-d][data-a]');if(!t)return;$('#wd').value=t.dataset.d;$('#ws').value=t.dataset.a;$('#we').value=t.dataset.b;dCheck()}}
async function dCheck(now){const r=$('#dres');if(!DV.sel.size){r.innerHTML='<div class="dean-empty">Pick at least one faculty member first.</div>';return}
 const a=$('#ws').value,b=$('#we').value,body={faculty:[...DV.sel]};if(a){body.day=$('#wd').value;body.start=a;if(b&&!now)body.end=b}
 const btn=$('#chk');btn.disabled=true;btn.textContent='Checking…';
 try{dResult(await api('/dean/availability',{method:'POST',json:body}),!!body.end)}catch(e){r.innerHTML=`<div class="panel-card err">${esc(e.message)}</div>`}finally{btn.disabled=false;btn.textContent='Check availability'}}
const dWhere=b=>`<div class="where"><span class="room">${esc(b.room||'—')}</span> — ${esc(b.course_code)} ${esc(b.course_name)} (${esc(b.kind)})<span class="sub">${esc(b.section)} · ${esc(b.dept_display)} · ${r12(b.start,b.end)}</span></div>`;
function dPerson(p){const c=(p.info||[])[0]||{},contact=[c.cabin&&'Cabin: '+c.cabin,c.phone,c.email].filter(Boolean).map(esc).join(' · '),top=(cls,l)=>`<div class="person-top"><span class="person-name">${esc(p.name)}</span><span class="badge ${cls}">${l}</span></div><div class="person-depts">${esc(dshort(p.departments))}</div>`;
 if(!p.free)return`<div class="person busy">${top('busy','BUSY')}${p.busy.map(dWhere).join('')}<div class="note">Free from <b>${t12a(p.free_from)}</b></div>${contact?`<div class="note">${contact}</div>`:''}</div>`;
 const n=p.next_class;return`<div class="person free">${top('free','FREE')}<div class="note">${n?`Next class: <b>${t12a(n.start)}</b> in ${esc(n.room||'—')} (${esc(n.dept)} · ${esc(n.course_code)})`:'No further classes that day.'}</div>${contact?`<div class="note">${contact}</div>`:''}</div>`}
function dResult(r,hadEnd){const o=[],at=r.at_time;
 if(at){const when=hadEnd?`${esc(at.day)}, ${r12(at.start,at.end)}`:`${esc(at.day)} at ${t12a(at.start)}`,n=at.people.length;
  o.push(at.all_free?`<div class="verdict free">✅ <b>${n==1?'Free':`All ${n} are free`}</b> on ${when}.</div>`:`<div class="verdict busy">⚠️ <b>${at.busy_count} of ${n}</b> ${at.busy_count==1?'is':'are'} busy on ${when}. Their locations are shown below.</div>`);
  o.push(`<div class="people">${at.people.slice().sort((a,b)=>a.free-b.free||a.name.localeCompare(b.name)).map(dPerson).join('')}</div>`)}
 if(!r.has_data)o.push('<div class="dean-empty">No department has published a timetable yet, so there is nothing to compare.</div>');
 else{const sug=r.days.flatMap(d=>(r.suggested[d]||[]).map(([a,b])=>({d,a,b})));
  o.push('<h2 class="section-h">When is everyone free together?</h2>');
  o.push(sug.length?`<p class="mute" style="margin:0 0 8px">Every selected person has no class during these windows — tap one to check it.</p><div class="suggest">${sug.map(s=>`<button type="button" data-d="${esc(s.d)}" data-a="${s.a}" data-b="${s.b}">${esc(s.d.slice(0,3))} ${r12(s.a,s.b)}</button>`).join('')}</div>`:
   '<div class="dean-empty">There is <b>no common free time</b> during teaching hours for this group. Try fewer people, or look at the grid to see who is blocking each slot.</div>');
  const sd=$('#wd').value,sa=$('#ws').value;
  o.push(`<div class="grid-wrap"><table class="week"><thead><tr><th>Time</th>${r.days.map(d=>`<th>${esc(d.slice(0,3))}</th>`).join('')}</tr></thead><tbody>${r.slots.map((s,i)=>`<tr><th>${r12(s.start,s.end)}</th>${r.days.map(d=>{const c=r.grid[d][i],sel=at&&d==sd&&s.start==sa?' sel':'',
   tip=c.busy.map(b=>`${b.name}: ${b.room||'—'} (${b.course_code}, ${b.dept})`).join('\n');
   return c.all_free?`<td class="wk ok${sel}" data-d="${esc(d)}" data-a="${s.start}" data-b="${s.end}">✓ free</td>`:`<td class="wk no${sel}" data-d="${esc(d)}" data-a="${s.start}" data-b="${s.end}" title="${esc(tip)}">✕ ${c.busy.length} busy<small>${esc(c.busy.slice(0,2).map(b=>b.name.split(' ').pop()).join(', '))}${c.busy.length>2?'…':''}</small></td>`}).join('')}</tr>`).join('')}</tbody></table></div>
  <p class="mute" style="margin-top:8px">Hover a red cell to see who is busy and where. Tap any cell to check that slot.</p>`)}
 $('#dres').innerHTML=o.join('')}

// ---------------------------------------------------------------- university-wide notices
async function dNotes(){const p=$('#pane');let ns;try{ns=await api('/dean/notices')}catch(e){p.innerHTML=`<div class="panel-card err">${esc(e.message)}</div>`;return}
 p.innerHTML=`<div class="two"><div class="panel-card"><h2>Post a university notice</h2><p class="mute">Appears at once on the notice board of every department’s students, faculty and admins you choose, marked as from the Dean’s Office.</p>
  <form id="dn"><label for="dnt">Title</label><input id="dnt" required maxlength="200"><label for="dnb">Message</label><textarea id="dnb" maxlength="2000"></textarea>
  <div class="row2"><div><label for="dna">Audience</label><select id="dna">${Object.entries(AUD).map(([k,l])=>`<option value="${k}">${l}</option>`).join('')}</select></div><div><label for="dnp">Pin to top</label><select id="dnp"><option value="0">No</option><option value="1">Yes</option></select></div></div>
  <p><button class="btn">Post to all departments</button></p><div class="msg" id="dnm"></div></form></div>
  <div class="panel-card"><h2>Active university notices</h2><div class="alist">${ns.map(n=>`<div class="notice ${n.pinned?'pin':''}"><div><b>${esc(n.title)}</b> <span class="mute">· ${esc(AUD[n.audience]||n.audience)} · ${esc(n.posted)}</span>${n.body?`<p>${esc(n.body)}</p>`:''}</div><button onclick="dDelN(${n.id})">Delete</button></div>`).join('')||'<p class="mute">No university notices yet.</p>'}</div></div></div>`;
 $('#dn').onsubmit=async e=>{e.preventDefault();try{await api('/dean/notice',{method:'POST',json:{title:$('#dnt').value,body:$('#dnb').value,audience:$('#dna').value,pinned:$('#dnp').value=='1'}});dNotes()}catch(x){$('#dnm').className='msg err';$('#dnm').textContent=x.message}}}
async function dDelN(id){if(confirm('Delete this university notice?')){await api('/dean/notice/'+id,{method:'DELETE'});dNotes()}}
