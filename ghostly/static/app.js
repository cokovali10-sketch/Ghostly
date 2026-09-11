(() => {
  'use strict';

  const $ = s => document.querySelector(s);
  const $$ = s => document.querySelectorAll(s);

  const PALETTE = ['#00d4ff','#00ff88','#a855f7','#ffbb00','#ff4444','#ec4899','#06b6d4','#22d3ee','#34d399','#a78bfa'];
  const RANGE_TO_DAYS = { '24h': 1, '7d': 7, '30d': 30, '90d': 90 };
  const RANGE_LABELS = { '24h': 'Last 24 hours', '7d': 'Last 7 days', '30d': 'Last 30 days', '90d': 'Last 90 days' };

  let currentSiteId = null;
  let currentDateRange = '7d';
  let charts = {};
  let refreshTimer = null;

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

  async function api(path) {
    try {
      const res = await fetch(path);
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      console.error('API error:', path, e);
      return null;
    }
  }

  function getDays() {
    return RANGE_TO_DAYS[currentDateRange] || 7;
  }

  // ── Chart helpers ─────────────────────────────────────────────────────

  function destroyChart(name) {
    if (charts[name]) { charts[name].destroy(); charts[name] = null; }
  }

  function chartTooltip() {
    return {
      backgroundColor: 'rgba(17,17,19,.95)',
      titleColor: '#e4e4e7',
      bodyColor: '#a1a1aa',
      borderColor: 'rgba(255,255,255,.08)',
      borderWidth: 1,
      padding: 10,
      cornerRadius: 8,
      titleFont: { weight: '600' }
    };
  }

  function gridOpts() {
    return { color: 'rgba(255,255,255,.04)', drawBorder: false };
  }

  function renderViewsChart(daily) {
    destroyChart('views');
    const ctx = $('#viewsChart');
    if (!ctx || !daily || !daily.length) return;

    charts.views = new Chart(ctx, {
      type: 'line',
      data: {
        labels: daily.map(d => d.day),
        datasets: [{
          label: 'Views',
          data: daily.map(d => d.views),
          borderColor: '#00d4ff',
          backgroundColor: 'rgba(0,212,255,.12)',
          fill: true, tension: 0.4, borderWidth: 2,
          pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: '#00d4ff'
        }, {
          label: 'Visitors',
          data: daily.map(d => d.unique_visitors),
          borderColor: '#00ff88',
          backgroundColor: 'rgba(0,255,136,.12)',
          fill: true, tension: 0.4, borderWidth: 2,
          pointRadius: 0, pointHoverRadius: 5, pointHoverBackgroundColor: '#00ff88'
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true, position: 'top', align: 'end',
            labels: { color: '#71717a', usePointStyle: true, pointStyle: 'circle', padding: 16, font: { size: 12 } }
          },
          tooltip: chartTooltip()
        },
        scales: {
          x: { grid: gridOpts(), ticks: { color: '#52525b', font: { size: 11 }, maxTicksLimit: 10 } },
          y: { grid: gridOpts(), ticks: { color: '#52525b', font: { size: 11 } }, beginAtZero: true }
        }
      }
    });
  }

  function renderBarChart(canvasId, items, labelKey, valueKey, color) {
    destroyChart(canvasId);
    const ctx = $(`#${canvasId}`);
    if (!ctx || !items || !items.length) return;

    charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: items.map(i => i[labelKey] || 'Unknown'),
        datasets: [{
          data: items.map(i => i[valueKey]),
          backgroundColor: color || '#00d4ff',
          borderRadius: 4, barThickness: 20
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        indexAxis: 'y',
        plugins: { legend: { display: false }, tooltip: chartTooltip() },
        scales: {
          x: { grid: gridOpts(), ticks: { color: '#52525b', font: { size: 11 } }, beginAtZero: true },
          y: { grid: { display: false }, ticks: { color: '#a1a1aa', font: { size: 11 } } }
        }
      }
    });
  }

  function renderDoughnutChart(canvasId, items, labelKey, valueKey) {
    destroyChart(canvasId);
    const ctx = $(`#${canvasId}`);
    if (!ctx || !items || !items.length) return;

    charts[canvasId] = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: items.map(i => i[labelKey] || 'Unknown'),
        datasets: [{
          data: items.map(i => i[valueKey]),
          backgroundColor: PALETTE.slice(0, items.length),
          borderWidth: 0, hoverOffset: 6
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '65%',
        plugins: {
          legend: {
            display: true, position: 'bottom',
            labels: { color: '#71717a', usePointStyle: true, pointStyle: 'circle', padding: 12, font: { size: 11 } }
          },
          tooltip: chartTooltip()
        }
      }
    });
  }

  // ── Data loading ──────────────────────────────────────────────────────

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
        currentSiteId = id === 'all' ? null : parseInt(id);
        $('#siteName').textContent = item.textContent.trim();
        loadDashboard();
      });
    });
  }

  async function loadDashboard() {
    const days = getDays();

    if (!currentSiteId) {
      await loadAllSitesDashboard(days);
      return;
    }

    const base = `/api/sites/${currentSiteId}`;
    const [stats, daily, pages, devices, browsers, countries, referrers, realtime] = await Promise.all([
      api(`${base}/stats?days=${days}`),
      api(`${base}/daily?days=${days}`),
      api(`${base}/pages?days=${days}`),
      api(`${base}/devices?days=${days}`),
      api(`${base}/browsers?days=${days}`),
      api(`${base}/countries?days=${days}`),
      api(`${base}/referrers?days=${days}`),
      api(`${base}/realtime`)
    ]);

    updateStats(stats);
    renderViewsChart(daily?.daily);
    renderBarChart('pagesChart', pages?.pages?.slice(0, 8), 'path', 'views', '#00d4ff');
    renderDoughnutChart('devicesChart', devices?.devices, 'device_type', 'views');
    renderBarChart('countriesChart', countries?.countries?.slice(0, 8), 'country', 'views', '#00ff88');
    renderBarChart('referrersChart', referrers?.referrers?.slice(0, 8), 'domain', 'visits', '#a855f7');
    renderDoughnutChart('browsersChart', browsers?.browsers, 'browser', 'views');
    updateRealtime(realtime);
  }

  async function loadAllSitesDashboard(days) {
    const data = await api('/api/sites');
    if (!data || !data.sites || !data.sites.length) {
      updateStats(null);
      renderViewsChart(null);
      return;
    }

    const siteIds = data.sites.map(s => s.id);
    const allStats = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/stats?days=${days}`)));
    const allDaily = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/daily?days=${days}`)));
    const allPages = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/pages?days=${days}`)));
    const allDevices = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/devices?days=${days}`)));
    const allBrowsers = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/browsers?days=${days}`)));
    const allCountries = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/countries?days=${days}`)));
    const allReferrers = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/referrers?days=${days}`)));
    const allRealtime = await Promise.all(siteIds.map(id => api(`/api/sites/${id}/realtime`)));

    const stats = mergeStats(allStats);
    const daily = mergeDaily(allDaily);
    const pages = mergeTopItems(allPages, 'pages', 'path', 'views');
    const devices = mergeItems(allDevices, 'devices', 'device_type', 'views');
    const browsers = mergeItems(allBrowsers, 'browsers', 'browser', 'views');
    const countries = mergeItems(allCountries, 'countries', 'country', 'views');
    const referrers = mergeTopItems(allReferrers, 'referrers', 'domain', 'visits');
    const activeNow = allRealtime.reduce((sum, r) => sum + (r?.active_visitors || 0), 0);

    updateStats(stats);
    renderViewsChart(daily);
    renderBarChart('pagesChart', pages.slice(0, 8), 'path', 'views', '#00d4ff');
    renderDoughnutChart('devicesChart', devices, 'device_type', 'views');
    renderBarChart('countriesChart', countries.slice(0, 8), 'country', 'views', '#00ff88');
    renderBarChart('referrersChart', referrers.slice(0, 8), 'domain', 'visits', '#a855f7');
    renderDoughnutChart('browsersChart', browsers, 'browser', 'views');
    $('#activeNow').textContent = formatNumber(activeNow);
    $('#activeNowCount').textContent = formatNumber(activeNow);
  }

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

  function mergeTopItems(arr, key, groupBy, countKey) {
    return mergeItems(arr, key, groupBy, countKey);
  }

  function updateStats(data) {
    if (!data) {
      ['totalViews','uniqueVisitors','activeNow','avgTime'].forEach(id => $(`#${id}`).textContent = '--');
      return;
    }
    $('#totalViews').textContent = formatNumber(data.total_pageviews);
    $('#uniqueVisitors').textContent = formatNumber(data.unique_visitors);
    $('#avgTime').textContent = formatDuration(data.avg_session_seconds);
    $('#eventsToday').textContent = formatNumber(data.total_sessions);
  }

  function updateRealtime(realtime) {
    if (!realtime) return;
    const active = realtime.active_visitors || 0;
    $('#activeNow').textContent = formatNumber(active);
    $('#activeNowCount').textContent = formatNumber(active);
  }

  // ── Init ──────────────────────────────────────────────────────────────

  function init() {
    $('#dateRange').addEventListener('change', e => {
      currentDateRange = e.target.value;
      $('#dateRangeLabel').textContent = RANGE_LABELS[currentDateRange] || currentDateRange;
      loadDashboard();
    });

    $('#refreshBtn').addEventListener('click', () => {
      const btn = $('#refreshBtn');
      btn.classList.add('spinning');
      loadDashboard().finally(() => setTimeout(() => btn.classList.remove('spinning'), 600));
    });

    $('#menuToggle').addEventListener('click', () => $('#sidebar').classList.toggle('open'));

    $('#addSiteBtn').addEventListener('click', () => $('#addSiteModal').classList.add('show'));
    $('#closeModal').addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#cancelAddSite').addEventListener('click', () => $('#addSiteModal').classList.remove('show'));
    $('#addSiteModal').addEventListener('click', e => { if (e.target === e.currentTarget) e.target.classList.remove('show'); });

    $('#confirmAddSite').addEventListener('click', async () => {
      const name = $('#newSiteName').value.trim();
      const domain = $('#newSiteDomain').value.trim();
      if (!name || !domain) return;
      await fetch('/api/sites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, domain })
      });
      $('#addSiteModal').classList.remove('show');
      $('#newSiteName').value = '';
      $('#newSiteDomain').value = '';
      loadSites();
    });

    loadSites();
    loadDashboard();
    refreshTimer = setInterval(loadDashboard, 30000);
  }

  document.addEventListener('DOMContentLoaded', init);
})();
