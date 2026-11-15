/* The optional guide: a free-floating, draggable character, a first-visit tutorial with a
   spotlight, and "?" tips. No voice, no video, no third-party library.

   He is a transparent cut-out (three poses, one picture each) in a fixed-position element above
   the page: no panel, no frame, only a drop-shadow. His speech bubble is a separate element that
   exists only while he speaks. If a picture fails to load, a small drawn drone takes his place.

   Everything here is optional. Any failure removes the guide and leaves the page exactly as
   it works without it; nothing is ever written to the console.

   Texts, the guide's name and the picture addresses come from config.js
   (GUIDE_NAME, GUIDE_IMAGES, GUIDE_STEPS, GUIDE_STEPS_GLOBE, GUIDE_TIPS). */
(function () {
  'use strict';

  var dead = false, made = [], listeners = [], cleanups = [];

  // remove every trace of the guide (the page keeps working)
  function teardown() {
    dead = true;
    try {
      made.forEach(function (el) { if (el && el.parentNode) el.parentNode.removeChild(el); });
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
      cleanups.forEach(function (fn) { fn(); });
      document.querySelectorAll('button.tip').forEach(function (b) { b.hidden = true; });
      document.body.classList.remove('guide-on', 'guide-touring');
    } catch (e) { /* nothing more to do */ }
  }

  // wrap a function so that an error (now or in a returned promise) switches the guide off quietly
  function safe(fn) {
    return function () {
      if (dead) return undefined;
      try {
        var r = fn.apply(this, arguments);
        if (r && typeof r.catch === 'function') r.catch(teardown);
        return r;
      } catch (e) { teardown(); return undefined; }
    };
  }

  function on(target, type, fn, opts) {
    var f = safe(fn);
    target.addEventListener(type, f, opts);
    listeners.push([target, type, f, opts]);
  }

  var KEY_ON = 'estd.guide.enabled';          // "on" | "off" (missing = on)
  var KEY_SEEN = 'estd.guide.tutorialSeen';   // set once the tutorial has been started
  var KEY_SEEN_GLOBE = 'estd.guide.globeTutorialSeen';   // the same, for the Globe-view tutorial
  var KEY_POS = 'estd.guide.pos';             // where he stands: {"x": 0..1, "y": 0..1} across the free area
  var KEY_TUCK = 'estd.guide.tucked';         // "yes" | "no" (missing = tucked only in a narrow window)

  var POSES = ['neutral', 'talking', 'pointing'];
  var OVER = 12;          // px he may stand past the window edge
  var MARGIN = 8;         // px kept free around the speech bubble
  var GAP = 12;           // px between him, his bubble and what he points at
  var NARROW = 700;       // windows this narrow start with only his head showing
  // what he keeps off while idle: the chart, the result card and the globe with its controls
  var AVOID = ['#chart', '#card', '#globePanel', '#viewToggle'];

  var SVG =
    '<svg class="guide-drone-svg" viewBox="0 0 96 96" aria-hidden="true" focusable="false">' +
    '<g class="guide-drone">' +
    '<ellipse class="guide-thrust" cx="48" cy="76" rx="9" ry="3.5"/>' +
    '<line class="guide-strut" x1="24" y1="48" x2="72" y2="48"/>' +
    '<g class="guide-wing"><rect x="4" y="38" width="20" height="20" rx="3"/><path d="M14 38v20M4 48h20"/></g>' +
    '<g class="guide-wing"><rect x="72" y="38" width="20" height="20" rx="3"/><path d="M82 38v20M72 48h20"/></g>' +
    '<line class="guide-mast" x1="48" y1="28" x2="48" y2="17"/>' +
    '<circle class="guide-beacon" cx="48" cy="13" r="4.5"/>' +
    '<rect class="guide-body" x="27" y="27" width="42" height="42" rx="11"/>' +
    '<rect class="guide-visor" x="33" y="36" width="30" height="17" rx="8.5"/>' +
    '<g class="guide-eyes"><circle cx="42" cy="44.5" r="3.2"/><circle cx="54" cy="44.5" r="3.2"/></g>' +
    '<path class="guide-smile" d="M43 60q5 4 10 0"/>' +
    '</g></svg>';

  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function vw() { return document.documentElement.clientWidth || window.innerWidth; }
  function vh() { return document.documentElement.clientHeight || window.innerHeight; }

  function init() {
    if (typeof GUIDE_NAME !== 'string' || !GUIDE_NAME) return;
    if (typeof GUIDE_STEPS === 'undefined' || !Array.isArray(GUIDE_STEPS) || !GUIDE_STEPS.length) return;
    if (typeof GUIDE_TIPS === 'undefined' || !GUIDE_TIPS || typeof GUIDE_TIPS !== 'object') return;
    var NAME = GUIDE_NAME, STEPS = GUIDE_STEPS, TIPS = GUIDE_TIPS;
    // two tutorials: STEPS is the one that is running (or ran last)
    var CLASSIC = GUIDE_STEPS;
    var GLOBE = typeof GUIDE_STEPS_GLOBE !== 'undefined' && Array.isArray(GUIDE_STEPS_GLOBE) ? GUIDE_STEPS_GLOBE : [];
    var GREETING = typeof GUIDE_GREETING === 'string' ? GUIDE_GREETING : "Hi, I'm {name}.";
    var IMAGES = typeof GUIDE_IMAGES === 'object' && GUIDE_IMAGES ? GUIDE_IMAGES : null;
    var haveArt = !!IMAGES && POSES.every(function (p) { return typeof IMAGES[p] === 'string' && IMAGES[p]; });
    var fill = function (s) { return String(s).split('{name}').join(NAME); };

    // localStorage may be unavailable (private mode, blocked): fall back to memory for this visit
    var mem = {};
    var store = {
      get: function (k) {
        try { var v = window.localStorage.getItem(k); if (v !== null) return v; } catch (e) { /* use memory */ }
        return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null;
      },
      set: function (k, v) { mem[k] = v; try { window.localStorage.setItem(k, v); } catch (e) { /* memory only */ } }
    };
    var reduced = function () {
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    };

    // ------------------------------------------------------------ elements
    var root = document.createElement('div');
    root.id = 'guide';
    root.className = 'guide';
    root.dataset.state = 'idle';                       // idle | talking | pointing
    root.dataset.art = haveArt ? 'fox' : 'drone';
    root.dataset.facing = 'right';                     // left: flipped, he points to his left
    root.dataset.edge = 'right';
    root.setAttribute('role', 'region');
    root.setAttribute('aria-label', NAME + ', the guide');
    // all three poses are in the page from the start (preloaded) and stacked; the state shows one
    var pictures = haveArt ? POSES.map(function (p) {
      return '<img class="guide-img" data-pose="' + p + '" src="' + IMAGES[p] + '" alt="" draggable="false">';
    }).join('') : '';
    root.innerHTML =
      '<div class="guide-bubble" id="guideBubble" hidden>' +
      '<p class="guide-name"></p>' +
      '<p class="guide-text" aria-hidden="true"><span class="guide-typed"></span><span class="guide-rest"></span></p>' +
      '<p class="guide-sr" role="status" aria-live="polite"></p>' +
      '<div class="guide-actions"><span class="guide-progress"></span>' +
      '<button type="button" data-act="skip">Skip</button>' +
      '<button type="button" data-act="back">Back</button>' +
      '<button type="button" data-act="next">Next</button>' +
      '<button type="button" data-act="close">Close</button></div></div>' +
      '<button type="button" class="guide-avatar" id="guideAvatar" aria-expanded="false" aria-controls="guideBubble">' +
      '<span class="guide-flip"><span class="guide-sway"><span class="guide-bobber">' + pictures + SVG +
      '</span></span></span></button>' +
      '<button type="button" class="guide-tuck" id="guideTuck"></button>';
    var spot = document.createElement('div');
    spot.id = 'guideSpot';
    spot.className = 'guide-spot';
    spot.hidden = true;
    made.push(root, spot);

    var q = function (sel) { return root.querySelector(sel); };
    var bubble = q('.guide-bubble'), avatar = q('.guide-avatar'), tuckBtn = q('.guide-tuck');
    var typed = q('.guide-typed'), rest = q('.guide-rest'), sr = q('.guide-sr'), progress = q('.guide-progress');
    var btn = { skip: q('[data-act="skip"]'), back: q('[data-act="back"]'), next: q('[data-act="next"]'), close: q('[data-act="close"]') };
    q('.guide-name').textContent = NAME;
    avatar.setAttribute('aria-label', NAME + ', your guide: show or hide the speech bubble. Arrow keys move him.');
    avatar.title = NAME;

    // header controls: "<name>: on/off" and "Replay with <name>"
    var controls = document.getElementById('guideControls');
    var toggleBtn = document.createElement('button'), replayBtn = document.createElement('button');
    toggleBtn.type = replayBtn.type = 'button';
    toggleBtn.id = 'guideToggle';
    replayBtn.id = 'guideReplay';
    replayBtn.textContent = 'Replay with ' + NAME;
    replayBtn.title = 'Run the short tutorial again';
    made.push(toggleBtn, replayBtn);

    // ------------------------------------------------------------ state
    var enabled = store.get(KEY_ON) !== 'off';
    var tour = -1;          // index of the tutorial step shown, -1 when the tutorial is not running
    var seq = 0;            // increases whenever what the guide shows changes (cancels stale waits)
    var current = null;     // () => rect of what the guide points at, or null
    var typing = null, finishTyping = null, returnFocus = null;
    var saved = readPos();  // where he stands when idle, as a share of the free area (survives resizes)
    var dragPos = null;     // {x, y} in pixels while he is being dragged
    var suppressClick = false;
    var tucked = (function () { var s = store.get(KEY_TUCK); return s === null ? vw() <= NARROW : s === 'yes'; })();

    function setState(s) { root.dataset.state = s; }
    function settle() { setState(current && current() ? 'pointing' : 'idle'); }

    function stopTyping() {
      if (typing) { window.clearInterval(typing); typing = null; }
      finishTyping = null;
    }

    // speech bubble text with a typewriter effect (instant with prefers-reduced-motion)
    function say(text) {
      stopTyping();
      sr.textContent = text;                           // screen readers get the whole sentence at once
      if (reduced()) { typed.textContent = text; rest.textContent = ''; settle(); return; }
      var i = 0;
      typed.textContent = '';
      rest.textContent = text;                         // invisible, keeps the bubble at its final size
      setState('talking');
      finishTyping = function () { stopTyping(); typed.textContent = text; rest.textContent = ''; settle(); };
      typing = window.setInterval(safe(function () {
        i += 2;
        if (i >= text.length) { finishTyping(); return; }
        typed.textContent = text.slice(0, i);
        rest.textContent = text.slice(i);
      }), 30);
    }

    // union of the boxes of the visible elements matching a selector, or null
    function rectOf(sel) {
      var els, r = null;
      try { els = document.querySelectorAll(sel); } catch (e) { return null; }
      Array.prototype.forEach.call(els, function (el) {
        var b = el.getBoundingClientRect();
        if (b.width < 1 || b.height < 1) return;
        r = r ? { left: Math.min(r.left, b.left), top: Math.min(r.top, b.top), right: Math.max(r.right, b.right), bottom: Math.max(r.bottom, b.bottom) }
              : { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
      });
      return r;
    }

    function spotlight(r) {
      if (!r) { spot.hidden = true; return; }
      var pad = 6;
      spot.style.left = (r.left - pad) + 'px';
      spot.style.top = (r.top - pad) + 'px';
      spot.style.width = (r.right - r.left + 2 * pad) + 'px';
      spot.style.height = (r.bottom - r.top + 2 * pad) + 'px';
      spot.hidden = false;
    }

    // ------------------------------------------------------------ where he stands
    function readPos() {
      try {
        var p = JSON.parse(store.get(KEY_POS));
        if (p && isFinite(p.x) && isFinite(p.y)) return { x: clamp(+p.x, 0, 1), y: clamp(+p.y, 0, 1) };
      } catch (e) { /* use the default */ }
      return { x: 1, y: 1 };                           // bottom-right, slightly over the edge
    }
    function savePos() {
      store.set(KEY_POS, JSON.stringify({ x: Math.round(saved.x * 10000) / 10000, y: Math.round(saved.y * 10000) / 10000 }));
    }
    function dims() { var b = avatar.getBoundingClientRect(); return { w: b.width, h: b.height }; }
    function toPx(f, d) {
      return { x: -OVER + f.x * Math.max(1, vw() - d.w + 2 * OVER), y: f.y * Math.max(1, vh() - d.h) };
    }
    function toFrac(x, y, d) {
      return { x: clamp((x + OVER) / Math.max(1, vw() - d.w + 2 * OVER), 0, 1), y: clamp(y / Math.max(1, vh() - d.h), 0, 1) };
    }

    function avoidRects() {
      var out = [];
      AVOID.forEach(function (sel) {
        var el = document.querySelector(sel);
        if (!el) return;
        var b = el.getBoundingClientRect();
        if (b.width > 1 && b.height > 1) out.push(b);
      });
      return out;
    }
    function overlapArea(x, y, w, h, rs) {
      var a = 0;
      rs.forEach(function (b) {
        var ox = Math.min(x + w, b.right) - Math.max(x, b.left), oy = Math.min(y + h, b.bottom) - Math.max(y, b.top);
        if (ox > 0 && oy > 0) a += ox * oy;
      });
      return a;
    }

    // idle: if where he stands would cover the chart, the result card or the globe, move him to the
    // nearest spot along a window edge that does not (the saved position itself is not changed)
    function nudge(p, d) {
      var rs = avoidRects();
      if (!overlapArea(p.x, p.y, d.w, d.h, rs)) return p;
      var W = vw(), H = vh(), best = null;
      function consider(x, y) {
        var score = overlapArea(x, y, d.w, d.h, rs) * 1000 + Math.hypot(x - p.x, y - p.y);
        if (!best || score < best.score) best = { x: x, y: y, score: score };
      }
      for (var y = 0; y <= H - d.h; y += 12) { consider(-OVER, y); consider(W - d.w + OVER, y); }
      for (var x = -OVER; x <= W - d.w + OVER; x += 12) { consider(x, 0); consider(x, H - d.h); }
      return best ? { x: best.x, y: best.y } : p;
    }

    // tutorial: next to the highlighted element, never on top of it. Tries the zones right of, left of,
    // below and above it; in each, him and his bubble side by side, then stacked. First one that fits wins.
    function planTour(r, d) {
      var W = vw(), H = vh(), bw = bubble.offsetWidth, bh = bubble.offsetHeight;
      var cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
      var zones = [
        { n: 'right', x0: r.right + GAP, y0: MARGIN, x1: W - MARGIN, y1: H - MARGIN },
        { n: 'left', x0: MARGIN, y0: MARGIN, x1: r.left - GAP, y1: H - MARGIN },
        { n: 'below', x0: MARGIN, y0: r.bottom + GAP, x1: W - MARGIN, y1: H - MARGIN },
        { n: 'above', x0: MARGIN, y0: MARGIN, x1: W - MARGIN, y1: r.top - GAP }
      ];
      function arrange(z, stack) {
        var gw = stack ? Math.max(d.w, bw) : d.w + GAP + bw, gh = stack ? d.h + GAP + bh : Math.max(d.h, bh);
        var gx, gy, foxLeft = z.n !== 'left';
        if (z.n === 'right') { gx = z.x0; gy = clamp(cy - gh / 2, z.y0, z.y1 - gh); }
        else if (z.n === 'left') { gx = z.x1 - gw; gy = clamp(cy - gh / 2, z.y0, z.y1 - gh); }
        else { gx = clamp(cx - gw / 2, z.x0, z.x1 - gw); gy = z.n === 'below' ? z.y0 : z.y1 - gh; }
        if (stack) {
          return { fox: { x: clamp(z.n === 'left' ? gx + gw - d.w : gx, -OVER, W - d.w + OVER), y: gy + bh + GAP }, bubble: { x: gx, y: gy } };
        }
        return { fox: { x: foxLeft ? gx : gx + gw - d.w, y: gy + gh - d.h }, bubble: { x: foxLeft ? gx + d.w + GAP : gx, y: gy } };
      }
      var best = null, bestArea = -1;
      for (var i = 0; i < zones.length; i++) {
        var z = zones[i], zw = z.x1 - z.x0, zh = z.y1 - z.y0;
        if (zw > 0 && zh > 0 && zw * zh > bestArea) { bestArea = zw * zh; best = z; }
        if (zw <= 0 || zh <= 0) continue;
        if (d.w + GAP + bw <= zw && Math.max(d.h, bh) <= zh) return arrange(z, false);
        if (Math.max(d.w, bw) <= zw && d.h + GAP + bh <= zh) return arrange(z, true);
      }
      // nothing fits (a very small window or a very large target): the roomiest zone, as close as it gets
      return best ? arrange(best, d.h + GAP + bh <= best.y1 - best.y0) : { fox: { x: W - d.w, y: H - d.h }, bubble: { x: MARGIN, y: MARGIN } };
    }

    // outside the tutorial: his bubble beside him, inside the window, not on top of him
    function beside(f, d) {
      var W = vw(), H = vh(), bw = bubble.offsetWidth, bh = bubble.offsetHeight, leftFirst = f.x + d.w / 2 > W / 2;
      var low = Math.min(f.y + d.h, H - MARGIN) - bh;   // bottoms aligned, but inside the window when he stands at its bottom
      var left = { x: f.x - GAP - bw, y: low }, right = { x: f.x + d.w + GAP, y: low };
      var cands = [leftFirst ? left : right, leftFirst ? right : left,
                   { x: f.x + d.w / 2 - bw / 2, y: f.y - GAP - bh }, { x: f.x + d.w / 2 - bw / 2, y: f.y + d.h + GAP }];
      for (var i = 0; i < cands.length; i++) {
        var c = cands[i];
        if (c.x >= MARGIN && c.y >= MARGIN && c.x + bw <= W - MARGIN && c.y + bh <= H - MARGIN) return c;
      }
      return cands[2];                                 // above him, clamped into the window by layout()
    }

    // put him, his bubble and the bubble's tail where they belong
    function layout() {
      if (root.hidden) return;
      var d = dims();
      if (!d.w || !d.h) return;
      var W = vw(), H = vh(), r = current ? current() : null, open = !bubble.hidden, fox, bub = null;
      if (tour >= 0 && open && r) {
        var plan = planTour(r, d);
        fox = plan.fox;
        bub = plan.bubble;
      } else {
        fox = dragPos || nudge(toPx(saved, d), d);
        if (open) bub = beside(fox, d);
      }
      fox = { x: clamp(fox.x, -OVER, W - d.w + OVER), y: clamp(fox.y, 0, H - d.h) };
      root.style.left = Math.round(fox.x) + 'px';
      root.style.top = Math.round(fox.y) + 'px';
      root.dataset.edge = fox.x + d.w / 2 > W / 2 ? 'right' : 'left';
      root.dataset.facing = r && (r.left + r.right) / 2 < fox.x + d.w / 2 ? 'left' : 'right';
      if (!bub) return;
      var bw = bubble.offsetWidth, bh = bubble.offsetHeight;
      bub = { x: clamp(bub.x, MARGIN, W - bw - MARGIN), y: clamp(bub.y, MARGIN, H - bh - MARGIN) };
      bubble.style.left = Math.round(bub.x) + 'px';
      bubble.style.top = Math.round(bub.y) + 'px';
      var tail = 'bottom', pos;                        // the side of the bubble that faces him
      if (fox.x >= bub.x + bw - 1) tail = 'right';
      else if (fox.x + d.w <= bub.x + 1) tail = 'left';
      else if (fox.y + d.h <= bub.y + 1) tail = 'top';
      pos = tail === 'left' || tail === 'right' ? fox.y + d.h * 0.3 - bub.y : fox.x + d.w / 2 - bub.x;
      bubble.dataset.tail = tail;
      bubble.style.setProperty('--tail', clamp(pos, 18, (tail === 'left' || tail === 'right' ? bh : bw) - 18).toFixed(0) + 'px');
    }

    function setTucked(yes, remember) {
      tucked = yes;
      root.dataset.tucked = String(yes);
      tuckBtn.textContent = yes ? '+' : '–';
      tuckBtn.setAttribute('aria-label', (yes ? 'Bring ' : 'Tuck ') + NAME + (yes ? ' back' : ' away'));
      tuckBtn.title = tuckBtn.getAttribute('aria-label');
      tuckBtn.setAttribute('aria-pressed', String(yes));
      if (remember) {
        store.set(KEY_TUCK, yes ? 'yes' : 'no');
        if (yes) { saved.x = saved.x >= 0.5 ? 1 : 0; savePos(); }   // only his head, at the nearest edge
      }
      layout();
    }

    // ------------------------------------------------------------ bubble
    // keep the target in view, near the top of the window (there is room for him below it)
    function bringIntoView(r) {
      if (!r) return;
      if (r.top >= 12 && r.bottom <= vh() - 12) return;
      window.scrollBy(0, r.top - 12);
    }

    // re-measure after scrolling, resizing or a new result
    function sync() {
      var r = current ? current() : null;
      spotlight(tour >= 0 ? r : null);
      layout();
      if (root.dataset.state !== 'talking') settle();
    }

    function show(el, yes) { el.hidden = !yes; }

    function openBubble() {
      root.hidden = false;
      bubble.hidden = false;
      avatar.setAttribute('aria-expanded', 'true');
      var touring = tour >= 0;
      show(btn.skip, touring);
      show(btn.back, touring && tour > 0);
      show(btn.next, touring);
      show(btn.close, !touring);
      btn.next.textContent = touring && stepFrom(tour + 1, 1) < 0 ? 'Finish' : 'Next';
      progress.textContent = touring ? 'Step ' + (tour + 1) + ' of ' + STEPS.length : '';
    }

    function closeBubble() {
      seq += 1;
      stopTyping();
      tour = -1;
      current = null;
      spotlight(null);
      bubble.hidden = true;
      document.body.classList.remove('guide-touring');
      avatar.setAttribute('aria-expanded', 'false');
      setState('idle');
      if (!enabled) root.hidden = true;
      layout();                                        // back to where he stands
      if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
      returnFocus = null;
      window.setTimeout(safe(maybeGlobeTour), 0);      // Globe view was opened meanwhile: its own first visit
    }

    // ------------------------------------------------------------ tutorial
    function resultShown() {
      var c = document.getElementById('card');
      return !!c && !c.classList.contains('hidden');
    }

    // a step that explains a result needs one: press the first demo button and wait for the card
    function ensureResult() {
      if (resultShown()) return Promise.resolve();
      var first = document.querySelector('#demos button');
      if (!first) return Promise.resolve();
      first.click();
      return new Promise(function (done) {
        var n = 0;
        var t = window.setInterval(function () {
          n += 1;
          if (resultShown() || n > 60 || dead) { window.clearInterval(t); done(); }
        }, 100);
      });
    }

    // ---- which tutorial: the page (web/globe/globe.js) says on <body> which view is shown and how the globe is doing
    function globeActive() {
      var b = document.body.dataset;
      return GLOBE.length > 0 && b.view === 'globe' && b.globe === 'ready';
    }
    function targetOf(step) { return rectOf(step.target) || (step.fallback ? rectOf(step.fallback) : null); }
    // the first step from i on (dir 1) or back (dir -1) whose element is in the page; -1 when there is none.
    // A step that will show a result first is taken as it is.
    function stepFrom(i, dir) {
      for (; i >= 0 && i < STEPS.length; i += dir) {
        if (STEPS[i].needsResult || targetOf(STEPS[i])) return i;
      }
      return -1;
    }
    // a step may ask the globe to do something first (turn so that the regions are in sight)
    function globeAction(step) {
      var g = window.EstdGlobe;
      if (!step.globeAction || !g || typeof g[step.globeAction] !== 'function') return false;
      try { g[step.globeAction](); } catch (e) { return false; }
      return true;
    }

    function showStep(i) {
      var step = STEPS[i], my = ++seq;
      tour = i;
      returnFocus = null;
      if (globeAction(step)) {                         // the globe has moved: measure again once it has
        [200, 700].forEach(function (ms) {
          window.setTimeout(safe(function () { if (my === seq) sync(); }), ms);
        });
      }
      current = function () {
        var r = rectOf(step.target);
        return r || (step.fallback ? rectOf(step.fallback) : null);
      };
      document.body.classList.add('guide-touring');    // room to scroll the last panel up next to him
      openBubble();
      say(fill(step.text));                            // first, so the bubble already has its final size
      bringIntoView(current());
      sync();
      btn.next.focus({ preventScroll: true });
      if (!step.needsResult || resultShown()) return undefined;
      return ensureResult().then(safe(function () {
        if (my !== seq) return;                        // the user has moved on meanwhile
        bringIntoView(current());
        sync();
      }));
    }

    function startTour() {
      if (globeActive()) return startGlobeTour();      // the tutorial of the view that is shown
      STEPS = CLASSIC;
      store.set(KEY_SEEN, '1');                        // first visit only: never starts by itself again
      return showStep(0);
    }

    function startGlobeTour() {
      STEPS = GLOBE;
      store.set(KEY_SEEN_GLOBE, '1');                  // its own first-visit flag
      var first = stepFrom(0, 1);
      return first < 0 ? undefined : showStep(first);
    }

    // Globe view opened for the first time (and the globe and its trend maps have settled): its tutorial.
    // Leaving Globe view while that tutorial runs ends it.
    function maybeGlobeTour() {
      var b = document.body.dataset;
      if (tour >= 0 && STEPS === GLOBE && b.view !== 'globe') return closeBubble();
      if (!enabled || tour >= 0 || !bubble.hidden || !globeActive()) return undefined;
      if (b.trend !== 'ready' && b.trend !== 'failed') return undefined;
      if (store.get(KEY_SEEN_GLOBE) !== null) return undefined;
      return startGlobeTour();
    }

    // ------------------------------------------------------------ tips and greeting
    function explain(key, from) {
      var tip = TIPS[key];
      if (!tip || !tip.text) return;
      if (!bubble.hidden) closeBubble();
      seq += 1;
      current = function () {
        var b = from.getBoundingClientRect();
        return b.width ? { left: b.left, top: b.top, right: b.right, bottom: b.bottom } : null;
      };
      openBubble();
      say(fill(tip.text));
      sync();
      returnFocus = from;
      btn.close.focus({ preventScroll: true });
    }

    function greet() {
      seq += 1;
      current = null;
      openBubble();
      say(fill(GREETING));
      sync();
    }

    function tipLabel(b) {
      var tip = TIPS[b.dataset.tip];
      b.setAttribute('aria-label', 'Ask ' + NAME + ' to explain' + (tip && tip.label ? ': ' + tip.label : ' this'));
      b.title = b.getAttribute('aria-label');
    }

    function setEnabled(yes) {
      enabled = yes;
      store.set(KEY_ON, yes ? 'on' : 'off');
      toggleBtn.textContent = NAME + (yes ? ': on' : ': off');
      toggleBtn.setAttribute('aria-pressed', String(yes));
      toggleBtn.title = yes ? 'Hide ' + NAME : 'Show ' + NAME;
      document.body.classList.toggle('guide-on', yes);
      if (yes) { root.hidden = false; layout(); } else closeBubble();
    }

    // ------------------------------------------------------------ dragging and keys
    var drag = null;
    on(avatar, 'pointerdown', function (e) {
      if (e.button > 0 || tour >= 0) return;           // not during the tutorial: he places himself
      var d = dims(), b = root.getBoundingClientRect();
      drag = { id: e.pointerId, sx: e.clientX, sy: e.clientY, ox: b.left, oy: b.top, d: d, moved: false };
      try { avatar.setPointerCapture(e.pointerId); } catch (err) { /* synthetic pointer: no capture */ }
    });
    on(avatar, 'pointermove', function (e) {
      if (!drag || e.pointerId !== drag.id) return;
      var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
      if (!drag.moved && Math.hypot(dx, dy) < 5) return;
      drag.moved = true;
      root.classList.add('guide-dragging');
      dragPos = { x: clamp(drag.ox + dx, -OVER, vw() - drag.d.w + OVER), y: clamp(drag.oy + dy, 0, vh() - drag.d.h) };
      layout();
    });
    function endDrag(e) {
      if (!drag || e.pointerId !== drag.id) return;
      var moved = drag.moved, d = drag.d;
      drag = null;
      root.classList.remove('guide-dragging');
      if (!moved) return;
      suppressClick = true;                            // the click that follows a drag is not a click
      window.setTimeout(function () { suppressClick = false; }, 0);
      saved = toFrac(dragPos.x, dragPos.y, d);
      savePos();
      dragPos = null;
      layout();
    }
    on(avatar, 'pointerup', endDrag);
    on(avatar, 'pointercancel', endDrag);

    // keyboard: arrow keys move him while he has the focus (Shift: bigger steps)
    on(avatar, 'keydown', function (e) {
      var step = e.shiftKey ? 48 : 16, dx = 0, dy = 0;
      if (e.key === 'ArrowLeft') dx = -step; else if (e.key === 'ArrowRight') dx = step;
      else if (e.key === 'ArrowUp') dy = -step; else if (e.key === 'ArrowDown') dy = step;
      else return;
      e.preventDefault();
      if (tour >= 0) return;
      var d = dims(), p = toPx(saved, d);
      saved = toFrac(p.x + dx, p.y + dy, d);
      savePos();
      layout();
    });

    // ------------------------------------------------------------ wiring
    on(btn.next, 'click', function () { var n = stepFrom(tour + 1, 1); return n < 0 ? closeBubble() : showStep(n); });
    on(btn.back, 'click', function () { var n = stepFrom(tour - 1, -1); return n < 0 ? undefined : showStep(n); });
    on(btn.skip, 'click', closeBubble);
    on(btn.close, 'click', closeBubble);
    on(q('.guide-text'), 'click', function () { if (finishTyping) finishTyping(); });
    on(avatar, 'click', function () {
      if (suppressClick) return;
      if (bubble.hidden) greet(); else closeBubble();
    });
    on(tuckBtn, 'click', function () { setTucked(!tucked, true); });
    on(toggleBtn, 'click', function () { setEnabled(!enabled); });
    on(replayBtn, 'click', function () { setEnabled(true); return startTour(); });
    on(document, 'keydown', function (e) { if (e.key === 'Escape' && !bubble.hidden) closeBubble(); });
    on(document, 'click', function (e) {
      var b = e.target && e.target.closest ? e.target.closest('button.tip') : null;
      if (b) { tipLabel(b); explain(b.dataset.tip, b); }
    });
    on(document, 'focusin', function (e) {
      if (e.target && e.target.matches && e.target.matches('button.tip')) tipLabel(e.target);
    });
    on(window, 'scroll', sync, { passive: true });
    on(window, 'resize', function () {
      // a window that has not been tucked by hand tucks him when it is narrow and brings him back when it is wide
      if (store.get(KEY_TUCK) === null && (vw() <= NARROW) !== tucked) setTucked(vw() <= NARROW, false);
      sync();
    });
    on(window, 'load', sync);
    // a picture that cannot be loaded: the drawn drone takes his place
    Array.prototype.forEach.call(root.querySelectorAll('.guide-img'), function (img) {
      on(img, 'error', function () { root.dataset.art = 'drone'; sync(); });
    });
    // the result card and the globe appear and disappear: keep off them
    if (window.MutationObserver) {
      var watcher = new MutationObserver(safe(sync));
      ['card', 'globePanel'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) watcher.observe(el, { attributes: true, attributeFilter: ['class', 'hidden'] });
      });
      // the view switch and the globe's progress, written on <body> by the page
      var views = new MutationObserver(safe(maybeGlobeTour));
      views.observe(document.body, { attributes: true, attributeFilter: ['data-view', 'data-globe', 'data-trend'] });
      cleanups.push(function () { watcher.disconnect(); views.disconnect(); });
    }

    document.body.appendChild(spot);
    document.body.appendChild(root);
    if (controls) { controls.appendChild(toggleBtn); controls.appendChild(replayBtn); }
    Array.prototype.forEach.call(document.querySelectorAll('button.tip'), function (b) { tipLabel(b); b.hidden = false; });
    setTucked(tucked, false);
    setEnabled(enabled);
    // flying (animated moves) only starts once he stands in his first place
    window.setTimeout(safe(function () { root.classList.add('guide-fly'); }), 80);

    if (enabled && store.get(KEY_SEEN) === null) return startTour();   // first visit
    return undefined;
  }

  safe(init)();
})();
