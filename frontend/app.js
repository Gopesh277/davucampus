const $=s=>document.querySelector(s),D=['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];let tok=sessionStorage.tok,role=sessionStorage.role;
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
async function api(p,o={}){const h={...(tok&&{Authorization:'Bearer '+tok})};if(o.json){h['Content-Type']='application/json';o.body=JSON.stringify(o.json)}
 const r=await fetch('/api'+p,{...o,headers:h});if(r.status==401&&tok&&p!='/login'){out();throw Error('Session expired')}
 const j=await r.json().catch(()=>({}));if(!r.ok){const d=j.detail;throw Error(typeof d=='string'?d:(d?.message+'\n'+(d?.errors||[]).join('\n')))}return j}
function out(){sessionStorage.clear();tok=role=null;boot()}
$('#logoutBtn').onclick=out;
function brand(dept){$('#deptHeading').textContent=dept||'Student Timetable Portal';$('#logoutBtn').hidden=!dept;$('#pwBtn').hidden=!(dept&&role=='admin')}
$('#pwBtn').onclick=()=>{const d=$('#dlg');d.innerHTML=`<h2>Change password</h2><form id="pf"><label for="p0">Current password</label><input id="p0" type="password" autocomplete="current-password" required>
 <label for="p1">New password (at least 8 characters)</label><input id="p1" type="password" autocomplete="new-password" minlength="8" required>
 <label for="p2">Confirm new password</label><input id="p2" type="password" autocomplete="new-password" minlength="8" required><div class="err" id="pe"></div>
 <p style="text-align:right;margin:16px 0 0"><button type="button" class="logout-link" id="pc" style="margin-right:16px">Cancel</button><button class="btn">Update password</button></p></form>`;
 $('#pc').onclick=()=>d.close();$('#pf').onsubmit=async e=>{e.preventDefault();const m=$('#pe');m.className='err';
  if($('#p1').value!=$('#p2').value){m.textContent='The new passwords do not match';return}
  try{await api('/admin/password',{method:'POST',json:{current:$('#p0').value,new:$('#p1').value}});m.className='ok';m.textContent='Password updated.';setTimeout(()=>d.close(),1200)}catch(x){m.textContent=x.message}};d.showModal()};
const board=(eyebrow,title,sub,stats)=>`<div class="board"><div class="board-top"><div><p class="board-eyebrow">${esc(eyebrow)}</p><h2 class="board-title">${esc(title)}</h2><p class="board-sub">${esc(sub)}</p></div>
 <div class="board-stats">${stats.map(([n,l])=>`<div class="stat"><div class="stat-num">${esc(n)}</div><div class="stat-label">${esc(l)}</div></div>`).join('')}</div></div></div>`;
async function boot(){brand(sessionStorage.dept);tok?(role=='admin'?adminView():studentView()):loginView()}
async function loginView(){brand('');const ds=await api('/departments').catch(()=>[]);
 $('#app').innerHTML=`<div class="panel-card login-card"><h2>Sign in</h2><p class="mute">Choose your department and sign in with your registration number.</p>
 <form id="f"><label for="d">Department</label><select id="d" required><option value="">Select department</option>${ds.map(d=>`<option value="${esc(d.code)}">${esc(d.name)}</option>`).join('')}</select>
 <label for="u">Registration number</label><input id="u" autocomplete="username" required>
 <label for="p">Password</label><input id="p" type="password" autocomplete="current-password" required>
 <p class="mute" style="margin:10px 0 0">Students: your password is your registration number.</p>
 <button class="btn">Sign in</button><div class="err" id="e"></div></form></div>`;
 $('#f').onsubmit=async e=>{e.preventDefault();try{const r=await api('/login',{method:'POST',json:{dept:$('#d').value,username:$('#u').value,password:$('#p').value}});
  tok=sessionStorage.tok=r.token;role=sessionStorage.role=r.role;sessionStorage.dept=r.dept;boot()}catch(x){$('#e').textContent=x.message}}}
const f12=t=>t?`${(+t.split(':')[0]%12)||12}:${t.split(':')[1]}`:'';
const noticeHtml=n=>`<div class="notice ${n.pinned?'pin':''}"><time>${esc(n.posted)}</time><b>${n.pinned?'📌 ':''}${esc(n.title)}</b>${n.body?`<p>${esc(n.body)}</p>`:''}</div>`;
async function studentView(){let t;try{t=await api('/timetable')}catch{return}
 const fac=t.role=='faculty',S=t.slots,today=(new Date().getDay()+6)%7,tds=S.filter(s=>s.day==today);window.S=S;window.FAC=fac;window.T=t;
 $('#app').innerHTML=board(fac?`Faculty${t.info?.designation?' · '+t.info.designation:''}`:`Section ${t.section||'—'}`,`Welcome, ${t.name}`,
  fac?'Your teaching schedule, assignments and syllabus progress.':'Your timetable, assignments and syllabus covered.',
  [[S.length,'Periods / week'],[fac?new Set(S.map(s=>s.section)).size:new Set(S.map(s=>s.subject)).size,fac?'Classes':'Subjects'],[tds.length,'Today']])+
 (t.notices.length?`<h2 class="section-h">Notice board</h2><div class="notices">${t.notices.map(noticeHtml).join('')}</div>`:'')+
 `<div class="tabs" role="tablist"><button class="tab on" data-t="tt" role="tab">Timetable</button><button class="tab" data-t="cw" role="tab">${fac?'Teaching':'Assignments'}</button></div><div id="pane"></div>`+chatHtml(fac);
 const show=k=>{document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('on',b.dataset.t==k));k=='tt'?ttPane():cwPane()};
 document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>show(b.dataset.t));show('tt');chatInit()}
