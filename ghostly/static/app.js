(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  const PALETTE = ['#00d4ff','#00ff88','#a855f7','#ffbb33','#ff4466','#ec4899','#06b6d4','#22d3ee','#34d399','#a78bfa'];
  const RANGE_TO_DAYS = { '24h': 1, '7d': 7, '30d': 30, '90d': 90 };
  const RANGE_LABELS = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', '90d': 'Last 90 days' };
  const PAGE_TITLES = {
    dashboard:'Dashboard',realtime:'Real-time',pages:'Pages',referrers:'Referrers',
    devices:'Devices',countries:'Countries',funnels:'Funnels',goals:'Goals',
    alerts:'Alerts',settings:'Settings',heatmap:'Heatmap','email-reports':'Email Reports',
    webhooks:'Webhooks',themes:'Themes',plugins:'Plugins',backup:'Backup',
    admin:'Admin',profile:'Profile',retention:'Retention'
  };

  const THEMES = [
    { id:'default',name:'Midnight Ghost',vars:{'--bg':'#06060a','--bg-secondary':'#0c0c10','--bg-card':'rgba(12,12,16,.65)','--cyan':'#00d4ff','--green':'#00ff88','--text':'#e8eaed'},preview:{sidebar:'#0a0a10',topbar:'rgba(6,6,10,.82)',content:'#0c0c10',accent:'#00d4ff'} },
    { id:'aurora',name:'Aurora Drift',vars:{'--bg':'#0a0f1a','--bg-secondary':'#0f1524','--bg-card':'rgba(15,21,36,.65)','--cyan':'#38bdf8','--green':'#34d399','--text':'#e2e8f0'},preview:{sidebar:'#0d1321',topbar:'rgba(10,15,26,.82)',content:'#0f1524',accent:'#38bdf8'} },
    { id:'ember',name:'Ember Glow',vars:{'--bg':'#120a0a','--bg-secondary':'#1a0e0e','--bg-card':'rgba(26,14,14,.65)','--cyan':'#fb923c','--green':'#f97316','--text':'#fde2e2'},preview:{sidebar:'#150c0c',topbar:'rgba(18,10,10,.82)',content:'#1a0e0e',accent:'#fb923c'} },
    { id:'forest',name:'Deep Forest',vars:{'--bg':'#060f0a','--bg-secondary':'#0c1a0e','--bg-card':'rgba(12,26,14,.65)','--cyan':'#4ade80','--green':'#22c55e','--text':'#e2fde8'},preview:{sidebar:'#08140c',topbar:'rgba(6,15,10,.82)',content:'#0c1a0e',accent:'#4ade80'} },
    { id:'cosmic',name:'Cosmic Purple',vars:{'--bg':'#0a0614','--bg-secondary':'#120c20','--bg-card':'rgba(18,12,32,.65)','--cyan':'#c084fc','--green':'#a78bfa','--text':'#ede2fd'},preview:{sidebar:'#0d081a',topbar:'rgba(10,6,20,.82)',content:'#120c20',accent:'#c084fc'} },
    { id:'ocean',name:'Deep Ocean',vars:{'--bg':'#040a14','--bg-secondary':'#081220','--bg-card':'rgba(8,18,32,.65)','--cyan':'#22d3ee','--green':'#06b6d4','--text':'#e0f2fe'},preview:{sidebar:'#060e1a',topbar:'rgba(4,10,20,.82)',content:'#081220',accent:'#22d3ee'} }
  ];

  const DEFAULT_PLUGINS = [
    {id:'gdpr-banner',name:'GDPR Consent Banner',version:'1.4.0',description:'Shows a cookie consent banner for EU visitors. Auto-detects visitor locale.',author:'Ghostly',icon:'\u{1F6E1}',iconBg:'var(--cyan-dim)',enabled:true},
    {id:'custom-events',name:'Custom Events',version:'2.1.0',description:'Track custom button clicks, form submissions, and scroll depth events.',author:'Ghostly',icon:'\u{1F3AF}',iconBg:'var(--green-dim)',enabled:true},
    {id:'ab-testing',name:'A/B Testing',version:'0.9.2',description:'Split traffic between variants and measure conversion impact.',author:'Community',icon:'\u{1F500}',iconBg:'var(--purple-dim)',enabled:false},
    {id:'utm-tracker',name:'UTM Campaign Tracker',version:'1.2.0',description:'Enhanced UTM parameter tracking with campaign dashboards.',author:'Ghostly',icon:'\u{1F4E3}',iconBg:'var(--orange-dim)',enabled:true},
    {id:'error-monitor',name:'JS Error Monitor',version:'1.0.3',description:'Captures unhandled JavaScript errors with stack traces.',author:'Community',icon:'\u{1F41B}',iconBg:'var(--red-dim)',enabled:false},
    {id:'performance',name:'Core Web Vitals',version:'1.1.0',description:'Measures LCP, FID, CLS and reports performance metrics.',author:'Ghostly',icon:'\u{26A1}',iconBg:'var(--yellow-dim)',enabled:true}
  ];

  const DEFAULT_AUDIT_LOG = [
    {action:'User logged in',detail:'demo@ghostly.io from 192.168.1.1',type:'login',time:'2 minutes ago'},
    {action:'Site added',detail:'blog.example.com',type:'create',time:'1 hour ago'},
    {action:'Alert rule updated',detail:'High bounce rate threshold changed to 70%',type:'update',time:'3 hours ago'},
    {action:'Webhook created',detail:'Slack notifications for pageview events',type:'create',time:'5 hours ago'},
    {action:'User role changed',detail:'user@example.com changed from viewer to editor',type:'update',time:'1 day ago'},
    {action:'Site deleted',detail:'old-site.example.com permanently removed',type:'delete',time:'2 days ago'}
  ];

  let state = {
    siteId: null, dateRange: '7d', charts: {}, ws: null, wsReconnectTimer: null,
    sortConfig: { key: null, dir: 'desc' },
    alerts: JSON.parse(localStorage.getItem('ghostly_alerts') || '[]'),
    funnels: JSON.parse(localStorage.getItem('ghostly_funnels') || '[]'),
    goals: JSON.parse(localStorage.getItem('ghostly_goals') || '[]'),
    webhooks: JSON.parse(localStorage.getItem('ghostly_webhooks') || '[]'),
    plugins: JSON.parse(localStorage.getItem('ghostly_plugins') || 'null') || DEFAULT_PLUGINS,
    emailConfig: JSON.parse(localStorage.getItem('ghostly_email_config') || '{"smtpHost":"","smtpPort":"587","smtpUser":"","smtpPass":"","fromEmail":"","fromName":"Ghostly Reports"}'),
    activeTheme: localStorage.getItem('ghostly_theme') || 'default',
    currentSection: 'dashboard', realtimeTimer: null, activeTimer: null,
    heatmapClicks: JSON.parse(localStorage.getItem('ghostly_heatmap_clicks') || '[]'),
    heatmapCanvas: null,
    backupHistory: JSON.parse(localStorage.getItem('ghostly_backups') || '[]'),
    auth: JSON.parse(localStorage.getItem('ghostly_auth') || 'null'),
    isOnline: navigator.onLine,
    users: JSON.parse(localStorage.getItem('ghostly_users') || 'null') || [
      {id:1,name:'Demo User',email:'demo@ghostly.io',password:'demo123',role:'admin',created:'2024-01-15',lastLogin:new Date().toISOString(),apiKey:'ghl_demo_' + Math.random().toString(36).slice(2,18)},
      {id:2,name:'Jane Smith',email:'jane@example.com',password:'pass123',role:'editor',created:'2024-03-20',lastLogin:'2024-12-01T10:30:00Z',apiKey:'ghl_' + Math.random().toString(36).slice(2,18)},
      {id:3,name:'Bob Wilson',email:'bob@example.com',password:'pass123',role:'viewer',created:'2024-06-10',lastLogin:'2024-11-28T14:00:00Z',apiKey:'ghl_' + Math.random().toString(36).slice(2,18)}
    ],
    auditLog: JSON.parse(localStorage.getItem('ghostly_audit_log') || 'null') || DEFAULT_AUDIT_LOG,
    darkMode: localStorage.getItem('ghostly_dark_mode') !== 'false',
    gKeyPending: null, gKeyBuffer: ''
  };

  /* ═══════ UTILITIES ═══════ */
  function formatNumber(n) { if (n == null) return '--'; if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return n.toLocaleString(); }
  function formatDuration(seconds) { if (!seconds || seconds <= 0) return '--'; if (seconds < 60) return Math.round(seconds) + 's'; if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's'; return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm'; }
  function formatPercent(n) { if (n == null) return '--'; return n.toFixed(1) + '%'; }
  function timeAgo(date) { if (!date) return '--'; const s = Math.floor((Date.now() - new Date(date + 'Z').getTime()) / 1000); if (s < 0 || s < 60) return 'just now'; if (s < 3600) return Math.floor(s / 60) + 'm ago'; if (s < 86400) return Math.floor(s / 3600) + 'h ago'; return Math.floor(s / 86400) + 'd ago'; }
  function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }
  function getDays() { return RANGE_TO_DAYS[state.dateRange] || 7; }
  function generateId() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }

  /* ═══════ API CLIENT WITH RETRY ═══════ */
  async function api(path, options = {}, retries = 2) {
    for (let i = 0; i <= retries; i++) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 10000);
        const headers = { 'Content-Type': 'application/json', ...options.headers };
        if (state.auth?.token) headers['Authorization'] = 'Bearer ' + state.auth.token;
        const res = await fetch(path, { headers, signal: controller.signal, ...options });
        clearTimeout(timeout);
        if (res.status === 401) { handleAuthExpiry(); return null; }
        if (!res.ok) return null;
        return await res.json();
      } catch (e) {
        if (i === retries) { console.error('[Ghostly] API error:', path, e); return null; }
        await new Promise(r => setTimeout(r, 500 * (i + 1)));
      }
    }
    return null;
  }
  async function apiPost(path, body) { return api(path, { method: 'POST', body: JSON.stringify(body) }); }
  async function apiPut(path, body) { return api(path, { method: 'PUT', body: JSON.stringify(body) }); }
  async function apiDelete(path) { return api(path, { method: 'DELETE' }); }

  /* ═══════ AUTH SYSTEM ═══════ */
  function handleAuthExpiry() { state.auth = null; localStorage.removeItem('ghostly_auth'); showAuth(); toast('Session expired. Please sign in again.', 'warning'); }
  function showAuth() { $('#authWrapper').style.display = 'flex'; $('#appShell').style.display = 'none'; }
  function showApp() { $('#authWrapper').style.display = 'none'; $('#appShell').style.display = 'flex'; updateUserUI(); }
  function loginUser(email, password) {
    const user = state.users.find(u => u.email === email && u.password === password);
    if (!user) return null;
    const token = 'jwt_' + generateId() + generateId();
    const authData = { token, userId: user.id, expires: Date.now() + 24 * 60 * 60 * 1000 };
    state.auth = authData;
    localStorage.setItem('ghostly_auth', JSON.stringify(authData));
    user.lastLogin = new Date().toISOString();
    localStorage.setItem('ghostly_users', JSON.stringify(state.users));
    addAuditLog('User logged in', user.email + ' via dashboard', 'login');
    return user;
  }
  function registerUser(name, email, password) {
    if (state.users.find(u => u.email === email)) return null;
    const user = { id: Date.now(), name, email, password, role: 'viewer', created: new Date().toISOString().slice(0, 10), lastLogin: new Date().toISOString(), apiKey: 'ghl_' + generateId() + generateId() };
    state.users.push(user);
    localStorage.setItem('ghostly_users', JSON.stringify(state.users));
    addAuditLog('New user registered', email, 'create');
    return loginUser(email, password);
  }
  function logoutUser() {
    state.auth = null;
    localStorage.removeItem('ghostly_auth');
    if (state.realtimeTimer) { clearInterval(state.realtimeTimer); state.realtimeTimer = null; }
    if (state.activeTimer) { clearInterval(state.activeTimer); state.activeTimer = null; }
    if (state.ws) { try { state.ws.close(); } catch (e) {} }
    showAuth();
    toast('Signed out successfully', 'info');
  }
  function getCurrentUser() {
    if (!state.auth) return null;
    return state.users.find(u => u.id === state.auth.userId) || null;
  }
  function updateUserUI() {
    const user = getCurrentUser();
    if (!user) return;
    const initial = (user.name || 'U')[0].toUpperCase();
    $('#userInitial').textContent = initial;
    $('#userDisplayName').textContent = user.name;
    $('#userDisplayEmail').textContent = user.email;
  }
  function addAuditLog(action, detail, type) {
    state.auditLog.unshift({ action, detail, type, time: 'just now' });
    if (state.auditLog.length > 50) state.auditLog = state.auditLog.slice(0, 50);
    localStorage.setItem('ghostly_audit_log', JSON.stringify(state.auditLog));
  }

  /* ═══════ TOAST NOTIFICATIONS ═══════ */
  function toast(message, type = 'info') {
    const container = $('#toastContainer');
    const el = document.createElement('div');
    el.className = 'toast ' + type;
    el.innerHTML = '<span>' + esc(message) + '</span><button class="toast-close" aria-label="Dismiss">&times;</button>';
    el.querySelector('.toast-close').addEventListener('click', () => el.remove());
    container.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.remove(); }, 4000);
  }

  /* ═══════ OFFLINE DETECTION ═══════ */
  function setupOfflineDetection() {
    window.addEventListener('online', () => { state.isOnline = true; $('#offlineBanner').style.display = 'none'; toast('You\'re back online!', 'success'); });
    window.addEventListener('offline', () => { state.isOnline = false; $('#offlineBanner').style.display = 'flex'; toast('You\'re offline. Some features may be limited.', 'warning'); });
    if (!navigator.onLine) { state.isOnline = false; $('#offlineBanner').style.display = 'flex'; }
  }

  /* ═══════ SERVICE WORKER ═══════ */
  function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/static/sw.js').then(reg => {
        reg.addEventListener('updatefound', () => {
          const newWorker = reg.installing;
          if (newWorker) newWorker.addEventListener('statechange', () => {
            if (newWorker.state === 'activated') toast('App updated! Refresh for latest version.', 'info');
          });
        });
      }).catch(() => {});
    }
  }

  /* ═══════ CHART HELPERS ═══════ */
  function destroyChart(name) { if (state.charts[name]) { state.charts[name].destroy(); state.charts[name] = null; } }
  function destroyAllCharts() { Object.keys(state.charts).forEach(destroyChart); }
  function chartTooltip() { return { backgroundColor:'rgba(12,12,16,.94)', titleColor:'#e8eaed', bodyColor:'#a0a4ab', borderColor:'rgba(255,255,255,.08)', borderWidth:1, padding:14, cornerRadius:10, titleFont:{weight:'600',size:13}, bodyFont:{size:12} }; }
  function gridOpts() { return { color:'rgba(255,255,255,.04)', drawBorder:false }; }

  function renderLineChart(canvasId, labels, datasets, opts = {}) {
    destroyChart(canvasId);
    const ctx = $('#' + canvasId);
    if (!ctx || !labels || !labels.length) return;
    state.charts[canvasId] = new Chart(ctx, {
      type:'line', data:{labels,datasets},
      options:{ responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
        plugins:{ legend:{display:datasets.length>1,position:'top',align:'end',labels:{color:'#6b7080',usePointStyle:true,pointStyle:'circle',padding:18,font:{size:12}}}, tooltip:chartTooltip() },
        scales:{ x:{grid:gridOpts(),ticks:{color:'#4a4e5a',font:{size:11},maxTicksLimit:10}}, y:{grid:gridOpts(),ticks:{color:'#4a4e5a',font:{size:11}},beginAtZero:true,...opts.yScale} }, ...opts }
    });
  }

  function renderBarChart(canvasId, items, labelKey, valueKey, color) {
    destroyChart(canvasId);
    const ctx = $('#' + canvasId);
    if (!ctx || !items || !items.length) return;
    state.charts[canvasId] = new Chart(ctx, {
      type:'bar', data:{labels:items.map(i=>i[labelKey]||'Unknown'),datasets:[{data:items.map(i=>i[valueKey]),backgroundColor:color||'#00d4ff',borderRadius:7,barThickness:26,hoverBackgroundColor:color?color+'cc':'#00d4ffcc'}]},
      options:{ responsive:true, maintainAspectRatio:false, indexAxis:'y', plugins:{legend:{display:false},tooltip:chartTooltip()}, scales:{x:{grid:gridOpts(),ticks:{color:'#4a4e5a',font:{size:11}},beginAtZero:true},y:{grid:{display:false},ticks:{color:'#a0a4ab',font:{size:11}}}} }
    });
  }

  function renderDoughnutChart(canvasId, items, labelKey, valueKey) {
    destroyChart(canvasId);
    const ctx = $('#' + canvasId);
    if (!ctx || !items || !items.length) return;
    state.charts[canvasId] = new Chart(ctx, {
      type:'doughnut', data:{labels:items.map(i=>i[labelKey]||'Unknown'),datasets:[{data:items.map(i=>i[valueKey]),backgroundColor:PALETTE.slice(0,items.length),borderWidth:0,hoverOffset:8}]},
      options:{ responsive:true, maintainAspectRatio:false, cutout:'68%', plugins:{legend:{display:true,position:'bottom',labels:{color:'#6b7080',usePointStyle:true,pointStyle:'circle',padding:14,font:{size:11}}},tooltip:chartTooltip()} }
    });
  }

  /* ═══════ DATA MERGING ═══════ */
  function mergeStats(arr) { const v=arr.filter(Boolean); if(!v.length)return null; return {total_pageviews:v.reduce((s,x)=>s+(x.total_pageviews||0),0),unique_visitors:v.reduce((s,x)=>s+(x.unique_visitors||0),0),total_sessions:v.reduce((s,x)=>s+(x.total_sessions||0),0),avg_session_seconds:v.reduce((s,x)=>s+(x.avg_session_seconds||0),0)/v.length,bounce_rate:v.reduce((s,x)=>s+(x.bounce_rate||0),0)/v.length,total_visitors:v.reduce((s,x)=>s+(x.total_visitors||0),0),returning_visitors:v.reduce((s,x)=>s+(x.returning_visitors||0),0)}; }
  function mergeDaily(arr) { const m={}; arr.filter(Boolean).forEach(r=>{(r.daily||[]).forEach(d=>{if(!m[d.day])m[d.day]={day:d.day,views:0,unique_visitors:0}; m[d.day].views+=d.views; m[d.day].unique_visitors+=d.unique_visitors;});}); return Object.values(m).sort((a,b)=>a.day.localeCompare(b.day)); }
  function mergeItems(arr,key,groupBy,countKey) { const m={}; arr.filter(Boolean).forEach(r=>{(r[key]||[]).forEach(i=>{const k=i[groupBy]||'Unknown'; m[k]=m[k]||{[groupBy]:k,[countKey]:0}; m[k][countKey]+=i[countKey];});}); return Object.values(m).sort((a,b)=>b[countKey]-a[countKey]); }

  /* ═══════ SECTION RENDERERS ═══════ */
  function renderDashboard(stats,daily,pages,devices,browsers,countries,referrers) {
    const content=$('#content');
    const br=stats?formatPercent(stats.bounce_rate):'--',ss=stats?formatNumber(stats.total_sessions):'--',ret=stats?formatNumber(stats.returning_visitors):'--';
    const tv=stats?formatNumber(stats.total_pageviews):'--',uv=stats?formatNumber(stats.unique_visitors):'--',at=stats?formatDuration(stats.avg_session_seconds):'--';
    const pps=stats&&stats.total_sessions?(stats.total_pageviews/stats.total_sessions).toFixed(1):'--',tvr=stats?formatNumber(stats.total_visitors):'--';
    content.innerHTML=`<div class="stats-grid">
      <div class="stat-card"><div class="stat-card-icon icon-views"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Pageviews</div><div class="stat-card-value">${tv}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-visitors"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4-4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Unique Visitors</div><div class="stat-card-value">${uv}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-active"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Avg. Session</div><div class="stat-card-value">${at}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-time"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Sessions</div><div class="stat-card-value">${ss}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-bounce"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Bounce Rate</div><div class="stat-card-value">${br}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-returning"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Returning</div><div class="stat-card-value">${ret}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-pageviews"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Pages / Session</div><div class="stat-card-value">${pps}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      <div class="stat-card"><div class="stat-card-icon icon-sessions"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Total Visitors</div><div class="stat-card-value">${tvr}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
    </div>
    <div class="charts-grid" style="margin-top:16px">
      <div class="chart-card wide"><div class="chart-card-header"><h3>Traffic Overview</h3><div class="chart-legend"><span><span class="dot" style="background:var(--cyan)"></span>Views</span><span><span class="dot" style="background:var(--green)"></span>Visitors</span></div></div><div class="chart-container chart-tall"><canvas id="viewsChart"></canvas></div></div>
      <div class="chart-card"><div class="chart-card-header"><h3>Top Pages</h3></div><div class="chart-container"><canvas id="pagesChart"></canvas></div></div>
      <div class="chart-card"><div class="chart-card-header"><h3>Devices</h3></div><div class="chart-container chart-doughnut"><canvas id="devicesChart"></canvas></div></div>
      <div class="chart-card"><div class="chart-card-header"><h3>Countries</h3></div><div class="chart-container"><canvas id="countriesChart"></canvas></div></div>
      <div class="chart-card"><div class="chart-card-header"><h3>Referrers</h3></div><div class="chart-container"><canvas id="referrersChart"></canvas></div></div>
      <div class="chart-card wide"><div class="chart-card-header"><h3>Browsers</h3></div><div class="chart-container"><canvas id="browsersChart"></canvas></div></div>
    </div>`;
    if(daily&&daily.length) renderLineChart('viewsChart',daily.map(d=>d.day),[{label:'Views',data:daily.map(d=>d.views),borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,.08)',fill:true,tension:.4,borderWidth:2,pointRadius:0,pointHoverRadius:5,pointHoverBackgroundColor:'#00d4ff'},{label:'Visitors',data:daily.map(d=>d.unique_visitors),borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,.08)',fill:true,tension:.4,borderWidth:2,pointRadius:0,pointHoverRadius:5,pointHoverBackgroundColor:'#00ff88'}]);
    if(pages&&pages.length) renderBarChart('pagesChart',pages.slice(0,8),'path','views','#00d4ff');
    if(devices&&devices.length) renderDoughnutChart('devicesChart',devices,'device_type','views');
    if(countries&&countries.length) renderBarChart('countriesChart',countries.slice(0,8),'country','views','#00ff88');
    if(referrers&&referrers.length) renderBarChart('referrersChart',referrers.slice(0,8),'domain','visits','#a855f7');
    if(browsers&&browsers.length) renderDoughnutChart('browsersChart',browsers,'browser','views');
  }

  function renderRealtimeSection(data) {
    const content=$('#content'), active=data?data.active_visitors||0:0, topPages=data?data.top_pages||[]:[];
    content.innerHTML=`<div class="realtime-hero"><div class="realtime-count" id="realtimeCount">${formatNumber(active)}</div><div class="realtime-label">visitors active right now</div></div>
    <div class="table-card"><div class="table-card-header"><h3>Active Pages</h3><span class="table-count">${topPages.length} pages</span></div>
    <div class="realtime-pages-list" id="realtimePagesList">${topPages.length?topPages.map(p=>`<div class="realtime-page-item"><span class="realtime-page-path">${esc(p.path)}</span><span class="realtime-page-views">${p.views} view${p.views!==1?'s':''}</span></div>`).join(''):'<div class="empty-state"><p>No active visitors</p></div>'}</div></div>`;
  }

  function renderPagesSection(pages) {
    const content=$('#content'), sorted=sortArray(pages||[],state.sortConfig);
    content.innerHTML=`<div class="section-header"><h2>Pages</h2></div>
    <div class="table-card"><div class="table-card-header"><h3>All Pages</h3><span class="table-count">${sorted.length} pages</span></div>
    <div class="table-wrapper"><table class="data-table" id="pagesTable"><thead><tr>
      <th data-sort="path" class="${state.sortConfig.key==='path'?'sorted':''}">Page <span class="sort-arrow">${state.sortConfig.key==='path'?(state.sortConfig.dir==='asc'?'\u25B2':'\u25BC'):'\u25BC'}</span></th>
      <th data-sort="views" class="${state.sortConfig.key==='views'?'sorted':''}">Views <span class="sort-arrow">${state.sortConfig.key==='views'?(state.sortConfig.dir==='asc'?'\u25B2':'\u25BC'):'\u25BC'}</span></th>
      <th data-sort="unique_visitors">Visitors</th><th data-sort="avg_time">Avg Time</th><th data-sort="bounce_rate">Bounce Rate</th><th>Trend</th>
    </tr></thead><tbody>${sorted.length?sorted.map(p=>{const mx=sorted[0]?sorted[0].views:1,bp=Math.max(5,(p.views/mx)*100);return`<tr><td class="page-cell">${esc(p.path)}</td><td>${formatNumber(p.views)}</td><td>${formatNumber(p.unique_visitors)}</td><td class="time-cell">${formatDuration(p.avg_time)}</td><td>${formatPercent(p.bounce_rate)}</td><td><div class="table-bar-bg"><div class="table-bar" style="width:${bp}%"></div></div></td></tr>`;}).join(''):'<tr><td colspan="6" class="table-empty">No page data</td></tr>'}</tbody></table></div></div>`;
    $$('#pagesTable th[data-sort]').forEach(th=>{th.addEventListener('click',()=>{const k=th.dataset.sort;state.sortConfig.key===k?state.sortConfig.dir=state.sortConfig.dir==='asc'?'desc':'asc':((state.sortConfig.key=k,state.sortConfig.dir='desc'));renderPagesSection(pages);});});
  }

  function renderReferrersSection(referrers) {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Referrers</h2></div>
    <div class="charts-grid"><div class="chart-card wide"><div class="chart-card-header"><h3>Top Referrers</h3></div><div class="chart-container chart-tall"><canvas id="referrerChartFull"></canvas></div></div></div>
    <div class="table-card" style="margin-top:16px"><div class="table-card-header"><h3>All Referrers</h3><span class="table-count">${(referrers||[]).length} referrers</span></div>
    <div class="table-wrapper"><table class="data-table"><thead><tr><th>Source</th><th>Domain</th><th>Visits</th></tr></thead><tbody>${(referrers||[]).map(r=>`<tr><td class="referrer-cell">${esc(r.url)}</td><td>${esc(r.domain)}</td><td>${formatNumber(r.visits)}</td></tr>`).join('')||'<tr><td colspan="3" class="table-empty">No referrer data</td></tr>'}</tbody></table></div></div>`;
    if(referrers&&referrers.length) renderBarChart('referrerChartFull',referrers.slice(0,15),'domain','visits','#a855f7');
  }

  function renderDevicesSection(devices,browsers) {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Devices & Browsers</h2></div>
    <div class="charts-grid"><div class="chart-card"><div class="chart-card-header"><h3>Device Types</h3></div><div class="chart-container chart-doughnut"><canvas id="deviceChartFull"></canvas></div></div><div class="chart-card"><div class="chart-card-header"><h3>Browsers</h3></div><div class="chart-container chart-doughnut"><canvas id="browserChartFull"></canvas></div></div></div>
    <div class="charts-grid" style="margin-top:16px"><div class="table-card"><div class="table-card-header"><h3>Devices</h3></div><div class="table-wrapper"><table class="data-table"><thead><tr><th>Device</th><th>Views</th></tr></thead><tbody>${(devices||[]).map(d=>`<tr><td>${esc(d.device_type)}</td><td>${formatNumber(d.views)}</td></tr>`).join('')||'<tr><td colspan="2" class="table-empty">No data</td></tr>'}</tbody></table></div></div><div class="table-card"><div class="table-card-header"><h3>Browsers</h3></div><div class="table-wrapper"><table class="data-table"><thead><tr><th>Browser</th><th>Views</th></tr></thead><tbody>${(browsers||[]).map(b=>`<tr><td>${esc(b.browser)}</td><td>${formatNumber(b.views)}</td></tr>`).join('')||'<tr><td colspan="2" class="table-empty">No data</td></tr>'}</tbody></table></div></div></div>`;
    if(devices&&devices.length) renderDoughnutChart('deviceChartFull',devices,'device_type','views');
    if(browsers&&browsers.length) renderDoughnutChart('browserChartFull',browsers,'browser','views');
  }

  function renderCountriesSection(countries) {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Countries</h2></div>
    <div class="charts-grid"><div class="chart-card wide"><div class="chart-card-header"><h3>Top Countries</h3></div><div class="chart-container chart-tall"><canvas id="countryChartFull"></canvas></div></div></div>
    <div class="table-card" style="margin-top:16px"><div class="table-card-header"><h3>All Countries</h3><span class="table-count">${(countries||[]).length} countries</span></div>
    <div class="table-wrapper"><table class="data-table"><thead><tr><th>Country</th><th>Views</th></tr></thead><tbody>${(countries||[]).map(c=>`<tr><td>${esc(c.country)}</td><td>${formatNumber(c.views)}</td></tr>`).join('')||'<tr><td colspan="2" class="table-empty">No country data</td></tr>'}</tbody></table></div></div>`;
    if(countries&&countries.length) renderBarChart('countryChartFull',countries.slice(0,20),'country','views','#00ff88');
  }

  function renderFunnelsSection(pages) {
    const content=$('#content'), steps=(pages||[]).slice(0,5), maxCount=steps.length?steps[0].views:1;
    content.innerHTML=`<div class="alerts-header"><h2>Funnels</h2><button class="btn btn-primary" id="createFunnelBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Funnel</button></div>
    <div class="chart-card"><div class="chart-card-header"><h3>Page Flow Funnel</h3><p style="font-size:.78rem;color:var(--text-dim)">Top pages as funnel steps</p></div>
    <div class="funnel-container">${steps.length?steps.map((s,i)=>{const pct=maxCount?(s.views/maxCount)*100:0;const drop=i>0&&steps[i-1].views?((1-s.views/steps[i-1].views)*100).toFixed(1):null;return`${drop!==null?`<div class="funnel-dropoff">-${drop}% drop-off</div>`:''}<div class="funnel-step"><div class="funnel-bar-wrapper"><div class="funnel-bar" style="--progress:${pct}%;width:${Math.max(20,pct)}%"><span class="funnel-bar-label">${esc(s.path)}</span></div></div><div class="funnel-stats"><div class="funnel-count">${formatNumber(s.views)}</div><div class="funnel-pct">${pct.toFixed(1)}% of total</div></div></div>`;}).join(''):'<div class="empty-state"><p>No funnel data available</p></div>'}</div></div>`;
    $('#createFunnelBtn')?.addEventListener('click',()=>$('#funnelModal').classList.add('show'));
  }

  function renderGoalsSection() {
    const content=$('#content');
    const defaults=[{name:'Pageviews Target',value:12500,target:15000,status:'active',color:'cyan'},{name:'Daily Active Users',value:342,target:500,status:'active',color:'green'},{name:'Bounce Rate Goal',value:28,target:35,status:'active',color:'purple',invert:true},{name:'Session Duration',value:185,target:240,status:'active',color:'cyan'}];
    const all=[...defaults,...state.goals];
    content.innerHTML=`<div class="alerts-header"><h2>Goals</h2><button class="btn btn-primary" id="createGoalBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Goal</button></div>
    <div class="goals-grid">${all.map(g=>{const rate=g.invert?Math.min(100,((g.target-g.value)/g.target)*100):Math.min(100,(g.value/g.target)*100);const dv=g.name.includes('Duration')?formatDuration(g.value):formatNumber(g.value);const dt=g.name.includes('Duration')?formatDuration(g.target):formatNumber(g.target);return`<div class="goal-card"><div class="goal-card-header"><div class="goal-card-title">${esc(g.name)}</div><div class="goal-card-status ${g.status}">${g.status}</div></div><div class="goal-card-value">${dv}</div><div class="goal-card-target">Target: ${dt}</div><div class="goal-progress-bar"><div class="goal-progress-fill ${g.color}" style="width:${rate}%"></div></div><div class="goal-card-rate"><strong>${rate.toFixed(1)}%</strong> completion</div></div>`;}).join('')}</div>`;
    $('#createGoalBtn')?.addEventListener('click',()=>$('#goalModal').classList.add('show'));
  }

  function renderAlertsSection() {
    const content=$('#content');
    content.innerHTML=`<div class="alerts-header"><h2>Alerts</h2><button class="btn btn-primary" id="createAlertBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Alert</button></div>
    <div id="alertsList">${state.alerts.length?state.alerts.map((a,i)=>`<div class="alert-item"><div class="alert-icon ok"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div><div class="alert-info"><div class="alert-name">${esc(a.name)}</div><div class="alert-detail">${esc(a.metric)} ${a.condition==='gt'?'>':a.condition==='lt'?'<':'='} ${a.threshold}</div></div><button class="btn btn-danger btn-sm" data-alert-delete="${i}">Delete</button></div>`).join(''):'<div class="empty-state"><div class="empty-state-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div><h3>No alerts yet</h3><p>Create an alert to get notified when metrics cross thresholds.</p></div>'}</div>`;
    $('#createAlertBtn')?.addEventListener('click',()=>$('#alertModal').classList.add('show'));
    $$('[data-alert-delete]').forEach(btn=>{btn.addEventListener('click',()=>{const i=parseInt(btn.dataset.alertDelete);state.alerts.splice(i,1);localStorage.setItem('ghostly_alerts',JSON.stringify(state.alerts));renderAlertsSection();toast('Alert deleted','info');});});
  }

  function renderSettingsSection() {
    const content=$('#content'), host=window.location.origin;
    const snippet=`<script src="${host}/static/tracking.js" data-domain="yourdomain.com"><\/script>`;
    const apiKey=state.users[0]?.apiKey || 'ghl_' + generateId() + generateId();
    content.innerHTML=`<div class="section-header"><h2>Settings</h2></div>
    <div class="settings-section"><h3>Tracking Code</h3><p>Add this snippet to the <code>&lt;head&gt;</code> of your website to start tracking.</p><div class="code-block"><button class="copy-btn" id="copyTrackingCode">Copy</button>${esc(snippet)}</div></div>
    <div class="settings-section"><h3>API Keys</h3><p>Use these keys to access the Ghostly API programmatically.</p><div class="api-key-row"><span class="api-key-label">Read Key</span><div class="api-key-value" id="apiKeyValue">${apiKey}</div><button class="btn btn-secondary btn-sm" id="copyApiKey">Copy</button></div></div>
    <div class="settings-section"><h3>Data Retention</h3><p>Configure how long analytics data is stored.</p><div class="form-group"><label>Retention Period</label><select class="form-input" style="max-width:200px"><option value="90">90 days</option><option value="180">180 days</option><option value="365" selected>1 year</option><option value="730">2 years</option></select></div></div>
    <div class="settings-section"><h3>Danger Zone</h3><p>Irreversible actions for your account.</p><button class="btn btn-danger btn-sm" id="deleteAllData">Delete All Data</button></div>`;
    $('#copyTrackingCode')?.addEventListener('click',()=>{navigator.clipboard.writeText(snippet);toast('Tracking code copied!','success');});
    $('#copyApiKey')?.addEventListener('click',()=>{navigator.clipboard.writeText(apiKey);toast('API key copied!','success');});
    $('#deleteAllData')?.addEventListener('click',()=>{if(confirm('Are you sure? This cannot be undone.'))toast('Data deletion requested','info');});
  }

  function renderAdminSection() {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Admin Panel</h2></div>
    <div class="settings-section"><h3>User Management</h3><p>Manage user accounts, roles, and permissions.</p>
    <div style="overflow-x:auto"><table class="admin-table"><thead><tr><th>User</th><th>Email</th><th>Role</th><th>Last Login</th><th>Actions</th></tr></thead><tbody>
    ${state.users.map(u=>`<tr><td style="font-weight:600;color:var(--text)">${esc(u.name)}</td><td>${esc(u.email)}</td><td><span class="admin-role-badge ${u.role}">${u.role}</span></td><td>${timeAgo(u.lastLogin)}</td>
    <td><div style="display:flex;gap:6px"><button class="btn btn-secondary btn-sm" data-user-edit="${u.id}">Edit</button><button class="btn btn-danger btn-sm" data-user-delete="${u.id}">Delete</button></div></td></tr>`).join('')}
    </tbody></table></div></div>
    <div class="settings-section"><h3>Audit Log</h3><p>Recent administrative actions and system events.</p>
    <div>${state.auditLog.map(l=>`<div class="audit-log-item"><div class="audit-log-icon ${l.type}">${l.type==='create'?'+':l.type==='delete'?'-':l.type==='update'?'~':'\u25B6'}</div><div class="audit-log-content"><div class="audit-log-action">${esc(l.action)}</div><div class="audit-log-detail">${esc(l.detail)}</div></div><div class="audit-log-time">${esc(l.time)}</div></div>`).join('')}</div></div>`;
    $$('#userDelete').forEach(btn=>{btn.addEventListener('click',()=>{const id=parseInt(btn.dataset.userDelete);if(id===state.auth?.userId){toast('Cannot delete your own account','error');return;}state.users=state.users.filter(u=>u.id!==id);localStorage.setItem('ghostly_users',JSON.stringify(state.users));renderAdminSection();toast('User deleted','info');});});
  }

  function renderProfileSection() {
    const content=$('#content'), user=getCurrentUser();
    if(!user){content.innerHTML='<div class="empty-state"><p>Please sign in to view your profile.</p></div>';return;}
    content.innerHTML=`<div class="section-header"><h2>Profile</h2></div>
    <div class="settings-section"><div class="profile-avatar-section"><div class="profile-avatar-large">${(user.name||'U')[0].toUpperCase()}</div><div class="profile-info"><h2>${esc(user.name)}</h2><p>${esc(user.email)}</p><p style="font-size:.78rem;color:var(--text-dim);margin-top:4px">Role: <span class="admin-role-badge ${user.role}">${user.role}</span> | Member since ${user.created}</p></div></div></div>
    <div class="settings-section"><h3>Change Password</h3><p>Update your account password.</p>
    <div class="form-group" style="margin-bottom:14px"><label for="currentPassword">Current Password</label><input type="password" id="currentPassword" class="form-input" placeholder="Enter current password" autocomplete="current-password"></div>
    <div class="form-group" style="margin-bottom:14px"><label for="newPassword">New Password</label><input type="password" id="newPassword" class="form-input" placeholder="Min 8 characters" autocomplete="new-password"></div>
    <div class="form-group" style="margin-bottom:14px"><label for="confirmNewPassword">Confirm New Password</label><input type="password" id="confirmNewPassword" class="form-input" placeholder="Repeat new password" autocomplete="new-password"></div>
    <button class="btn btn-primary btn-sm" id="changePasswordBtn">Update Password</button></div>
    <div class="settings-section"><h3>API Keys</h3><p>Manage your API keys for programmatic access.</p>
    <div class="profile-api-keys-list"><div class="profile-api-key-item"><span class="profile-api-key-name">Read Key</span><span class="profile-api-key-value">${user.apiKey||'Not generated'}</span><button class="btn btn-secondary btn-sm" id="copyProfileApiKey">Copy</button></div>
    <div class="profile-api-key-item"><span class="profile-api-key-name">Write Key</span><span class="profile-api-key-value">ghl_write_${generateId()}</span><button class="btn btn-secondary btn-sm">Copy</button></div></div>
    <button class="btn btn-secondary btn-sm" style="margin-top:14px" id="regenerateApiKey">Regenerate Read Key</button></div>`;
    $('#changePasswordBtn')?.addEventListener('click',()=>{const cur=$('#currentPassword').value,np=$('#newPassword').value,cf=$('#confirmNewPassword').value;if(!cur||!np){toast('Please fill in all fields','error');return;}if(cur!==user.password){toast('Current password is incorrect','error');return;}if(np.length<8){toast('Password must be at least 8 characters','error');return;}if(np!==cf){toast('Passwords do not match','error');return;}user.password=np;localStorage.setItem('ghostly_users',JSON.stringify(state.users));toast('Password updated!','success');$('#currentPassword').value='';$('#newPassword').value='';$('#confirmNewPassword').value='';});
    $('#copyProfileApiKey')?.addEventListener('click',()=>{navigator.clipboard.writeText(user.apiKey||'');toast('API key copied!','success');});
    $('#regenerateApiKey')?.addEventListener('click',()=>{user.apiKey='ghl_'+generateId()+generateId();localStorage.setItem('ghostly_users',JSON.stringify(state.users));renderProfileSection();toast('API key regenerated!','success');});
  }

  /* ═══════ HEATMAP ═══════ */
  function renderHeatmapSection() {
    const content=$('#content'),totalClicks=state.heatmapClicks.length,uniquePages=[...new Set(state.heatmapClicks.map(c=>c.page))].length;
    const avgX=totalClicks?Math.round(state.heatmapClicks.reduce((s,c)=>s+c.x,0)/totalClicks):0,avgY=totalClicks?Math.round(state.heatmapClicks.reduce((s,c)=>s+c.y,0)/totalClicks):0;
    content.innerHTML=`<div class="section-header"><h2>Heatmap</h2></div>
    <div class="heatmap-stats" style="margin-bottom:18px"><div class="heatmap-stat"><div class="heatmap-stat-value">${formatNumber(totalClicks)}</div><div class="heatmap-stat-label">Total Clicks</div></div><div class="heatmap-stat"><div class="heatmap-stat-value">${uniquePages}</div><div class="heatmap-stat-label">Pages Tracked</div></div><div class="heatmap-stat"><div class="heatmap-stat-value">${avgX}, ${avgY}</div><div class="heatmap-stat-label">Avg Click Position</div></div></div>
    <div class="heatmap-wrapper"><div class="heatmap-toolbar"><div class="heatmap-toolbar-left"><button class="heatmap-filter-btn active" data-filter="clicks">Clicks</button><button class="heatmap-filter-btn" data-filter="moves">Mouse Moves</button><button class="heatmap-filter-btn" data-filter="scroll">Scroll Depth</button></div><div class="heatmap-toolbar-right"><button class="btn btn-secondary btn-sm" id="heatmapClearBtn">Clear Data</button><button class="btn btn-primary btn-sm" id="heatmapSimulateBtn">Simulate Clicks</button></div></div>
    <div class="heatmap-canvas-container" id="heatmapContainer"><div class="heatmap-overlay" id="heatmapOverlay"></div><canvas id="heatmapCanvas"></canvas></div>
    <div class="heatmap-legend"><span>Less</span><div class="heatmap-legend-gradient"></div><span>More</span></div></div>`;
    initHeatmapCanvas();setupHeatmapEvents();
  }
  function initHeatmapCanvas(){const c=$('#heatmapContainer'),cv=$('#heatmapCanvas');if(!c||!cv)return;const r=c.getBoundingClientRect();cv.width=r.width;cv.height=Math.max(r.height,400);state.heatmapCanvas=cv;drawHeatmap();}
  function drawHeatmap(){const cv=state.heatmapCanvas;if(!cv)return;const ctx=cv.getContext('2d'),w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);ctx.fillStyle='rgba(6,6,10,1)';ctx.fillRect(0,0,w,h);const gw=40,gh=40,cols=Math.ceil(w/gw),rows=Math.ceil(h/gh);const grid=Array.from({length:rows},()=>Array(cols).fill(0));state.heatmapClicks.forEach(cl=>{const c=Math.floor((cl.x/100)*w/gw),r=Math.floor((cl.y/100)*h/gh);if(c>=0&&c<cols&&r>=0&&r<rows){grid[r][c]++;for(let dr=-1;dr<=1;dr++)for(let dc=-1;dc<=1;dc++){const nr=r+dr,nc=c+dc;if(nr>=0&&nr<rows&&nc>=0&&nc<cols&&(dr!==0||dc!==0))grid[nr][nc]+=.3;}}});let mx=0;grid.forEach(row=>row.forEach(v=>{if(v>mx)mx=v;}));if(mx>0)for(let r=0;r<rows;r++)for(let c=0;c<cols;c++){const v=grid[r][c];if(v<=0)continue;const int=v/mx,rad=gw*.8*(.4+int*.6);const g=ctx.createRadialGradient(c*gw+gw/2,r*gh+gh/2,0,c*gw+gw/2,r*gh+gh/2,rad);if(int<.25){g.addColorStop(0,'rgba(0,212,255,.6)');g.addColorStop(1,'rgba(0,212,255,0)');}else if(int<.5){g.addColorStop(0,'rgba(0,255,136,.7)');g.addColorStop(1,'rgba(0,255,136,0)');}else if(int<.75){g.addColorStop(0,'rgba(255,187,51,.75)');g.addColorStop(1,'rgba(255,187,51,0)');}else{g.addColorStop(0,'rgba(255,68,102,.8)');g.addColorStop(1,'rgba(255,68,102,0)');}ctx.fillStyle=g;ctx.fillRect(c*gw,r*gh,gw,gh);}state.heatmapClicks.forEach(cl=>{const x=(cl.x/100)*w,y=(cl.y/100)*h;ctx.beginPath();ctx.arc(x,y,4,0,Math.PI*2);ctx.fillStyle='rgba(255,255,255,.9)';ctx.fill();ctx.beginPath();ctx.arc(x,y,6,0,Math.PI*2);ctx.strokeStyle='rgba(255,255,255,.3)';ctx.lineWidth=1;ctx.stroke();});}
  function setupHeatmapEvents(){const c=$('#heatmapContainer');if(!c)return;c.addEventListener('click',e=>{const r=c.getBoundingClientRect(),x=((e.clientX-r.left)/r.width)*100,y=((e.clientY-r.top)/r.height)*100;state.heatmapClicks.push({x,y,page:window.location.hash||'dashboard',time:Date.now()});localStorage.setItem('ghostly_heatmap_clicks',JSON.stringify(state.heatmapClicks));drawHeatmap();});$$('.heatmap-filter-btn').forEach(btn=>{btn.addEventListener('click',()=>{$$('.heatmap-filter-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');toast(`Showing ${btn.dataset.filter} data`,'info');});});$('#heatmapClearBtn')?.addEventListener('click',()=>{state.heatmapClicks=[];localStorage.setItem('ghostly_heatmap_clicks','[]');drawHeatmap();toast('Heatmap data cleared','info');});$('#heatmapSimulateBtn')?.addEventListener('click',()=>{for(let i=0;i<50;i++){state.heatmapClicks.push({x:10+Math.random()*80,y:10+Math.random()*80,page:'simulated',time:Date.now()});}localStorage.setItem('ghostly_heatmap_clicks',JSON.stringify(state.heatmapClicks));drawHeatmap();toast('Generated 50 simulated clicks','success');});window.addEventListener('resize',()=>{if(state.currentSection==='heatmap')initHeatmapCanvas();});}

  /* ═══════ EMAIL REPORTS ═══════ */
  function renderEmailReportsSection() {
    const content=$('#content'),cfg=state.emailConfig;
    content.innerHTML=`<div class="section-header"><h2>Email Reports</h2></div>
    <div class="email-config-grid"><div class="email-config-card"><h3>SMTP Configuration</h3><p>Configure your email server to send automated reports.</p>
    <div class="form-group" style="margin-bottom:14px"><label for="smtpHost">SMTP Host</label><input type="text" id="smtpHost" class="form-input" placeholder="smtp.gmail.com" value="${esc(cfg.smtpHost)}"></div>
    <div class="form-row" style="margin-bottom:14px"><div class="form-group"><label for="smtpPort">Port</label><input type="text" id="smtpPort" class="form-input" placeholder="587" value="${esc(cfg.smtpPort)}"></div><div class="form-group"><label for="smtpEncryption">Encryption</label><select id="smtpEncryption" class="form-input"><option value="tls">TLS</option><option value="ssl">SSL</option><option value="none">None</option></select></div></div>
    <div class="form-group" style="margin-bottom:14px"><label for="smtpUser">Username</label><input type="text" id="smtpUser" class="form-input" placeholder="you@gmail.com" value="${esc(cfg.smtpUser)}"></div>
    <div class="form-group" style="margin-bottom:14px"><label for="smtpPass">Password</label><input type="password" id="smtpPass" class="form-input" placeholder="App password" value="${esc(cfg.smtpPass)}"></div>
    <div class="form-row" style="margin-bottom:18px"><div class="form-group"><label for="fromEmail">From Email</label><input type="email" id="fromEmail" class="form-input" placeholder="reports@ghostly.io" value="${esc(cfg.fromEmail)}"></div><div class="form-group"><label for="fromName">From Name</label><input type="text" id="fromName" class="form-input" placeholder="Ghostly Reports" value="${esc(cfg.fromName)}"></div></div>
    <div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn btn-primary btn-sm" id="saveEmailConfig">Save Configuration</button><button class="btn btn-secondary btn-sm" id="testEmailBtn">Send Test Email</button></div></div>
    <div class="email-config-card"><h3>Scheduled Reports</h3><p>Set up automatic email reports on a schedule.</p>
    <div class="email-schedule-list"><div class="email-schedule-item"><div class="email-schedule-info"><div class="email-schedule-name">Daily Summary</div><div class="email-schedule-detail">Pageviews, visitors, top pages - every morning at 8am</div></div><div class="email-toggle active" data-schedule="daily"></div></div>
    <div class="email-schedule-item"><div class="email-schedule-info"><div class="email-schedule-name">Weekly Digest</div><div class="email-schedule-detail">Full analytics report - every Monday at 9am</div></div><div class="email-toggle active" data-schedule="weekly"></div></div>
    <div class="email-schedule-item"><div class="email-schedule-info"><div class="email-schedule-name">Monthly Report</div><div class="email-schedule-detail">Comprehensive monthly analytics - 1st of each month</div></div><div class="email-toggle" data-schedule="monthly"></div></div>
    <div class="email-schedule-item"><div class="email-schedule-info"><div class="email-schedule-name">Alert Notifications</div><div class="email-schedule-detail">Instant email when alert thresholds are crossed</div></div><div class="email-toggle active" data-schedule="alerts"></div></div></div>
    <div class="form-group" style="margin-top:18px"><label for="reportRecipients">Recipients (comma-separated)</label><input type="text" id="reportRecipients" class="form-input" placeholder="team@example.com, ceo@example.com" value=""></div>
    <button class="btn btn-primary btn-sm" style="margin-top:14px" id="saveRecipients">Save Recipients</button></div></div>`;
    setupEmailEvents();
  }
  function setupEmailEvents(){$('#saveEmailConfig')?.addEventListener('click',()=>{state.emailConfig={smtpHost:$('#smtpHost').value.trim(),smtpPort:$('#smtpPort').value.trim(),smtpUser:$('#smtpUser').value.trim(),smtpPass:$('#smtpPass').value.trim(),fromEmail:$('#fromEmail').value.trim(),fromName:$('#fromName').value.trim()};localStorage.setItem('ghostly_email_config',JSON.stringify(state.emailConfig));toast('Email configuration saved!','success');});$('#testEmailBtn')?.addEventListener('click',()=>{toast('Test email sent! Check your inbox.','success');});$$('.email-toggle').forEach(t=>{t.addEventListener('click',()=>{t.classList.toggle('active');toast(`${t.dataset.schedule} report ${t.classList.contains('active')?'enabled':'disabled'}`,'info');});});$('#saveRecipients')?.addEventListener('click',()=>{const r=$('#reportRecipients').value.trim();if(r){localStorage.setItem('ghostly_email_recipients',r);toast('Recipients saved!','success');}else toast('Please enter at least one recipient','error');});const sr=localStorage.getItem('ghostly_email_recipients')||'';if($('#reportRecipients'))$('#reportRecipients').value=sr;}

  /* ═══════ WEBHOOKS ═══════ */
  function renderWebhooksSection() {
    const content=$('#content');
    content.innerHTML=`<div class="alerts-header"><h2>Webhooks</h2><button class="btn btn-primary" id="addWebhookBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Add Webhook</button></div>
    <div class="table-card"><div class="table-card-header"><h3>Configured Webhooks</h3><span class="table-count">${state.webhooks.length} webhooks</span></div>
    <div class="table-wrapper"><table class="webhook-table"><thead><tr><th>Name</th><th>URL</th><th>Event</th><th>Status</th><th>Actions</th></tr></thead><tbody>
    ${state.webhooks.length?state.webhooks.map((wh,i)=>`<tr><td style="font-weight:600;color:var(--text)">${esc(wh.name)}</td><td><span class="webhook-url">${esc(wh.url)}</span></td><td><span class="webhook-event-badge">${esc(wh.event)}</span></td><td><span class="webhook-status ${wh.active?'active':'inactive'}"><span class="webhook-status-dot"></span>${wh.active?'Active':'Inactive'}</span></td><td><div class="webhook-actions"><button class="btn btn-secondary btn-sm webhook-test-btn" data-wh-test="${i}">Test</button><button class="btn btn-secondary btn-sm webhook-toggle-btn" data-wh-toggle="${i}">${wh.active?'Disable':'Enable'}</button><button class="btn btn-danger btn-sm webhook-delete-btn" data-wh-delete="${i}">Delete</button></div></td></tr>`).join(''):`<tr><td colspan="5" class="table-empty"><div class="empty-state" style="padding:32px"><div class="empty-state-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg></div><h3>No webhooks configured</h3><p>Add a webhook to receive real-time notifications.</p></div></td></tr>`}
    </tbody></table></div></div>`;
    setupWebhookEvents();
  }
  function setupWebhookEvents(){$('#addWebhookBtn')?.addEventListener('click',()=>{$('#webhookModalTitle').textContent='Add Webhook';$('#webhookName').value='';$('#webhookUrl').value='';$('#webhookEvent').value='pageview';$('#webhookSecret').value='';$('#webhookModal').classList.add('show');});$('#closeWebhookModal')?.addEventListener('click',()=>$('webhookModal')?.classList.remove('show'));$('#cancelWebhookModal')?.addEventListener('click',()=>$('webhookModal')?.classList.remove('show'));$('#webhookModal')?.addEventListener('click',e=>{if(e.target===e.currentTarget)e.target.classList.remove('show');});$('#confirmWebhook')?.addEventListener('click',()=>{const n=$('#webhookName').value.trim(),u=$('#webhookUrl').value.trim(),ev=$('#webhookEvent').value,s=$('#webhookSecret').value.trim();if(!n||!u){toast('Please fill in name and URL','error');return;}state.webhooks.push({id:generateId(),name:n,url:u,event:ev,secret:s,active:true,created:new Date().toISOString()});localStorage.setItem('ghostly_webhooks',JSON.stringify(state.webhooks));$('#webhookModal').classList.remove('show');toast('Webhook added!','success');renderWebhooksSection();});$$('.webhook-test-btn').forEach(btn=>{btn.addEventListener('click',()=>{const i=parseInt(btn.dataset.whTest);toast(`Testing webhook "${state.webhooks[i].name}"...`,'info');setTimeout(()=>toast('Webhook test successful!','success'),1500);});});$$('.webhook-toggle-btn').forEach(btn=>{btn.addEventListener('click',()=>{const i=parseInt(btn.dataset.whToggle);state.webhooks[i].active=!state.webhooks[i].active;localStorage.setItem('ghostly_webhooks',JSON.stringify(state.webhooks));renderWebhooksSection();toast(`Webhook ${state.webhooks[i].active?'enabled':'disabled'}`,'info');});});$$('.webhook-delete-btn').forEach(btn=>{btn.addEventListener('click',()=>{const i=parseInt(btn.dataset.whDelete);if(confirm(`Delete webhook "${state.webhooks[i].name}"?`)){state.webhooks.splice(i,1);localStorage.setItem('ghostly_webhooks',JSON.stringify(state.webhooks));renderWebhooksSection();toast('Webhook deleted','info');}});});}

  /* ═══════ THEMES ═══════ */
  function renderThemesSection() {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Themes</h2></div><div class="themes-grid">${THEMES.map(t=>`<div class="theme-card ${t.id===state.activeTheme?'active':''}" data-theme-id="${t.id}"><div class="theme-preview"><div class="theme-preview-sidebar" style="background:${t.preview.sidebar}"></div><div class="theme-preview-topbar" style="background:${t.preview.topbar}"></div><div class="theme-preview-content"><div class="theme-preview-stat" style="width:40%;background:${t.preview.accent}"></div><div class="theme-preview-stat" style="width:70%;background:${t.preview.accent};opacity:.3"></div><div class="theme-preview-chart" style="background:${t.preview.accent}"></div></div></div><div class="theme-card-info"><span class="theme-card-name">${t.name}</span>${t.id===state.activeTheme?'<span class="theme-card-active-badge">Active</span>':''}</div></div>`).join('')}</div>`;
    $$('.theme-card').forEach(card=>{card.addEventListener('click',()=>{const id=card.dataset.themeId;applyTheme(id);state.activeTheme=id;localStorage.setItem('ghostly_theme',id);renderThemesSection();toast('Theme applied!','success');});});
  }
  function applyTheme(id){const t=THEMES.find(x=>x.id===id);if(!t)return;Object.entries(t.vars).forEach(([k,v])=>document.documentElement.style.setProperty(k,v));}

  /* ═══════ PLUGINS ═══════ */
  function renderPluginsSection() {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Plugins</h2></div><div class="plugins-grid">${state.plugins.map((p,i)=>`<div class="plugin-card"><div class="plugin-card-header"><div class="plugin-icon" style="background:${p.iconBg}">${p.icon}</div><div class="plugin-card-meta"><div class="plugin-card-name">${esc(p.name)}</div><div class="plugin-card-version">v${esc(p.version)}</div></div></div><div class="plugin-card-desc">${esc(p.description)}</div><div class="plugin-card-footer"><span class="plugin-author">by ${esc(p.author)}</span><div class="plugin-toggle ${p.enabled?'active':''}" data-plugin-idx="${i}"></div></div></div>`).join('')}</div>`;
    $$('.plugin-toggle').forEach(t=>{t.addEventListener('click',()=>{const i=parseInt(t.dataset.pluginIdx);state.plugins[i].enabled=!state.plugins[i].enabled;localStorage.setItem('ghostly_plugins',JSON.stringify(state.plugins));t.classList.toggle('active');toast(`${state.plugins[i].name} ${state.plugins[i].enabled?'enabled':'disabled'}`,'info');});});
  }

  /* ═══════ BACKUP ═══════ */
  function renderBackupSection() {
    const content=$('#content');
    content.innerHTML=`<div class="section-header"><h2>Backup & Restore</h2></div>
    <div class="backup-section-grid"><div class="backup-card"><h3>Create Backup</h3><p>Export all analytics data, settings, and configurations.</p>
    <div class="backup-progress-container" id="backupProgressContainer" style="display:none"><div class="backup-progress-bar"><div class="backup-progress-fill" id="backupProgressFill"></div></div><div class="backup-progress-text"><span id="backupProgressLabel">Preparing backup...</span><span id="backupProgressPct">0%</span></div></div>
    <div class="backup-actions"><button class="btn btn-primary btn-sm" id="createBackupBtn">Create Backup Now</button><button class="btn btn-secondary btn-sm" id="downloadBackupBtn">Download Latest</button></div></div>
    <div class="backup-card"><h3>Restore from Backup</h3><p>Import data from a previously exported backup file.</p>
    <div class="form-group" style="margin-bottom:14px"><label for="restoreFile">Upload Backup File</label><input type="file" id="restoreFile" class="form-input" accept=".json,.ghostly" style="padding:8px"></div>
    <div class="backup-actions"><button class="btn btn-success btn-sm" id="restoreBackupBtn">Restore Backup</button></div></div></div>
    <div class="backup-card" style="margin-top:18px"><h3>Backup History</h3><p>Previous backup snapshots.</p>
    <div class="backup-history-list">${state.backupHistory.length?state.backupHistory.map((b,i)=>`<div class="backup-history-item"><div class="backup-history-info"><div class="backup-history-name">${esc(b.name)}</div><div class="backup-history-detail">${b.date} - ${b.type}</div></div><div style="display:flex;align-items:center;gap:12px"><span class="backup-history-size">${b.size}</span><button class="btn btn-secondary btn-sm" data-restore-idx="${i}">Restore</button></div></div>`).join(''):'<div class="empty-state" style="padding:32px"><p>No backups yet. Create your first backup above.</p></div>'}</div></div>`;
    setupBackupEvents();
  }
  function setupBackupEvents(){$('#createBackupBtn')?.addEventListener('click',()=>{const pc=$('#backupProgressContainer'),pf=$('#backupProgressFill'),pl=$('#backupProgressLabel'),pp=$('#backupProgressPct');pc.style.display='block';let p=0;const iv=setInterval(()=>{p+=Math.random()*15+5;if(p>=100){p=100;clearInterval(iv);const n=new Date(),ds=n.toLocaleDateString()+' '+n.toLocaleTimeString();state.backupHistory.unshift({name:`Backup ${n.toLocaleDateString()}`,date:ds,type:'Full',size:(Math.random()*5+1).toFixed(1)+' MB'});localStorage.setItem('ghostly_backups',JSON.stringify(state.backupHistory));pl.textContent='Backup complete!';toast('Backup created successfully!','success');setTimeout(()=>{pc.style.display='none';pf.style.width='0';renderBackupSection();},1500);}else pl.textContent=p<30?'Collecting data...':p<60?'Compressing...':p<90?'Finalizing...':'Almost done...';pf.style.width=p+'%';pp.textContent=Math.round(p)+'%';},200);});$('#downloadBackupBtn')?.addEventListener('click',()=>{const d={version:'2.0',created:new Date().toISOString(),alerts:state.alerts,funnels:state.funnels,goals:state.goals,webhooks:state.webhooks,plugins:state.plugins,emailConfig:state.emailConfig,theme:state.activeTheme};const b=new Blob([JSON.stringify(d,null,2)],{type:'application/json'}),u=URL.createObjectURL(b),a=document.createElement('a');a.href=u;a.download=`ghostly-backup-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(u);toast('Backup downloaded!','success');});$('#restoreBackupBtn')?.addEventListener('click',()=>{const fi=$('#restoreFile');if(!fi.files.length){toast('Please select a backup file','error');return;}const r=new FileReader();r.onload=e=>{try{const d=JSON.parse(e.target.result);if(d.alerts){state.alerts=d.alerts;localStorage.setItem('ghostly_alerts',JSON.stringify(d.alerts));}if(d.funnels){state.funnels=d.funnels;localStorage.setItem('ghostly_funnels',JSON.stringify(d.funnels));}if(d.goals){state.goals=d.goals;localStorage.setItem('ghostly_goals',JSON.stringify(d.goals));}if(d.webhooks){state.webhooks=d.webhooks;localStorage.setItem('ghostly_webhooks',JSON.stringify(d.webhooks));}if(d.plugins){state.plugins=d.plugins;localStorage.setItem('ghostly_plugins',JSON.stringify(d.plugins));}if(d.emailConfig){state.emailConfig=d.emailConfig;localStorage.setItem('ghostly_email_config',JSON.stringify(d.emailConfig));}if(d.theme){state.activeTheme=d.theme;localStorage.setItem('ghostly_theme',d.theme);applyTheme(d.theme);}toast('Backup restored successfully!','success');renderBackupSection();}catch(err){toast('Invalid backup file','error');}};r.readAsText(fi.files[0]);});$$('[data-restore-idx]').forEach(btn=>{btn.addEventListener('click',()=>{const i=parseInt(btn.dataset.restoreIdx);toast(`Restoring backup from ${state.backupHistory[i].name}...`,'info');});});}

  /* ═══════ SORT HELPER ═══════ */
  function sortArray(arr,config){if(!config.key)return arr;return[...arr].sort((a,b)=>{const va=a[config.key]||0,vb=b[config.key]||0;if(typeof va==='string')return config.dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);return config.dir==='asc'?va-vb:vb-va;});}

  /* ═══════ DATA LOADING ═══════ */
  async function loadSites() {
    const data=await api('/api/sites'),list=$('#sitesList');
    if(!data||!data.sites)return;
    list.innerHTML=`<li class="site-item active" data-site-id="all" role="option" aria-selected="true" tabindex="0"><span class="site-dot" style="background:#00d4ff"></span>All Sites</li>`+data.sites.map((s,i)=>`<li class="site-item" data-site-id="${s.id}" role="option" tabindex="0"><span class="site-dot" style="background:${PALETTE[i%PALETTE.length]}"></span>${esc(s.name||s.domain)}</li>`).join('');
    list.querySelectorAll('.site-item').forEach(item=>{item.addEventListener('click',()=>{list.querySelectorAll('.site-item').forEach(el=>el.classList.remove('active'));item.classList.add('active');const id=item.dataset.siteId;state.siteId=id==='all'?null:parseInt(id);navigateTo(state.currentSection);});});
  }

  async function loadDashboardData() {
    const days=getDays();
    if(!state.siteId){const data=await api('/api/sites');if(!data||!data.sites||!data.sites.length){renderDashboard(null,null,null,null,null,null,null);return;}const ids=data.sites.map(s=>s.id);const results=await Promise.all(ids.map(id=>Promise.all([api(`/api/sites/${id}/stats?days=${days}`),api(`/api/sites/${id}/daily?days=${days}`),api(`/api/sites/${id}/pages?days=${days}`),api(`/api/sites/${id}/devices?days=${days}`),api(`/api/sites/${id}/browsers?days=${days}`),api(`/api/sites/${id}/countries?days=${days}`),api(`/api/sites/${id}/referrers?days=${days}`)])));renderDashboard(mergeStats(results.map(r=>r[0])),mergeDaily(results.map(r=>r[1])),mergeItems(results.map(r=>r[2]),'pages','path','views'),mergeItems(results.map(r=>r[3]),'devices','device_type','views'),mergeItems(results.map(r=>r[4]),'browsers','browser','views'),mergeItems(results.map(r=>r[5]),'countries','country','views'),mergeItems(results.map(r=>r[6]),'referrers','domain','visits'));return;}
    const base=`/api/sites/${state.siteId}`;const[stats,daily,pages,devices,browsers,countries,referrers]=await Promise.all([api(`${base}/stats?days=${days}`),api(`${base}/daily?days=${days}`),api(`${base}/pages?days=${days}`),api(`${base}/devices?days=${days}`),api(`${base}/browsers?days=${days}`),api(`${base}/countries?days=${days}`),api(`${base}/referrers?days=${days}`)]);renderDashboard(stats,daily?.daily,pages?.pages,devices?.devices,browsers?.browsers,countries?.countries,referrers?.referrers);
  }

  async function loadSectionData(section) {
    const days=getDays(),base=state.siteId?`/api/sites/${state.siteId}`:null;
    switch(section){
      case 'dashboard':await loadDashboardData();break;
      case 'realtime':{if(base){const d=await api(`${base}/realtime`);renderRealtimeSection(d);}else{const sd=await api('/api/sites');if(sd?.sites?.length){const r=await Promise.all(sd.sites.map(s=>api(`/api/sites/${s.id}/realtime`)));renderRealtimeSection({active_visitors:r.reduce((s,x)=>s+(x?.active_visitors||0),0),top_pages:r.flatMap(x=>x?.top_pages||[]).slice(0,10)});}else renderRealtimeSection(null);}break;}
      case 'heatmap':renderHeatmapSection();break;
      case 'pages':{if(base){const d=await api(`${base}/pages?days=${days}`);renderPagesSection(d?.pages);}else{const sd=await api('/api/sites');if(sd?.sites?.length){const r=await Promise.all(sd.sites.map(s=>api(`/api/sites/${s.id}/pages?days=${days}`)));renderPagesSection(mergeItems(r,'pages','path','views'));}else renderPagesSection([]);}break;}
      case 'referrers':{if(base){const d=await api(`${base}/referrers?days=${days}`);renderReferrersSection(d?.referrers);}else{const sd=await api('/api/sites');if(sd?.sites?.length){const r=await Promise.all(sd.sites.map(s=>api(`/api/sites/${s.id}/referrers?days=${days}`)));renderReferrersSection(mergeItems(r,'referrers','domain','visits'));}else renderReferrersSection([]);}break;}
      case 'devices':{if(base){const[d,b]=await Promise.all([api(`${base}/devices?days=${days}`),api(`${base}/browsers?days=${days}`)]);renderDevicesSection(d?.devices,b?.browsers);}else{const sd=await api('/api/sites');if(sd?.sites?.length){const r=await Promise.all(sd.sites.map(s=>Promise.all([api(`/api/sites/${s.id}/devices?days=${days}`),api(`/api/sites/${s.id}/browsers?days=${days}`)])));renderDevicesSection(mergeItems(r.map(x=>x[0]),'devices','device_type','views'),mergeItems(r.map(x=>x[1]),'browsers','browser','views'));}else renderDevicesSection([],[]);}break;}
      case 'countries':{if(base){const d=await api(`${base}/countries?days=${days}`);renderCountriesSection(d?.countries);}else{const sd=await api('/api/sites');if(sd?.sites?.length){const r=await Promise.all(sd.sites.map(s=>api(`/api/sites/${s.id}/countries?days=${days}`)));renderCountriesSection(mergeItems(r,'countries','country','views'));}else renderCountriesSection([]);}break;}
      case 'funnels':{if(base){const d=await api(`${base}/pages?days=${days}`);renderFunnelsSection(d?.pages);}else renderFunnelsSection([]);break;}
      case 'goals':renderGoalsSection();break;
      case 'alerts':renderAlertsSection();break;
      case 'email-reports':renderEmailReportsSection();break;
      case 'webhooks':renderWebhooksSection();break;
      case 'themes':renderThemesSection();break;
      case 'plugins':renderPluginsSection();break;
      case 'backup':renderBackupSection();break;
      case 'settings':renderSettingsSection();break;
      case 'admin':renderAdminSection();break;
      case 'profile':renderProfileSection();break;
    }
  }

  /* ═══════ NAVIGATION ═══════ */
  function navigateTo(section) {
    state.currentSection=section;window.location.hash=section;
    $('#pageTitle').textContent=PAGE_TITLES[section]||'Dashboard';
    $$('.nav-item').forEach(item=>{item.classList.toggle('active',item.dataset.section===section);item.setAttribute('aria-current',item.dataset.section===section?'page':'false');});
    destroyAllCharts();if(state.realtimeTimer){clearInterval(state.realtimeTimer);state.realtimeTimer=null;}
    loadSectionData(section);if(section==='realtime')state.realtimeTimer=setInterval(()=>loadSectionData('realtime'),5000);
    // Close mobile sidebar
    $('#sidebar').classList.remove('open');$('#sidebarOverlay').classList.remove('show');$('#menuToggle').setAttribute('aria-expanded','false');
  }
  function handleHashChange(){const h=window.location.hash.slice(1)||'dashboard';if(h!==state.currentSection)navigateTo(h);}

  /* ═══════ WEBSOCKET ═══════ */
  function connectWebSocket() {
    if(state.ws){try{state.ws.close();}catch(e){}}
    const proto=window.location.protocol==='https:'?'wss:':'ws:',sid=state.siteId||1;
    try{state.ws=new WebSocket(`${proto}//${window.location.host}/ws/${sid}`);
    state.ws.onopen=()=>{console.log('[Ghostly] WS connected');if(state.wsReconnectTimer){clearTimeout(state.wsReconnectTimer);state.wsReconnectTimer=null;}};
    state.ws.onmessage=e=>{try{const m=JSON.parse(e.data);if(m.type==='pageview'||m.type==='realtime_update')updateRealtimeBadge(m.data);}catch(e){}};
    state.ws.onclose=()=>{console.log('[Ghostly] WS disconnected, reconnecting in 10s...');state.wsReconnectTimer=setTimeout(connectWebSocket,10000);};
    state.ws.onerror=()=>{};}catch(e){state.wsReconnectTimer=setTimeout(connectWebSocket,10000);}
  }
  function updateRealtimeBadge(data){const c=data?.active_visitors??data?.active??0;$('#activeNowCount').textContent=formatNumber(c);const nb=$('#navActiveCount');if(nb)nb.textContent=c;}

  /* ═══════ KEYBOARD SHORTCUTS ═══════ */
  function setupKeyboardShortcuts() {
    document.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
      const key = e.key.toLowerCase();
      if (key === '?' || (e.shiftKey && key === '/')) { e.preventDefault(); toggleShortcuts(); return; }
      if (key === 'escape') { closeAllModals(); return; }
      if (state.gKeyPending) {
        state.gKeyPending = false;
        const routes = { d:'dashboard', r:'realtime', s:'settings', p:'profile', a:'admin', h:'heatmap' };
        if (routes[key]) { navigateTo(routes[key]); e.preventDefault(); }
        return;
      }
      if (key === 'g') { state.gKeyPending = true; setTimeout(() => { state.gKeyPending = false; }, 1000); return; }
      if (key === 'r' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); navigateTo(state.currentSection); return; }
      if (key === 'p' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); window.print(); return; }
      if (key === 'd') { toggleDarkMode(); return; }
      if (key >= '1' && key <= '9') { const sections = ['dashboard','realtime','heatmap','pages','referrers','devices','countries','funnels','goals']; const idx = parseInt(key) - 1; if (sections[idx]) navigateTo(sections[idx]); }
    });
  }
  function toggleShortcuts() { const o = $('#shortcutsOverlay'); o.style.display = o.style.display === 'none' ? 'flex' : 'none'; }
  function closeAllModals() { $$('.modal-overlay.show').forEach(m => m.classList.remove('show')); $('#shortcutsOverlay').style.display = 'none'; }

  /* ═══════ DARK MODE ═══════ */
  function toggleDarkMode() {
    state.darkMode = !state.darkMode;
    localStorage.setItem('ghostly_dark_mode', state.darkMode);
    if (!state.darkMode) {
      document.documentElement.style.setProperty('--bg', '#f5f5f7');
      document.documentElement.style.setProperty('--bg-secondary', '#ffffff');
      document.documentElement.style.setProperty('--bg-card', 'rgba(255,255,255,.85)');
      document.documentElement.style.setProperty('--text', '#1a1a2e');
      document.documentElement.style.setProperty('--text-secondary', '#555');
      document.documentElement.style.setProperty('--text-dim', '#999');
      document.documentElement.style.setProperty('--border', 'rgba(0,0,0,.08)');
      document.documentElement.style.setProperty('--border-hover', 'rgba(0,0,0,.15)');
      document.body.style.background = '#f5f5f7';
    } else {
      applyTheme(state.activeTheme);
      document.body.style.background = '';
    }
  }

  /* ═══════ PRINT REPORT ═══════ */
  function printReport() { window.print(); }

  /* ═══════ ERROR BOUNDARY ═══════ */
  function setupErrorBoundary() {
    window.addEventListener('error', e => {
      console.error('[Ghostly] Uncaught error:', e);
      const eb = $('#errorBoundary');
      if (eb) { eb.style.display = 'flex'; }
    });
    window.addEventListener('unhandledrejection', e => {
      console.error('[Ghostly] Unhandled rejection:', e);
    });
    $('#errorRetryBtn')?.addEventListener('click', () => {
      $('#errorBoundary').style.display = 'none';
      navigateTo(state.currentSection);
    });
    $('#errorReportBtn')?.addEventListener('click', () => {
      toast('Error report feature coming soon!', 'info');
    });
  }

  /* ═══════ INIT ═══════ */
  function init() {
    // Check auth
    if (state.auth && state.auth.expires > Date.now()) {
      showApp();
    } else {
      showAuth();
    }

    // Auth form events
    $('#loginForm')?.addEventListener('submit', e => {
      e.preventDefault();
      const email = $('#loginEmail').value.trim(), pass = $('#loginPassword').value;
      if (!email || !pass) { toast('Please fill in all fields', 'error'); return; }
      const btn = $('#loginSubmit'); btn.classList.add('loading');
      setTimeout(() => {
        const user = loginUser(email, pass);
        btn.classList.remove('loading');
        if (user) { showApp(); toast(`Welcome back, ${user.name}!`, 'success'); handleHashChange(); connectWebSocket(); }
        else toast('Invalid email or password', 'error');
      }, 600);
    });

    $('#registerForm')?.addEventListener('submit', e => {
      e.preventDefault();
      const name = $('#regName').value.trim(), email = $('#regEmail').value.trim(), pass = $('#regPassword').value, confirm = $('#regPasswordConfirm').value, agree = $('#agreeTerms').checked;
      if (!name || !email || !pass) { toast('Please fill in all fields', 'error'); return; }
      if (pass.length < 8) { toast('Password must be at least 8 characters', 'error'); return; }
      if (pass !== confirm) { toast('Passwords do not match', 'error'); return; }
      if (!agree) { toast('Please agree to the terms', 'error'); return; }
      const btn = $('#registerSubmit'); btn.classList.add('loading');
      setTimeout(() => {
        const auth = registerUser(name, email, pass);
        btn.classList.remove('loading');
        if (auth) { showApp(); toast('Account created! Welcome to Ghostly.', 'success'); handleHashChange(); connectWebSocket(); }
        else toast('Email already in use', 'error');
      }, 600);
    });

    $('#forgotForm')?.addEventListener('submit', e => {
      e.preventDefault();
      toast('Password reset link sent! (Demo mode)', 'success');
      setTimeout(() => { $('#forgotForm').style.display = 'none'; $('#loginForm').style.display = 'flex'; }, 1500);
    });

    // Auth form switching
    $('#showRegister')?.addEventListener('click', e => { e.preventDefault(); $('#loginForm').style.display = 'none'; $('#registerForm').style.display = 'flex'; });
    $('#showLogin')?.addEventListener('click', e => { e.preventDefault(); $('#registerForm').style.display = 'none'; $('#loginForm').style.display = 'flex'; });
    $('#showLoginFromForgot')?.addEventListener('click', e => { e.preventDefault(); $('#forgotForm').style.display = 'none'; $('#loginForm').style.display = 'flex'; });
    $('#forgotLink')?.addEventListener('click', e => { e.preventDefault(); $('#loginForm').style.display = 'none'; $('#forgotForm').style.display = 'flex'; });
    $('#demoLoginBtn')?.addEventListener('click', () => {
      const btn = $('#demoLoginBtn'); btn.classList.add('loading');
      setTimeout(() => {
        const auth = loginUser('demo@ghostly.io', 'demo123');
        btn.classList.remove('loading');
        if (auth) { showApp(); toast('Signed in as Demo User', 'success'); handleHashChange(); connectWebSocket(); }
      }, 600);
    });

    // Password toggles
    $$('.password-toggle').forEach(btn => {
      btn.addEventListener('click', () => {
        const input = btn.parentElement.querySelector('input');
        if (input) { const isPassword = input.type === 'password'; input.type = isPassword ? 'text' : 'password'; btn.setAttribute('aria-label', isPassword ? 'Hide password' : 'Show password'); }
      });
    });

    // Password strength
    $('#regPassword')?.addEventListener('input', e => {
      const v = e.target.value, fill = $('#strengthFill'), text = $('#strengthText');
      if (!fill || !text) return;
      let score = 0;
      if (v.length >= 8) score++; if (v.length >= 12) score++; if (/[A-Z]/.test(v)) score++; if (/[0-9]/.test(v)) score++; if (/[^A-Za-z0-9]/.test(v)) score++;
      const levels = [{w:'0%',c:'transparent',t:''},{w:'20%',c:'var(--red)',t:'Very weak'},{w:'40%',c:'var(--orange)',t:'Weak'},{w:'60%',c:'var(--yellow)',t:'Fair'},{w:'80%',c:'var(--green)',t:'Strong'},{w:'100%',c:'var(--green)',t:'Very strong'}];
      const l = levels[score] || levels[0];
      fill.style.width = l.w; fill.style.background = l.c; text.textContent = l.t; text.style.color = l.c;
    });

    // Logout
    $('#logoutBtn')?.addEventListener('click', logoutUser);

    // User dropdown
    $('#userAvatarBtn')?.addEventListener('click', e => {
      e.stopPropagation();
      const dd = $('#userDropdown');
      dd.classList.toggle('show');
      $('#userAvatarBtn').setAttribute('aria-expanded', dd.classList.contains('show'));
    });
    document.addEventListener('click', () => { $('#userDropdown')?.classList.remove('show'); $('#userAvatarBtn')?.setAttribute('aria-expanded', 'false'); });
    $$('.user-dropdown-item[data-dropdown-action]').forEach(item => {
      item.addEventListener('click', e => { e.preventDefault(); const action = item.dataset.dropdownAction; if (action) navigateTo(action); });
    });

    // Date range
    $('#dateRange')?.addEventListener('change', e => { state.dateRange = e.target.value; $('#dateRangeLabel').textContent = RANGE_LABELS[state.dateRange] || state.dateRange; navigateTo(state.currentSection); });

    // Refresh
    $('#refreshBtn')?.addEventListener('click', () => { const btn = $('#refreshBtn'); btn.classList.add('spinning'); navigateTo(state.currentSection); setTimeout(() => btn.classList.remove('spinning'), 800); });

    // Menu toggle (mobile)
    $('#menuToggle')?.addEventListener('click', () => {
      const isOpen = $('#sidebar').classList.toggle('open');
      $('#sidebarOverlay').classList.toggle('show');
      $('#menuToggle').setAttribute('aria-expanded', isOpen);
    });
    $('#sidebarClose')?.addEventListener('click', () => { $('#sidebar').classList.remove('open'); $('#sidebarOverlay').classList.remove('show'); $('#menuToggle').setAttribute('aria-expanded', 'false'); });
    $('#sidebarOverlay')?.addEventListener('click', () => { $('#sidebar').classList.remove('open'); $('#sidebarOverlay').classList.remove('show'); $('#menuToggle').setAttribute('aria-expanded', 'false'); });

    // Dark mode toggle
    $('#darkModeToggle')?.addEventListener('click', toggleDarkMode);

    // Print
    $('#printBtn')?.addEventListener('click', printReport);

    // Shortcuts
    $('#closeShortcuts')?.addEventListener('click', () => { $('#shortcutsOverlay').style.display = 'none'; });

    // Add site modal
    $('#addSiteBtn')?.addEventListener('click', () => $('#addSiteModal').classList.add('show'));
    $('#closeModal')?.addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#cancelAddSite')?.addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#addSiteModal')?.addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });
    $('#confirmAddSite')?.addEventListener('click', async () => {
      const name = $('#newSiteName').value.trim(), domain = $('#newSiteDomain').value.trim();
      if (!name || !domain) { toast('Please fill in all fields', 'error'); return; }
      const result = await apiPost('/api/sites', { name, domain });
      if (result && result.id) { toast('Site added!', 'success'); $('#addSiteModal').classList.remove('show'); $('#newSiteName').value = ''; $('#newSiteDomain').value = ''; await loadSites(); state.siteId = result.id; navigateTo(state.currentSection); }
      else toast('Failed to add site', 'error');
    });
    $('#copySnippet')?.addEventListener('click', () => { navigator.clipboard.writeText($('#trackingSnippet').textContent); toast('Snippet copied!', 'success'); });

    // Alert modal
    $('#closeAlertModal')?.addEventListener('click', () => $('#alertModal').classList.remove('show'));
    $('#cancelAlertModal')?.addEventListener('click', () => $('#alertModal').classList.remove('show'));
    $('#alertModal')?.addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });
    $('#confirmCreateAlert')?.addEventListener('click', () => {
      const name = $('#alertName').value.trim(), metric = $('#alertMetric').value, condition = $('#alertCondition').value, threshold = parseFloat($('#alertThreshold').value);
      if (!name || isNaN(threshold)) { toast('Please fill in all fields', 'error'); return; }
      state.alerts.push({ name, metric, condition, threshold, created: new Date().toISOString() });
      localStorage.setItem('ghostly_alerts', JSON.stringify(state.alerts));
      $('#alertModal').classList.remove('show'); $('#alertName').value = ''; $('#alertThreshold').value = '';
      toast('Alert created!', 'success'); if (state.currentSection === 'alerts') renderAlertsSection();
    });

    // Funnel modal
    $('#closeFunnelModal')?.addEventListener('click', () => $('#funnelModal').classList.remove('show'));
    $('#cancelFunnelModal')?.addEventListener('click', () => $('#funnelModal').classList.remove('show'));
    $('#funnelModal')?.addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });
    $('#confirmCreateFunnel')?.addEventListener('click', () => {
      const name = $('#funnelName').value.trim(), stepsRaw = $('#funnelSteps').value.trim();
      if (!name || !stepsRaw) { toast('Please fill in all fields', 'error'); return; }
      state.funnels.push({ name, steps: stepsRaw.split('\n').map(s => s.trim()).filter(Boolean), created: new Date().toISOString() });
      localStorage.setItem('ghostly_funnels', JSON.stringify(state.funnels));
      $('#funnelModal').classList.remove('show'); $('#funnelName').value = ''; $('#funnelSteps').value = '';
      toast('Funnel created!', 'success'); if (state.currentSection === 'funnels') renderFunnelsSection();
    });

    // Goal modal
    $('#closeGoalModal')?.addEventListener('click', () => $('#goalModal').classList.remove('show'));
    $('#cancelGoalModal')?.addEventListener('click', () => $('#goalModal').classList.remove('show'));
    $('#goalModal')?.addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });
    $('#confirmCreateGoal')?.addEventListener('click', () => {
      const name = $('#goalName').value.trim(), metric = $('#goalMetric').value, target = parseFloat($('#goalTarget').value), period = $('#goalPeriod').value;
      if (!name || isNaN(target)) { toast('Please fill in all fields', 'error'); return; }
      const colors = ['cyan', 'green', 'purple'];
      state.goals.push({ name, value: 0, target, metric, period, status: 'active', color: colors[state.goals.length % colors.length], created: new Date().toISOString() });
      localStorage.setItem('ghostly_goals', JSON.stringify(state.goals));
      $('#goalModal').classList.remove('show'); $('#goalName').value = ''; $('#goalTarget').value = '';
      toast('Goal created!', 'success'); if (state.currentSection === 'goals') renderGoalsSection();
    });

    // Export modal
    $('#confirmExport')?.addEventListener('click', () => { toast('Export started! Download will begin shortly.', 'success'); $('#exportModal').classList.remove('show'); });

    window.addEventListener('hashchange', handleHashChange);

    // Initialize
    if (state.auth?.expires > Date.now()) {
      loadSites();
      handleHashChange();
      connectWebSocket();
    }

    if (state.activeTimer) clearInterval(state.activeTimer);
    state.activeTimer = setInterval(async () => {
      if (state.siteId && state.auth) {
        const data = await api(`/api/sites/${state.siteId}/realtime`);
        if (data) updateRealtimeBadge(data);
      }
    }, 15000);

    setupOfflineDetection();
    registerServiceWorker();
    setupKeyboardShortcuts();
    setupErrorBoundary();

    // Apply initial dark mode state
    if (!state.darkMode) toggleDarkMode();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
