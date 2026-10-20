// am-theme:start
// archi-magic time-of-day theme (see design/DESIGN-SYSTEM.md). Single source: copied between the
// am-theme markers into every page template by scripts/sync-design-tokens.ps1. Edit only here.
// Day (paper) 07:00-19:00 local time, night otherwise; re-checked every minute. A manual choice
// (window.amTheme.set('night'|'paper'|'auto')) holds until the next day/night boundary.
// Without JavaScript the page follows the OS light/dark setting through the CSS tokens.
(function () {
  var DAY_START = 7, NIGHT_START = 19, KEY = 'am-theme-override';
  var root = document.documentElement, current = null;
  function timeTheme(d) { var h = d.getHours(); return (h >= DAY_START && h < NIGHT_START) ? 'paper' : 'night'; }
  function nextBoundary(d) {
    var b = new Date(d); var h = d.getHours();
    if (h < DAY_START) b.setHours(DAY_START, 0, 0, 0);
    else if (h < NIGHT_START) b.setHours(NIGHT_START, 0, 0, 0);
    else { b.setDate(b.getDate() + 1); b.setHours(DAY_START, 0, 0, 0); }
    return b.getTime();
  }
  function readOverride() {
    try {
      var o = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (o && (o.theme === 'night' || o.theme === 'paper') && Date.now() < o.until) return o.theme;
      if (o) localStorage.removeItem(KEY);
    } catch (e) { /* storage blocked: time of day only */ }
    return null;
  }
  function show(theme) {   // the one place that changes the page theme, so every path sends the event
    if (theme === current) return;
    current = theme;
    root.classList.toggle('am-night', theme === 'night');
    root.classList.toggle('am-paper', theme === 'paper');
    root.setAttribute('data-am-theme', theme);
    try { document.dispatchEvent(new CustomEvent('am-theme-change', { detail: { theme: theme } })); } catch (e) { /* old browsers */ }
  }
  var pinned = null;   // manual choice kept in memory when storage is blocked
  function apply() {
    var now = new Date();
    if (pinned && Date.now() >= pinned.until) pinned = null;
    show((pinned && pinned.theme) || readOverride() || timeTheme(now));
  }
  window.amTheme = {
    get: function () { return current; },
    set: function (t) {
      try {
        if (t === 'auto') localStorage.removeItem(KEY);
        else localStorage.setItem(KEY, JSON.stringify({ theme: t, until: nextBoundary(new Date()) }));
      } catch (e) { /* storage blocked: keep the choice in memory for this page view */ }
      pinned = (t === 'auto') ? null : { theme: t, until: nextBoundary(new Date()) };
      apply();
    },
    toggle: function () { this.set(current === 'night' ? 'paper' : 'night'); },
    _timeTheme: timeTheme, _nextBoundary: nextBoundary
  };
  apply();
  setInterval(apply, 60000);
})();
// am-theme:end