function ttPane(){const S=window.S,fac=window.FAC,today=(new Date().getDay()+6)%7,per={};S.forEach(s=>per[s.period]=[s.start,s.end]);const ps=Object.keys(per).map(Number).sort((a,b)=>a-b);
 const days=[...new Set([0,1,2,3,4,5,...S.map(s=>s.day)])].sort(),tds=S.filter(s=>s.day==today),who=s=>fac?s.section+(s.group?' '+s.group:''):s.faculty.name,d0=days.includes(today)?today:days[0];
 $('#pane').innerHTML=S.length?`<h2 class="section-h today-h">Today, ${D[today]}</h2><div class="today">${tds.length?tds.map(s=>`<div class="t"><b>${f12(s.start)}–${f12(s.end)}</b><div>${esc(s.subject)}</div><div class="mute">${esc(who(s))} · Room ${esc(s.room.name)}</div></div>`).join(''):'<div class="t mute">No classes today.</div>'}</div>
 <div class="grid-wrap"><table class="tt"><thead><tr><th class="timecol">Period</th>${days.map(d=>`<th class="${d==today?'now':''}">${D[d]}</th>`).join('')}</tr></thead><tbody>
 ${ps.map(p=>`<tr><th>P${p}<small>${f12(per[p][0])}–${f12(per[p][1])}</small></th>${days.map(d=>`<td class="cell ${d==today?'now':''}">${S.map((s,i)=>s.day==d&&s.period==p?`<button class="slot ${esc(s.kind)}" onclick="detail(${i})"><span class="code">${esc(s.code||s.subject)}</span>${s.code?esc(s.subject):''}<span class="meta">${esc(s.room.name)} · ${esc(who(s))}</span></button>`:'').join('')}</td>`).join('')}</tr>`).join('')}
 </tbody></table></div>
 <div class="mview"><div class="daytabs" role="tablist">${days.map(d=>`<button class="dt${d==d0?' on':''}${d==today?' today':''}" data-d="${d}" role="tab">${D[d]}</button>`).join('')}</div><div id="daylist"></div></div>`:'<div class="panel-card">Your timetable has not been published yet. Check back soon.</div>';
 const dv=d=>{const xs=[];S.forEach((s,i)=>{if(s.day!=d)return;const p=xs[xs.length-1];if(p&&p.s.period+p.n==s.period&&['subject','section','group'].every(k=>p.s[k]==s[k])&&p.s.room.name==s.room.name){p.n++;p.e=s.end}else xs.push({s,i,n:1,e:s.end})});
  $('#daylist').innerHTML=xs.length?xs.map(x=>`<button class="dc ${esc(x.s.kind)}" onclick="detail(${x.i})"><span class="dtime">${f12(x.s.start)}–${f12(x.e)}</span><b>${esc(x.s.subject)}</b><span class="mute">${esc(who(x.s))} · Room ${esc(x.s.room.name)}</span></button>`).join(''):`<div class="panel-card mute">No classes on ${D[d]}.</div>`};
 if(S.length){document.querySelectorAll('.dt').forEach(b=>b.onclick=()=>{document.querySelectorAll('.dt').forEach(x=>x.classList.toggle('on',x==b));dv(+b.dataset.d)});dv(d0)}}
