/* The optional guide: a small animated helper in a corner, a first-visit tutorial with a
   spotlight, and "?" tips. No voice, no video, no third-party library.

   Everything here is optional. Any failure removes the guide and leaves the page exactly as
   it works without it; nothing is ever written to the console.

   Texts and the guide's name come from config.js (GUIDE_NAME, GUIDE_STEPS, GUIDE_TIPS). */
(function () {
  'use strict';

  var dead = false, made = [], listeners = [];

  // remove every trace of the guide (the page keeps working)
  function teardown() {
    dead = true;
    try {
      made.forEach(function (el) { if (el && el.parentNode) el.parentNode.removeChild(el); });
      listeners.forEach(function (l) { l[0].removeEventListener(l[1], l[2], l[3]); });
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

  var SVG =
    '<svg class="guide-svg" viewBox="0 0 96 96" aria-hidden="true" focusable="false">' +
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

  function init() {
    if (typeof GUIDE_NAME !== 'string' || !GUIDE_NAME) return;
    if (typeof GUIDE_STEPS === 'undefined' || !Array.isArray(GUIDE_STEPS) || !GUIDE_STEPS.length) return;
    if (typeof GUIDE_TIPS === 'undefined' || !GUIDE_TIPS || typeof GUIDE_TIPS !== 'object') return;
    var NAME = GUIDE_NAME, STEPS = GUIDE_STEPS, TIPS = GUIDE_TIPS;
    var GREETING = typeof GUIDE_GREETING === 'string' ? GUIDE_GREETING : "Hi, I'm {name}.";
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
    root.setAttribute('role', 'region');
    root.setAttribute('aria-label', NAME + ', the guide');
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
      '<button type="button" class="guide-avatar" id="guideAvatar" aria-expanded="false" aria-controls="guideBubble">' + SVG + '</button>';
    var spot = document.createElement('div');
    spot.id = 'guideSpot';
    spot.className = 'guide-spot';
    spot.hidden = true;
    made.push(root, spot);

    var q = function (sel) { return root.querySelector(sel); };
    var bubble = q('.guide-bubble'), avatar = q('.guide-avatar');
    var typed = q('.guide-typed'), rest = q('.guide-rest'), sr = q('.guide-sr'), progress = q('.guide-progress');
    var btn = { skip: q('[data-act="skip"]'), back: q('[data-act="back"]'), next: q('[data-act="next"]'), close: q('[data-act="close"]') };
    q('.guide-name').textContent = NAME;
    avatar.setAttribute('aria-label', NAME + ', your guide: show or hide the speech bubble');
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

    // height the panel needs at the bottom of the window (bubble, margins)
    function room() { return root.offsetHeight + 24; }

    // keep off the target (move to the top corner when the target reaches into the bottom corner
    // and there is more free space above it) and turn toward the target
    function place(r) {
      var h = window.innerHeight;
      root.classList.toggle('guide--top', !!r && r.bottom > h - room() && r.top > h - r.bottom);
      if (!r) {
        root.style.setProperty('--guide-tilt', '0deg');
        root.style.setProperty('--guide-look-x', '0px');
        root.style.setProperty('--guide-look-y', '0px');
        return;
      }
      var a = avatar.getBoundingClientRect();
      var dx = (r.left + r.right) / 2 - (a.left + a.width / 2), dy = (r.top + r.bottom) / 2 - (a.top + a.height / 2);
      var len = Math.sqrt(dx * dx + dy * dy) || 1;
      root.style.setProperty('--guide-tilt', (16 * dx / len).toFixed(1) + 'deg');
      root.style.setProperty('--guide-look-x', (3 * dx / len).toFixed(1) + 'px');
      root.style.setProperty('--guide-look-y', (3 * dy / len).toFixed(1) + 'px');
    }

    // re-measure after scrolling, resizing or a new result
    function sync() {
      var r = current ? current() : null;
      spotlight(tour >= 0 ? r : null);
      place(r);
      if (root.dataset.state !== 'talking') settle();
    }

    // scroll the target into the part of the window that the panel does not use
    function bringIntoView(r) {
      if (!r) return;
      root.classList.remove('guide--top');             // measure against the panel's home corner
      var free = window.innerHeight - room() - 12, height = r.bottom - r.top;
      if (r.top >= 12 && r.bottom <= free) return;
      window.scrollBy(0, r.top - (height <= free - 12 ? 12 + (free - 12 - height) / 2 : 12));
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
      btn.next.textContent = touring && tour === STEPS.length - 1 ? 'Finish' : 'Next';
      progress.textContent = touring ? 'Step ' + (tour + 1) + ' of ' + STEPS.length : '';
    }

    function closeBubble() {
      seq += 1;
      stopTyping();
      tour = -1;
      current = null;
      spotlight(null);
      place(null);
      bubble.hidden = true;
      document.body.classList.remove('guide-touring');
      avatar.setAttribute('aria-expanded', 'false');
      setState('idle');
      if (!enabled) root.hidden = true;
      if (returnFocus && document.contains(returnFocus)) returnFocus.focus();
      returnFocus = null;
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

    function showStep(i) {
      var step = STEPS[i], my = ++seq;
      tour = i;
      returnFocus = null;
      current = function () {
        var r = rectOf(step.target);
        return r || (step.fallback ? rectOf(step.fallback) : null);
      };
      document.body.classList.add('guide-touring');    // room to scroll the last panel clear of the bubble
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
      store.set(KEY_SEEN, '1');                        // first visit only: never starts by itself again
      return showStep(0);
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
      sync();
      say(fill(tip.text));
      returnFocus = from;
      btn.close.focus({ preventScroll: true });
    }

    function greet() {
      seq += 1;
      current = null;
      openBubble();
      sync();
      say(fill(GREETING));
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
      if (yes) root.hidden = false; else closeBubble();
    }

    // ------------------------------------------------------------ wiring
    on(btn.next, 'click', function () { return tour >= STEPS.length - 1 ? closeBubble() : showStep(tour + 1); });
    on(btn.back, 'click', function () { return tour > 0 ? showStep(tour - 1) : undefined; });
    on(btn.skip, 'click', closeBubble);
    on(btn.close, 'click', closeBubble);
    on(q('.guide-text'), 'click', function () { if (finishTyping) finishTyping(); });
    on(avatar, 'click', function () { if (bubble.hidden) greet(); else closeBubble(); });
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
    on(window, 'resize', sync);

    document.body.appendChild(spot);
    document.body.appendChild(root);
    if (controls) { controls.appendChild(toggleBtn); controls.appendChild(replayBtn); }
    Array.prototype.forEach.call(document.querySelectorAll('button.tip'), function (b) { tipLabel(b); b.hidden = false; });
    setEnabled(enabled);
    place(null);

    if (enabled && store.get(KEY_SEEN) === null) return startTour();   // first visit
    return undefined;
  }

  safe(init)();
})();
