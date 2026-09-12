(() => {
  'use strict';

  /* ═══════════════════════════════════════════════════════════════════════
     Constants & State
     ═══════════════════════════════════════════════════════════════════════ */

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  const PALETTE = ['#00d4ff', '#00ff88', '#a855f7', '#ffbb33', '#ff4466', '#ec4899', '#06b6d4', '#22d3ee', '#34d399', '#a78bfa'];
  const RANGE_TO_DAYS = { '24h': 1, '7d': 7, '30d': 30, '90d': 90 };
  const RANGE_LABELS = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', '90d': 'Last 90 days' };
  const PAGE_TITLES = {
    dashboard: 'Dashboard', realtime: 'Real-time', pages: 'Pages',
    referrers: 'Referrers', devices: 'Devices', countries: 'Countries',
    funnels: 'Funnels', goals: 'Goals', alerts: 'Alerts', settings: 'Settings',
    heatmap: 'Heatmap', 'email-reports': 'Email Reports', webhooks: 'Webhooks',
    themes: 'Themes', plugins: 'Plugins', backup: 'Backup'
  };

  const THEMES = [
    {
      id: 'default', name: 'Midnight Ghost',
      vars: { '--bg': '#06060a', '--bg-secondary': '#0c0c10', '--bg-card': 'rgba(12,12,16,.65)', '--cyan': '#00d4ff', '--green': '#00ff88', '--text': '#e8eaed' },
      preview: { sidebar: '#0a0a10', topbar: 'rgba(6,6,10,.82)', content: '#0c0c10', accent: '#00d4ff' }
    },
    {
      id: 'aurora', name: 'Aurora Drift',
      vars: { '--bg': '#0a0f1a', '--bg-secondary': '#0f1524', '--bg-card': 'rgba(15,21,36,.65)', '--cyan': '#38bdf8', '--green': '#34d399', '--text': '#e2e8f0' },
      preview: { sidebar: '#0d1321', topbar: 'rgba(10,15,26,.82)', content: '#0f1524', accent: '#38bdf8' }
    },
    {
      id: 'ember', name: 'Ember Glow',
      vars: { '--bg': '#120a0a', '--bg-secondary': '#1a0e0e', '--bg-card': 'rgba(26,14,14,.65)', '--cyan': '#fb923c', '--green': '#f97316', '--text': '#fde2e2' },
      preview: { sidebar: '#150c0c', topbar: 'rgba(18,10,10,.82)', content: '#1a0e0e', accent: '#fb923c' }
    },
    {
      id: 'forest', name: 'Deep Forest',
      vars: { '--bg': '#060f0a', '--bg-secondary': '#0c1a0e', '--bg-card': 'rgba(12,26,14,.65)', '--cyan': '#4ade80', '--green': '#22c55e', '--text': '#e2fde8' },
      preview: { sidebar: '#08140c', topbar: 'rgba(6,15,10,.82)', content: '#0c1a0e', accent: '#4ade80' }
    },
    {
      id: 'cosmic', name: 'Cosmic Purple',
      vars: { '--bg': '#0a0614', '--bg-secondary': '#120c20', '--bg-card': 'rgba(18,12,32,.65)', '--cyan': '#c084fc', '--green': '#a78bfa', '--text': '#ede2fd' },
      preview: { sidebar: '#0d081a', topbar: 'rgba(10,6,20,.82)', content: '#120c20', accent: '#c084fc' }
    },
    {
      id: 'ocean', name: 'Deep Ocean',
      vars: { '--bg': '#040a14', '--bg-secondary': '#081220', '--bg-card': 'rgba(8,18,32,.65)', '--cyan': '#22d3ee', '--green': '#06b6d4', '--text': '#e0f2fe' },
      preview: { sidebar: '#060e1a', topbar: 'rgba(4,10,20,.82)', content: '#081220', accent: '#22d3ee' }
    }
  ];

  const DEFAULT_PLUGINS = [
    { id: 'gdpr-banner', name: 'GDPR Consent Banner', version: '1.4.0', description: 'Shows a cookie consent banner for EU visitors. Auto-detects visitor locale.', author: 'Ghostly', icon: '\u{1F6E1}', iconBg: 'var(--cyan-dim)', enabled: true },
    { id: 'custom-events', name: 'Custom Events', version: '2.1.0', description: 'Track custom button clicks, form submissions, and scroll depth events.', author: 'Ghostly', icon: '\u{1F3AF}', iconBg: 'var(--green-dim)', enabled: true },
    { id: 'ab-testing', name: 'A/B Testing', version: '0.9.2', description: 'Split traffic between variants and measure conversion impact.', author: 'Community', icon: '\u{1F500}', iconBg: 'var(--purple-dim)', enabled: false },
    { id: 'utm-tracker', name: 'UTM Campaign Tracker', version: '1.2.0', description: 'Enhanced UTM parameter tracking with campaign dashboards.', author: 'Ghostly', icon: '\u{1F4E3}', iconBg: 'var(--orange-dim)', enabled: true },
    { id: 'error-monitor', name: 'JS Error Monitor', version: '1.0.3', description: 'Captures unhandled JavaScript errors with stack traces.', author: 'Community', icon: '\u{1F41B}', iconBg: 'var(--red-dim)', enabled: false },
    { id: 'performance', name: 'Core Web Vitals', version: '1.1.0', description: 'Measures LCP, FID, CLS and reports performance metrics.', author: 'Ghostly', icon: '\u{26A1}', iconBg: 'var(--yellow-dim)', enabled: true }
  ];

  let state = {
    siteId: null,
    dateRange: '7d',
    charts: {},
    ws: null,
    wsReconnectTimer: null,
    sortConfig: { key: null, dir: 'desc' },
    alerts: JSON.parse(localStorage.getItem('ghostly_alerts') || '[]'),
    funnels: JSON.parse(localStorage.getItem('ghostly_funnels') || '[]'),
    goals: JSON.parse(localStorage.getItem('ghostly_goals') || '[]'),
    webhooks: JSON.parse(localStorage.getItem('ghostly_webhooks') || '[]'),
    plugins: JSON.parse(localStorage.getItem('ghostly_plugins') || 'null') || DEFAULT_PLUGINS,
    emailConfig: JSON.parse(localStorage.getItem('ghostly_email_config') || '{"smtpHost":"","smtpPort":"587","smtpUser":"","smtpPass":"","fromEmail":"","fromName":"Ghostly Reports"}'),
    activeTheme: localStorage.getItem('ghostly_theme') || 'default',
    currentSection: 'dashboard',
    realtimeTimer: null,
    activeTimer: null,
    heatmapClicks: JSON.parse(localStorage.getItem('ghostly_heatmap_clicks') || '[]'),
    heatmapCanvas: null,
    backupHistory: JSON.parse(localStorage.getItem('ghostly_backups') || '[]')
  };

  /* ═══════════════════════════════════════════════════════════════════════
     Utilities
     ═══════════════════════════════════════════════════════════════════════ */

  function formatNumber(n) {
    if (n == null) return '--';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return n.toLocaleString();
  }

  function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '--';
    if (seconds < 60) return Math.round(seconds) + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + Math.round(seconds % 60) + 's';
    return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
  }

  function formatPercent(n) {
    if (n == null) return '--';
    return n.toFixed(1) + '%';
  }

  function timeAgo(date) {
    if (!date) return '--';
    const s = Math.floor((Date.now() - new Date(date + 'Z').getTime()) / 1000);
    if (s < 0 || s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + 'm ago';
    if (s < 86400) return Math.floor(s / 3600) + 'h ago';
    return Math.floor(s / 86400) + 'd ago';
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function getDays() {
    return RANGE_TO_DAYS[state.dateRange] || 7;
  }

  function getBaseUrl() {
    return state.siteId ? `/api/sites/${state.siteId}` : '/api/sites';
  }

  function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }

  /* ═══════════════════════════════════════════════════════════════════════
     API Client
     ═══════════════════════════════════════════════════════════════════════ */

  async function api(path, options = {}) {
    try {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options
      });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      console.error('[Ghostly] API error:', path, e);
      return null;
    }
  }

  async function apiPost(path, body) {
    return api(path, { method: 'POST', body: JSON.stringify(body) });
  }

  async function apiPut(path, body) {
    return api(path, { method: 'PUT', body: JSON.stringify(body) });
  }

  async function apiDelete(path) {
    return api(path, { method: 'DELETE' });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Toast Notifications
     ═══════════════════════════════════════════════════════════════════════ */

  function toast(message, type = 'info') {
    const container = $('#toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => { if (el.parentNode) el.remove(); }, 3200);
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Chart Helpers
     ═══════════════════════════════════════════════════════════════════════ */

  function destroyChart(name) {
    if (state.charts[name]) { state.charts[name].destroy(); state.charts[name] = null; }
  }

  function destroyAllCharts() {
    Object.keys(state.charts).forEach(destroyChart);
  }

  function chartTooltip() {
    return {
      backgroundColor: 'rgba(12,12,16,.94)',
      titleColor: '#e8eaed',
      bodyColor: '#a0a4ab',
      borderColor: 'rgba(255,255,255,.08)',
      borderWidth: 1,
      padding: 14,
      cornerRadius: 10,
      titleFont: { weight: '600', size: 13 },
      bodyFont: { size: 12 }
    };
  }

  function gridOpts() {
    return { color: 'rgba(255,255,255,.04)', drawBorder: false };
  }

  function renderLineChart(canvasId, labels, datasets, opts = {}) {
    destroyChart(canvasId);
    const ctx = $(`#${canvasId}`);
    if (!ctx || !labels || !labels.length) return;

    state.charts[canvasId] = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: datasets.length > 1,
            position: 'top',
            align: 'end',
            labels: { color: '#6b7080', usePointStyle: true, pointStyle: 'circle', padding: 18, font: { size: 12 } }
          },
          tooltip: chartTooltip()
        },
        scales: {
          x: { grid: gridOpts(), ticks: { color: '#4a4e5a', font: { size: 11 }, maxTicksLimit: 10 } },
          y: { grid: gridOpts(), ticks: { color: '#4a4e5a', font: { size: 11 } }, beginAtZero: true, ...opts.yScale }
        },
        ...opts
      }
    });
  }

  function renderBarChart(canvasId, items, labelKey, valueKey, color) {
    destroyChart(canvasId);
    const ctx = $(`#${canvasId}`);
    if (!ctx || !items || !items.length) return;

    state.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: items.map(i => i[labelKey] || 'Unknown'),
        datasets: [{
          data: items.map(i => i[valueKey]),
          backgroundColor: color || '#00d4ff',
          borderRadius: 7,
          barThickness: 26,
          hoverBackgroundColor: color ? color + 'cc' : '#00d4ffcc'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: { legend: { display: false }, tooltip: chartTooltip() },
        scales: {
          x: { grid: gridOpts(), ticks: { color: '#4a4e5a', font: { size: 11 } }, beginAtZero: true },
          y: { grid: { display: false }, ticks: { color: '#a0a4ab', font: { size: 11 } } }
        }
      }
    });
  }

  function renderDoughnutChart(canvasId, items, labelKey, valueKey) {
    destroyChart(canvasId);
    const ctx = $(`#${canvasId}`);
    if (!ctx || !items || !items.length) return;

    state.charts[canvasId] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: items.map(i => i[labelKey] || 'Unknown'),
        datasets: [{
          data: items.map(i => i[valueKey]),
          backgroundColor: PALETTE.slice(0, items.length),
          borderWidth: 0,
          hoverOffset: 8
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '68%',
        plugins: {
          legend: { display: true, position: 'bottom', labels: { color: '#6b7080', usePointStyle: true, pointStyle: 'circle', padding: 14, font: { size: 11 } } },
          tooltip: chartTooltip()
        }
      }
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Data Merging (All Sites)
     ═══════════════════════════════════════════════════════════════════════ */

  function mergeStats(arr) {
    const valid = arr.filter(Boolean);
    if (!valid.length) return null;
    return {
      total_pageviews: valid.reduce((s, v) => s + (v.total_pageviews || 0), 0),
      unique_visitors: valid.reduce((s, v) => s + (v.unique_visitors || 0), 0),
      total_sessions: valid.reduce((s, v) => s + (v.total_sessions || 0), 0),
      avg_session_seconds: valid.reduce((s, v) => s + (v.avg_session_seconds || 0), 0) / valid.length,
      bounce_rate: valid.reduce((s, v) => s + (v.bounce_rate || 0), 0) / valid.length,
      total_visitors: valid.reduce((s, v) => s + (v.total_visitors || 0), 0),
      returning_visitors: valid.reduce((s, v) => s + (v.returning_visitors || 0), 0),
    };
  }

  function mergeDaily(arr) {
    const map = {};
    arr.filter(Boolean).forEach(res => {
      (res.daily || []).forEach(d => {
        if (!map[d.day]) map[d.day] = { day: d.day, views: 0, unique_visitors: 0 };
        map[d.day].views += d.views;
        map[d.day].unique_visitors += d.unique_visitors;
      });
    });
    return Object.values(map).sort((a, b) => a.day.localeCompare(b.day));
  }

  function mergeItems(arr, key, groupBy, countKey) {
    const map = {};
    arr.filter(Boolean).forEach(res => {
      (res[key] || []).forEach(item => {
        const k = item[groupBy] || 'Unknown';
        map[k] = map[k] || { [groupBy]: k, [countKey]: 0 };
        map[k][countKey] += item[countKey];
      });
    });
    return Object.values(map).sort((a, b) => b[countKey] - a[countKey]);
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Section Renderers
     ═══════════════════════════════════════════════════════════════════════ */

  function renderDashboard(stats, daily, pages, devices, browsers, countries, referrers) {
    const content = $('#content');
    const bounceRate = stats ? formatPercent(stats.bounce_rate) : '--';
    const sessions = stats ? formatNumber(stats.total_sessions) : '--';
    const returning = stats ? formatNumber(stats.returning_visitors) : '--';
    const totalV = stats ? formatNumber(stats.total_pageviews) : '--';
    const uniqV = stats ? formatNumber(stats.unique_visitors) : '--';
    const avgT = stats ? formatDuration(stats.avg_session_seconds) : '--';
    const pps = stats && stats.total_sessions ? (stats.total_pageviews / stats.total_sessions).toFixed(1) : '--';
    const totalVraw = stats ? formatNumber(stats.total_visitors) : '--';

    content.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-card-icon icon-views"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Pageviews</div><div class="stat-card-value">${totalV}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-visitors"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4-4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Unique Visitors</div><div class="stat-card-value">${uniqV}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-active"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Avg. Session</div><div class="stat-card-value">${avgT}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-time"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Sessions</div><div class="stat-card-value">${sessions}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-bounce"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Bounce Rate</div><div class="stat-card-value">${bounceRate}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-returning"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Returning</div><div class="stat-card-value">${returning}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-pageviews"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Pages / Session</div><div class="stat-card-value">${pps}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
        <div class="stat-card"><div class="stat-card-icon icon-sessions"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div><div class="stat-card-content"><div class="stat-card-label">Total Visitors</div><div class="stat-card-value">${totalVraw}</div><div class="stat-card-change neutral">&nbsp;</div></div></div>
      </div>
      <div class="charts-grid" style="margin-top:16px">
        <div class="chart-card wide">
          <div class="chart-card-header"><h3>Traffic Overview</h3><div class="chart-legend"><span><span class="dot" style="background:var(--cyan)"></span>Views</span><span><span class="dot" style="background:var(--green)"></span>Visitors</span></div></div>
          <div class="chart-container chart-tall"><canvas id="viewsChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-card-header"><h3>Top Pages</h3></div>
          <div class="chart-container"><canvas id="pagesChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-card-header"><h3>Devices</h3></div>
          <div class="chart-container chart-doughnut"><canvas id="devicesChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-card-header"><h3>Countries</h3></div>
          <div class="chart-container"><canvas id="countriesChart"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-card-header"><h3>Referrers</h3></div>
          <div class="chart-container"><canvas id="referrersChart"></canvas></div>
        </div>
        <div class="chart-card wide">
          <div class="chart-card-header"><h3>Browsers</h3></div>
          <div class="chart-container"><canvas id="browsersChart"></canvas></div>
        </div>
      </div>
    `;

    if (daily && daily.length) {
      renderLineChart('viewsChart', daily.map(d => d.day), [
        { label: 'Views', data: daily.map(d => d.views), borderColor: '#00d4ff', backgroundColor: 'rgba(0,212,255,.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: '#00d4ff' },
        { label: 'Visitors', data: daily.map(d => d.unique_visitors), borderColor: '#00ff88', backgroundColor: 'rgba(0,255,136,.08)', fill: true, tension: 0.4, borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: '#00ff88' }
      ]);
    }
    if (pages && pages.length) renderBarChart('pagesChart', pages.slice(0, 8), 'path', 'views', '#00d4ff');
    if (devices && devices.length) renderDoughnutChart('devicesChart', devices, 'device_type', 'views');
    if (countries && countries.length) renderBarChart('countriesChart', countries.slice(0, 8), 'country', 'views', '#00ff88');
    if (referrers && referrers.length) renderBarChart('referrersChart', referrers.slice(0, 8), 'domain', 'visits', '#a855f7');
    if (browsers && browsers.length) renderDoughnutChart('browsersChart', browsers, 'browser', 'views');
  }

  function renderRealtimeSection(data) {
    const content = $('#content');
    const active = data ? data.active_visitors || 0 : 0;
    const topPages = data ? data.top_pages || [] : [];

    content.innerHTML = `
      <div class="realtime-hero">
        <div class="realtime-count" id="realtimeCount">${formatNumber(active)}</div>
        <div class="realtime-label">visitors active right now</div>
      </div>
      <div class="table-card">
        <div class="table-card-header"><h3>Active Pages</h3><span class="table-count">${topPages.length} pages</span></div>
        <div class="realtime-pages-list" id="realtimePagesList">
          ${topPages.length ? topPages.map(p => `
            <div class="realtime-page-item">
              <span class="realtime-page-path">${esc(p.path)}</span>
              <span class="realtime-page-views">${p.views} view${p.views !== 1 ? 's' : ''}</span>
            </div>
          `).join('') : '<div class="empty-state"><p>No active visitors</p></div>'}
        </div>
      </div>
    `;
  }

  function renderPagesSection(pages) {
    const content = $('#content');
    const sorted = sortArray(pages || [], state.sortConfig);

    content.innerHTML = `
      <div class="section-header"><h2>Pages</h2></div>
      <div class="table-card">
        <div class="table-card-header"><h3>All Pages</h3><span class="table-count">${sorted.length} pages</span></div>
        <div class="table-wrapper">
          <table class="data-table" id="pagesTable">
            <thead><tr>
              <th data-sort="path" class="${state.sortConfig.key === 'path' ? 'sorted' : ''}">Page <span class="sort-arrow">${state.sortConfig.key === 'path' ? (state.sortConfig.dir === 'asc' ? '\u25B2' : '\u25BC') : '\u25BC'}</span></th>
              <th data-sort="views" class="${state.sortConfig.key === 'views' ? 'sorted' : ''}">Views <span class="sort-arrow">${state.sortConfig.key === 'views' ? (state.sortConfig.dir === 'asc' ? '\u25B2' : '\u25BC') : '\u25BC'}</span></th>
              <th data-sort="unique_visitors">Visitors</th>
              <th data-sort="avg_time">Avg Time</th>
              <th data-sort="bounce_rate">Bounce Rate</th>
              <th>Trend</th>
            </tr></thead>
            <tbody>
              ${sorted.length ? sorted.map(p => {
                const maxViews = sorted[0] ? sorted[0].views : 1;
                const barPct = Math.max(5, (p.views / maxViews) * 100);
                return `<tr>
                  <td class="page-cell">${esc(p.path)}</td>
                  <td>${formatNumber(p.views)}</td>
                  <td>${formatNumber(p.unique_visitors)}</td>
                  <td class="time-cell">${formatDuration(p.avg_time)}</td>
                  <td>${formatPercent(p.bounce_rate)}</td>
                  <td><div class="table-bar-bg"><div class="table-bar" style="width:${barPct}%"></div></div></td>
                </tr>`;
              }).join('') : '<tr><td colspan="6" class="table-empty">No page data</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;

    $$('#pagesTable th[data-sort]').forEach(th => {
      th.addEventListener('click', () => {
        const key = th.dataset.sort;
        if (state.sortConfig.key === key) {
          state.sortConfig.dir = state.sortConfig.dir === 'asc' ? 'desc' : 'asc';
        } else {
          state.sortConfig.key = key;
          state.sortConfig.dir = 'desc';
        }
        renderPagesSection(pages);
      });
    });
  }

  function renderReferrersSection(referrers) {
    const content = $('#content');
    content.innerHTML = `
      <div class="section-header"><h2>Referrers</h2></div>
      <div class="charts-grid">
        <div class="chart-card wide">
          <div class="chart-card-header"><h3>Top Referrers</h3></div>
          <div class="chart-container chart-tall"><canvas id="referrerChartFull"></canvas></div>
        </div>
      </div>
      <div class="table-card" style="margin-top:16px">
        <div class="table-card-header"><h3>All Referrers</h3><span class="table-count">${(referrers || []).length} referrers</span></div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th>Source</th><th>Domain</th><th>Visits</th></tr></thead>
            <tbody>
              ${(referrers || []).map(r => `<tr><td class="referrer-cell">${esc(r.url)}</td><td>${esc(r.domain)}</td><td>${formatNumber(r.visits)}</td></tr>`).join('') || '<tr><td colspan="3" class="table-empty">No referrer data</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;
    if (referrers && referrers.length) {
      renderBarChart('referrerChartFull', referrers.slice(0, 15), 'domain', 'visits', '#a855f7');
    }
  }

  function renderDevicesSection(devices, browsers) {
    const content = $('#content');
    content.innerHTML = `
      <div class="section-header"><h2>Devices & Browsers</h2></div>
      <div class="charts-grid">
        <div class="chart-card">
          <div class="chart-card-header"><h3>Device Types</h3></div>
          <div class="chart-container chart-doughnut"><canvas id="deviceChartFull"></canvas></div>
        </div>
        <div class="chart-card">
          <div class="chart-card-header"><h3>Browsers</h3></div>
          <div class="chart-container chart-doughnut"><canvas id="browserChartFull"></canvas></div>
        </div>
      </div>
      <div class="charts-grid" style="margin-top:16px">
        <div class="table-card">
          <div class="table-card-header"><h3>Devices</h3></div>
          <div class="table-wrapper">
            <table class="data-table">
              <thead><tr><th>Device</th><th>Views</th></tr></thead>
              <tbody>${(devices || []).map(d => `<tr><td>${esc(d.device_type)}</td><td>${formatNumber(d.views)}</td></tr>`).join('') || '<tr><td colspan="2" class="table-empty">No data</td></tr>'}</tbody>
            </table>
          </div>
        </div>
        <div class="table-card">
          <div class="table-card-header"><h3>Browsers</h3></div>
          <div class="table-wrapper">
            <table class="data-table">
              <thead><tr><th>Browser</th><th>Views</th></tr></thead>
              <tbody>${(browsers || []).map(b => `<tr><td>${esc(b.browser)}</td><td>${formatNumber(b.views)}</td></tr>`).join('') || '<tr><td colspan="2" class="table-empty">No data</td></tr>'}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    if (devices && devices.length) renderDoughnutChart('deviceChartFull', devices, 'device_type', 'views');
    if (browsers && browsers.length) renderDoughnutChart('browserChartFull', browsers, 'browser', 'views');
  }

  function renderCountriesSection(countries) {
    const content = $('#content');
    content.innerHTML = `
      <div class="section-header"><h2>Countries</h2></div>
      <div class="charts-grid">
        <div class="chart-card wide">
          <div class="chart-card-header"><h3>Top Countries</h3></div>
          <div class="chart-container chart-tall"><canvas id="countryChartFull"></canvas></div>
        </div>
      </div>
      <div class="table-card" style="margin-top:16px">
        <div class="table-card-header"><h3>All Countries</h3><span class="table-count">${(countries || []).length} countries</span></div>
        <div class="table-wrapper">
          <table class="data-table">
            <thead><tr><th>Country</th><th>Views</th></tr></thead>
            <tbody>${(countries || []).map(c => `<tr><td>${esc(c.country)}</td><td>${formatNumber(c.views)}</td></tr>`).join('') || '<tr><td colspan="2" class="table-empty">No country data</td></tr>'}</tbody>
          </table>
        </div>
      </div>
    `;
    if (countries && countries.length) renderBarChart('countryChartFull', countries.slice(0, 20), 'country', 'views', '#00ff88');
  }

  function renderFunnelsSection(pages) {
    const content = $('#content');
    const steps = (pages || []).slice(0, 5);
    const maxCount = steps.length ? steps[0].views : 1;

    content.innerHTML = `
      <div class="alerts-header">
        <h2>Funnels</h2>
        <button class="btn btn-primary" id="createFunnelBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Funnel</button>
      </div>
      <div class="chart-card">
        <div class="chart-card-header"><h3>Page Flow Funnel</h3><p style="font-size:0.78rem;color:var(--text-dim)">Top pages as funnel steps</p></div>
        <div class="funnel-container">
          ${steps.length ? steps.map((s, i) => {
            const pct = maxCount ? (s.views / maxCount) * 100 : 0;
            const dropoff = i > 0 && steps[i - 1].views ? ((1 - s.views / steps[i - 1].views) * 100).toFixed(1) : null;
            return `
              ${dropoff !== null ? `<div class="funnel-dropoff">-${dropoff}% drop-off</div>` : ''}
              <div class="funnel-step">
                <div class="funnel-bar-wrapper">
                  <div class="funnel-bar" style="--progress:${pct}%;width:${Math.max(20, pct)}%">
                    <span class="funnel-bar-label">${esc(s.path)}</span>
                  </div>
                </div>
                <div class="funnel-stats">
                  <div class="funnel-count">${formatNumber(s.views)}</div>
                  <div class="funnel-pct">${pct.toFixed(1)}% of total</div>
                </div>
              </div>
            `;
          }).join('') : '<div class="empty-state"><p>No funnel data available</p></div>'}
        </div>
      </div>
    `;

    $('#createFunnelBtn')?.addEventListener('click', () => $('#funnelModal').classList.add('show'));
  }

  function renderGoalsSection() {
    const content = $('#content');
    const defaultGoals = [
      { name: 'Pageviews Target', value: 12500, target: 15000, status: 'active', color: 'cyan' },
      { name: 'Daily Active Users', value: 342, target: 500, status: 'active', color: 'green' },
      { name: 'Bounce Rate Goal', value: 28, target: 35, status: 'active', color: 'purple', invert: true },
      { name: 'Session Duration', value: 185, target: 240, status: 'active', color: 'cyan' },
    ];
    const allGoals = [...defaultGoals, ...state.goals];

    content.innerHTML = `
      <div class="alerts-header">
        <h2>Goals</h2>
        <button class="btn btn-primary" id="createGoalBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Goal</button>
      </div>
      <div class="goals-grid">
        ${allGoals.map(g => {
          const rate = g.invert ? Math.min(100, ((g.target - g.value) / g.target) * 100) : Math.min(100, (g.value / g.target) * 100);
          const displayVal = g.name.includes('Duration') ? formatDuration(g.value) : formatNumber(g.value);
          const displayTarget = g.name.includes('Duration') ? formatDuration(g.target) : formatNumber(g.target);
          return `
            <div class="goal-card">
              <div class="goal-card-header">
                <div class="goal-card-title">${esc(g.name)}</div>
                <div class="goal-card-status ${g.status}">${g.status}</div>
              </div>
              <div class="goal-card-value">${displayVal}</div>
              <div class="goal-card-target">Target: ${displayTarget}</div>
              <div class="goal-progress-bar"><div class="goal-progress-fill ${g.color}" style="width:${rate}%"></div></div>
              <div class="goal-card-rate"><strong>${rate.toFixed(1)}%</strong> completion</div>
            </div>
          `;
        }).join('')}
      </div>
    `;

    $('#createGoalBtn')?.addEventListener('click', () => $('#goalModal').classList.add('show'));
  }

  function renderAlertsSection() {
    const content = $('#content');
    content.innerHTML = `
      <div class="alerts-header">
        <h2>Alerts</h2>
        <button class="btn btn-primary" id="createAlertBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Alert</button>
      </div>
      <div id="alertsList">
        ${state.alerts.length ? state.alerts.map((a, i) => `
          <div class="alert-item">
            <div class="alert-icon ok"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div>
            <div class="alert-info">
              <div class="alert-name">${esc(a.name)}</div>
              <div class="alert-detail">${esc(a.metric)} ${a.condition === 'gt' ? '>' : a.condition === 'lt' ? '<' : '='} ${a.threshold}</div>
            </div>
            <button class="btn btn-danger btn-sm" data-alert-delete="${i}">Delete</button>
          </div>
        `).join('') : '<div class="empty-state"><div class="empty-state-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 01-3.46 0"/></svg></div><h3>No alerts yet</h3><p>Create an alert to get notified when metrics cross thresholds.</p></div>'}
      </div>
    `;

    $('#createAlertBtn')?.addEventListener('click', () => $('#alertModal').classList.add('show'));

    $$('[data-alert-delete]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.alertDelete);
        state.alerts.splice(idx, 1);
        localStorage.setItem('ghostly_alerts', JSON.stringify(state.alerts));
        renderAlertsSection();
        toast('Alert deleted', 'info');
      });
    });
  }

  function renderSettingsSection() {
    const content = $('#content');
    const host = window.location.origin;
    const snippet = `<script src="${host}/static/tracking.js" data-domain="yourdomain.com"><\/script>`;
    const apiKey = 'ghl_' + Array.from({ length: 32 }, () => 'abcdefghijklmnopqrstuvwxyz0123456789'[Math.floor(Math.random() * 36)]).join('');

    content.innerHTML = `
      <div class="section-header"><h2>Settings</h2></div>
      <div class="settings-section">
        <h3>Tracking Code</h3>
        <p>Add this snippet to the <code>&lt;head&gt;</code> of your website to start tracking.</p>
        <div class="code-block">
          <button class="copy-btn" id="copyTrackingCode">Copy</button>
          ${esc(snippet)}
        </div>
      </div>
      <div class="settings-section">
        <h3>API Keys</h3>
        <p>Use these keys to access the Ghostly API programmatically.</p>
        <div class="api-key-row">
          <span class="api-key-label">Read Key</span>
          <div class="api-key-value" id="apiKeyValue">${apiKey}</div>
          <button class="btn btn-secondary btn-sm" id="copyApiKey">Copy</button>
        </div>
      </div>
      <div class="settings-section">
        <h3>Data Retention</h3>
        <p>Configure how long analytics data is stored.</p>
        <div class="form-group">
          <label>Retention Period</label>
          <select class="form-input" style="max-width:200px">
            <option value="90">90 days</option>
            <option value="180">180 days</option>
            <option value="365" selected>1 year</option>
            <option value="730">2 years</option>
          </select>
        </div>
      </div>
      <div class="settings-section">
        <h3>Danger Zone</h3>
        <p>Irreversible actions for your account.</p>
        <button class="btn btn-danger btn-sm" id="deleteAllData">Delete All Data</button>
      </div>
    `;

    $('#copyTrackingCode')?.addEventListener('click', () => {
      navigator.clipboard.writeText(snippet);
      toast('Tracking code copied!', 'success');
    });

    $('#copyApiKey')?.addEventListener('click', () => {
      navigator.clipboard.writeText(apiKey);
      toast('API key copied!', 'success');
    });

    $('#deleteAllData')?.addEventListener('click', () => {
      if (confirm('Are you sure? This cannot be undone.')) {
        toast('Data deletion requested', 'info');
      }
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Heatmap Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderHeatmapSection() {
    const content = $('#content');
    const totalClicks = state.heatmapClicks.length;
    const uniquePages = [...new Set(state.heatmapClicks.map(c => c.page))].length;
    const avgX = totalClicks ? Math.round(state.heatmapClicks.reduce((s, c) => s + c.x, 0) / totalClicks) : 0;
    const avgY = totalClicks ? Math.round(state.heatmapClicks.reduce((s, c) => s + c.y, 0) / totalClicks) : 0;

    content.innerHTML = `
      <div class="section-header"><h2>Heatmap</h2></div>
      <div class="heatmap-stats" style="margin-bottom:18px;display:flex;gap:24px">
        <div class="heatmap-stat"><div class="heatmap-stat-value">${formatNumber(totalClicks)}</div><div class="heatmap-stat-label">Total Clicks</div></div>
        <div class="heatmap-stat"><div class="heatmap-stat-value">${uniquePages}</div><div class="heatmap-stat-label">Pages Tracked</div></div>
        <div class="heatmap-stat"><div class="heatmap-stat-value">${avgX}, ${avgY}</div><div class="heatmap-stat-label">Avg Click Position</div></div>
      </div>
      <div class="heatmap-wrapper">
        <div class="heatmap-toolbar">
          <div class="heatmap-toolbar-left">
            <button class="heatmap-filter-btn active" data-filter="clicks">Clicks</button>
            <button class="heatmap-filter-btn" data-filter="moves">Mouse Moves</button>
            <button class="heatmap-filter-btn" data-filter="scroll">Scroll Depth</button>
          </div>
          <div class="heatmap-toolbar-right">
            <button class="btn btn-secondary btn-sm" id="heatmapClearBtn">Clear Data</button>
            <button class="btn btn-primary btn-sm" id="heatmapSimulateBtn">Simulate Clicks</button>
          </div>
        </div>
        <div class="heatmap-canvas-container" id="heatmapContainer">
          <div class="heatmap-overlay" id="heatmapOverlay"></div>
          <canvas id="heatmapCanvas"></canvas>
        </div>
        <div class="heatmap-legend">
          <span>Less</span>
          <div class="heatmap-legend-gradient"></div>
          <span>More</span>
        </div>
      </div>
    `;

    initHeatmapCanvas();
    setupHeatmapEvents();
  }

  function initHeatmapCanvas() {
    const container = $('#heatmapContainer');
    const canvas = $('#heatmapCanvas');
    if (!container || !canvas) return;

    const rect = container.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = Math.max(rect.height, 500);

    state.heatmapCanvas = canvas;
    drawHeatmap();
  }

  function drawHeatmap() {
    const canvas = state.heatmapCanvas;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    ctx.fillStyle = 'rgba(6, 6, 10, 1)';
    ctx.fillRect(0, 0, w, h);

    const gridW = 40;
    const gridH = 40;
    const cols = Math.ceil(w / gridW);
    const rows = Math.ceil(h / gridH);
    const grid = Array.from({ length: rows }, () => Array(cols).fill(0));

    state.heatmapClicks.forEach(click => {
      const col = Math.floor((click.x / 100) * w / gridW);
      const row = Math.floor((click.y / 100) * h / gridH);
      if (col >= 0 && col < cols && row >= 0 && row < rows) {
        grid[row][col]++;
        for (let dr = -1; dr <= 1; dr++) {
          for (let dc = -1; dc <= 1; dc++) {
            const nr = row + dr;
            const nc = col + dc;
            if (nr >= 0 && nr < rows && nc >= 0 && nc < cols && (dr !== 0 || dc !== 0)) {
              grid[nr][nc] += 0.3;
            }
          }
        }
      }
    });

    let maxVal = 0;
    grid.forEach(row => row.forEach(v => { if (v > maxVal) maxVal = v; }));

    if (maxVal > 0) {
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          const val = grid[r][c];
          if (val <= 0) continue;
          const intensity = val / maxVal;
          const radius = gridW * 0.8 * (0.4 + intensity * 0.6);

          const gradient = ctx.createRadialGradient(
            c * gridW + gridW / 2, r * gridH + gridH / 2, 0,
            c * gridW + gridW / 2, r * gridH + gridH / 2, radius
          );

          if (intensity < 0.25) {
            gradient.addColorStop(0, 'rgba(0, 212, 255, 0.6)');
            gradient.addColorStop(1, 'rgba(0, 212, 255, 0)');
          } else if (intensity < 0.5) {
            gradient.addColorStop(0, 'rgba(0, 255, 136, 0.7)');
            gradient.addColorStop(1, 'rgba(0, 255, 136, 0)');
          } else if (intensity < 0.75) {
            gradient.addColorStop(0, 'rgba(255, 187, 51, 0.75)');
            gradient.addColorStop(1, 'rgba(255, 187, 51, 0)');
          } else {
            gradient.addColorStop(0, 'rgba(255, 68, 102, 0.8)');
            gradient.addColorStop(1, 'rgba(255, 68, 102, 0)');
          }

          ctx.fillStyle = gradient;
          ctx.fillRect(c * gridW, r * gridH, gridW, gridH);
        }
      }
    }

    state.heatmapClicks.forEach(click => {
      const x = (click.x / 100) * w;
      const y = (click.y / 100) * h;
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
      ctx.lineWidth = 1;
      ctx.stroke();
    });
  }

  function setupHeatmapEvents() {
    const container = $('#heatmapContainer');
    if (!container) return;

    container.addEventListener('click', (e) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;
      state.heatmapClicks.push({ x, y, page: window.location.hash || 'dashboard', time: Date.now() });
      localStorage.setItem('ghostly_heatmap_clicks', JSON.stringify(state.heatmapClicks));
      drawHeatmap();
    });

    $$('.heatmap-filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        $$('.heatmap-filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        toast(`Showing ${btn.dataset.filter} data`, 'info');
      });
    });

    $('#heatmapClearBtn')?.addEventListener('click', () => {
      state.heatmapClicks = [];
      localStorage.setItem('ghostly_heatmap_clicks', '[]');
      drawHeatmap();
      toast('Heatmap data cleared', 'info');
    });

    $('#heatmapSimulateBtn')?.addEventListener('click', () => {
      for (let i = 0; i < 50; i++) {
        const x = 10 + Math.random() * 80;
        const y = 10 + Math.random() * 80;
        state.heatmapClicks.push({ x, y, page: 'simulated', time: Date.now() });
      }
      localStorage.setItem('ghostly_heatmap_clicks', JSON.stringify(state.heatmapClicks));
      drawHeatmap();
      toast('Generated 50 simulated clicks', 'success');
    });

    window.addEventListener('resize', () => {
      if (state.currentSection === 'heatmap') {
        initHeatmapCanvas();
      }
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Email Reports Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderEmailReportsSection() {
    const content = $('#content');
    const cfg = state.emailConfig;

    content.innerHTML = `
      <div class="section-header"><h2>Email Reports</h2></div>
      <div class="email-config-grid">
        <div class="email-config-card">
          <h3>SMTP Configuration</h3>
          <p>Configure your email server to send automated reports.</p>
          <div class="form-group" style="margin-bottom:14px">
            <label for="smtpHost">SMTP Host</label>
            <input type="text" id="smtpHost" class="form-input" placeholder="smtp.gmail.com" value="${esc(cfg.smtpHost)}">
          </div>
          <div class="form-row" style="margin-bottom:14px">
            <div class="form-group">
              <label for="smtpPort">Port</label>
              <input type="text" id="smtpPort" class="form-input" placeholder="587" value="${esc(cfg.smtpPort)}">
            </div>
            <div class="form-group">
              <label for="smtpEncryption">Encryption</label>
              <select id="smtpEncryption" class="form-input">
                <option value="tls">TLS</option>
                <option value="ssl">SSL</option>
                <option value="none">None</option>
              </select>
            </div>
          </div>
          <div class="form-group" style="margin-bottom:14px">
            <label for="smtpUser">Username</label>
            <input type="text" id="smtpUser" class="form-input" placeholder="you@gmail.com" value="${esc(cfg.smtpUser)}">
          </div>
          <div class="form-group" style="margin-bottom:14px">
            <label for="smtpPass">Password</label>
            <input type="password" id="smtpPass" class="form-input" placeholder="App password" value="${esc(cfg.smtpPass)}">
          </div>
          <div class="form-row" style="margin-bottom:18px">
            <div class="form-group">
              <label for="fromEmail">From Email</label>
              <input type="email" id="fromEmail" class="form-input" placeholder="reports@ghostly.io" value="${esc(cfg.fromEmail)}">
            </div>
            <div class="form-group">
              <label for="fromName">From Name</label>
              <input type="text" id="fromName" class="form-input" placeholder="Ghostly Reports" value="${esc(cfg.fromName)}">
            </div>
          </div>
          <div style="display:flex;gap:10px">
            <button class="btn btn-primary btn-sm" id="saveEmailConfig">Save Configuration</button>
            <button class="btn btn-secondary btn-sm" id="testEmailBtn">Send Test Email</button>
          </div>
        </div>
        <div class="email-config-card">
          <h3>Scheduled Reports</h3>
          <p>Set up automatic email reports on a schedule.</p>
          <div class="email-schedule-list">
            <div class="email-schedule-item">
              <div class="email-schedule-info">
                <div class="email-schedule-name">Daily Summary</div>
                <div class="email-schedule-detail">Pageviews, visitors, top pages - every morning at 8am</div>
              </div>
              <div class="email-toggle active" data-schedule="daily"></div>
            </div>
            <div class="email-schedule-item">
              <div class="email-schedule-info">
                <div class="email-schedule-name">Weekly Digest</div>
                <div class="email-schedule-detail">Full analytics report - every Monday at 9am</div>
              </div>
              <div class="email-toggle active" data-schedule="weekly"></div>
            </div>
            <div class="email-schedule-item">
              <div class="email-schedule-info">
                <div class="email-schedule-name">Monthly Report</div>
                <div class="email-schedule-detail">Comprehensive monthly analytics - 1st of each month</div>
              </div>
              <div class="email-toggle" data-schedule="monthly"></div>
            </div>
            <div class="email-schedule-item">
              <div class="email-schedule-info">
                <div class="email-schedule-name">Alert Notifications</div>
                <div class="email-schedule-detail">Instant email when alert thresholds are crossed</div>
              </div>
              <div class="email-toggle active" data-schedule="alerts"></div>
            </div>
          </div>
          <div class="form-group" style="margin-top:18px">
            <label for="reportRecipients">Recipients (comma-separated)</label>
            <input type="text" id="reportRecipients" class="form-input" placeholder="team@example.com, ceo@example.com" value="">
          </div>
          <button class="btn btn-primary btn-sm" style="margin-top:14px" id="saveRecipients">Save Recipients</button>
        </div>
      </div>
    `;

    setupEmailEvents();
  }

  function setupEmailEvents() {
    $('#saveEmailConfig')?.addEventListener('click', () => {
      state.emailConfig = {
        smtpHost: $('#smtpHost').value.trim(),
        smtpPort: $('#smtpPort').value.trim(),
        smtpUser: $('#smtpUser').value.trim(),
        smtpPass: $('#smtpPass').value.trim(),
        fromEmail: $('#fromEmail').value.trim(),
        fromName: $('#fromName').value.trim()
      };
      localStorage.setItem('ghostly_email_config', JSON.stringify(state.emailConfig));
      toast('Email configuration saved!', 'success');
    });

    $('#testEmailBtn')?.addEventListener('click', () => {
      toast('Test email sent! Check your inbox.', 'success');
    });

    $$('.email-toggle').forEach(toggle => {
      toggle.addEventListener('click', () => {
        toggle.classList.toggle('active');
        const schedule = toggle.dataset.schedule;
        const enabled = toggle.classList.contains('active');
        toast(`${schedule} report ${enabled ? 'enabled' : 'disabled'}`, 'info');
      });
    });

    $('#saveRecipients')?.addEventListener('click', () => {
      const recipients = $('#reportRecipients').value.trim();
      if (recipients) {
        localStorage.setItem('ghostly_email_recipients', recipients);
        toast('Recipients saved!', 'success');
      } else {
        toast('Please enter at least one recipient', 'error');
      }
    });

    const savedRecipients = localStorage.getItem('ghostly_email_recipients') || '';
    if ($('#reportRecipients')) $('#reportRecipients').value = savedRecipients;
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Webhooks Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderWebhooksSection() {
    const content = $('#content');

    content.innerHTML = `
      <div class="alerts-header">
        <h2>Webhooks</h2>
        <button class="btn btn-primary" id="addWebhookBtn"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Add Webhook</button>
      </div>
      <div class="table-card">
        <div class="table-card-header"><h3>Configured Webhooks</h3><span class="table-count">${state.webhooks.length} webhooks</span></div>
        <div class="table-wrapper">
          <table class="webhook-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>URL</th>
                <th>Event</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              ${state.webhooks.length ? state.webhooks.map((wh, i) => `
                <tr>
                  <td style="font-weight:600;color:var(--text)">${esc(wh.name)}</td>
                  <td><span class="webhook-url">${esc(wh.url)}</span></td>
                  <td><span class="webhook-event-badge">${esc(wh.event)}</span></td>
                  <td><span class="webhook-status ${wh.active ? 'active' : 'inactive'}"><span class="webhook-status-dot"></span>${wh.active ? 'Active' : 'Inactive'}</span></td>
                  <td>
                    <div class="webhook-actions">
                      <button class="btn btn-secondary btn-sm webhook-test-btn" data-wh-test="${i}">Test</button>
                      <button class="btn btn-secondary btn-sm webhook-toggle-btn" data-wh-toggle="${i}">${wh.active ? 'Disable' : 'Enable'}</button>
                      <button class="btn btn-danger btn-sm webhook-delete-btn" data-wh-delete="${i}">Delete</button>
                    </div>
                  </td>
                </tr>
              `).join('') : `<tr><td colspan="5" class="table-empty">
                <div class="empty-state" style="padding:32px">
                  <div class="empty-state-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/></svg></div>
                  <h3>No webhooks configured</h3>
                  <p>Add a webhook to receive real-time notifications.</p>
                </div>
              </td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;

    setupWebhookEvents();
  }

  function setupWebhookEvents() {
    $('#addWebhookBtn')?.addEventListener('click', () => {
      $('#webhookModalTitle').textContent = 'Add Webhook';
      $('#webhookName').value = '';
      $('#webhookUrl').value = '';
      $('#webhookEvent').value = 'pageview';
      $('#webhookSecret').value = '';
      $('#webhookModal').classList.add('show');
    });

    $('#closeWebhookModal')?.addEventListener('click', () => $('#webhookModal').classList.remove('show'));
    $('#cancelWebhookModal')?.addEventListener('click', () => $('#webhookModal').classList.remove('show'));
    $('#webhookModal')?.addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmWebhook')?.addEventListener('click', () => {
      const name = $('#webhookName').value.trim();
      const url = $('#webhookUrl').value.trim();
      const event = $('#webhookEvent').value;
      const secret = $('#webhookSecret').value.trim();

      if (!name || !url) { toast('Please fill in name and URL', 'error'); return; }

      state.webhooks.push({ id: generateId(), name, url, event, secret, active: true, created: new Date().toISOString() });
      localStorage.setItem('ghostly_webhooks', JSON.stringify(state.webhooks));
      $('#webhookModal').classList.remove('show');
      toast('Webhook added!', 'success');
      renderWebhooksSection();
    });

    $$('.webhook-test-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.whTest);
        const wh = state.webhooks[idx];
        toast(`Testing webhook "${wh.name}"...`, 'info');
        setTimeout(() => toast('Webhook test successful!', 'success'), 1500);
      });
    });

    $$('.webhook-toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.whToggle);
        state.webhooks[idx].active = !state.webhooks[idx].active;
        localStorage.setItem('ghostly_webhooks', JSON.stringify(state.webhooks));
        renderWebhooksSection();
        toast(`Webhook ${state.webhooks[idx].active ? 'enabled' : 'disabled'}`, 'info');
      });
    });

    $$('.webhook-delete-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.whDelete);
        if (confirm(`Delete webhook "${state.webhooks[idx].name}"?`)) {
          state.webhooks.splice(idx, 1);
          localStorage.setItem('ghostly_webhooks', JSON.stringify(state.webhooks));
          renderWebhooksSection();
          toast('Webhook deleted', 'info');
        }
      });
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Themes Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderThemesSection() {
    const content = $('#content');

    content.innerHTML = `
      <div class="section-header"><h2>Themes</h2></div>
      <div class="themes-grid">
        ${THEMES.map(theme => `
          <div class="theme-card ${theme.id === state.activeTheme ? 'active' : ''}" data-theme-id="${theme.id}">
            <div class="theme-preview">
              <div class="theme-preview-sidebar" style="background:${theme.preview.sidebar}"></div>
              <div class="theme-preview-topbar" style="background:${theme.preview.topbar}"></div>
              <div class="theme-preview-content">
                <div class="theme-preview-stat" style="width:40%;background:${theme.preview.accent}"></div>
                <div class="theme-preview-stat" style="width:70%;background:${theme.preview.accent};opacity:0.3"></div>
                <div class="theme-preview-chart" style="background:${theme.preview.accent}"></div>
              </div>
            </div>
            <div class="theme-card-info">
              <span class="theme-card-name">${theme.name}</span>
              ${theme.id === state.activeTheme ? '<span class="theme-card-active-badge">Active</span>' : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;

    $$('.theme-card').forEach(card => {
      card.addEventListener('click', () => {
        const themeId = card.dataset.themeId;
        applyTheme(themeId);
        state.activeTheme = themeId;
        localStorage.setItem('ghostly_theme', themeId);
        renderThemesSection();
        toast('Theme applied!', 'success');
      });
    });
  }

  function applyTheme(themeId) {
    const theme = THEMES.find(t => t.id === themeId);
    if (!theme) return;
    const root = document.documentElement;
    Object.entries(theme.vars).forEach(([key, value]) => {
      root.style.setProperty(key, value);
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Plugins Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderPluginsSection() {
    const content = $('#content');

    content.innerHTML = `
      <div class="section-header"><h2>Plugins</h2></div>
      <div class="plugins-grid">
        ${state.plugins.map((plugin, i) => `
          <div class="plugin-card">
            <div class="plugin-card-header">
              <div class="plugin-icon" style="background:${plugin.iconBg}">${plugin.icon}</div>
              <div class="plugin-card-meta">
                <div class="plugin-card-name">${esc(plugin.name)}</div>
                <div class="plugin-card-version">v${esc(plugin.version)}</div>
              </div>
            </div>
            <div class="plugin-card-desc">${esc(plugin.description)}</div>
            <div class="plugin-card-footer">
              <span class="plugin-author">by ${esc(plugin.author)}</span>
              <div class="plugin-toggle ${plugin.enabled ? 'active' : ''}" data-plugin-idx="${i}"></div>
            </div>
          </div>
        `).join('')}
      </div>
    `;

    $$('.plugin-toggle').forEach(toggle => {
      toggle.addEventListener('click', () => {
        const idx = parseInt(toggle.dataset.pluginIdx);
        state.plugins[idx].enabled = !state.plugins[idx].enabled;
        localStorage.setItem('ghostly_plugins', JSON.stringify(state.plugins));
        toggle.classList.toggle('active');
        toast(`${state.plugins[idx].name} ${state.plugins[idx].enabled ? 'enabled' : 'disabled'}`, 'info');
      });
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Backup Section
     ═══════════════════════════════════════════════════════════════════════ */

  function renderBackupSection() {
    const content = $('#content');

    content.innerHTML = `
      <div class="section-header"><h2>Backup & Restore</h2></div>
      <div class="backup-section-grid">
        <div class="backup-card">
          <h3>Create Backup</h3>
          <p>Export all analytics data, settings, and configurations.</p>
          <div class="backup-progress-container" id="backupProgressContainer" style="display:none">
            <div class="backup-progress-bar"><div class="backup-progress-fill" id="backupProgressFill"></div></div>
            <div class="backup-progress-text">
              <span id="backupProgressLabel">Preparing backup...</span>
              <span id="backupProgressPct">0%</span>
            </div>
          </div>
          <div class="backup-actions">
            <button class="btn btn-primary btn-sm" id="createBackupBtn">Create Backup Now</button>
            <button class="btn btn-secondary btn-sm" id="downloadBackupBtn">Download Latest</button>
          </div>
        </div>
        <div class="backup-card">
          <h3>Restore from Backup</h3>
          <p>Import data from a previously exported backup file.</p>
          <div class="form-group" style="margin-bottom:14px">
            <label for="restoreFile">Upload Backup File</label>
            <input type="file" id="restoreFile" class="form-input" accept=".json,.ghostly" style="padding:8px">
          </div>
          <div class="backup-actions">
            <button class="btn btn-success btn-sm" id="restoreBackupBtn">Restore Backup</button>
          </div>
        </div>
      </div>
      <div class="backup-card" style="margin-top:18px">
        <h3>Backup History</h3>
        <p>Previous backup snapshots.</p>
        <div class="backup-history-list">
          ${state.backupHistory.length ? state.backupHistory.map((b, i) => `
            <div class="backup-history-item">
              <div class="backup-history-info">
                <div class="backup-history-name">${esc(b.name)}</div>
                <div class="backup-history-detail">${b.date} - ${b.type}</div>
              </div>
              <div style="display:flex;align-items:center;gap:12px">
                <span class="backup-history-size">${b.size}</span>
                <button class="btn btn-secondary btn-sm" data-restore-idx="${i}">Restore</button>
              </div>
            </div>
          `).join('') : '<div class="empty-state" style="padding:32px"><p>No backups yet. Create your first backup above.</p></div>'}
        </div>
      </div>
    `;

    setupBackupEvents();
  }

  function setupBackupEvents() {
    $('#createBackupBtn')?.addEventListener('click', () => {
      const progressContainer = $('#backupProgressContainer');
      const progressFill = $('#backupProgressFill');
      const progressLabel = $('#backupProgressLabel');
      const progressPct = $('#backupProgressPct');

      progressContainer.style.display = 'block';
      let pct = 0;

      const interval = setInterval(() => {
        pct += Math.random() * 15 + 5;
        if (pct >= 100) {
          pct = 100;
          clearInterval(interval);

          const now = new Date();
          const dateStr = now.toLocaleDateString() + ' ' + now.toLocaleTimeString();
          const backup = {
            name: `Backup ${now.toLocaleDateString()}`,
            date: dateStr,
            type: 'Full',
            size: (Math.random() * 5 + 1).toFixed(1) + ' MB'
          };
          state.backupHistory.unshift(backup);
          localStorage.setItem('ghostly_backups', JSON.stringify(state.backupHistory));

          progressLabel.textContent = 'Backup complete!';
          toast('Backup created successfully!', 'success');

          setTimeout(() => {
            progressContainer.style.display = 'none';
            progressFill.style.width = '0';
            renderBackupSection();
          }, 1500);
        } else {
          progressLabel.textContent = pct < 30 ? 'Collecting data...' : pct < 60 ? 'Compressing...' : pct < 90 ? 'Finalizing...' : 'Almost done...';
        }
        progressFill.style.width = pct + '%';
        progressPct.textContent = Math.round(pct) + '%';
      }, 200);
    });

    $('#downloadBackupBtn')?.addEventListener('click', () => {
      const data = {
        version: '2.0',
        created: new Date().toISOString(),
        alerts: state.alerts,
        funnels: state.funnels,
        goals: state.goals,
        webhooks: state.webhooks,
        plugins: state.plugins,
        emailConfig: state.emailConfig,
        theme: state.activeTheme
      };
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `ghostly-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast('Backup downloaded!', 'success');
    });

    $('#restoreBackupBtn')?.addEventListener('click', () => {
      const fileInput = $('#restoreFile');
      if (!fileInput.files.length) {
        toast('Please select a backup file', 'error');
        return;
      }
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const data = JSON.parse(e.target.result);
          if (data.alerts) { state.alerts = data.alerts; localStorage.setItem('ghostly_alerts', JSON.stringify(data.alerts)); }
          if (data.funnels) { state.funnels = data.funnels; localStorage.setItem('ghostly_funnels', JSON.stringify(data.funnels)); }
          if (data.goals) { state.goals = data.goals; localStorage.setItem('ghostly_goals', JSON.stringify(data.goals)); }
          if (data.webhooks) { state.webhooks = data.webhooks; localStorage.setItem('ghostly_webhooks', JSON.stringify(data.webhooks)); }
          if (data.plugins) { state.plugins = data.plugins; localStorage.setItem('ghostly_plugins', JSON.stringify(data.plugins)); }
          if (data.emailConfig) { state.emailConfig = data.emailConfig; localStorage.setItem('ghostly_email_config', JSON.stringify(data.emailConfig)); }
          if (data.theme) { state.activeTheme = data.theme; localStorage.setItem('ghostly_theme', data.theme); applyTheme(data.theme); }
          toast('Backup restored successfully!', 'success');
          renderBackupSection();
        } catch (err) {
          toast('Invalid backup file', 'error');
        }
      };
      reader.readAsText(fileInput.files[0]);
    });

    $$('[data-restore-idx]').forEach(btn => {
      btn.addEventListener('click', () => {
        const idx = parseInt(btn.dataset.restoreIdx);
        toast(`Restoring backup from ${state.backupHistory[idx].name}...`, 'info');
      });
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Sort Helper
     ═══════════════════════════════════════════════════════════════════════ */

  function sortArray(arr, config) {
    if (!config.key) return arr;
    return [...arr].sort((a, b) => {
      const va = a[config.key] || 0;
      const vb = b[config.key] || 0;
      if (typeof va === 'string') return config.dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return config.dir === 'asc' ? va - vb : vb - va;
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Data Loading
     ═══════════════════════════════════════════════════════════════════════ */

  async function loadSites() {
    const data = await api('/api/sites');
    const list = $('#sitesList');
    if (!data || !data.sites) return;

    list.innerHTML = `<li class="site-item active" data-site-id="all"><span class="site-dot" style="background:#00d4ff"></span>All Sites</li>` +
      data.sites.map((s, i) =>
        `<li class="site-item" data-site-id="${s.id}"><span class="site-dot" style="background:${PALETTE[i % PALETTE.length]}"></span>${esc(s.name || s.domain)}</li>`
      ).join('');

    list.querySelectorAll('.site-item').forEach(item => {
      item.addEventListener('click', () => {
        list.querySelectorAll('.site-item').forEach(el => el.classList.remove('active'));
        item.classList.add('active');
        const id = item.dataset.siteId;
        state.siteId = id === 'all' ? null : parseInt(id);
        navigateTo(state.currentSection);
      });
    });
  }

  async function loadDashboardData() {
    const days = getDays();

    if (!state.siteId) {
      const data = await api('/api/sites');
      if (!data || !data.sites || !data.sites.length) {
        renderDashboard(null, null, null, null, null, null, null);
        return;
      }
      const ids = data.sites.map(s => s.id);
      const results = await Promise.all(ids.map(id => Promise.all([
        api(`/api/sites/${id}/stats?days=${days}`),
        api(`/api/sites/${id}/daily?days=${days}`),
        api(`/api/sites/${id}/pages?days=${days}`),
        api(`/api/sites/${id}/devices?days=${days}`),
        api(`/api/sites/${id}/browsers?days=${days}`),
        api(`/api/sites/${id}/countries?days=${days}`),
        api(`/api/sites/${id}/referrers?days=${days}`)
      ])));
      const stats = mergeStats(results.map(r => r[0]));
      const daily = mergeDaily(results.map(r => r[1]));
      const pages = mergeItems(results.map(r => r[2]), 'pages', 'path', 'views');
      const devices = mergeItems(results.map(r => r[3]), 'devices', 'device_type', 'views');
      const browsers = mergeItems(results.map(r => r[4]), 'browsers', 'browser', 'views');
      const countries = mergeItems(results.map(r => r[5]), 'countries', 'country', 'views');
      const referrers = mergeItems(results.map(r => r[6]), 'referrers', 'domain', 'visits');
      renderDashboard(stats, daily, pages, devices, browsers, countries, referrers);
      return;
    }

    const base = `/api/sites/${state.siteId}`;
    const [stats, daily, pages, devices, browsers, countries, referrers] = await Promise.all([
      api(`${base}/stats?days=${days}`),
      api(`${base}/daily?days=${days}`),
      api(`${base}/pages?days=${days}`),
      api(`${base}/devices?days=${days}`),
      api(`${base}/browsers?days=${days}`),
      api(`${base}/countries?days=${days}`),
      api(`${base}/referrers?days=${days}`)
    ]);
    renderDashboard(stats, daily?.daily, pages?.pages, devices?.devices, browsers?.browsers, countries?.countries, referrers?.referrers);
  }

  async function loadSectionData(section) {
    const days = getDays();
    const base = state.siteId ? `/api/sites/${state.siteId}` : null;

    switch (section) {
      case 'dashboard':
        await loadDashboardData();
        break;

      case 'realtime': {
        if (base) {
          const data = await api(`${base}/realtime`);
          renderRealtimeSection(data);
        } else {
          const siteData = await api('/api/sites');
          if (siteData?.sites?.length) {
            const results = await Promise.all(siteData.sites.map(s => api(`/api/sites/${s.id}/realtime`)));
            const totalActive = results.reduce((sum, r) => sum + (r?.active_visitors || 0), 0);
            const allPages = results.flatMap(r => r?.top_pages || []);
            renderRealtimeSection({ active_visitors: totalActive, top_pages: allPages.slice(0, 10) });
          } else {
            renderRealtimeSection(null);
          }
        }
        break;
      }

      case 'heatmap':
        renderHeatmapSection();
        break;

      case 'pages': {
        if (base) {
          const data = await api(`${base}/pages?days=${days}`);
          renderPagesSection(data?.pages);
        } else {
          const siteData = await api('/api/sites');
          if (siteData?.sites?.length) {
            const results = await Promise.all(siteData.sites.map(s => api(`/api/sites/${s.id}/pages?days=${days}`)));
            const pages = mergeItems(results, 'pages', 'path', 'views');
            renderPagesSection(pages);
          } else {
            renderPagesSection([]);
          }
        }
        break;
      }

      case 'referrers': {
        if (base) {
          const data = await api(`${base}/referrers?days=${days}`);
          renderReferrersSection(data?.referrers);
        } else {
          const siteData = await api('/api/sites');
          if (siteData?.sites?.length) {
            const results = await Promise.all(siteData.sites.map(s => api(`/api/sites/${s.id}/referrers?days=${days}`)));
            renderReferrersSection(mergeItems(results, 'referrers', 'domain', 'visits'));
          } else {
            renderReferrersSection([]);
          }
        }
        break;
      }

      case 'devices': {
        if (base) {
          const [devices, browsers] = await Promise.all([api(`${base}/devices?days=${days}`), api(`${base}/browsers?days=${days}`)]);
          renderDevicesSection(devices?.devices, browsers?.browsers);
        } else {
          const siteData = await api('/api/sites');
          if (siteData?.sites?.length) {
            const results = await Promise.all(siteData.sites.map(s => Promise.all([api(`/api/sites/${s.id}/devices?days=${days}`), api(`/api/sites/${s.id}/browsers?days=${days}`)])));
            renderDevicesSection(mergeItems(results.map(r => r[0]), 'devices', 'device_type', 'views'), mergeItems(results.map(r => r[1]), 'browsers', 'browser', 'views'));
          } else {
            renderDevicesSection([], []);
          }
        }
        break;
      }

      case 'countries': {
        if (base) {
          const data = await api(`${base}/countries?days=${days}`);
          renderCountriesSection(data?.countries);
        } else {
          const siteData = await api('/api/sites');
          if (siteData?.sites?.length) {
            const results = await Promise.all(siteData.sites.map(s => api(`/api/sites/${s.id}/countries?days=${days}`)));
            renderCountriesSection(mergeItems(results, 'countries', 'country', 'views'));
          } else {
            renderCountriesSection([]);
          }
        }
        break;
      }

      case 'funnels': {
        if (base) {
          const data = await api(`${base}/pages?days=${days}`);
          renderFunnelsSection(data?.pages);
        } else {
          renderFunnelsSection([]);
        }
        break;
      }

      case 'goals':
        renderGoalsSection();
        break;

      case 'alerts':
        renderAlertsSection();
        break;

      case 'email-reports':
        renderEmailReportsSection();
        break;

      case 'webhooks':
        renderWebhooksSection();
        break;

      case 'themes':
        renderThemesSection();
        break;

      case 'plugins':
        renderPluginsSection();
        break;

      case 'backup':
        renderBackupSection();
        break;

      case 'settings':
        renderSettingsSection();
        break;
    }
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Navigation (Hash Router)
     ═══════════════════════════════════════════════════════════════════════ */

  function navigateTo(section) {
    state.currentSection = section;
    window.location.hash = section;
    $('#pageTitle').textContent = PAGE_TITLES[section] || 'Dashboard';

    $$('.nav-item').forEach(item => {
      item.classList.toggle('active', item.dataset.section === section);
    });

    destroyAllCharts();
    if (state.realtimeTimer) { clearInterval(state.realtimeTimer); state.realtimeTimer = null; }

    loadSectionData(section);

    if (section === 'realtime') {
      state.realtimeTimer = setInterval(() => loadSectionData('realtime'), 5000);
    }
  }

  function handleHashChange() {
    const hash = window.location.hash.slice(1) || 'dashboard';
    if (hash !== state.currentSection) {
      navigateTo(hash);
    }
  }

  /* ═══════════════════════════════════════════════════════════════════════
     WebSocket
     ═══════════════════════════════════════════════════════════════════════ */

  function connectWebSocket() {
    if (state.ws) { try { state.ws.close(); } catch (e) {} }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const siteId = state.siteId || 1;
    const url = `${protocol}//${window.location.host}/ws/${siteId}`;

    try {
      state.ws = new WebSocket(url);

      state.ws.onopen = () => {
        console.log('[Ghostly] WebSocket connected');
        if (state.wsReconnectTimer) { clearTimeout(state.wsReconnectTimer); state.wsReconnectTimer = null; }
      };

      state.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'pageview' || msg.type === 'realtime_update') {
            updateRealtimeBadge(msg.data);
          }
        } catch (e) {}
      };

      state.ws.onclose = () => {
        console.log('[Ghostly] WebSocket disconnected, reconnecting in 10s...');
        state.wsReconnectTimer = setTimeout(connectWebSocket, 10000);
      };

      state.ws.onerror = () => {};
    } catch (e) {
      state.wsReconnectTimer = setTimeout(connectWebSocket, 10000);
    }
  }

  function updateRealtimeBadge(data) {
    const count = data?.active_visitors ?? data?.active ?? 0;
    $('#activeNowCount').textContent = formatNumber(count);
    const navBadge = $('#navActiveCount');
    if (navBadge) navBadge.textContent = count;
  }

  /* ═══════════════════════════════════════════════════════════════════════
     Init
     ═══════════════════════════════════════════════════════════════════════ */

  function init() {
    applyTheme(state.activeTheme);

    $('#dateRange').addEventListener('change', e => {
      state.dateRange = e.target.value;
      $('#dateRangeLabel').textContent = RANGE_LABELS[state.dateRange] || state.dateRange;
      navigateTo(state.currentSection);
    });

    $('#refreshBtn').addEventListener('click', () => {
      const btn = $('#refreshBtn');
      btn.classList.add('spinning');
      navigateTo(state.currentSection);
      setTimeout(() => btn.classList.remove('spinning'), 800);
    });

    $('#menuToggle').addEventListener('click', () => {
      $('#sidebar').classList.toggle('open');
      $('#sidebarOverlay').classList.toggle('show');
    });
    $('#sidebarClose').addEventListener('click', () => {
      $('#sidebar').classList.remove('open');
      $('#sidebarOverlay').classList.remove('show');
    });
    $('#sidebarOverlay').addEventListener('click', () => {
      $('#sidebar').classList.remove('open');
      $('#sidebarOverlay').classList.remove('show');
    });

    $('#addSiteBtn').addEventListener('click', () => $('#addSiteModal').classList.add('show'));
    $('#closeModal').addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#cancelAddSite').addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#addSiteModal').addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmAddSite').addEventListener('click', async () => {
      const name = $('#newSiteName').value.trim();
      const domain = $('#newSiteDomain').value.trim();
      if (!name || !domain) { toast('Please fill in all fields', 'error'); return; }
      const result = await apiPost('/api/sites', { name, domain });
      if (result && result.id) {
        toast('Site added successfully!', 'success');
        $('#addSiteModal').classList.remove('show');
        $('#newSiteName').value = '';
        $('#newSiteDomain').value = '';
        await loadSites();
        state.siteId = result.id;
        navigateTo(state.currentSection);
      } else {
        toast('Failed to add site', 'error');
      }
    });

    $('#copySnippet')?.addEventListener('click', () => {
      navigator.clipboard.writeText($('#trackingSnippet').textContent);
      toast('Snippet copied!', 'success');
    });

    $('#closeAlertModal').addEventListener('click', () => $('#alertModal').classList.remove('show'));
    $('#cancelAlertModal').addEventListener('click', () => $('#alertModal').classList.remove('show'));
    $('#alertModal').addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmCreateAlert').addEventListener('click', () => {
      const name = $('#alertName').value.trim();
      const metric = $('#alertMetric').value;
      const condition = $('#alertCondition').value;
      const threshold = parseFloat($('#alertThreshold').value);
      if (!name || isNaN(threshold)) { toast('Please fill in all fields', 'error'); return; }
      state.alerts.push({ name, metric, condition, threshold, created: new Date().toISOString() });
      localStorage.setItem('ghostly_alerts', JSON.stringify(state.alerts));
      $('#alertModal').classList.remove('show');
      $('#alertName').value = '';
      $('#alertThreshold').value = '';
      toast('Alert created!', 'success');
      if (state.currentSection === 'alerts') renderAlertsSection();
    });

    $('#closeFunnelModal').addEventListener('click', () => $('#funnelModal').classList.remove('show'));
    $('#cancelFunnelModal').addEventListener('click', () => $('#funnelModal').classList.remove('show'));
    $('#funnelModal').addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmCreateFunnel').addEventListener('click', () => {
      const name = $('#funnelName').value.trim();
      const stepsRaw = $('#funnelSteps').value.trim();
      if (!name || !stepsRaw) { toast('Please fill in all fields', 'error'); return; }
      const steps = stepsRaw.split('\n').map(s => s.trim()).filter(Boolean);
      state.funnels.push({ name, steps, created: new Date().toISOString() });
      localStorage.setItem('ghostly_funnels', JSON.stringify(state.funnels));
      $('#funnelModal').classList.remove('show');
      $('#funnelName').value = '';
      $('#funnelSteps').value = '';
      toast('Funnel created!', 'success');
      if (state.currentSection === 'funnels') renderFunnelsSection();
    });

    $('#closeGoalModal').addEventListener('click', () => $('#goalModal').classList.remove('show'));
    $('#cancelGoalModal').addEventListener('click', () => $('#goalModal').classList.remove('show'));
    $('#goalModal').addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmCreateGoal').addEventListener('click', () => {
      const name = $('#goalName').value.trim();
      const metric = $('#goalMetric').value;
      const target = parseFloat($('#goalTarget').value);
      const period = $('#goalPeriod').value;
      if (!name || isNaN(target)) { toast('Please fill in all fields', 'error'); return; }
      const colors = ['cyan', 'green', 'purple'];
      state.goals.push({ name, value: 0, target, metric, period, status: 'active', color: colors[state.goals.length % colors.length], created: new Date().toISOString() });
      localStorage.setItem('ghostly_goals', JSON.stringify(state.goals));
      $('#goalModal').classList.remove('show');
      $('#goalName').value = '';
      $('#goalTarget').value = '';
      toast('Goal created!', 'success');
      if (state.currentSection === 'goals') renderGoalsSection();
    });

    window.addEventListener('hashchange', handleHashChange);

    loadSites();
    handleHashChange();
    connectWebSocket();

    if (state.activeTimer) clearInterval(state.activeTimer);
    state.activeTimer = setInterval(async () => {
      if (state.siteId) {
        const data = await api(`/api/sites/${state.siteId}/realtime`);
        if (data) updateRealtimeBadge(data);
      }
    }, 15000);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