const fd=d=>new Date(d+'T00:00').toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});
async function cwPane(){const p=$('#pane');p.innerHTML='<p class="mute">Loading…</p>';let r;try{r=await api('/classwork')}catch(e){p.innerHTML=`<div class="panel-card err">${esc(e.message)}</div>`;return}
 const left=d=>{const n=Math.round((new Date(d+'T00:00')-new Date(r.today+'T00:00'))/864e5);return n<0?`${-n} day${n<-1?'s':''} ago`:n==0?'Due today':n==1?'Due tomorrow':`Due in ${n} days`};
 const asg=(a,del)=>`<div class="asg${a.due<r.today?' past':''}"><div class="asg-h"><b>${esc(a.title)}</b><span class="chip${a.due>=r.today&&a.due<=new Date(Date.parse(r.today)+2*864e5).toISOString().slice(0,10)?' hot':''}">${left(a.due)}</span></div>
  <div class="mute">${esc(a.subject)} · ${esc(a.section)}${del?'':' · '+esc(a.teacher)} · Due ${fd(a.due)}</div>${a.details?`<p>${esc(a.details)}</p>`:''}${del?`<button class="del" onclick="delPost('assignment',${a.id})">Delete</button>`:''}</div>`;
 if(window.FAC)return teacherPane(r,asg);
 const up=r.assignments.filter(a=>a.due>=r.today),past=r.assignments.filter(a=>a.due<r.today).reverse(),by={};r.syllabus.forEach(y=>(by[y.subject]=by[y.subject]||[]).push(y));
 const subs=[...new Set([...window.S.map(s=>s.subject),...Object.keys(by)])];
 p.innerHTML=`<div class="two"><div><h2 class="section-h">Upcoming assignments</h2>${up.map(a=>asg(a)).join('')||'<div class="panel-card mute">No upcoming assignments. 🎉</div>'}
  ${past.length?`<details class="past"><summary>Past assignments (${past.length})</summary>${past.map(a=>asg(a)).join('')}</details>`:''}</div>
  <div><h2 class="section-h">Syllabus covered</h2>${subs.map(sub=>{const xs=by[sub]||[];return `<details class="syl"><summary><b>${esc(sub)}</b><span class="chip">${xs.length} topic${xs.length==1?'':'s'}</span></summary>
   ${xs.length?`<ul>${xs.map(y=>`<li>${y.unit?`<span class="u">${esc(y.unit)}</span> `:''}${esc(y.topic)}<time>${fd(y.covered)}</time></li>`).join('')}</ul><div class="mute" style="margin-top:6px">Updated by ${esc(xs[0].teacher)}</div>`:'<p class="mute">Nothing logged yet.</p>'}</details>`}).join('')||'<div class="panel-card mute">No subjects yet.</div>'}</div></div>`}
