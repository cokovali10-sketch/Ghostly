/**
 * Ghostly Analytics - Lightweight Tracking Snippet (< 2KB minified)
 * Usage: <script src="http://localhost:8080/static/tracking.js" data-site-id="YOUR_SITE_ID" data-domain="example.com"></script>
 */
(function () {
  'use strict';

  var scriptEl = document.currentScript || (function () {
    var s = document.getElementsByTagName('script');
    return s[s.length - 1];
  })();

  var SITE_ID = scriptEl.getAttribute('data-site-id');
  var DOMAIN = scriptEl.getAttribute('data-domain') || '';
  if (!SITE_ID && !DOMAIN) return;

  var SERVER = (function () {
    return scriptEl.src.replace(/\/static\/tracking\.js.*$/, '');
  })();

  var pageLoadTime = Date.now();
  var maxScroll = 0;
  var sentPageview = false;

  function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2, 9);
  }

  function getVisitorId() {
    var key = 'ghostly_vid';
    var id;
    try { id = localStorage.getItem(key); } catch (e) {}
    if (!id) { id = generateId(); try { localStorage.setItem(key, id); } catch (e) {} }
    return id;
  }

  function getSessionId() {
    var key = 'ghostly_sid';
    var id;
    try { id = sessionStorage.getItem(key); } catch (e) {}
    if (!id) { id = generateId(); try { sessionStorage.setItem(key, id); } catch (e) {} }
    return id;
  }

  function parseUA(ua) {
    var browser = 'Other', os = 'Other';
    if (ua.indexOf('Firefox') > -1) browser = 'Firefox';
    else if (ua.indexOf('Edg') > -1) browser = 'Edge';
    else if (ua.indexOf('Chrome') > -1) browser = 'Chrome';
    else if (ua.indexOf('Safari') > -1) browser = 'Safari';
    else if (ua.indexOf('Opera') > -1 || ua.indexOf('OPR') > -1) browser = 'Opera';

    if (ua.indexOf('Windows') > -1) os = 'Windows';
    else if (ua.indexOf('Mac OS') > -1) os = 'MacOS';
    else if (ua.indexOf('Linux') > -1) os = 'Linux';
    else if (ua.indexOf('Android') > -1) os = 'Android';
    else if (ua.indexOf('iPhone') > -1 || ua.indexOf('iPad') > -1) os = 'iOS';

    return { browser: browser, os: os };
  }

  function getDeviceType() {
    var w = window.innerWidth || document.documentElement.clientWidth || 1024;
    if (w < 768) return 'mobile';
    if (w < 1024) return 'tablet';
    return 'desktop';
  }

  function getPageData() {
    var ua = navigator.userAgent;
    var parsed = parseUA(ua);
    return {
      domain: DOMAIN,
      site_id: SITE_ID,
      type: 'pageview',
      url: location.href,
      path: location.pathname + location.search,
      title: document.title || '',
      referrer: document.referrer || '',
      visitor_id: getVisitorId(),
      session_id: getSessionId(),
      language: navigator.language || '',
      screen_size: screen.width + 'x' + screen.height,
      browser: parsed.browser,
      os: parsed.os,
      device_type: getDeviceType(),
      country: ''
    };
  }

  function trackScroll() {
    var doc = document.documentElement;
    var scrollTop = window.pageYOffset || doc.scrollTop || 0;
    var scrollHeight = Math.max(
      doc.scrollHeight || 0, document.body.scrollHeight || 0, doc.offsetHeight || 0
    ) - doc.clientHeight;
    var pct = scrollHeight > 0 ? Math.round((scrollTop / scrollHeight) * 100) : 0;
    if (pct > maxScroll) maxScroll = pct;
  }

  function send(data) {
    var payload = JSON.stringify(data);

    if (navigator.sendBeacon) {
      var blob = new Blob([payload], { type: 'application/json' });
      if (navigator.sendBeacon(SERVER + '/api/track', blob)) return;
    }

    var xhr = new XMLHttpRequest();
    xhr.open('POST', SERVER + '/api/track', true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.send(payload);
  }

  function sendPageview() {
    if (sentPageview) return;
    sentPageview = true;
    send(getPageData());
  }

  function sendLeave() {
    var timeSpent = Math.round((Date.now() - pageLoadTime) / 1000);
    send({
      domain: DOMAIN,
      site_id: SITE_ID,
      type: 'pageview',
      url: location.href,
      path: location.pathname + location.search,
      title: document.title || '',
      referrer: document.referrer || '',
      visitor_id: getVisitorId(),
      session_id: getSessionId(),
      language: navigator.language || '',
      screen_size: screen.width + 'x' + screen.height,
      browser: parseUA(navigator.userAgent).browser,
      os: parseUA(navigator.userAgent).os,
      device_type: getDeviceType(),
      country: '',
      time_on_page: timeSpent,
      scroll_depth: maxScroll
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', sendPageview);
  } else {
    sendPageview();
  }

  var scrollTimer;
  window.addEventListener('scroll', function () {
    trackScroll();
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(trackScroll, 500);
  }, { passive: true });

  window.addEventListener('beforeunload', sendLeave);
  window.addEventListener('pagehide', sendLeave);

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      sendLeave();
    } else {
      pageLoadTime = Date.now();
      sentPageview = false;
    }
  });
})();
