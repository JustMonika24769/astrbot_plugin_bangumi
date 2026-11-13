const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const bridge = window.AstrBotPluginView || window.AstrBotPluginPage;
const state = {subscriptions: [], platforms: [], jobs: [], checking: false};
let page = 'subscriptions', filter = 'all', calendar = null, selectedDay = null;
let detailVersion = 0;
let loading = false, refreshQueued = false, targetsInitialized = false, searchVersion = 0, pollTimer, toastTimer, confirmAction = null;

// Images travel through the authenticated bridge, using the server's network/proxy.
const coverCache = new Map(), coverRequests = new Map();
const coverQueue = [];
let activeCovers = 0;
function coverURL(value) {
  return /^data:image\/(?:jpeg|png|gif|webp|avif);base64,[A-Za-z0-9+/]+={0,2}$/.test(value || '') ? value : '';
}
function cover(value, cls = '', alt = '', subjectId = '') {
  const id = String(subjectId);
  const entry = coverCache.get(id);
  const cached = entry && entry.expires > Date.now() ? entry.url : '';
  const url = cached || coverURL(value);
  if (!url && !/^[0-9]+$/.test(id)) return `<span class="${cls}" aria-hidden="true"></span>`;
  return `<img class="${cls}" ${url ? `src="${escape(url)}"` : 'style="opacity:0"'} data-cover-id="${escape(id)}" alt="${escape(alt)}" loading="lazy">`;
}
function fetchCover(id) {
  const cached = coverCache.get(id);
  if (cached && cached.expires > Date.now()) return Promise.resolve(cached.url);
  if (coverRequests.has(id)) return coverRequests.get(id);
  const promise = new Promise(resolve => { coverQueue.push({id, resolve}); });
  coverRequests.set(id, promise);
  drainCovers();
  return promise;
}
function drainCovers() {
  while (activeCovers < 3 && coverQueue.length) {
    const {id, resolve} = coverQueue.shift();
    activeCovers++;
    (async () => {
      let url = '';
      try { url = coverURL((await api('cover', {subject_id:id})).cover_url); }
      catch { /* A failed cover must not block subscription management. */ }
      coverCache.delete(id);
      coverCache.set(id, {url, expires:Date.now() + (url ? 3600000 : 30000)});
      while (coverCache.size > 128) coverCache.delete(coverCache.keys().next().value);
      coverRequests.delete(id); activeCovers--; resolve(url); drainCovers();
    })();
  }
}
const coverObserver = new IntersectionObserver(entries => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const img = entry.target;
    coverObserver.unobserve(img);
    fetchCover(img.dataset.coverId).then(url => {
      if (!img.isConnected) return;
      if (url) { img.src = url; img.style.opacity = ''; img.style.display = ''; }
      else { img.style.display = 'none'; img.title = '封面暂时不可用，稍后刷新重试'; }
    });
  }
}, {rootMargin:'200px'});
function loadCovers() {
  coverObserver.disconnect();
  $$('img[data-cover-id]').forEach(img => {
    if (!img.hasAttribute('src')) coverObserver.observe(img);
  });
}
function sessionLabel(value) {
  const parts = value.split(':');
  if (parts.length < 3) return `旧版群聊 · ${value}`;
  const [platform, type, ...target] = parts;
  const name = state.platforms.find(item => item.id === platform)?.name || platform;
  return `${name} · ${type.toLowerCase().includes('group') ? '群' : '私聊'} ${target.join(':')}`;
}
function formatTime(value) {
  if (!value) return '尚未检查';
  // Stored SQLite timestamps are local wall time. Do not guess a historical timezone.
  return value.replace('T', ' ').slice(0, 16);
}
function toast(message, error = false) {
  clearTimeout(toastTimer); $('#toast').textContent = message;
  $('#toast').classList.toggle('error', error); $('#toast').hidden = false;
  toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500);
}
function notice(message) {
  $('#notice').replaceChildren(document.createTextNode(message));
  const retry = document.createElement('button'); retry.textContent = '重新连接';
  retry.onclick = () => refresh(); $('#notice').append(retry); $('#notice').hidden = false;
}
function empty(title, description, action = false) {
  return `<div class="empty-state"><span>✧</span><h3>${escape(title)}</h3><p>${escape(description)}</p>${action ? `<button class="button primary" data-discover>${icon('plus')}寻找下一部心动</button>` : ''}</div>`;
}
async function api(endpoint, body) {
  if (!bridge) throw new Error('请在 AstrBot 后台的插件详情中打开「追番手帐」');
  return body === undefined ? bridge.apiGet(`webui/${endpoint}`) : bridge.apiPost(`webui/${endpoint}`, body);
}
function schedulePoll() {
  clearTimeout(pollTimer);
  if (!document.hidden && bridge) pollTimer = setTimeout(() => refresh(), state.checking ? 2200 : 45000);
}
async function refresh() {
  if (loading) { refreshQueued = true; return; }
  loading = true; $('#reload').disabled = true;
  try {
    const data = await api('state');
    const runningIds = new Set(state.jobs.filter(job => job.status === 'running').map(job => job.id));
    Object.assign(state, data);
    for (const job of state.jobs) if (runningIds.has(job.id) && job.status !== 'running') toast(job.summary || '检查已结束', job.status === 'error');
    $('#connection').textContent = '已连接 AstrBot'; $('#notice').hidden = true;
    $('#sync-time').textContent = `最近同步 ${new Date().toLocaleTimeString('zh-CN', {hour12:false, hour:'2-digit', minute:'2-digit'})}`;
    renderState();
  } catch (error) {
    $('#connection').textContent = '连接暂不可用'; notice(error.message);
    if (!state.subscriptions.length) $('#subscription-grid').innerHTML = empty('手帐还未连接', '连接成功后，你的订阅会在这里出现。');
  } finally { loading = false; $('#reload').disabled = false; schedulePoll(); if (refreshQueued) { refreshQueued = false; queueMicrotask(() => refresh()); } }
}
function setOptions(select, options, previous) {
  select.innerHTML = options;
  if ([...select.options].some(option => option.value === previous)) select.value = previous;
}
function renderState() {
  const items = state.subscriptions;
  $('#stat-subjects').textContent = new Set(items.map(item => item.subject_id)).size;
  $('#stat-sessions').textContent = new Set(items.map(item => item.session_id)).size;
  $('#stat-pending').textContent = items.filter(item => item.pending).length;
  $('#stat-errors').textContent = items.filter(item => item.delivery_error || item.subject_error).length;
  $('#pending-count').textContent = items.filter(item => item.pending).length;
  $('#nav-count').textContent = items.length;
  $('#job-dot').hidden = !state.checking;
  $('#check').disabled = state.checking;
  $('#check span').textContent = state.checking ? '正在检查…' : '检查更新';
  const options = [...new Set(items.map(item => item.session_id))].sort().map(id => `<option value="${escape(id)}">${escape(sessionLabel(id))}</option>`).join('');
  setOptions($('#session-filter'), `<option value="">全部会话</option>${options}`, $('#session-filter').value);
  setOptions($('#target-session'), `${options}<option value="new">＋ 添加新会话</option>`, targetsInitialized ? $('#target-session').value : (items[0]?.session_id || 'new'));
  targetsInitialized = true;
  setOptions($('#target-platform'), state.platforms.map(p => `<option value="${escape(p.id)}">${escape(p.name)} · ${escape(p.id)}</option>`).join(''), $('#target-platform').value);
  $('#new-session').hidden = $('#target-session').value !== 'new';
  renderSubscriptions(); renderActivity(); updateSearchActions();
}
function renderSubscriptions() {
  const query = $('#local-search').value.trim().toLowerCase();
  const session = $('#session-filter').value;
  const rows = state.subscriptions.filter(item => (!session || item.session_id === session) && (!query || `${item.title} ${item.subject_id}`.toLowerCase().includes(query)) && (filter !== 'pending' || item.pending) && (filter !== 'error' || item.delivery_error || item.subject_error));
  $('#list-count').textContent = rows.length;
  $$('.filter').forEach(button => { button.classList.toggle('active', button.dataset.filter === filter); button.setAttribute('aria-pressed', String(button.dataset.filter === filter)); });
  if (!rows.length) {
    $('#subscription-grid').innerHTML = state.subscriptions.length ? empty('这一页，暂时留白', '试试其他会话、关键词或筛选条件。') : empty('故事的第一页，等你开启', '添加一部喜欢的动画，把更新交给追番手帐。', true);
    return;
  }
  $('#subscription-grid').innerHTML = rows.map((item, index) => {
    const error = item.delivery_error || item.subject_error;
    const badge = error ? '需要留意' : item.pending ? '等待通知' : '追番中';
    const progress = item.total_episodes > 0 ? Math.max(0, Math.min(100, item.current_episode / item.total_episodes * 100)) : 0;
    const number = state.subscriptions.indexOf(item);
    return `<article class="anime-card" style="animation-delay:${Math.min(index, 8) * 35}ms"><div class="poster">${cover(item.cover_url, '', item.title, item.subject_id)}<div class="poster-top"><span class="badge ${error ? 'error' : item.pending ? 'pending' : ''}">${escape(badge)}</span><span class="poster-index">No. ${String(index + 1).padStart(2, '0')}</span></div><div class="poster-bottom"><span>${escape(item.weekly_schedule || item.broadcast_schedule || '常规放送时间待定')}</span><span>BGM ${escape(item.subject_id)}</span></div></div><div class="card-body"><h3 class="card-title" title="${escape(item.title)}">${escape(item.title)}</h3><p class="card-subtitle" title="${escape(item.session_id)}">${icon('bell')}${escape(sessionLabel(item.session_id))}</p><div class="progress-label"><span>已播 <b>EP ${escape(item.current_episode)}</b></span><span>全 ${item.total_episodes || '待定'} 集</span></div><div class="progress-track" role="progressbar" aria-label="已播进度" aria-valuenow="${Math.round(progress)}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill" style="width:${progress}%"></div></div><p class="card-status ${error ? 'has-error' : ''}" title="${escape(error || item.broadcast_schedule)}">${escape(error || `已通知 EP ${item.last_notified_episode} · ${formatTime(item.last_checked_at)}`)}</p><div class="card-actions"><button class="text-button detail-button" data-detail="${escape(item.subject_id)}">条目详情 ${icon('link')}</button><button class="text-button" data-remove="${number}">取消订阅</button></div></div></article>`;
  }).join('');
  loadCovers();
}
function renderActivity() {
  $('#activity-list').innerHTML = state.jobs.length ? state.jobs.map(job => `<article class="activity-card"><div class="activity-head"><span class="badge ${job.status === 'error' ? 'error' : job.status === 'running' ? 'pending' : ''}">${escape({running:'检查中', done:'已完成', error:'未完成', cancelled:'已停止'}[job.status] || job.status)}</span><h3>${escape(job.session_id ? sessionLabel(job.session_id) : '全部会话')}</h3><time>${escape(formatTime(job.started_at))}</time></div><p>${escape(job.summary || '正在查询番剧更新，完成后会自动刷新。')}</p>${job.report?.details?.length ? `<details><summary>查看检查明细</summary><ul>${job.report.details.map(detail => `<li>${escape(detail)}</li>`).join('')}</ul></details>` : ''}</article>`).join('') : empty('还没有检查记录', '在「我的追番」中发起检查，结果会记录在这里。');
}
function navigate(next) {
  page = ['subscriptions', 'calendar', 'activity'].includes(next) ? next : 'subscriptions';
  $$('.page-section').forEach(section => { section.hidden = section.id !== `${page}-page`; });
  $$('.nav-item').forEach(button => { button.classList.toggle('active', button.dataset.page === page); button.setAttribute('aria-current', button.dataset.page === page ? 'page' : 'false'); });
  $('#page-label').textContent = {subscriptions:'我的追番', calendar:'每周放送', activity:'检查记录'}[page];
  $('#hero').hidden = page !== 'subscriptions';
  if (page === 'calendar') loadCalendar();
}
async function loadCalendar(force = false) {
  if (calendar && !force) { renderCalendar(); return; }
  $('#calendar-list').innerHTML = '<div class="loading-state"><span class="spinner"></span>正在翻开放送日历…</div>';
  try {
    const data = await api('calendar'); calendar = data.days;
    selectedDay = calendar.find(day => day.is_today)?.weekday_id ?? calendar[0]?.weekday_id;
    renderCalendar();
  } catch (error) { $('#calendar-list').innerHTML = empty('放送表暂时没有送达', error.message); toast(error.message, true); }
}
function renderCalendar() {
  if (!calendar) return;
  $('#week-tabs').innerHTML = calendar.map(day => `<button class="week-tab ${selectedDay === day.weekday_id ? 'active' : ''}" data-day="${day.weekday_id}" aria-pressed="${selectedDay === day.weekday_id}">${escape(day.weekday_name)}${day.is_today ? ' · 今' : ''}<small>${day.items.length} 部放送</small></button>`).join('');
  const day = calendar.find(item => item.weekday_id === selectedDay);
  $('#calendar-list').innerHTML = day?.items.length ? day.items.map(item => `<article class="calendar-card">${cover(item.cover_url, 'calendar-cover', item.title, item.id)}<div><h3>${escape(item.title)}</h3><p>${item.score > 0 ? `★ ${Number(item.score).toFixed(1)} · ` : ''}ID ${escape(item.id)}</p><button data-calendar-add="${escape(item.id)}">＋ 加入追番</button></div></article>`).join('') : empty('今天，可以补一补进度', '这一天暂时没有放送条目。');
  loadCovers();
}
function openAdd(query = '') {
  $('#search-message').hidden = true;
  if ($('#session-filter').value) $('#target-session').value = $('#session-filter').value;
  $('#new-session').hidden = $('#target-session').value !== 'new';
  $('#remote-query').value = query;
  if (!$('#add-dialog').open) $('#add-dialog').showModal();
  $('#remote-query').focus();
  if (query) $('#search-form').requestSubmit();
}
function episodeDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '日期待定';
  const day = new Date(`${value}T12:00:00Z`);
  return `${value}（周${'日一二三四五六'[day.getUTCDay()]}）`;
}
async function openDetails(id) {
  const version = ++detailVersion;
  $('#detail-title').textContent = '正在翻开故事…';
  $('#detail-body').innerHTML = '<div class="loading-state"><span class="spinner"></span>正在读取条目与单集排期…</div>';
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  try {
    const data = await api('subject', {subject_id:id});
    if (version !== detailVersion || !$('#detail-dialog').open) return;
    const subject = data.subject;
    $('#detail-title').textContent = subject.title;
    $('#detail-body').innerHTML = `<div class="detail-intro">${cover(subject.cover_url, 'detail-cover', subject.title, subject.id)}<div><p class="detail-schedule">${escape(data.weekly_schedule)}</p><p class="muted">${subject.score > 0 ? `★ ${Number(subject.score).toFixed(1)} · ` : ''}全 ${Number(subject.total_episodes) || '待定'} 集 · ID ${escape(subject.id)}</p><label class="field-hint">Bangumi 条目地址（可复制到浏览器）<input class="detail-url" readonly aria-label="Bangumi 条目地址" value="https://bgm.tv/subject/${encodeURIComponent(id)}"></label></div></div><p class="detail-summary">${escape(subject.summary || '这个故事还没有简介。')}</p><h3>单集放送手帐</h3><p class="airing-notice" role="status">${escape(data.airing.message)}</p><p class="field-hint">日期来自 Bangumi 单集资料，不代表已确认播出；常规时间为北京时间，不套用到临时调整的单集日期。</p><ol class="episode-list">${data.episodes.map(ep => `<li class="${data.airing.upcoming?.includes(ep.id) ? 'upcoming' : ''}"><span>EP ${escape(ep.number)} · ${escape(ep.title)}</span><time>${escape(episodeDate(ep.air_date))}</time></li>`).join('') || '<li>暂未收录普通剧集排期</li>'}</ol>`;
    loadCovers();
  } catch (error) {
    if (version !== detailVersion || !$('#detail-dialog').open) return;
    $('#detail-title').textContent = '故事暂时未能打开';
    $('#detail-body').innerHTML = `${empty('条目详情加载失败', error.message)}<button class="button primary" data-detail="${escape(id)}">重试</button>`;
  }
}
function selectedSession() {
  if ($('#target-session').value !== 'new') return $('#target-session').value;
  const platform = $('#target-platform').value, target = $('#target-id').value.trim();
  if (!platform) throw new Error('请先在 AstrBot 中启用一个消息平台');
  if (!target) { $('#target-id').focus(); throw new Error('请填写接收更新的群号或用户 ID'); }
  return `${platform}:${$('#target-type').value}:${target}`;
}
async function search(event) {
  event.preventDefault(); const query = $('#remote-query').value.trim(); if (!query) return;
  const version = ++searchVersion, button = $('#search-form button');
  button.disabled = true; $('#search-message').hidden = true;
  $('#search-results').innerHTML = '<div class="loading-state"><span class="spinner"></span>正在寻找你的下一部心动…</div>';
  try {
    const {subjects} = await api('search', {query});
    if (version !== searchVersion) return;
    $('#search-results').innerHTML = subjects.length ? subjects.map(subject => `<article class="search-result">${cover(subject.cover_url, 'result-cover', subject.title, subject.id)}<div class="result-copy"><h3>${escape(subject.title)}</h3><p>${subject.score > 0 ? `★ ${Number(subject.score).toFixed(1)} · ` : ''}${escape(subject.air_date || '开播待定')} · ID ${escape(subject.id)}</p></div><button class="button primary" data-subscribe="${escape(subject.id)}">＋ 追番</button></article>`).join('') : empty('暂时没有遇见', '试试原名、其他关键词，或直接输入 Bangumi ID。');
    loadCovers();
  } catch (error) { if (version === searchVersion) $('#search-results').innerHTML = empty('搜索暂时未完成', error.message); }
  finally { if (version === searchVersion) button.disabled = false; }
}
function updateSearchActions() {
  const session = $('#target-session').value === 'new'
    ? `${$('#target-platform').value}:${$('#target-type').value}:${$('#target-id').value.trim()}`
    : $('#target-session').value;
  $$('#search-results [data-subscribe]').forEach(button => {
    if (button.dataset.busy) return;
    const subscribed = state.subscriptions.some(item => item.session_id === session && String(item.subject_id) === button.dataset.subscribe);
    button.disabled = subscribed;
    button.textContent = subscribed ? '已订阅' : '＋ 追番';
  });
}
async function subscribe(button) {
  let session_id;
  try { session_id = selectedSession(); } catch (error) { showSearchError(error.message); return; }
  button.disabled = true; button.dataset.busy = 'true';
  try {
    const result = await api('subscribe', {subject_id:button.dataset.subscribe, session_id});
    button.textContent = '已订阅'; toast(result.created ? `已收藏《${result.title}》，期待下一集！` : '这个会话已经订阅过这部动画了');
    await refresh();
    // Keep the chosen destination stable when adding several shows to a new session.
    if ([...$('#target-session').options].some(option => option.value === session_id)) { $('#target-session').value = session_id; $('#new-session').hidden = true; }
  } catch (error) { showSearchError(error.message); }
  finally { delete button.dataset.busy; updateSearchActions(); }
}
function showSearchError(message) { $('#search-message').textContent = message; $('#search-message').hidden = false; }
function ask(title, message, action, label = '确认') {
  $('#confirm-title').textContent = title; $('#confirm-message').textContent = message;
  $('#confirm-action').textContent = label; confirmAction = action; $('#confirm-dialog').showModal();
}
async function removeSubscription(item) {
  await api('unsubscribe', {subject_id:item.subject_id, session_id:item.session_id});
  toast(`已取消《${item.title}》在此会话的订阅`); await refresh();
}
async function startCheck() {
  const session = $('#session-filter').value;
  ask('让新故事，准时送达', `即将检查${session ? `「${sessionLabel(session)}」` : '全部会话'}的追番更新。\n检测到新集数或待重试通知时，会实际发送消息。`, async () => {
    await api('check', session ? {session_id:session} : {});
    toast('检查已开始，可以继续浏览手帐'); await refresh();
  }, '开始检查');
}
function exportSubscriptions() {
  if (!state.subscriptions.length) { toast('还没有可以导出的订阅'); return; }
  const data = {format:'bangumi-subscriptions-v1', exported_at:new Date().toISOString(), subscriptions:state.subscriptions};
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type:'application/json'}));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = `bangumi-subscriptions-${new Date().toISOString().slice(0,10)}.json`;
  document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('订阅清单已导出');
}
$$('.nav-item').forEach(button => button.onclick = () => { location.hash = button.dataset.page; });
window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
$$('.filter').forEach(button => button.onclick = () => { filter = button.dataset.filter; renderSubscriptions(); });
$('#session-filter').onchange = renderSubscriptions; $('#local-search').oninput = renderSubscriptions;
$('#show-errors').onclick = () => { filter = 'error'; location.hash = 'subscriptions'; navigate('subscriptions'); renderSubscriptions(); };
$('#reload').onclick = async () => { for (const [id, entry] of coverCache) if (!entry.url) coverCache.delete(id); await refresh(); if (page === 'calendar') await loadCalendar(true); };
$('#add').onclick = () => openAdd(); $('#hero-add').onclick = () => openAdd();
$('#target-session').onchange = () => { $('#new-session').hidden = $('#target-session').value !== 'new'; updateSearchActions(); };
$('#target-id').oninput = updateSearchActions; $('#target-platform').onchange = updateSearchActions; $('#target-type').onchange = updateSearchActions;
$('#search-form').onsubmit = search; $('#check').onclick = startCheck; $('#export').onclick = exportSubscriptions;
$$('[data-close]').forEach(button => button.onclick = () => $(`#${button.dataset.close}`).close());
$('#confirm-dialog').addEventListener('close', () => { confirmAction = null; });
$('#confirm-action').onclick = async () => {
  if (!confirmAction) return;
  const action = confirmAction, button = $('#confirm-action'); button.disabled = true;
  try { await action(); $('#confirm-dialog').close(); } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
};
document.addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  if (button.hasAttribute('data-discover')) openAdd();
  if (button.dataset.subscribe) subscribe(button);
  if (button.dataset.detail) openDetails(button.dataset.detail);
  if (button.dataset.remove !== undefined) {
    const item = state.subscriptions[Number(button.dataset.remove)];
    if (item) ask('暂时和这个故事告别？', `取消《${item.title}》在「${sessionLabel(item.session_id)}」的订阅。其他会话的订阅不受影响。`, () => removeSubscription(item), '取消订阅');
  }
  if (button.dataset.day) { selectedDay = Number(button.dataset.day); renderCalendar(); }
  if (button.dataset.calendarAdd) openAdd(button.dataset.calendarAdd);
});
document.addEventListener('error', event => { if (event.target instanceof HTMLImageElement) event.target.style.display = 'none'; }, true);
document.addEventListener('visibilitychange', () => { clearTimeout(pollTimer); if (!document.hidden) refresh(); });
window.addEventListener('beforeunload', () => { clearTimeout(pollTimer); clearTimeout(toastTimer); coverObserver.disconnect(); });
$('#today-date').textContent = new Date().toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai', year:'numeric', month:'long', day:'numeric', weekday:'long'});
if (bridge) {
  try { await bridge.ready(); await refresh(); navigate(location.hash.slice(1)); } catch (error) { notice(error.message); }
} else {
  notice('请从 AstrBot 后台 → 插件 → Bangumi → 追番手帐 打开此页面');
  $('#subscription-grid').innerHTML = empty('欢迎来到追番手帐', '在 AstrBot 后台打开，连接你的真实追番收藏。');
}