function teacherPane(r,asg){const C=r.classes,p=$('#pane');
 if(!C.length){p.innerHTML='<div class="panel-card">No classes found for you in the timetable yet.</div>';return}
 const opts=C.map((c,i)=>`<option value="${i}">${esc(c.subject)} — ${esc(c.section)}</option>`).join('');
 p.innerHTML=`<div class="two"><div class="panel-card"><h2>Post an assignment</h2><form id="af"><label for="ac">Class</label><select id="ac">${opts}</select>
  <label for="at">Title</label><input id="at" required maxlength="200"><label for="ad">Details</label><textarea id="ad" maxlength="2000"></textarea>
  <label for="au">Due date</label><input id="au" type="date" required min="${r.today}"><p><button class="btn btn-gold">Post assignment</button></p><div class="msg" id="am"></div></form></div>
  <div class="panel-card"><h2>Log syllabus covered</h2><form id="yf"><label for="yc">Class</label><select id="yc">${opts}</select>
  <label for="yu">Unit (optional)</label><input id="yu" maxlength="80" placeholder="e.g. Unit 2"><label for="yt">Topic covered</label><textarea id="yt" required maxlength="500"></textarea>
  <label for="yd">Date</label><input id="yd" type="date" value="${r.today}" required><p><button class="btn btn-gold">Save topic</button></p><div class="msg" id="ym"></div></form></div></div>
  <div class="two" style="margin-top:16px"><div><h2 class="section-h">My assignments</h2>${r.assignments.map(a=>asg(a,1)).join('')||'<div class="panel-card mute">Nothing posted yet.</div>'}</div>
  <div><h2 class="section-h">My syllabus log</h2>${r.syllabus.map(y=>`<div class="asg"><div class="asg-h"><b>${esc(y.subject)}</b><span class="chip">${fd(y.covered)}</span></div><div class="mute">${esc(y.section)}${y.unit?' · '+esc(y.unit):''}</div><p>${esc(y.topic)}</p><button class="del" onclick="delPost('syllabus',${y.id})">Delete</button></div>`).join('')||'<div class="panel-card mute">Nothing logged yet.</div>'}</div></div>`;
 const send=(id,mid,path,body)=>async e=>{e.preventDefault();const c=C[$('#'+id).value],m=$('#'+mid);try{await api(path,{method:'POST',json:{section:c.section,subject:c.subject,...body()}});cwPane()}catch(x){m.className='msg err';m.textContent=x.message}};
 $('#af').onsubmit=send('ac','am','/teacher/assignment',()=>({title:$('#at').value,details:$('#ad').value,due:$('#au').value}));
 $('#yf').onsubmit=send('yc','ym','/teacher/syllabus',()=>({unit:$('#yu').value,topic:$('#yt').value,covered:$('#yd').value}))}
async function delPost(k,id){if(confirm('Delete this entry?')){await api(`/teacher/${k}/${id}`,{method:'DELETE'});cwPane()}}
function detail(i){const s=S[i],f=s.faculty,r=s.room,row=(k,v)=>v?`<dt>${k}</dt><dd>${esc(v)}</dd>`:'';
 $('#dlg').innerHTML=`<h2>${esc(s.subject)}</h2><dl>${row('Code',s.code)}${row('Type',s.kind)}${row('Time',`${D[s.day]} ${f12(s.start)}–${f12(s.end)}`)}${FAC?row('Class',s.section+(s.group?' '+s.group:'')):''}${FAC?'':row('Faculty',f.name)}${FAC?'':row('Designation',f.designation)+row('Email',f.email)+row('Phone',f.phone)+row('Cabin',f.cabin)}${row('Room',r.name)}${row('Building',r.building)}${row('Floor',r.floor)}${row('Directions',r.directions)}</dl>
 <p style="text-align:right;margin:18px 0 0"><button class="btn" onclick="$('#dlg').close()">Close</button></p>`;$('#dlg').showModal()}
const chatHtml=fac=>`<button class="btn" id="chatbtn" aria-expanded="false">Ask about faculty &amp; rooms</button><div id="chat"><div class="chat-head">Campus assistant<small>FACULTY · ROOMS · SCHEDULE</small></div><div id="msgs"></div>
 <div class="chips">${(fac?['Next class','When am I free?','My info']:['Next class','Today','When is Dr. Sharma free?']).map(c=>`<button>${c}</button>`).join('')}</div><form id="cf"><input id="ci" placeholder="Ask a question" maxlength="300" aria-label="Message"><button class="btn">Send</button></form></div>`;
function chatInit(){const add=(t,c)=>{const m=document.createElement('div');m.className='m '+c;m.textContent=t;$('#msgs').append(m);$('#msgs').scrollTop=1e9};
 add('Hello! Ask about your next class, the location of a room, or when a faculty member is free to meet.','bot');
 $('#chatbtn').onclick=()=>{const o=$('#chat').classList.toggle('open');$('#chatbtn').setAttribute('aria-expanded',o);o&&$('#ci').focus()};
 const send=async q=>{if(!q.trim())return;add(q,'me');try{add((await api('/chat',{method:'POST',json:{message:q}})).reply,'bot')}catch(e){add(e.message,'bot')}};
 $('#cf').onsubmit=e=>{e.preventDefault();send($('#ci').value);$('#ci').value=''};document.querySelectorAll('.chips button').forEach(b=>b.onclick=()=>send(b.textContent))}
