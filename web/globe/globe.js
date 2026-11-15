/* Optional 3D globe view (Step A spike).
 *
 * Loaded after the page's own script. It adds a "Globe / Classic view" switch to the header and a
 * globe panel above the page. Classic view (the page as it always was) is the default; Cesium is
 * only downloaded when Globe is chosen. If anything here fails, the page stays in Classic view and
 * a short note says so. Nothing is written to the console.
 *
 * Region boxes come from GET /presets (presets.yml), never from this file. Clicking a box clicks
 * that preset's Demo button, so the globe runs exactly the same code as the button.
 *
 * Cesium: vendored at /vendor/cesium/ (frontend/vendor/cesium). Token: window.CESIUM_ION_TOKEN from
 * /frontend/config.local.js (git-ignored; the server sends an empty token when the file is absent).
 */
(function () {
  'use strict';

  var CESIUM_BASE = '/vendor/cesium/';
  var CONFIG_URL = '/frontend/config.local.js';
  var TERRAIN_TIMEOUT_MS = 8000;      // slow wifi: give up on terrain after this and go offline
  var TERRAIN_ERRORS_MAX = 20;        // terrain tiles failing after start (wifi dropped) -> offline
  var BOX_HEIGHT = 6000;              // metres; boxes float just above the highest terrain in them
  var SPIN_RAD_PER_S = 0.03;          // slow idle rotation
  var OFFLINE_NOTE = 'Globe running in offline mode, no terrain';
  var FAILED_NOTE = 'The globe could not start here (offline mode); showing Classic view.';
  var CYAN = '#4fd8ff';

  // public state, read by tests/browser/globe.html (and handy in the browser's dev tools)
  var state = window.EstdGlobe = {
    view: 'classic', status: 'idle', mode: null, note: '', regions: [],
    chooseMode: chooseMode, selectPreset: null
  };

  function $(id) { return document.getElementById(id); }
  function reduced() {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; }
  }

  // 'terrain' only with a non-empty token and a network; everything else is 'offline'
  function chooseMode(token, online) {
    return (typeof token === 'string' && token.trim() !== '' && online !== false) ? 'terrain' : 'offline';
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('could not load ' + src)); };
      document.head.appendChild(s);
    });
  }

  function loadCss(href) {
    var l = document.createElement('link');
    l.rel = 'stylesheet';
    l.href = href;
    document.head.appendChild(l);
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () { reject(new Error('timeout')); }, ms);
      promise.then(function (v) { clearTimeout(t); resolve(v); },
                   function (e) { clearTimeout(t); reject(e); });
    });
  }

  function getJson(path) {
    return fetch(path).then(function (r) {
      if (!r.ok) throw new Error(path + ': ' + r.status);
      return r.json();
    });
  }

  function hasWebGL() {
    try {
      var c = document.createElement('canvas');
      return !!(window.WebGLRenderingContext && (c.getContext('webgl2') || c.getContext('webgl')));
    } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ page furniture

  var ui = {};

  function build() {
    var header = document.querySelector('header'), main = document.querySelector('main');
    if (!header || !main) return false;

    var bar = document.createElement('div');
    bar.id = 'viewToggle';
    bar.setAttribute('role', 'group');
    bar.setAttribute('aria-label', 'View');
    bar.innerHTML =
      '<button type="button" data-view="globe" aria-pressed="false">Globe</button>' +
      '<button type="button" data-view="classic" aria-pressed="true">Classic view</button>';
    var controls = $('guideControls');
    header.insertBefore(bar, controls ? controls.nextSibling : header.firstChild);

    var note = document.createElement('p');
    note.id = 'viewNote';
    note.hidden = true;
    header.appendChild(note);

    var panel = document.createElement('section');
    panel.id = 'globePanel';
    panel.className = 'panel globe-panel';
    panel.hidden = true;
    panel.innerHTML =
      '<div class="globe-stage">' +
        '<div id="globeBox"></div>' +
        '<div id="globeTip" role="tooltip" hidden></div>' +
        '<p id="globeStatus">Loading the globe&hellip;</p>' +
      '</div>' +
      '<p class="globe-foot"><span>Click a highlighted region to load its trend below.</span>' +
      ' <span id="globeNote" hidden></span></p>';
    main.insertBefore(panel, main.firstChild);

    ui = {bar: bar, note: note, panel: panel, box: $('globeBox'), tip: $('globeTip'),
          status: $('globeStatus'), globeNote: $('globeNote'),
          globeBtn: bar.querySelector('[data-view="globe"]')};
    bar.addEventListener('click', function (ev) {
      var b = ev.target.closest && ev.target.closest('button[data-view]');
      if (b && !b.disabled) setView(b.dataset.view);
    });
    return true;
  }

  function setView(view) {
    state.view = view;
    ui.panel.hidden = view !== 'globe';
    [].forEach.call(ui.bar.querySelectorAll('button[data-view]'), function (b) {
      b.setAttribute('aria-pressed', String(b.dataset.view === view));
    });
    if (globe.viewer) {
      globe.viewer.useDefaultRenderLoop = view === 'globe';
      if (view === 'globe') globe.viewer.resize();
    }
    if (view === 'globe') start().catch(fail);
  }

  function showOfflineNote() {
    state.note = OFFLINE_NOTE;
    ui.globeNote.textContent = OFFLINE_NOTE;
    ui.globeNote.hidden = false;
  }

  // the globe cannot run at all: back to Classic view, for good, with a note in the header
  function fail() {
    state.status = 'failed';
    state.mode = 'offline';
    state.note = FAILED_NOTE;
    ui.note.textContent = FAILED_NOTE;
    ui.note.hidden = false;
    ui.globeBtn.disabled = true;
    ui.globeBtn.title = FAILED_NOTE;
    if (globe.viewer) { try { globe.viewer.destroy(); } catch (e) { /* already gone */ } globe.viewer = state.viewer = null; }
    setView('classic');
  }

  // ------------------------------------------------------------------ the globe

  var globe = {viewer: null, starting: null, spinning: false, byEntity: {}, hovered: null};

  function start() {
    if (!globe.starting) {
      state.status = 'loading';
      globe.starting = Promise.all([
        loadScript(CONFIG_URL).catch(function () { /* no token file: offline mode */ }),
        loadScript(CESIUM_BASE + 'Cesium.js'),
        getJson('/presets'),
        getJson('/lenses').catch(function () { return []; })
      ]).then(function (r) {
        if (!window.Cesium || !hasWebGL()) throw new Error('no Cesium or no WebGL');
        loadCss(CESIUM_BASE + 'Widgets/widgets.css');
        createViewer(r[2], r[3]);
      });
    }
    return globe.starting;
  }

  function quiet(event) {
    // Cesium logs to the console when nobody listens to an error event; we listen instead
    if (event && event.addEventListener) event.addEventListener(function () {});
  }

  function tint(layer) {
    layer.brightness = 0.6;
    layer.contrast = 1.25;
    layer.saturation = 0.35;
    layer.gamma = 1.1;
    quiet(layer.errorEvent);
    layer.readyEvent.addEventListener(function (provider) { quiet(provider && provider.errorEvent); });
    return layer;
  }

  function createViewer(presets, lensList) {
    var C = window.Cesium;
    window.CESIUM_BASE_URL = CESIUM_BASE;
    var token = typeof window.CESIUM_ION_TOKEN === 'string' ? window.CESIUM_ION_TOKEN : '';
    var mode = chooseMode(token, navigator.onLine);
    state.mode = mode;
    C.Ion.defaultAccessToken = token.trim();

    // bundled offline imagery: always there, so the globe is never blank
    var base = tint(C.ImageryLayer.fromProviderAsync(
      C.TileMapServiceImageryProvider.fromUrl(C.buildModuleUrl('Assets/Textures/NaturalEarthII'))));

    ui.status.hidden = true;
    var v = globe.viewer = state.viewer = new C.Viewer(ui.box, {
      baseLayer: base, terrainProvider: new C.EllipsoidTerrainProvider(),
      baseLayerPicker: false, geocoder: false, homeButton: false, sceneModePicker: false,
      navigationHelpButton: false, animation: false, timeline: false, fullscreenButton: false,
      infoBox: false, selectionIndicator: false, skyBox: false, shouldAnimate: false
    });
    var scene = v.scene;
    scene.backgroundColor = C.Color.fromCssColorString('#02060f');
    if (scene.sun) scene.sun.show = false;
    if (scene.moon) scene.moon.show = false;
    scene.globe.baseColor = C.Color.fromCssColorString('#061428');
    scene.globe.showGroundAtmosphere = true;
    if (scene.skyAtmosphere) {
      scene.skyAtmosphere.show = true;
      scene.skyAtmosphere.hueShift = -0.05;
      scene.skyAtmosphere.saturationShift = -0.2;
      scene.skyAtmosphere.brightnessShift = -0.25;
    }
    v.cesiumWidget.screenSpaceEventHandler.removeInputAction(C.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    scene.camera.setView({destination: C.Cartesian3.fromDegrees(-98, 39.5, 17000000)});

    if (mode === 'terrain') loadTerrain(C, v); else showOfflineNote();
    addRegions(C, v, presets, lensList);
    setupSpin(C, v);
    setupPointer(C, v);
    v.useDefaultRenderLoop = state.view === 'globe';
    state.status = 'ready';
  }

  function goOffline(C, v) {
    if (!v.isDestroyed()) v.terrainProvider = new C.EllipsoidTerrainProvider();
    state.mode = 'offline';
    showOfflineNote();
  }

  function loadTerrain(C, v) {
    withTimeout(C.CesiumTerrainProvider.fromIonAssetId(1, {requestVertexNormals: true}), TERRAIN_TIMEOUT_MS)
      .then(function (terrain) {
        if (v.isDestroyed() || state.mode !== 'terrain') return;
        var errors = 0;
        terrain.errorEvent.addEventListener(function () {
          if (++errors === TERRAIN_ERRORS_MAX && state.mode === 'terrain') goOffline(C, v);
        });
        v.terrainProvider = terrain;
        // sharper online imagery on top of the bundled one; on failure the bundled one stays
        withTimeout(C.IonImageryProvider.fromAssetId(2), TERRAIN_TIMEOUT_MS).then(function (p) {
          if (v.isDestroyed()) return;
          quiet(p.errorEvent);
          tint(v.imageryLayers.addImageryProvider(p));
        }).catch(function () { /* keep the bundled imagery */ });
      })
      .catch(function () { goOffline(C, v); });
  }

  function shortName(name) { return String(name).replace(/\s*\(.*\)\s*$/, ''); }

  function addRegions(C, v, presets, lensList) {
    var cyan = C.Color.fromCssColorString(CYAN);
    var lensName = function (id) {
      var l = (lensList || []).filter(function (x) { return x.id === id; })[0];
      return l ? l.name : id;
    };
    presets.forEach(function (p) {
      var b = p.bbox, w = b[0], s = b[1], e = b[2], n = b[3];
      var info = {preset: p, lens: lensName(p.lens), fill: new C.ColorMaterialProperty(cyan.withAlpha(0.16))};
      var box = v.entities.add({
        id: 'preset:' + p.id,
        position: C.Cartesian3.fromDegrees((w + e) / 2, (s + n) / 2, BOX_HEIGHT),
        rectangle: {coordinates: C.Rectangle.fromDegrees(w, s, e, n), height: BOX_HEIGHT, material: info.fill},
        label: {
          text: shortName(p.name), font: '600 15px system-ui, sans-serif',
          fillColor: C.Color.WHITE, outlineColor: C.Color.fromCssColorString('#02060f'), outlineWidth: 3,
          style: C.LabelStyle.FILL_AND_OUTLINE, showBackground: true,
          backgroundColor: C.Color.fromCssColorString('#02060f').withAlpha(0.55),
          verticalOrigin: C.VerticalOrigin.BOTTOM, pixelOffset: new C.Cartesian2(0, -6),
          disableDepthTestDistance: Number.POSITIVE_INFINITY
        }
      });
      var line = v.entities.add({
        id: 'preset-outline:' + p.id,
        polyline: {
          positions: C.Cartesian3.fromDegreesArrayHeights(
            [w, s, BOX_HEIGHT, e, s, BOX_HEIGHT, e, n, BOX_HEIGHT, w, n, BOX_HEIGHT, w, s, BOX_HEIGHT]),
          width: 3, arcType: C.ArcType.RHUMB,
          material: new C.PolylineGlowMaterialProperty({glowPower: 0.3, color: cyan})
        }
      });
      globe.byEntity[box.id] = globe.byEntity[line.id] = info;
      state.regions.push(p.id);
    });

    // same code path as the preset's Demo button: click it
    state.selectPreset = function (id) {
      var info = globe.byEntity['preset:' + id];
      if (!info) return false;
      stopSpin();
      var p = info.preset, b = p.bbox, dx = (b[2] - b[0]) * 0.35, dy = (b[3] - b[1]) * 0.35;
      v.camera.flyTo({
        destination: C.Rectangle.fromDegrees(b[0] - dx, b[1] - dy, b[2] + dx, b[3] + dy),
        duration: reduced() ? 0 : 2,
        complete: function () {
          var chart = $('chart');
          if (chart && chart.scrollIntoView) chart.scrollIntoView({behavior: reduced() ? 'auto' : 'smooth', block: 'start'});
        }
      });
      var button = document.querySelector('#demos button[data-id="' + p.id + '"]');
      if (!button) {
        var err = $('err');
        if (err) err.textContent = 'The demo regions are not loaded yet; reload the page and try again.';
        return false;
      }
      button.click();
      return true;
    };
  }

  function regionAt(v, position) {
    var picked = position && v.scene.pick(position);
    var id = picked && picked.id && picked.id.id;
    return (id && globe.byEntity[id]) || null;
  }

  function setupPointer(C, v) {
    var handler = new C.ScreenSpaceEventHandler(v.scene.canvas);
    handler.setInputAction(function (m) {
      var info = regionAt(v, m.endPosition);
      if (globe.hovered && globe.hovered !== info) {
        globe.hovered.fill.color = C.Color.fromCssColorString(CYAN).withAlpha(0.16);
      }
      globe.hovered = info;
      v.scene.canvas.style.cursor = info ? 'pointer' : '';
      if (!info) { ui.tip.hidden = true; return; }
      info.fill.color = C.Color.fromCssColorString(CYAN).withAlpha(0.34);
      ui.tip.textContent = '';
      var strong = document.createElement('strong');
      strong.textContent = info.preset.name;
      var lens = document.createElement('span');
      lens.textContent = 'Lens: ' + info.lens + ' · click to load its trend';
      ui.tip.appendChild(strong);
      ui.tip.appendChild(lens);
      ui.tip.style.left = (m.endPosition.x + 14) + 'px';
      ui.tip.style.top = (m.endPosition.y + 14) + 'px';
      ui.tip.hidden = false;
    }, C.ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction(function (c) {
      var info = regionAt(v, c.position);
      if (info) state.selectPreset(info.preset.id);       // anything else on the globe is not clickable
    }, C.ScreenSpaceEventType.LEFT_CLICK);
  }

  function stopSpin() { globe.spinning = false; }

  function setupSpin(C, v) {
    globe.spinning = !reduced();
    ['pointerdown', 'wheel', 'touchstart', 'keydown'].forEach(function (type) {
      ui.box.addEventListener(type, stopSpin, {capture: true, passive: true});
    });
    var last = null;
    v.scene.preRender.addEventListener(function () {
      var now = performance.now(), dt = last === null ? 0 : Math.min((now - last) / 1000, 0.1);
      last = now;
      if (globe.spinning) v.camera.rotate(C.Cartesian3.UNIT_Z, -SPIN_RAD_PER_S * dt);
    });
  }

  // ------------------------------------------------------------------ start

  try {
    if (build()) setView('classic');
  } catch (e) { /* the page works without the globe */ }
})();
