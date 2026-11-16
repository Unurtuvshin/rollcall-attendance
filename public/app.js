const $ = (selector, root = document) => root.querySelector(selector);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  check:'m5 12 4 4L19 6', grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  calendar:'M8 2v4m8-4v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2Z',
  arrow:'M5 12h14m-5-5 5 5-5 5', chevron:'m9 5 7 7-7 7', logout:'M9 4H4v16h5m5-4 4-4-4-4m-6 4h10',
  bell:'M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4',
  mail:'M3 5h18v14H3zM3 6l9 7 9-7', lock:'M5 10h14v11H5zM8 10V6a4 4 0 0 1 8 0v4',
  shield:'m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6l8-3Zm-4 9 3 3 5-6',
  user:'M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2M16 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z',
  users:'M16 21v-2a5 5 0 0 0-5-5H7a5 5 0 0 0-5 5v2M13 6a4 4 0 1 1-8 0 4 4 0 0 1 8 0ZM17 3a4 4 0 0 1 0 8m1 3a5 5 0 0 1 4 5v2',
  book:'M12 5C8 2 4 3 2 4v15c3-1 7-1 10 2m0-16c4-3 8-2 10-1v15c-3-1-7-1-10 2V5Z',
  clock:'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  pin:'M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0ZM15 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z',
  card:'M3 5h18v14H3zM3 9h18M6 15h4', plus:'M12 5v14M5 12h14', edit:'m15 4 5 5M4 20l5-1L21 7l-4-4L5 15l-1 5Z',
  trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7', close:'m6 6 12 12M6 18 18 6',
  search:'m21 21-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z', info:'M12 11v6m0-10v.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',
  network:'M9 2h6v6H9zM2 16h6v6H2zM16 16h6v6h-6zM12 8v4M5 16v-4h14v4',
  database:'M21 5c0 2-4 4-9 4S3 7 3 5s4-4 9-4 9 2 9 4ZM3 5v14c0 2 4 4 9 4s9-2 9-4V5M3 12c0 2 4 4 9 4s9-2 9-4',
  file:'M14 2H4v20h16V8l-6-6Zm0 0v6h6M8 13h8m-8 4h6', inbox:'M3 4h18v16H3zM3 13h5l2 3h4l2-3h5',
};
const icon = (name, cls = '') => `<svg class="icon ${cls}" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;
const labels = {present:'出席',late:'遅刻',early:'早退',absent:'欠席',excused:'公欠',pending:'手続き待ち',unrecorded:'未記録',local:'ローカル',sent:'送信済み',queued:'送信待ち',failed:'送信失敗'};
const badge = (status, label) => `<span class="status ${escape(status || 'pending')}">${escape(label || labels[status] || '未記録')}</span>`;
const opt = (value, label, current) => `<option value="${escape(value)}" ${String(value) === String(current) ? 'selected' : ''}>${escape(label)}</option>`;
const dateText = (date, options = {month:'long',day:'numeric'}) => new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo',...options}).format(new Date(date.length === 10 ? date+'T00:00:00+09:00' : date));
const timeText = date => date ? dateText(date,{hour:'2-digit',minute:'2-digit'}) : '—';
const mailTime = date => dateText(date,{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
const S = {boot:null,data:null,view:'overview',history:false,course:'all',recordCourse:'all',recordDate:'',query:'',auth:'student',demo:null,demoTab:'reader',demoStudent:'24C1001',demoLesson:null,demoMode:'entry'};
let toastTimer;

async function api(path, method='GET', data) {
  const response = await fetch('/api'+path, {method,headers:{'Content-Type':'application/json',...(S.boot?.user?.csrf ? {'X-CSRF-Token':S.boot.user.csrf} : {})},...(data === undefined ? {} : {body:JSON.stringify(data)})});
  const result = await response.json();
  if (!response.ok) {
    if(response.status===401 && !['/auth/link','/auth/admin'].includes(path) && S.boot?.user) {
      S.boot.user=null;S.data=null;S.view='overview';$('#modal').close();render();
    }
    throw new Error(result.error || '処理に失敗しました。');
  }
  return result;
}
function toast(message, error=false) {
  clearTimeout(toastTimer);
  $('#toast').textContent = message;
  $('#toast').className = 'toast show'+(error?' error':'');
  toastTimer = setTimeout(()=>$('#toast').className='toast',4500);
}
async function refresh() {
  S.boot = await api('/bootstrap');
  if (S.boot.user) S.data = await api('/'+S.boot.user.role+'/data');
  else S.data = null;
  if (!S.started) { S.started = true; if (user()?.role === 'student') S.view = 'checkin'; }
  render();
  clearTimeout(S.expiry);  // student logins end 15 min before the lesson does
  if (user()?.role === 'student') S.expiry = setTimeout(async()=>{await refresh();if(!user())toast('ログインの有効時間が終了しました。次の授業ではカードをかざしてください。',true);}, Math.max(1000,user().expires_at*1000-Date.now()+500));
}
function nav(view, extra={}) {
  Object.assign(S,{view,query:''},extra);
  render();
  window.scrollTo({top:0,behavior:'instant'});
}
function metrics(records) {
  const counts = {present:0,late:0,early:0,absent:0,excused:0};
  records.filter(r=>r.confirmed).forEach(r=>[r.first_status,r.second_status].forEach(s=>{if(s in counts) counts[s]++;}));
  const attended = counts.present+counts.late+counts.early;
  const total = attended+counts.absent;
  return {...counts,attended,total,rate:total?Math.round(attended/total*100):null};
}
const empty = (title, text='', name='inbox', action='') => `<div class="empty-state">${icon(name)}<h2>${escape(title)}</h2>${text?`<p>${escape(text)}</p>`:''}${action}</div>`;
const footer = () => `<footer class="page-footer"><span>© ${S.boot.today.slice(0,4)} Rollcall</span><span>${icon('shield')}あなたの出席情報は、あなたと担当教員だけに。</span></footer>`;
function heading(eyebrow,title,subtitle='',right='') {
  return `<div class="page-heading"><div><div class="eyebrow">${eyebrow}</div><h1>${title}</h1>${subtitle?`<p>${subtitle}</p>`:''}</div>${right}</div>`;
}
const button = (action, label, name='plus', cls='', attrs='') => `<button type="button" class="button ${cls}" data-action="${action}" ${attrs}>${icon(name)}${label}</button>`;
const textButton = (action,label,attrs='') => `<button type="button" class="text-button" data-action="${action}" ${attrs}>${label}${icon('arrow')}</button>`;
const statusOptions = current => Object.keys(labels).filter(k=>['present','late','absent','early','excused'].includes(k)).map(k=>opt(k,labels[k],current)).join('');
const user = () => S.boot?.user;

function shell(content) {
  const u = user();
  const admin = u?.role === 'admin';
  const navs = admin ? [['overview','grid','ダッシュボード'],['records','file','出席記録'],['courses','book','科目・受講名簿'],['students','users','学生'],['admins','shield','管理者']] : [['checkin','card','出席手続き'],['overview','grid','出席状況'],['log','clock','利用ログ'],['notifications','bell','お知らせ']];
  const current = navs.find(n=>n[0]===S.view)?.[2] || (admin?'ダッシュボード':'出席状況');
  return `<div class="app-shell"><aside class="sidebar"><a href="/" class="brand" aria-label="Rollcall ホーム"><span class="brand-icon">${icon('check')}</span><span>rollcall<small>ATTENDANCE, SIMPLIFIED.</small></span></a><div class="nav-section">${admin?'MANAGEMENT':'MY CAMPUS'}</div><nav class="navigation" aria-label="メインナビゲーション">${navs.map(([view,name,label])=>`<button type="button" class="nav-link ${S.view===view?'active':''}" data-action="nav" data-view="${view}" ${!u?'disabled':''} ${S.view===view?'aria-current="page"':''}>${icon(name)}<span>${label}</span>${view==='checkin'&&S.data?.records.some(r=>r.id===u?.record_id&&!r.confirmed)?'<span class="nav-counter">1</span>':''}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="sidebar-note">${icon('shield')} ${admin?'教員用ワークスペース':'毎日の出席を、ひと目で。'}</div><div class="profile"><span class="avatar">${u?escape(u.name.replaceAll(' ','').slice(0,1)):icon('user')}</span><div><strong>${escape(u?.name || 'ゲスト')}</strong><small>${escape(u?.id || 'STUDENT PORTAL')}</small></div>${u?`<button class="logout" data-action="logout" aria-label="ログアウト">${icon('logout')}</button>`:''}</div></div>${u?`<button class="mobile-logout" data-action="logout" aria-label="ログアウト">${icon('logout')}</button>`:''}</aside><div class="main"><header class="topbar"><div class="breadcrumbs"><span>${admin?'教員ポータル':'学生ポータル'}</span><span>/</span><strong>${u?current:'ログイン'}</strong></div><div class="top-actions"><span class="top-date">${dateText(S.boot.today,{year:'numeric',month:'2-digit',day:'2-digit',weekday:'short'})}</span>${S.boot.demo?`<button class="demo-button" data-action="demo"><span class="demo-dot"></span>デモを試す</button>`:''}${u?`<span class="top-user" aria-hidden="true">${escape(u.name.replaceAll(' ','').slice(0,1))}</span>`:''}</div></header><main class="content ${!u?'auth-content':''}" id="main-content">${content}${footer()}</main></div></div>`;
}

function login() {
  const admin = S.auth==='admin';
  return `${heading('WELCOME TO ROLLCALL','毎日の出席を、ひと目で。','今日も、ここから。')}<div class="auth-layout"><section class="auth-hero"><div class="eyebrow">A LITTLE CHECK, A NEW DAY.</div><h1>出席を、もっと<br>スムーズに。</h1><p>カードをかざして、コードを入力。<br>あなたの学びの記録が、ここに。</p><div class="hero-art" aria-hidden="true"><div class="art-orbit"></div><div class="art-card"><div class="art-card-header"><span>MY ATTENDANCE</span>${icon('book')}</div><h3>ソフトウェア工学</h3><div class="art-card-footer"><span>09:00 — 12:10</span><strong>出席</strong></div></div><span class="art-check">${icon('check')}</span><span class="art-spark">✧</span></div></section><section class="auth-form-panel"><div class="lock-icon">${icon(admin?'shield':'lock')}</div><h2>${admin?'教員ログイン':'メールのリンクから入ります'}</h2><p>${admin?'登録されたユーザーIDとパスワードでログイン。':'学生証をかざすと、学校のメールにログインリンクが届きます。学内ネットワークでそのリンクを開いてください。'}</p><form class="auth-form" data-form="admin-login"><div class="form-error" role="alert">${admin?'':escape(S.linkError||'')}</div>${admin?`<label class="field"><span>ユーザーID</span><input class="input" name="id" autocomplete="username" placeholder="ユーザーID" required maxlength="40"></label><label class="field"><span>パスワード</span><input class="input" name="password" type="password" autocomplete="current-password" placeholder="パスワード" required maxlength="200"></label>`:''}${admin?`<button class="button full" type="submit">ログイン${icon('arrow')}</button>`:''}${!admin?`<div class="auth-hint">${icon('clock')}リンクは発行から10分間有効で、1回しか使えません</div>`:''}</form><div class="auth-separator"></div><button class="teacher-link" data-action="auth-mode" data-mode="${admin?'student':'admin'}">${icon(admin?'user':'shield')}${admin?'学生のログインへ':'教員・管理者の方はこちら'}${icon('chevron')}</button>${admin&&S.boot.demo?'<div class="credential-note">デモ用ログイン<br>ID <code>teacher</code>　パスワード <code>teacher123</code></div>':''}</section></div>${S.boot.demo?`<div class="demo-start"><div><strong>ローカルプロトタイプ</strong><p>カード読取からメール通知まで、ここで体験できます。</p></div>${textButton('demo','デモを試す')}</div>`:''}`;
}

function studentOverview() {
  const data=S.data, m=metrics(data.records), today=data.lessons.filter(l=>l.day===S.boot.today);
  if(S.history) return studentHistory();
  return `${heading('MY ATTENDANCE','出席状況',`${escape(user().name)}さん、今日も一歩ずつ。`,`<span class="pill">${icon('calendar')}${S.boot.today.slice(0,4)}年度</span>`)}<div class="page-tabs"><button class="page-tab active" data-action="history" data-history="false">サマリー</button><button class="page-tab" data-action="history" data-history="true">出席履歴</button></div><div class="dashboard-top"><section class="card welcome-card"><span class="welcome-label">MAKE EVERY DAY COUNT.</span><h2>今日の学びも、<br>確かな記録に。</h2><p>カードの読取が済んだら、出席手続きを。</p>${textButton('nav','出席手続きへ','data-view="checkin"')}<span class="welcome-symbol">${icon('calendar')}</span></section><section class="card rate-card" aria-label="出席率 ${m.rate??0}パーセント"><div class="donut" style="--value:${m.rate??0}"><div class="donut-inner"><div class="donut-value">${m.rate??'—'}<small>%</small></div><small>出席率</small></div></div><div class="rate-summary"><h2>これまでの出席</h2><div class="legend-row"><span class="legend-label"><i class="tiny-dot"></i>出席</span><b>${m.attended}</b></div><div class="legend-row"><span class="legend-label"><i class="tiny-dot gray"></i>欠席</span><b>${m.absent}</b></div><div class="legend-row"><span class="legend-label">全コマ</span><b>${m.total}</b></div></div></section></div><div class="dashboard-middle"><section class="card"><div class="card-heading"><h2><span class="heading-dot"></span>今日の授業</h2><small>${dateText(S.boot.today,{month:'numeric',day:'numeric',weekday:'short'})}</small></div><div class="today-list">${today.length?today.map((l,i)=>lessonRow(l,i)).join(''):`<div class="empty-small">${icon('calendar')}今日の授業はありません</div>`}</div></section><section class="card"><div class="card-heading"><h2>お知らせ</h2>${textButton('nav','すべて','data-view="notifications"')}</div><div class="notice-list">${data.mail.filter(x=>x.kind!=='login').slice(0,2).map(mail=>`<button class="notice-item" data-action="mail" data-id="${mail.id}"><span class="notice-icon">${icon(mail.kind==='correction'?'edit':'mail')}</span><span><strong>${escape(mail.subject)}</strong><small>${mailTime(mail.created_at)}</small></span></button>`).join('')||`<div class="empty-small">${icon('bell')}新しいお知らせはありません</div>`}</div></section></div><section class="courses-section"><div class="section-title"><h2>受講中の科目</h2><small>${data.courses.length}科目</small></div><div class="course-grid">${data.courses.map(courseCard).join('')}</div>${!data.courses.length?empty('受講科目がありません','担当教員による登録をお待ちください。','book'):''}</section>`;
}

function lessonRow(lesson,i) {
  const record=S.data.records.find(r=>r.lesson_id===lesson.id);
  const summary=record?.first_status===record?.second_status ? labels[record?.first_status] : `${labels[record?.first_status]} / ${labels[record?.second_status]}`;
  return `<div class="lesson-row"><div class="lesson-time">${escape(lesson.first_start)}<small>${escape(lesson.second_end)}</small></div><span class="lesson-marker ${i%2?'blue':''}"></span><div class="lesson-info"><h3>${escape(lesson.course_name)}</h3><p>${icon('pin')}${escape(lesson.room)}<span>2コマ</span></p></div>${record?(record.confirmed?badge(record.first_status,summary):badge('pending')):'<span class="status">予定</span>'}</div>`;
}

function courseCard(course,i) {
  const records=S.data.records.filter(r=>r.course_id===course.id), m=metrics(records);
  const latest=records.filter(r=>r.confirmed).length;
  const total=S.data.lessons.filter(l=>l.course_id===course.id).length, a=S.data.absences.find(x=>x.course_id===course.id);
  return `<button class="card course-card" data-action="course-history" data-id="${course.id}"><div class="course-top"><span class="course-icon ${['','blue','purple'][i%3]}">${icon(['book','database','network'][i%3])}</span><span class="course-code">${escape(course.code)}</span></div><h3>${escape(course.name)}</h3><p class="teacher-name">${escape(course.teacher)} 先生</p><div class="course-rate"><span>出席率</span><strong>${m.rate??'—'}<small>%</small></strong></div><div class="progress"><span style="width:${m.rate??0}%"></span></div><div class="course-footer"><span>${latest} / ${total} 回${a&&a.limit>0?`　欠席 ${a.absent}/${a.limit}`:''}</span><span>履歴を見る　↗</span></div></button>`;
}

function studentHistory() {
  const records=S.data.records.filter(r=>S.course==='all'||String(r.course_id)===S.course);
  const m=metrics(records);
  return `${heading('MY ATTENDANCE','出席状況','授業ごとの記録を確認できます。')}<div class="page-tabs"><button class="page-tab" data-action="history" data-history="false">サマリー</button><button class="page-tab active" data-action="history" data-history="true">出席履歴</button></div><div class="stats-grid">${statCard('出席率',m.rate??'—','%','calendar')}${statCard('出席',m.present,'コマ','check')}${statCard('遅刻・早退',m.late+m.early,'コマ','clock')}${statCard('欠席',m.absent,'コマ','file')}</div><section class="card"><div class="card-heading"><h2>出席履歴</h2><div class="table-filters"><select data-filter="student-course" aria-label="科目を絞り込む">${opt('all','すべての科目',S.course)}${S.data.courses.map(c=>opt(c.id,c.name,S.course)).join('')}</select></div></div>${records.length?`<div class="table-wrap"><table><thead><tr><th>授業日</th><th>科目</th><th>入室</th><th>退室</th><th>1コマ目</th><th>2コマ目</th><th></th></tr></thead><tbody>${records.map(r=>`<tr><td>${dateText(r.day,{month:'2-digit',day:'2-digit',weekday:'short'})}</td><td><strong>${escape(r.course_name)}</strong>${r.reason?`<small>${escape(r.reason)}</small>`:''}</td><td>${timeText(r.entry_at)}</td><td>${timeText(r.exit_at)}</td><td>${badge(r.first_status)}</td><td>${badge(r.second_status)}</td><td>${!r.confirmed?badge('pending'):''}</td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${records.length}件</span><span>公欠を除くコマ数で出席率を計算</span></div>`:empty('出席記録がありません','出席手続きが完了すると、ここに表示されます。')}</section><div class="info-strip">${icon('info')}出席率は、公欠を除いたコマ数に対する出席・遅刻・早退の割合です。</div>`;
}
const statCard = (label,value,unit,name) => `<section class="card stat-card"><span>${label}${icon(name)}</span><strong>${value}<small>${unit}</small></strong></section>`;

const sessionStrip = () => `<div class="info-strip">${icon('clock')}ログインは ${timeText(new Date(user().expires_at*1000).toISOString())} まで有効です。次の授業では、もう一度カードをかざしてください。</div>`;
function absenceStrip(courseId) {
  const a=S.data.absences.find(x=>x.course_id===courseId);
  return a&&a.limit>0 ? `<div class="info-strip">${icon('info')}欠席 ${a.absent} / 上限 ${a.limit} コマ（残り ${Math.max(a.remaining,0)} コマ）</div>` : '';
}
function exitCheckin(r) {
  const done=!!r.exit_at, p=r.exit_preview||[];
  return `${heading('CHECK OUT','退室の手続き',dateText(r.day,{year:'numeric',month:'long',day:'numeric',weekday:'long'}))}<div class="detail-layout"><section class="card checkin-card"><div class="checkin-top"><span class="course-icon">${icon('book')}</span>${badge(done?'present':'pending',done?'手続き完了':'提出待ち')}</div><h2>${escape(r.course_name)}</h2><div class="course-meta"><span>${icon('pin')} ${escape(r.room)}</span><span>${escape(r.course_code)}</span></div><div class="time-proof"><span>${icon('logout')} カード読取時刻（退室）</span><div><strong>${timeText(r.exit_at||r.pending_exit_at)}</strong><small>入室 ${timeText(r.entry_at)}</small></div></div><div class="period-grid"><div class="period"><span>1コマ目</span><small>${r.first_start} — ${r.first_end}</small>${badge(done?r.first_status:p[0])}</div><div class="period"><span>2コマ目</span><small>${r.second_start} — ${r.second_end}</small>${badge(done?r.second_status:p[1])}</div></div>${done?`<div class="confirmation-success">${icon('check')}退室の手続きが完了しました</div>`:`<button class="button full" data-action="submit-exit">${icon('logout')}この内容で退室を提出</button>`}</section><div>${sessionStrip()}${absenceStrip(r.course_id)}</div></div>${footer()}`;
}
function usageLog() {
  const log=S.data.usage, at=d=>dateText(d,{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
  return `${heading('USAGE LOG','利用ログ','カードの読取・ログイン・手続きの記録です。')}<section class="card"><div class="card-heading"><h2>操作の記録</h2><small>${log.length}件</small></div>${log.length?`<div class="log-list">${log.map(u=>`<div class="log-item"><div><strong>${escape(u.action)}</strong><p>${escape(u.detail)}</p></div><time>${at(u.created_at)}</time></div>`).join('')}</div>`:empty('記録はまだありません','','clock')}</section>`;
}
function checkin() {
  const r=S.data.records.find(r=>r.id===user().record_id);
  if(r && user().purpose==='exit') return exitCheckin(r);
  if(!r) return heading('CHECK IN','出席手続き')+`<div class="card">${empty('認証済みの入室記録がありません','カードを読み取り、メールのログインリンクを開いてください。','card',S.boot.demo?button('demo','カードを読み取る','card'):button('logout','ログイン画面へ','arrow','secondary'))}</div>`;
  return `${heading('CHECK IN','出席手続き',dateText(r.day,{year:'numeric',month:'long',day:'numeric',weekday:'long'}))}<div class="detail-layout"><section class="card checkin-card"><div class="checkin-top"><span class="course-icon">${icon('book')}</span>${badge(r.confirmed?'present':'pending',r.confirmed?'手続き完了':'手続き待ち')}</div><h2>${escape(r.course_name)}</h2><div class="course-meta"><span>${icon('pin')} ${escape(r.room)}</span><span>${escape(r.course_code)}</span></div><div class="time-proof"><span>${icon('card')} カード読取時刻</span><div><strong>${timeText(r.entry_at)}</strong><small>${dateText(r.entry_at,{year:'numeric',month:'2-digit',day:'2-digit'})}</small></div></div><div class="period-grid"><div class="period"><span>1コマ目</span><small>${r.first_start} — ${r.first_end}</small>${badge(r.first_status)}</div><div class="period"><span>2コマ目</span><small>${r.second_start} — ${r.second_end}</small>${badge(r.second_status)}</div></div>${r.confirmed?`<div class="confirmation-success">${icon('check')}出席手続きが完了しました</div>`:`<button class="button full" data-action="confirm-attendance">${icon('check')}この内容で出席を登録</button>`}${r.confirmed?`<div class="auth-hint">${icon('mail')}出席状況を学生メールに通知しました</div>`:''}${r.exit_at?`<div class="info-strip">${icon('logout')}退室 ${timeText(r.exit_at)} の記録を反映済み</div>`:''}</section><div><section class="card"><div class="card-heading"><h2>今日のチェックイン</h2></div><div class="timeline"><div class="timeline-item"><span class="timeline-icon done">${icon('check')}</span><div><h3>カードを読み取る</h3><p>${timeText(r.entry_at)} に入室を記録</p></div></div><div class="timeline-item"><span class="timeline-icon done">${icon('check')}</span><div><h3>ログインリンクでログイン</h3><p>本人確認が完了しました</p></div></div><div class="timeline-item"><span class="timeline-icon ${r.confirmed?'done':''}">${icon(r.confirmed?'check':'mail')}</span><div><h3>出席を登録して、メールで確認</h3><p>${r.confirmed?'手続き完了・通知済み':'左のボタンから出席を登録'}</p></div></div></div></section><div class="info-strip">${icon('clock')}出席の判定には、カードをかざした時刻が使われます。</div>${sessionStrip()}${absenceStrip(r.course_id)}${r.confirmed?`<div style="margin-top:18px">${textButton('nav','出席状況を確認','data-view="overview"')}</div>`:''}</div></div>`;
}

function notifications() {
  const messages=S.data.mail.filter(m=>m.kind!=='login');
  return `${heading('NOTIFICATIONS','お知らせ','あなた宛ての通知を確認できます。')}<section class="card"><div class="card-heading"><h2>受信した通知</h2><small>${messages.length}件</small></div>${messages.length?messages.map(m=>`<button class="mail-card" data-action="mail" data-id="${m.id}"><span class="notice-icon">${icon(m.kind==='correction'?'edit':'mail')}</span><div><h3>${escape(m.subject)}</h3><p>${escape(m.body.split('\n').filter(Boolean)[2] || '')}</p></div><small>${mailTime(m.created_at)}</small>${icon('chevron')}</button>`).join(''):empty('お知らせはまだありません','出席手続きや記録の変更があると、ここに届きます。','bell')}</section>`;
}

function adminOverview() {
  const d=S.data, todayLessons=d.lessons.filter(l=>l.day===S.boot.today);
  const todayRecords=d.records.filter(r=>r.day===S.boot.today), confirmed=todayRecords.filter(r=>r.confirmed);
  const active=new Set(todayRecords.filter(r=>r.entry_at).map(r=>r.student_id)).size;
  return `${heading('TEACHER WORKSPACE','ダッシュボード',`${escape(user().name)}先生、お疲れさまです。`,`<span class="pill">${icon('shield')}管理者</span>`)}<div class="stats-grid">${statCard('登録学生',d.students.length,'人','users')}${statCard('今日の授業',todayLessons.length,'科目','book')}${statCard('入室した学生',active,'人','card')}${statCard('手続き完了',confirmed.length,'件','check')}</div><div class="card admin-banner"><span class="course-icon">${icon('book')}</span><div><h2>新しい年度の準備を。</h2><p>科目、授業時間、受講名簿をまとめて登録できます。</p></div>${button('course-create','科目を登録','plus','secondary')}</div><div class="admin-grid"><section class="card"><div class="card-heading"><h2>今日の授業</h2>${textButton('nav','出席記録へ','data-view="records"')}</div><div class="today-list">${todayLessons.map((l,i)=>`<div class="lesson-row"><div class="lesson-time">${l.first_start}<small>${l.second_end}</small></div><span class="lesson-marker ${i%2?'blue':''}"></span><div class="lesson-info"><h3>${escape(l.course_name)}</h3><p>${icon('pin')}${escape(l.room)}<span>${d.enrollments.filter(e=>e.course_id===l.course_id).length}人</span></p></div>${textButton('lesson-records','記録を見る',`data-id="${l.course_id}" data-day="${l.day}"`)}</div>`).join('')||'<div class="empty-small">今日の授業はありません</div>'}</div></section><section class="card"><div class="card-heading"><h2>最近の操作</h2><small>変更履歴</small></div>${d.audit.slice(0,4).map(a=>`<div class="audit-item"><strong>${escape(a.action)}</strong><p>${escape(a.detail)}</p><small>${escape(a.actor)} · ${mailTime(a.created_at)}</small></div>`).join('')||'<div class="empty-small">操作履歴はまだありません</div>'}</section></div><section class="card" style="margin-top:24px"><div class="card-heading"><h2>メール配信</h2><small>${S.boot.demo?'ローカルメールボックス':'SMTP配信状況'}</small></div>${d.mail.length?`<div class="table-wrap"><table><thead><tr><th>宛先</th><th>件名</th><th>日時</th><th>状態</th></tr></thead><tbody>${d.mail.slice(0,5).map(m=>`<tr><td>${escape(m.recipient)}</td><td><strong>${escape(m.subject)}</strong></td><td>${mailTime(m.created_at)}</td><td>${badge(m.delivery)}</td></tr>`).join('')}</tbody></table></div>`:empty('配信したメールはありません','','mail')}</section>`;
}

function adminRecordRows() {
  const d=S.data;
  let records=[...d.records];
  const existing=new Set(records.map(r=>r.student_id+'|'+r.lesson_id));
  for(const l of d.lessons.filter(l=>l.day===S.recordDate)) {
    for(const e of d.enrollments.filter(e=>e.course_id===l.course_id)) {
      if(existing.has(e.student_id+'|'+l.id)) continue;
      const student=d.students.find(s=>s.id===e.student_id);
      records.push({id:null,lesson_id:l.id,student_id:e.student_id,student_name:student.name,course_id:l.course_id,course_name:l.course_name,day:l.day,first_status:'unrecorded',second_status:'unrecorded',confirmed:0});
    }
  }
  return records.filter(r=>(S.recordCourse==='all'||String(r.course_id)===S.recordCourse)&&(!S.recordDate||r.day===S.recordDate)&&(!S.query||(r.student_name+r.student_id).toLowerCase().includes(S.query.toLowerCase()))).sort((a,b)=>b.day.localeCompare(a.day)||a.student_id.localeCompare(b.student_id));
}
function adminRecords() {
  const records=adminRecordRows();
  return `${heading('ATTENDANCE RECORDS','出席記録','記録の修正は対象学生にメールで通知されます。')}<section class="card"><div class="card-heading"><h2>学生の出席記録</h2><div class="table-filters"><label class="table-search">${icon('search')}<input type="search" placeholder="氏名・学籍番号" data-filter="search" value="${escape(S.query)}" aria-label="学生を検索"></label><select data-filter="record-course" aria-label="科目で絞り込む">${opt('all','すべての科目',S.recordCourse)}${S.data.courses.map(c=>opt(c.id,c.name,S.recordCourse)).join('')}</select><input type="date" data-filter="record-date" value="${escape(S.recordDate)}" aria-label="授業日で絞り込む"></div></div>${records.length?`<div class="table-wrap"><table><thead><tr><th>学生</th><th>科目・授業日</th><th>入室 / 退室</th><th>1コマ目</th><th>2コマ目</th><th></th></tr></thead><tbody>${records.map(r=>`<tr><td><strong>${escape(r.student_name)}</strong><small>${escape(r.student_id)}</small></td><td><strong>${escape(r.course_name)}</strong><small>${r.day}${r.reason?' · '+escape(r.reason):''}</small></td><td>${timeText(r.entry_at)} / ${timeText(r.exit_at)}${r.entry_at&&!r.confirmed?'<small>手続き待ち</small>':''}</td><td>${badge(r.first_status)}</td><td>${badge(r.second_status)}</td><td><button class="icon-button" data-action="record-edit" data-student="${escape(r.student_id)}" data-lesson="${r.lesson_id}" aria-label="${escape(r.student_name)}の出席記録を修正">${icon('edit')}修正</button></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${records.length}件の記録</span><span>カード読取時刻に基づく判定</span></div>`:empty('該当する記録がありません','科目や日付を変えてお試しください。','search')}</section>`;
}

function adminCourses() {
  const d=S.data;
  return `${heading('COURSES & ROSTERS','科目・受講名簿',`${S.boot.today.slice(0,4)}年度の授業を管理`,button('course-create','科目を登録'))}<section class="card"><div class="card-heading"><h2>登録済みの科目</h2><small>${d.courses.length}科目</small></div>${d.courses.length?`<div class="table-wrap"><table><thead><tr><th>科目</th><th>担当・教室</th><th>授業時間</th><th>年度</th><th>受講者</th><th></th></tr></thead><tbody>${d.courses.map(c=>{const l=d.lessons.find(l=>l.course_id===c.id); return `<tr><td><strong>${escape(c.name)}</strong><small>${escape(c.code)}</small></td><td>${escape(c.teacher)}<small>${escape(c.room)}</small></td><td>${l?`${l.first_start} — ${l.first_end}<small>${l.second_start} — ${l.second_end}</small>`:'—'}</td><td>${c.year}</td><td><span class="roster-count">${d.enrollments.filter(e=>e.course_id===c.id).length}人</span></td><td><button class="icon-button" data-action="roster-edit" data-id="${c.id}">${icon('users')}名簿</button></td></tr>`;}).join('')}</tbody></table></div>`:empty('科目が登録されていません','科目と授業時間、受講者を登録しましょう。','book')}</section>`;
}

function adminStudents() {
  const students=S.data.students.filter(s=>!S.query||(s.name+s.id+s.email).toLowerCase().includes(S.query.toLowerCase()));
  return `${heading('STUDENTS','学生',`${S.data.students.length}人が登録されています。`,button('student-create','学生を追加'))}<section class="card"><div class="card-heading"><h2>学生名簿</h2><div class="table-filters"><label class="table-search">${icon('search')}<input type="search" placeholder="氏名・学籍番号" data-filter="search" value="${escape(S.query)}" aria-label="学生を検索"></label></div></div>${students.length?`<div class="table-wrap"><table><thead><tr><th>学生</th><th>メールアドレス</th><th>カードID</th><th>登録年度</th><th></th></tr></thead><tbody>${students.map(s=>`<tr><td><strong>${escape(s.name)}</strong><small>${escape(s.id)}</small></td><td>${escape(s.email)}</td><td>${escape(s.card_id)}</td><td>${s.year}</td><td><div class="record-summary"><button class="icon-button" data-action="student-edit" data-id="${escape(s.id)}" aria-label="${escape(s.name)}の登録情報を編集">${icon('edit')}</button><button class="icon-button" data-action="student-delete" data-id="${escape(s.id)}" aria-label="${escape(s.name)}を削除">${icon('trash')}</button></div></td></tr>`).join('')}</tbody></table></div><div class="table-bottom"><span>${students.length}人</span><span>メールアドレスと学生証を紐付け</span></div>`:empty('学生が見つかりません','','users')}</section>`;
}

function adminAdmins() {
  return `${heading('ADMINISTRATORS','管理者','教員アカウントを管理します。',button('admin-create','管理者を追加'))}<section class="card"><div class="card-heading"><h2>管理者一覧</h2><small>${S.data.admins.length}人</small></div><div class="table-wrap"><table><thead><tr><th>氏名</th><th>ユーザーID</th><th>権限</th><th></th></tr></thead><tbody>${S.data.admins.map(a=>`<tr><td><strong>${escape(a.name)}</strong>${a.id===user().id?'<small>ログイン中</small>':''}</td><td>${escape(a.id)}</td><td><span class="status excused">教員・管理者</span></td><td>${a.id!==user().id?`<button class="icon-button" data-action="admin-delete" data-id="${escape(a.id)}" aria-label="${escape(a.name)}を削除">${icon('trash')}</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function render() {
  if(!S.boot) return;
  let content;
  if(!user()) content=login();
  else if(user().role==='student') content=({overview:studentOverview,checkin,log:usageLog,notifications}[S.view]||studentOverview)();
  else content=({overview:adminOverview,records:adminRecords,courses:adminCourses,students:adminStudents,admins:adminAdmins}[S.view]||adminOverview)();
  $('#app').innerHTML=shell(content);
  document.title='Rollcall — '+(!user()?'ログイン':({overview:'出席状況',checkin:'出席手続き',log:'利用ログ',notifications:'お知らせ',records:'出席記録',courses:'科目・受講名簿',students:'学生',admins:'管理者'}[S.view]||'出席管理'));
}

function modal(title,body) {
  const dialog=$('#modal');
  dialog.innerHTML=`<div class="modal-head"><h2 id="modal-title">${title}</h2><button class="close-button" data-action="close-modal" aria-label="閉じる">${icon('close')}</button></div><div class="modal-body">${body}</div>`;
  if(!dialog.open) dialog.showModal();
}
const actions = (label='保存する') => `<div class="modal-actions"><button type="button" class="button secondary" data-action="close-modal">キャンセル</button><button type="submit" class="button">${label}</button></div>`;
const errorBox = '<div class="form-error" role="alert"></div>';
function field(label,name,value='',type='text',attrs='') {
  return `<label class="field"><span>${label}</span><input class="input" type="${type}" name="${name}" value="${escape(value)}" ${attrs}></label>`;
}
function checkboxes(items,name,selected=[]) {
  return `<div class="checkbox-grid">${items.map(item=>`<label class="checkbox-item"><input type="checkbox" name="${name}" value="${escape(item.id)}" ${selected.includes(String(item.id))?'checked':''}>${escape(item.name)}${item.id?` <span class="field-hint">${escape(item.id)}</span>`:''}</label>`).join('')||'<span class="field-hint">登録がありません</span>'}</div>`;
}

function editRecord(studentId,lessonId) {
  const student=S.data.students.find(s=>s.id===studentId), lesson=S.data.lessons.find(l=>l.id===Number(lessonId));
  const record=S.data.records.find(r=>r.student_id===studentId&&r.lesson_id===Number(lessonId));
  modal('出席記録を修正',`<p>${escape(student.name)} · ${escape(student.id)}<br>${escape(lesson.course_name)} / ${lesson.day}</p><form data-form="record" style="margin-top:24px">${errorBox}<input type="hidden" name="student_id" value="${escape(studentId)}"><input type="hidden" name="lesson_id" value="${lesson.id}"><div class="form-grid"><label class="field"><span>1コマ目</span><select class="input" name="first_status">${statusOptions(record?.first_status||'absent')}</select></label><label class="field"><span>2コマ目</span><select class="input" name="second_status">${statusOptions(record?.second_status||'absent')}</select></label><label class="field span-2"><span>変更理由</span><textarea class="input" name="reason" placeholder="例：公欠届を確認したため" maxlength="500" required>${escape(record?.reason||'')}</textarea></label></div><div class="info-strip">${icon('mail')}変更後の出席情報を ${escape(student.email)} に通知します。</div>${actions('変更して通知')}</form>`);
}
function editStudent(id) {
  const student=S.data.students.find(s=>s.id===id);
  const enrolled=S.data.enrollments.filter(e=>e.student_id===id).map(e=>String(e.course_id));
  modal(student?'学生情報を編集':'学生を追加',`<form data-form="student">${errorBox}<input type="hidden" name="editing" value="${student?'1':''}"><div class="form-grid">${field('学籍番号','id',student?.id||'','text','required maxlength="30" '+(student?'readonly':''))}${field('氏名','name',student?.name||'','text','required maxlength="60"')}${field('メールアドレス','email',student?.email||'','email','required maxlength="200"')}${field('カードID','card_id',student?.card_id||'','text','required maxlength="80"')}${field('登録年度','year',student?.year||S.boot.today.slice(0,4),'number','required min="2000" max="2100"')}<div class="field span-2"><span>受講科目</span>${checkboxes(S.data.courses,'course_ids',enrolled)}</div></div>${actions(student?'変更を保存':'学生を追加')}</form>`);
}
function createCourse() {
  modal('科目を登録',`<form data-form="course">${errorBox}<div class="form-grid">${field('科目名','name','','text','required maxlength="120"')}${field('科目コード','code','','text','required maxlength="30"')}${field('担当教員','teacher',user().name,'text','required maxlength="60"')}${field('教室','room','','text','required maxlength="60"')}${field('年度','year',S.boot.today.slice(0,4),'number','required min="2000" max="2100"')}${field('初回授業日','start_date',S.boot.today,'date','required')}${field('1コマ目 開始','first_start','09:00','time','required')}${field('1コマ目 終了','first_end','10:30','time','required')}${field('2コマ目 開始','second_start','10:40','time','required')}${field('2コマ目 終了','second_end','12:10','time','required')}${field('授業回数（毎週）','weeks','15','number','required min="1" max="30"')}<div class="field span-2"><span>受講学生</span>${checkboxes(S.data.students,'student_ids')}</div></div>${actions('科目と時間割を登録')}</form>`);
}
function editRoster(id) {
  const course=S.data.courses.find(c=>c.id===Number(id));
  const selected=S.data.enrollments.filter(e=>e.course_id===course.id).map(e=>e.student_id);
  modal('受講名簿を編集',`<p>${escape(course.name)}</p><form data-form="roster" style="margin-top:22px">${errorBox}<input type="hidden" name="course_id" value="${course.id}"><div class="field"><span>受講学生</span>${checkboxes(S.data.students,'student_ids',selected)}</div>${actions('名簿を保存')}</form>`);
}
function createAdmin() {
  modal('管理者を追加',`<form data-form="new-admin">${errorBox}${field('氏名','name','','text','required maxlength="60"')}${field('ユーザーID','id','','text','required maxlength="40" autocomplete="off"')}${field('パスワード','password','','password','required minlength="10" maxlength="200" autocomplete="new-password"')}<p class="field-hint">パスワードは10文字以上</p>${actions('管理者を追加')}</form>`);
}
function deleteAccount(type,id) {
  const person=(type==='students'?S.data.students:S.data.admins).find(x=>x.id===id);
  modal(type==='students'?'学生を削除':'管理者を削除',`<p>${escape(person.name)}（${escape(id)}）を削除します。${type==='students'?'<br>この学生の出席記録と通知も削除されます。':''}</p><form data-form="delete"><input type="hidden" name="type" value="${type}"><input type="hidden" name="id" value="${escape(id)}">${errorBox}<div class="modal-actions"><button class="button secondary" type="button" data-action="close-modal">キャンセル</button><button class="button danger" type="submit">削除する</button></div></form>`);
}
function showMail(id) {
  const mail=S.data.mail.find(m=>m.id===Number(id));
  modal(escape(mail.subject),`<p>${escape(mail.recipient)}<br>${mailTime(mail.created_at)}　${badge(mail.delivery)}</p><div class="mail-body">${escape(mail.body)}</div>`);
}

async function openDemo() {
  S.demo=await api('/demo/data');
  drawDemo();
}
function drawDemo() {
  const d=S.demo;
  if(!d.students.some(s=>s.id===S.demoStudent)) S.demoStudent=d.students[0]?.id;
  const courses=d.enrollments.filter(e=>e.student_id===S.demoStudent).map(e=>e.course_id);
  const lessons=d.lessons.filter(l=>courses.includes(l.course_id));
  if(!lessons.some(l=>l.id===Number(S.demoLesson))) S.demoLesson=lessons[0]?.id;
  const lesson=lessons.find(l=>l.id===Number(S.demoLesson));
  const defaultTime=lesson ? lesson.day+'T'+(S.demoMode==='entry'?lesson.first_start:lesson.second_end) : '';
  const selectedStudent=d.students.find(s=>s.id===S.demoStudent);
  const messages=d.mail.filter(m=>m.student_id===S.demoStudent);
  modal('デモを試す',`<div class="demo-warning">${icon('info')}デモ専用 · 実際のメール送信やカードリーダーは使用しません。</div><div class="page-tabs"><button class="page-tab ${S.demoTab==='reader'?'active':''}" data-action="demo-tab" data-tab="reader">カードリーダー</button><button class="page-tab ${S.demoTab==='mail'?'active':''}" data-action="demo-tab" data-tab="mail">メールボックス</button></div><label class="field"><span>学生</span><select class="input" data-demo="student">${d.students.map(s=>opt(s.id,s.name+' · '+s.id,S.demoStudent)).join('')}</select></label>${S.demoTab==='reader'?`<form data-form="demo-event">${errorBox}<label class="field"><span>授業</span><select class="input" name="lesson_id" data-demo="lesson" required>${lessons.map(l=>opt(l.id,l.course_name+' / '+l.day,S.demoLesson)).join('')}</select></label><div class="field"><span>読み取り</span><div class="segmented"><label><input type="radio" name="mode" value="entry" data-demo="mode" ${S.demoMode==='entry'?'checked':''}>入室</label><label><input type="radio" name="mode" value="exit" data-demo="mode" ${S.demoMode==='exit'?'checked':''}>退室</label></div></div><label class="field"><span>カード読取時刻</span><input type="datetime-local" class="input" name="occurred_at" value="${escape(S.demoAt||defaultTime)}" required step="1"></label><p class="field-hint">${S.demoMode==='entry'?'入室後、メールボックスのログインリンクを開いてください。':'退室後、メールボックスのログインリンクを開き、退室を提出してください。'}</p><div class="modal-actions"><button type="submit" class="button full" ${!lesson?'disabled':''}>${icon('card')}${S.demoMode==='entry'?'入室カードを読み取る':'退室カードを読み取る'}</button></div></form>`:`<p class="field-hint">${escape(selectedStudent?.email||'')}</p><div class="demo-mail-list">${messages.map(m=>{const link=m.kind==='login'?m.body.match(/#login=([\w-]{43})/)?.[1]:null;return `<article class="demo-mail"><div class="demo-mail-header"><strong>${escape(m.subject)}</strong>${badge(m.delivery)}</div><small>${mailTime(m.created_at)}</small>${link?`<small>発行から10分間有効 · 1回限り</small>${textButton('demo-use','このリンクを開く',`data-token="${link}"`)}`:`<pre>${escape(m.body)}</pre>`}</article>`;}).join('')||'<div class="empty-small">まだメールがありません</div>'}</div>`}`);
}

async function performForm(form) {
  const type=form.dataset.form, fd=new FormData(form), data=Object.fromEntries(fd);
  const submit=$('button[type="submit"]',form), original=submit?.innerHTML;
  const error=$('.form-error',form);
  if(error) error.textContent='';
  if(submit){submit.disabled=true;submit.textContent='処理中…';}
  try {
    if(type==='admin-login') {
      await api('/auth/admin','POST',data);
      S.view='overview'; S.history=false; S.query='';
      await refresh();
      if(user().role==='admin') S.recordDate=S.boot.today;
      toast('ログインしました。');
      return;
    }
    if(type==='demo-event') {
      await api('/demo/event','POST',{student_id:S.demoStudent,lesson_id:Number(data.lesson_id),mode:data.mode,occurred_at:data.occurred_at+(/[+-]\d{2}:\d{2}$/.test(data.occurred_at)?'':'+09:00')});
      S.demoTab='mail';
      S.demo=await api('/demo/data');
      if(user()) await refresh();
      drawDemo();
      toast(data.mode==='entry'?'入室を記録しました。メールのコードでログインしてください。':'退室を記録しました。メールのコードでログインし、退室を提出してください。');
      return;
    }
    let message='保存しました。';
    if(type==='record') {
      data.lesson_id=Number(data.lesson_id);
      const result=await api('/admin/records','PUT',data);
      message=result.message;
    } else if(type==='student') {
      data.year=Number(data.year);data.course_ids=fd.getAll('course_ids').map(Number);
      await api('/admin/students',data.editing?'PUT':'POST',data);
      message=data.editing?'学生情報を更新しました。':'学生を追加しました。';
    } else if(type==='course') {
      data.year=Number(data.year);data.weeks=Number(data.weeks);data.student_ids=fd.getAll('student_ids');
      await api('/admin/courses','POST',data);
      message='科目・時間割・受講名簿を登録しました。';
    } else if(type==='roster') {
      await api('/admin/enrollments','PUT',{course_id:Number(data.course_id),student_ids:fd.getAll('student_ids')});
      message='受講名簿を更新しました。';
    } else if(type==='new-admin') {
      await api('/admin/admins','POST',data);
      message='管理者を追加しました。';
    } else if(type==='delete') {
      await api('/admin/'+data.type,'DELETE',{id:data.id});
      message='削除しました。';
    }
    $('#modal').close();
    await refresh();
    toast(message);
  } catch(err) {
    if(error) error.textContent=err.message;
    else toast(err.message,true);
  } finally {
    if(submit?.isConnected){submit.disabled=false;submit.innerHTML=original;}
  }
}

document.addEventListener('submit',event=>{
  const form=event.target.closest('form[data-form]');
  if(!form)return;
  event.preventDefault();
  performForm(form);
});
document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');
  if(!target || target.disabled)return;
  const action=target.dataset.action;
  try {
    if(action==='nav') {if(target.dataset.view==='records'&&!S.recordDate)S.recordDate=S.boot.today;nav(target.dataset.view);}
    if(action==='auth-mode'){S.auth=target.dataset.mode;render();}
    if(action==='history'){S.history=target.dataset.history==='true';S.course='all';render();}
    if(action==='course-history'){nav('overview',{history:true,course:target.dataset.id});}
    if(action==='lesson-records'){nav('records',{recordCourse:target.dataset.id,recordDate:target.dataset.day});}
    if(action==='logout'){
      await api('/auth/logout','POST',{});S.view='overview';S.auth='student';await refresh();toast('ログアウトしました。');
    }
    if(action==='confirm-attendance'){
      target.disabled=true;await api('/student/confirm','POST',{});await refresh();toast('出席手続きが完了しました。');
    }
    if(action==='submit-exit'){
      target.disabled=true;await api('/student/submit-exit','POST',{});await refresh();toast('退室の手続きが完了しました。');
    }
    if(action==='close-modal')$('#modal').close();
    if(action==='mail')showMail(target.dataset.id);
    if(action==='record-edit')editRecord(target.dataset.student,target.dataset.lesson);
    if(action==='student-create')editStudent();
    if(action==='student-edit')editStudent(target.dataset.id);
    if(action==='course-create')createCourse();
    if(action==='roster-edit')editRoster(target.dataset.id);
    if(action==='admin-create')createAdmin();
    if(action==='student-delete')deleteAccount('students',target.dataset.id);
    if(action==='admin-delete')deleteAccount('admins',target.dataset.id);
    if(action==='demo')await openDemo();
    if(action==='demo-tab'){S.demoTab=target.dataset.tab;S.demo=await api('/demo/data');drawDemo();}
    if(action==='demo-use'){
      if(user())await api('/auth/logout','POST',{});
      await api('/auth/link','POST',{token:target.dataset.token});
      S.auth='student';S.view='checkin';$('#modal').close();await refresh();toast('本人確認が完了しました。');
    }
  }catch(err){target.disabled=false;toast(err.message,true);}
});
document.addEventListener('change',event=>{
  const target=event.target;
  if(target.dataset.filter==='student-course'){S.course=target.value;render();}
  if(target.dataset.filter==='record-course'){S.recordCourse=target.value;render();}
  if(target.dataset.filter==='record-date'){S.recordDate=target.value;render();}
  if(target.dataset.demo){
    if(target.dataset.demo==='student'){S.demoStudent=target.value;S.demoLesson=null;}
    if(target.dataset.demo==='lesson')S.demoLesson=Number(target.value);
    if(target.dataset.demo==='mode')S.demoMode=target.value;
    S.demoAt=null;drawDemo();
  }
});
document.addEventListener('input',event=>{
  const target=event.target;
  if(target.name==='code')target.value=target.value.replace(/[０-９]/g,c=>String.fromCharCode(c.charCodeAt(0)-0xfee0)).replace(/\D/g,'').slice(0,6);
  if(target.name==='occurred_at')S.demoAt=target.value;
  if(target.dataset.filter==='search'){
    const position=target.selectionStart;S.query=target.value;render();
    const input=$('[data-filter="search"]');input.focus();input.setSelectionRange(position,position);
  }
});
$('#modal').addEventListener('click',event=>{
  if(event.target!==$('#modal'))return;
  const rect=event.target.getBoundingClientRect();
  if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)event.target.close();
});
async function start() {
  const link=location.hash.match(/^#login=([\w-]{43})$/);  // the mailed link; the token stays in the fragment, away from server logs
  if(link) {
    history.replaceState(null,'',location.pathname+location.search);
    try {await api('/auth/link','POST',{token:link[1]});S.view='checkin';S.linked=true;}
    catch(err){S.linkError=err.message;}
  }
  await refresh();
  if(S.linked)toast('本人確認が完了しました。');
}
start().catch(err=>{
  $('#app').innerHTML=`<main class="content"><div class="card">${empty('サーバーに接続できません',err.message,'info',button('reload','再読み込み','arrow','secondary'))}</div></main>`;
  document.addEventListener('click',event=>{if(event.target.closest('[data-action="reload"]'))location.reload();});
});