async function adminView(){const st=await api('/admin/stats').catch(()=>({})),ns=await api('/admin/announcements').catch(()=>[]);
 const up=(t,hint,kind,extra='')=>`<div class="panel-card"><h2>${t}</h2><p class="mute">${hint}</p><p><a href="#" onclick="tpl('${kind}');return false">↓ Download Excel template</a></p>
 <form data-k="${kind}"><input type="file" accept=".xlsx" required aria-label="${t}">${extra}<p><button class="btn btn-gold">↑ Upload</button></p><div class="msg"></div></form></div>`;
 const rep=l=>`<label style="font-weight:400"><input type="checkbox" name="replace" style="width:auto"> ${l}</label>`;
 $('#app').innerHTML=board('Department admin','Manage timetable, people & notices','Upload everything from Excel. Students and faculty sign in with their Reg No / Employee ID (password is the same).',
  [[st.students??'–','Students'],[st.faculty??'–','Faculty'],[st.sections??'–','Classes'],[st.notices??'–','Notices']])+
 `<div class="two">${up('Class timetable','Upload the scheduler’s exported .xlsx (sheet “Master”). Optional “Rooms” sheet adds building/floor. Replaces the current timetable.','timetable')}
 ${up('Students (class-wise)','Reg No, Name, Section (same text as in the timetable), optional Group.','students',rep('Remove students not in this file'))}
 ${up('Faculty list & info','Faculty Name, Employee ID, Nature of Appointment, Email, Phone, Cabin — or your teaching-load register. Creates faculty logins.','faculty',rep('Remove faculty logins not in this file'))}
 <div class="panel-card"><h2>Announcements</h2><form id="nf"><label for="nt">Title</label><input id="nt" required maxlength="200">
 <label for="nb">Message</label><textarea id="nb" maxlength="2000"></textarea><div class="row2"><div><label for="na">Audience</label><select id="na"><option value="all">Everyone</option><option value="students">Students</option><option value="faculty">Faculty</option></select></div>
 <div><label for="np">Pin to top</label><select id="np"><option value="0">No</option><option value="1">Yes</option></select></div></div><p><button class="btn">Post</button></p><div class="msg" id="nm"></div></form>
 <div class="alist">${ns.map(n=>`<div class="notice ${n.pinned?'pin':''}"><div><b>${esc(n.title)}</b> <span class="mute">· ${esc(n.audience)} · ${esc(n.posted)}</span>${n.body?`<p>${esc(n.body)}</p>`:''}</div><button onclick="delN(${n.id})">Delete</button></div>`).join('')||'<p class="mute">No announcements yet.</p>'}</div></div></div>`;
 $('#nf').onsubmit=async e=>{e.preventDefault();try{await api('/admin/announcement',{method:'POST',json:{title:$('#nt').value,body:$('#nb').value,audience:$('#na').value,pinned:$('#np').value=='1'}});adminView()}catch(x){$('#nm').className='msg err';$('#nm').textContent=x.message}};
 document.querySelectorAll('form[data-k]').forEach(f=>f.onsubmit=async e=>{e.preventDefault();const m=f.querySelector('.msg'),fd=new FormData();fd.append('file',f.querySelector('[type=file]').files[0]);
  const cb=f.querySelector('[type=checkbox]');if(cb)fd.append('replace',cb.checked);m.className='msg';m.textContent='Uploading…';
  try{const r=await api('/admin/'+f.dataset.k,{method:'POST',body:fd});m.className='msg ok';m.textContent='Saved. '+Object.entries(r).map(([k,v])=>`${k.replace(/_/g,' ')}: ${v}`).join(' · ');setTimeout(adminView,1800)}catch(x){m.className='msg err';m.textContent=x.message}})}
async function delN(id){if(confirm('Delete this announcement?')){await api('/admin/announcement/'+id,{method:'DELETE'});adminView()}}
async function tpl(k){const r=await fetch('/api/admin/template/'+k,{headers:{Authorization:'Bearer '+tok}}),a=document.createElement('a');a.href=URL.createObjectURL(await r.blob());a.download=k+'_template.xlsx';a.click()}
boot();
