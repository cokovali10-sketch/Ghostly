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
    funnels: 'Funnels', goals: 'Goals', alerts: 'Alerts', settings: 'Settings'
  };

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
    currentSection: 'dashboard',
    realtimeTimer: null,
    activeTimer: null
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
