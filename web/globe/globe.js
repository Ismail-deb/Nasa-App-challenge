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

  // Terrain, camera, render and label settings: plain JSON so tests/test_globe_relief.py can read it.
  //   terrain.timeoutMs              no terrain after this long (slow wifi): offline mode, with its note
  //   terrain.exaggeration*          the "Terrain height" slider (x times the real relief)
  //   terrain.maximumScreenSpaceError  higher = fewer, coarser tiles (2 is Cesium's default)
  //   terrain.requestVertexNormals   only needed for sun lighting, which the globe does not use
  //   camera.pitchDeg                tilt when flying to a region or the US (-90 = straight down)
  //   camera.minZoomM, maxZoomM      closest to the ground / farthest out the camera may go
  //   render.requestRenderMode       draw only when something changed (the idle spin keeps it drawing)
  //   render.software*               on a software WebGL renderer (SwiftShader, llvmpipe, Basic Render):
  //                                  fewer pixels and coarser tiles
  //   labels.clearDeg, nearOnlyM     a region label closer than clearDeg to a bigger region's label is shown
  //                                  only within nearOnlyM of the camera (or on hover)
  var GLOBE_CONFIG = {
    "terrain": {"assetId": 1, "timeoutMs": 8000, "exaggerationMin": 1, "exaggerationMax": 3,
                "exaggerationStep": 0.25, "exaggerationDefault": 1.5, "maximumScreenSpaceError": 3,
                "requestVertexNormals": false},
    "camera": {"pitchDeg": -40, "minZoomM": 2000, "maxZoomM": 25000000},
    "render": {"requestRenderMode": true, "softwareResolutionScale": 0.75, "softwareMaximumScreenSpaceError": 4},
    "labels": {"clearDeg": 9, "nearOnlyM": 3500000}
  };
  var CESIUM_BASE = '/vendor/cesium/';
  var CONFIG_URL = '/frontend/config.local.js';
  var TERRAIN_TIMEOUT_MS = GLOBE_CONFIG.terrain.timeoutMs;   // slow wifi: give up on terrain after this and go offline
  var KEY_TERRAIN = 'estd.globe.terrain';                     // "on" | "off" (missing = on)
  var KEY_EXAGGERATION = 'estd.globe.exaggeration';           // a number within the slider's range
  var TERRAIN_ERRORS_MAX = 20;        // terrain tiles failing after start (wifi dropped) -> offline
  var BOX_HEIGHT = 6000;              // metres; boxes float just above the highest terrain in them
  var SPIN_RAD_PER_S = 0.03;          // slow idle rotation
  var OFFLINE_NOTE = 'Globe running in offline mode, no terrain';
  var FAILED_NOTE = 'The globe could not start here (offline mode); showing Classic view.';
  var CYAN = '#3CE0D0';                // the design's stage glow
  var INK = '#3A2218', CREAM = '#FBF3E4';   // region label chips: ink on cream

  // public state, read by tests/browser/globe.html (and handy in the browser's dev tools)
  var state = window.EstdGlobe = {
    view: 'classic', status: 'idle', mode: null, note: '', regions: [], config: GLOBE_CONFIG,
    chooseMode: chooseMode, selectPreset: null, showRegions: null, showUS: null, topDown: null,
    readSettings: readSettings, setTerrainOn: null, setExaggeration: null, labelRules: labelRules
  };

  // ---- saved terrain settings (localStorage may be blocked: then the defaults, and nothing is saved)
  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* storage blocked */ }
    return null;
  }
  function clampExaggeration(x) {
    var t = GLOBE_CONFIG.terrain, n = Number(x);
    if (!isFinite(n) || x === null || x === '') return t.exaggerationDefault;
    return Math.min(t.exaggerationMax, Math.max(t.exaggerationMin, n));
  }
  function readSettings() {
    return {terrainOn: store(KEY_TERRAIN) !== 'off', exaggeration: clampExaggeration(store(KEY_EXAGGERATION))};
  }

  // which region labels are shown only near the camera: those whose centre is within clearDeg of the
  // centre of a bigger region (bigger box = keeps its label from afar). Read from the boxes, not by name.
  function labelRules(presets) {
    var clear = GLOBE_CONFIG.labels.clearDeg;
    var info = presets.map(function (p) {
      var b = p.bbox;
      return {id: p.id, x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2, area: (b[2] - b[0]) * (b[3] - b[1])};
    });
    var out = {};
    info.forEach(function (a) {
      out[a.id] = info.some(function (o) {
        return o !== a && o.area > a.area && Math.hypot(o.x - a.x, o.y - a.y) < clear;
      }) ? 'near' : 'always';
    });
    return out;
  }

  function $(id) { return document.getElementById(id); }
  // progress written on <body> (data-globe, data-trend) for the stylesheet and the optional guide
  function flag(name, value) { try { document.body.dataset[name] = value; } catch (e) { /* not essential */ } }
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
    if (controls) controls.parentNode.insertBefore(bar, controls); else header.appendChild(bar);

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
        '<div id="globeRegions" aria-hidden="true"></div>' +
        '<div id="globeOutline" class="globe-track" aria-hidden="true"></div>' +
        '<div id="globeCell" class="globe-track" aria-hidden="true"></div>' +
        '<div id="globeTip" role="tooltip" hidden></div>' +
        '<p id="globeStatus">Loading the globe&hellip;</p>' +
      '</div>' +
      '<p class="globe-foot"><span>Click a highlighted region to load its trend below.</span>' +
      ' <span id="globeNote" hidden></span></p>';
    var slot = $('topGrid') || main;                 // left of the scenario panel in Globe view
    slot.insertBefore(panel, slot.firstChild);

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
    document.body.dataset.view = view;               // the page lays itself out per view; the guide reads it too
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
    flag('globe', 'failed');
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

  var globe = {viewer: null, starting: null, spinning: false, byEntity: {}, hovered: null, boxes: [],
               boxHeight: BOX_HEIGHT, terrain: null, terrainOn: true, exaggeration: 1, current: null,
               outline: null, outlineIds: {}, renderUntil: 0};

  // request render mode only draws on change, and a camera flight only moves when drawn: keep drawing
  function keepDrawing(v, seconds) {
    globe.renderUntil = Math.max(globe.renderUntil, performance.now() + (seconds + 0.5) * 1000);
    v.scene.requestRender();
  }

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
    scene.backgroundColor = C.Color.fromCssColorString('#0B2530');
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
    scene.camera.setView({destination: C.Cartesian3.fromDegrees(HOME.lon, HOME.lat, HOME.height)});

    // never under the ground, never too close or too far
    var ctl = scene.screenSpaceCameraController, cam = GLOBE_CONFIG.camera;
    ctl.enableCollisionDetection = true;
    ctl.minimumZoomDistance = cam.minZoomM;
    ctl.maximumZoomDistance = cam.maxZoomM;
    // performance on a laptop with software rendering: coarser tiles, draw only when something changed
    scene.globe.maximumScreenSpaceError = GLOBE_CONFIG.terrain.maximumScreenSpaceError;
    scene.globe.preloadSiblings = false;
    scene.requestRenderMode = !!GLOBE_CONFIG.render.requestRenderMode;
    scene.maximumRenderTimeChange = Infinity;
    state.software = softwareRenderer(scene);
    if (state.software) {
      v.resolutionScale = GLOBE_CONFIG.render.softwareResolutionScale;
      scene.globe.maximumScreenSpaceError = GLOBE_CONFIG.render.softwareMaximumScreenSpaceError;
    }
    var s = readSettings();
    globe.terrainOn = s.terrainOn;
    globe.exaggeration = s.exaggeration;

    if (mode === 'terrain') loadTerrain(C, v); else showOfflineNote();
    addRegions(C, v, presets, lensList);
    setupSpin(C, v);
    setupPointer(C, v);
    setupRegionsBox(C, v, presets);
    setupTerrainPanel(C, v);
    setupOutline(C, v);
    setupTrendMaps(C, v);
    v.useDefaultRenderLoop = state.view === 'globe';
    state.status = 'ready';
    flag('globe', 'ready');
  }

  // a WebGL renderer without a graphics card (drawn by the processor)
  function softwareRenderer(scene) {
    try {
      var gl = scene.context._gl, ext = gl.getExtension('WEBGL_debug_renderer_info');
      var name = String(gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER));
      return /swiftshader|llvmpipe|softpipe|basic render|software/i.test(name);
    } catch (e) { return false; }
  }

  function goOffline(C, v) {
    globe.terrain = null;
    if (!v.isDestroyed()) { v.terrainProvider = new C.EllipsoidTerrainProvider(); applyRelief(C, v); }
    state.mode = 'offline';
    showOfflineNote();
  }

  // the relief as the switch and the slider say: real terrain (exaggerated) or the smooth ellipsoid
  function applyRelief(C, v) {
    if (v.isDestroyed()) return;
    var on = !!globe.terrain && globe.terrainOn;
    var want = on ? globe.terrain : null;
    if (want && v.terrainProvider !== want) v.terrainProvider = want;
    if (!want && !(v.terrainProvider instanceof C.EllipsoidTerrainProvider)) v.terrainProvider = new C.EllipsoidTerrainProvider();
    v.scene.verticalExaggeration = on ? globe.exaggeration : 1;
    state.relief = {terrain: on, exaggeration: v.scene.verticalExaggeration};
    updateBoxHeights(C);
    syncTerrainPanel();
    v.scene.requestRender();
  }

  function loadTerrain(C, v) {
    var t = GLOBE_CONFIG.terrain;
    withTimeout(C.CesiumTerrainProvider.fromIonAssetId(t.assetId, {requestVertexNormals: t.requestVertexNormals}), TERRAIN_TIMEOUT_MS)
      .then(function (terrain) {
        if (v.isDestroyed() || state.mode !== 'terrain') return;
        var errors = 0;
        terrain.errorEvent.addEventListener(function () {
          if (++errors === TERRAIN_ERRORS_MAX && state.mode === 'terrain') goOffline(C, v);
        });
        globe.terrain = terrain;
        applyRelief(C, v);                       // the user may have switched terrain off: then not drawn
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

  function boxRing(C, b, h) {
    return C.Cartesian3.fromDegreesArrayHeights([b[0], b[1], h, b[2], b[1], h, b[2], b[3], h, b[0], b[3], h, b[0], b[1], h]);
  }

  // the boxes float above the highest ground in them, also when the relief is stretched
  function updateBoxHeights(C) {
    var h = globe.boxHeight = BOX_HEIGHT * (globe.terrain && globe.terrainOn ? globe.exaggeration : 1);
    globe.boxes.forEach(function (info) {
      var b = info.preset.bbox;
      info.box.rectangle.height = h;
      info.box.position = C.Cartesian3.fromDegrees((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, h);
      info.line.polyline.positions = boxRing(C, b, h);
    });
  }

  // a tilted view (camera.pitchDeg) of a [west, south, east, north] box, looking north, the whole box in sight
  function flyTilted(C, v, b, complete) {
    var sphere = C.BoundingSphere.fromRectangle3D(C.Rectangle.fromDegrees(b[0], b[1], b[2], b[3]));
    var fovy = (v.camera.frustum && v.camera.frustum.fovy) || 1;
    var range = Math.min(sphere.radius / Math.sin(fovy / 2), GLOBE_CONFIG.camera.maxZoomM);
    // the pitch is taken at the box's centre; seen from the camera, the Earth's curve adds to it, so less here
    var pitch = C.Math.toRadians(GLOBE_CONFIG.camera.pitchDeg);
    pitch = Math.min(pitch + range * Math.cos(pitch) / v.scene.globe.ellipsoid.maximumRadius, -0.1);
    v.camera.cancelFlight();
    v.camera.flyToBoundingSphere(sphere, {
      offset: new C.HeadingPitchRange(0, pitch, range),
      duration: reduced() ? 0 : 2,
      complete: complete
    });
    keepDrawing(v, reduced() ? 0 : 2);
  }

  // "Top-down": straight down over the point in the middle of the view, from the same distance
  function topDown(C, v) {
    stopSpin();
    var scene = v.scene, cam = v.camera;
    var mid = new C.Cartesian2(scene.canvas.clientWidth / 2, scene.canvas.clientHeight / 2);
    var at = cam.pickEllipsoid(mid, scene.globe.ellipsoid);
    cam.cancelFlight();
    if (!at) {
      cam.flyTo({destination: C.Cartesian3.fromDegrees(HOME.lon, HOME.lat, HOME.height), duration: reduced() ? 0 : 1});
    } else {
      var g = C.Cartographic.fromCartesian(at);
      var dist = Math.max(C.Cartesian3.distance(cam.positionWC, at), GLOBE_CONFIG.camera.minZoomM);
      var end = {destination: C.Cartesian3.fromRadians(g.longitude, g.latitude, dist),
                 orientation: {heading: 0, pitch: -C.Math.PI_OVER_TWO, roll: 0}};
      cam.flyTo({destination: end.destination, orientation: end.orientation, duration: reduced() ? 0 : 1});
      // a flight can stall while the scene is not drawing: make sure it ends looking straight down
      window.setTimeout(function () {
        if (v.isDestroyed() || cam.pitch < -C.Math.PI_OVER_TWO + 0.02) return;
        cam.cancelFlight();
        cam.setView(end);
        scene.requestRender();
      }, reduced() ? 60 : 1800);
    }
    keepDrawing(v, reduced() ? 0 : 1);
  }

  function addRegions(C, v, presets, lensList) {
    var cyan = C.Color.fromCssColorString(CYAN);
    var lensName = function (id) {
      var l = (lensList || []).filter(function (x) { return x.id === id; })[0];
      return l ? l.name : id;
    };
    var rules = state.labelShown = labelRules(presets);
    var near = new C.DistanceDisplayCondition(0, GLOBE_CONFIG.labels.nearOnlyM);
    presets.forEach(function (p) {
      var b = p.bbox, w = b[0], s = b[1], e = b[2], n = b[3];
      var info = {preset: p, lens: lensName(p.lens), fill: new C.ColorMaterialProperty(cyan.withAlpha(0.16)),
                  near: rules[p.id] === 'near' ? near : undefined};
      var box = info.box = v.entities.add({
        id: 'preset:' + p.id,
        position: C.Cartesian3.fromDegrees((w + e) / 2, (s + n) / 2, BOX_HEIGHT),
        rectangle: {coordinates: C.Rectangle.fromDegrees(w, s, e, n), height: BOX_HEIGHT, material: info.fill},
        label: {
          text: shortName(p.name), font: '700 15px "Nunito Sans", system-ui, sans-serif',
          fillColor: C.Color.fromCssColorString(INK), style: C.LabelStyle.FILL, showBackground: true,
          backgroundColor: C.Color.fromCssColorString(CREAM), backgroundPadding: new C.Cartesian2(10, 6),
          verticalOrigin: C.VerticalOrigin.BOTTOM, pixelOffset: new C.Cartesian2(0, -6),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
          distanceDisplayCondition: info.near            // a crowded label: only when zoomed in (or hovered)
        }
      });
      var line = info.line = v.entities.add({
        id: 'preset-outline:' + p.id,
        polyline: {
          positions: boxRing(C, b, BOX_HEIGHT),
          width: 3, arcType: C.ArcType.RHUMB,
          material: new C.PolylineGlowMaterialProperty({glowPower: 0.3, color: cyan})
        }
      });
      globe.byEntity[box.id] = globe.byEntity[line.id] = info;
      globe.boxes.push(info);
      state.regions.push(p.id);
    });

    // same code path as the preset's Demo button: click it
    state.selectPreset = function (id) {
      var info = globe.byEntity['preset:' + id];
      if (!info) return false;
      stopSpin();
      closeCell();
      globe.current = id;
      var p = info.preset;
      flyTilted(C, v, p.bbox, function () {
        var chart = $('chart');
        if (chart && chart.scrollIntoView) chart.scrollIntoView({behavior: reduced() ? 'auto' : 'smooth', block: 'start'});
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

  // the US outline under the pointer: a thin line, so it is picked in a wider window than the boxes
  function outlineAt(v, position) {
    if (!position || !globe.outline) return false;
    var picked = v.scene.pick(position, OUTLINE_PICK_PX, OUTLINE_PICK_PX);
    var id = picked && picked.id && picked.id.id;
    return !!(id && globe.outlineIds[id]);
  }

  function showTip(at, title, text) {
    ui.tip.textContent = '';
    var strong = document.createElement('strong');
    strong.textContent = title;
    var span = document.createElement('span');
    span.textContent = text;
    ui.tip.appendChild(strong);
    ui.tip.appendChild(document.createTextNode(' '));
    ui.tip.appendChild(span);
    ui.tip.style.left = (at.x + 14) + 'px';
    ui.tip.style.top = (at.y + 14) + 'px';
    ui.tip.hidden = false;
  }

  function setupPointer(C, v) {
    var handler = new C.ScreenSpaceEventHandler(v.scene.canvas);
    handler.setInputAction(function (m) {
      var info = regionAt(v, m.endPosition);
      if (globe.hovered && globe.hovered !== info) {
        globe.hovered.fill.color = C.Color.fromCssColorString(CYAN).withAlpha(0.16);
        globe.hovered.box.label.distanceDisplayCondition = globe.hovered.near;     // back to its distance rule
      }
      var changed = globe.hovered !== info;
      globe.hovered = info;
      var onOutline = !info && outlineAt(v, m.endPosition);
      v.scene.canvas.style.cursor = info || onOutline ? 'pointer' : '';
      if (info) {
        info.fill.color = C.Color.fromCssColorString(CYAN).withAlpha(0.34);
        info.box.label.distanceDisplayCondition = undefined;                       // hovered: always labelled
        showTip(m.endPosition, info.preset.name, 'Lens: ' + info.lens + ' · click to load its trend');
      } else if (onOutline) {
        showTip(m.endPosition, OUTLINE_TIP[0], OUTLINE_TIP[1]);
      } else {
        ui.tip.hidden = true;
      }
      if (changed) v.scene.requestRender();
    }, C.ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction(function (c) {
      var info = regionAt(v, c.position);
      // inside the region already chosen, a click reads the cell under it instead of loading it again
      var cell = (!info || info.preset.id === globe.current) ? cellAtScreen(C, v, c.position) : null;
      if (info && !cell) { state.selectPreset(info.preset.id); return; }       // boxes first
      if (!info && outlineAt(v, c.position)) { closeCell(); state.showUS(true); return; }
      if (cell) showCell(cell, c.position); else closeCell();                 // masked / outside: nothing
    }, C.ScreenSpaceEventType.LEFT_CLICK);
  }

  function stopSpin() { globe.spinning = false; }

  // #globeRegions: an unseen element kept over the cyan region boxes as they move on screen, so that the
  // guide can point at them. It has no size while any box is out of sight (behind the globe, off screen).
  // state.showRegions() turns the globe back to its first view, where all boxes are in sight.
  var HOME = {lon: -98, lat: 39.5, height: 17000000};       // the first view: over the middle of the US
  // Unseen elements kept over things on the globe as they move on screen, so that the guide can point at
  // them: #globeRegions (the region boxes), #globeOutline (the US outline), #globeCell (one example cell).
  // Each has no size while any of its corners is out of sight (behind the globe, off screen).
  function track(C, v, el, cornersOf, minPx) {
    var scene = v.scene;
    var project = C.SceneTransforms.worldToWindowCoordinates || C.SceneTransforms.wgs84ToWindowCoordinates;
    function hide() { el.style.width = el.style.height = '0px'; }
    scene.postRender.addEventListener(function () {
      var corners = cornersOf();
      if (!el || !project || !corners || !corners.length) { if (el) hide(); return; }
      var occluder = new C.EllipsoidalOccluder(scene.globe.ellipsoid, scene.camera.positionWC);
      var w = scene.canvas.clientWidth, h = scene.canvas.clientHeight;
      var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (var i = 0; i < corners.length; i++) {
        var at = occluder.isPointVisible(corners[i]) ? project(scene, corners[i]) : null;
        if (!at || at.x < 0 || at.y < 0 || at.x > w || at.y > h) { hide(); return; }
        x0 = Math.min(x0, at.x); y0 = Math.min(y0, at.y); x1 = Math.max(x1, at.x); y1 = Math.max(y1, at.y);
      }
      var grow = minPx ? Math.max(0, minPx - (x1 - x0)) / 2 : 0, growY = minPx ? Math.max(0, minPx - (y1 - y0)) / 2 : 0;
      el.style.left = (ui.box.offsetLeft + x0 - grow) + 'px';
      el.style.top = (ui.box.offsetTop + y0 - growY) + 'px';
      el.style.width = (x1 - x0 + 2 * grow) + 'px';
      el.style.height = (y1 - y0 + 2 * growY) + 'px';
    });
  }

  function bboxCorners(C, b, h) {
    return [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]].map(function (c) {
      return C.Cartesian3.fromDegrees(c[0], c[1], h);
    });
  }

  function setupRegionsBox(C, v, presets) {
    var cache = {h: null, corners: []};
    track(C, v, $('globeRegions'), function () {
      if (cache.h !== globe.boxHeight) {
        cache.h = globe.boxHeight;
        cache.corners = [];
        presets.forEach(function (p) { cache.corners = cache.corners.concat(bboxCorners(C, p.bbox, cache.h)); });
      }
      return cache.corners;
    });
    state.showRegions = function () {
      stopSpin();
      v.camera.cancelFlight();
      v.camera.setView({destination: C.Cartesian3.fromDegrees(HOME.lon, HOME.lat, HOME.height)});
      v.scene.requestRender();
    };
    state.topDown = function () { topDown(C, v); };
  }

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
    // request render mode draws only on change: while it spins, ask for the next frame after each one
    v.scene.postRender.addEventListener(function () {
      if (globe.spinning || performance.now() < globe.renderUntil) v.scene.requestRender();
    });
    v.camera.moveStart.addEventListener(function () { closeCell(); });   // the card points at a spot that moves
  }

  // ------------------------------------------------------------------ relief controls (bottom-left of the stage)
  //
  // "Terrain" switch and "Terrain height" slider: shown only when terrain can load (a token and a network);
  // in offline mode there is nothing to stretch, so only "Top-down" is there. Both are saved in localStorage.

  function syncTerrainPanel() {
    var r = ui.relief;
    if (!r) return;
    var can = state.mode === 'terrain';
    r.sw.hidden = r.height.hidden = !can;
    r.on.checked = globe.terrainOn;
    r.range.disabled = !globe.terrainOn;
    r.range.value = String(globe.exaggeration);
    r.out.textContent = fmtTimes(globe.exaggeration);
  }

  function fmtTimes(x) { return (Math.round(x * 100) / 100) + '×'; }

  function setupTerrainPanel(C, v) {
    var t = GLOBE_CONFIG.terrain;
    var p = el('div', 'relief-panel');
    p.id = 'reliefPanel';
    p.setAttribute('role', 'group');
    p.setAttribute('aria-label', 'Relief');

    var sw = el('label', 'trend-switch relief-switch');
    sw.id = 'terrainSwitch';
    var on = el('input');
    on.type = 'checkbox'; on.id = 'terrainOn';
    on.setAttribute('aria-label', 'Terrain on or off');
    sw.appendChild(on);
    sw.appendChild(el('span', null, 'Terrain'));
    p.appendChild(sw);

    var height = el('label', 'relief-height');
    height.id = 'terrainHeight';
    height.appendChild(el('span', null, 'Terrain height'));
    var range = el('input');
    range.type = 'range'; range.id = 'terrainExaggeration';
    range.min = String(t.exaggerationMin); range.max = String(t.exaggerationMax); range.step = String(t.exaggerationStep);
    range.setAttribute('aria-label', 'Terrain height (vertical exaggeration)');
    height.appendChild(range);
    var out = el('output', 'relief-value');
    out.setAttribute('aria-hidden', 'true');
    height.appendChild(out);
    p.appendChild(height);

    var top = el('button', 'relief-btn', 'Top-down');
    top.type = 'button'; top.id = 'globeTopDown';
    top.title = 'Look straight down again';
    p.appendChild(top);

    ui.relief = {panel: p, sw: sw, on: on, height: height, range: range, out: out, top: top};
    ui.box.parentNode.appendChild(p);

    state.setTerrainOn = function (yes) {
      globe.terrainOn = !!yes;
      store(KEY_TERRAIN, yes ? 'on' : 'off');
      applyRelief(C, v);
    };
    state.setExaggeration = function (x) {
      globe.exaggeration = clampExaggeration(x);
      store(KEY_EXAGGERATION, String(globe.exaggeration));
      applyRelief(C, v);
    };
    on.addEventListener('change', function () { state.setTerrainOn(on.checked); });
    range.addEventListener('input', function () { state.setExaggeration(range.value); });
    top.addEventListener('click', function () { topDown(C, v); });
    applyRelief(C, v);
  }

  // ------------------------------------------------------------------ the US outline (data/maps/us_outline.geojson)

  var OUTLINE_TIP = ['Contiguous United States.', 'Click for a tilted view of the whole country.'];
  var OUTLINE_PICK_PX = 9;

  // every ring of a GeoJSON (Multi)Polygon FeatureCollection, as [[lon, lat], ...] lists
  function ringsOf(geo) {
    var rings = [];
    ((geo && geo.features) || []).forEach(function (f) {
      var g = f && f.geometry;
      if (!g) return;
      var polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
      polys.forEach(function (poly) { (poly || []).forEach(function (ring) { if (ring && ring.length > 1) rings.push(ring); }); });
    });
    return rings;
  }

  function setupOutline(C, v) {
    state.outline = {status: 'loading', rings: 0, bbox: null};
    getJson(MAPS_URL + 'index.json').then(function (index) {
      var file = index && index.boundaries && index.boundaries.file;
      if (!file) throw new Error('no outline');
      return getJson(MAPS_URL + file);
    }).then(function (geo) {
      if (v.isDestroyed()) return;
      var rings = ringsOf(geo);
      if (!rings.length) throw new Error('empty outline');
      var b = [Infinity, Infinity, -Infinity, -Infinity];
      rings.forEach(function (ring) {
        ring.forEach(function (c) {
          b[0] = Math.min(b[0], c[0]); b[1] = Math.min(b[1], c[1]); b[2] = Math.max(b[2], c[0]); b[3] = Math.max(b[3], c[1]);
        });
      });
      var ground = C.Entity.supportsPolylinesOnTerrain ? C.Entity.supportsPolylinesOnTerrain(v.scene) : false;
      var color = C.Color.fromCssColorString(CYAN).withAlpha(0.9);
      rings.forEach(function (ring, i) {
        var flat = [];
        ring.forEach(function (c) { flat.push(c[0], c[1]); });
        var e = v.entities.add({
          id: 'us-outline:' + i,
          polyline: {positions: C.Cartesian3.fromDegreesArray(flat), width: 2, clampToGround: ground,
                     arcType: C.ArcType.RHUMB, material: color}
        });
        globe.outlineIds[e.id] = true;
      });
      globe.outline = {bbox: b};
      state.outline = {status: 'ready', rings: rings.length, bbox: b, onGround: ground};
      track(C, v, $('globeOutline'), function () { return bboxCorners(C, b, 0); });
      v.scene.requestRender();
    }).catch(function () { state.outline = {status: 'failed', rings: 0, bbox: null}; });

    // a tilted view of the whole country (from the outline's own extent); before it loads: the first view
    state.showUS = function (tilted) {
      stopSpin();
      closeCell();
      if (tilted && globe.outline) { flyTilted(C, v, globe.outline.bbox); return; }
      state.showRegions();
    };
  }

  // ------------------------------------------------------------------ cell readout (data/maps/*_cells.json)
  //
  // The layout is the one the file's own "decode" field documents: flag has one character per grid cell,
  // row-major, row 0 = north, index = row * nlon + col; '-' = masked or no data, '1' = significant after
  // FDR, '0' = not; slope[k] and p[k] belong to the k-th non-'-' character of flag.

  // where each cell's values are: -1 for a masked cell, else k
  function cellIndex(cells) {
    var flag = cells.flag, at = new Int32Array(flag.length), k = 0;
    for (var i = 0; i < flag.length; i++) at[i] = flag.charAt(i) === '-' ? -1 : k++;
    return at;
  }

  function nearestIndex(list, x) {
    var n = list.length;
    if (n < 2) return n === 1 && Math.abs(list[0] - x) < 1e-9 ? 0 : -1;
    var step = (list[n - 1] - list[0]) / (n - 1), i = Math.round((x - list[0]) / step);
    return i >= 0 && i < n && Math.abs(list[i] - x) <= Math.abs(step) / 2 + 1e-9 ? i : -1;
  }

  // the decoded values of the cell containing (lon, lat), or null when masked or outside the grid
  function decodeCell(cells, lon, lat) {
    if (!cells || !cells.flag || cells.flag.length !== cells.nlat * cells.nlon) return null;
    var row = nearestIndex(cells.lat, lat), col = nearestIndex(cells.lon, lon);
    if (row < 0 || col < 0) return null;
    var idx = row * cells.nlon + col, f = cells.flag.charAt(idx);
    if (f !== '0' && f !== '1') return null;
    var at = cells._at || (cells._at = cellIndex(cells)), k = at[idx];
    var dlat = Math.abs(cells.lat[1] - cells.lat[0]), dlon = Math.abs(cells.lon[1] - cells.lon[0]);
    return {row: row, col: col, lat: cells.lat[row], lon: cells.lon[col], slope: cells.slope[k], p: cells.p[k],
            significant: f === '1', units: cells.slope_units, dlat: dlat, dlon: dlon,
            kmNS: dlat * 111.32, kmEW: dlon * 111.32 * Math.cos(cells.lat[row] * Math.PI / 180)};
  }
  state.decodeCell = decodeCell;

  function cellsFor(key) {
    var x = trend.variables.filter(function (y) { return y.key === key; })[0];
    if (!x) return Promise.reject(new Error('no variable'));
    if (!x.cellsPromise) {
      x.cellsPromise = getJson(MAPS_URL + x.meta.cells).then(function (c) { x.cells = c; return c; });
      x.cellsPromise.catch(function () { x.cellsPromise = null; });   // try again on the next click
    }
    return x.cellsPromise;
  }

  // the cell under a screen position on the shown map (terrain included), or null
  function cellAtScreen(C, v, position) {
    if (!trend.show || !trend.key || !position) return null;
    var x = trend.variables.filter(function (y) { return y.key === trend.key; })[0];
    if (!x || !x.cells) return null;
    var ray = v.camera.getPickRay(position);
    var at = ray && (v.scene.globe.pick(ray, v.scene) || v.camera.pickEllipsoid(position, v.scene.globe.ellipsoid));
    if (!at) return null;
    var g = C.Cartographic.fromCartesian(at);
    var cell = decodeCell(x.cells, C.Math.toDegrees(g.longitude), C.Math.toDegrees(g.latitude));
    if (cell) { cell.name = x.name; cell.fdr = x.meta.fdr_level; }
    return cell;
  }

  function fmtSlope(x) {
    var s = Math.abs(x) >= 100 ? x.toFixed(0) : String(Number(x.toPrecision(3)));
    return (x > 0 ? '+' : '') + s.replace(/^-/, '−');
  }
  function fmtDeg(x, pos, neg) { return Math.abs(Number(x.toFixed(3))) + '° ' + (x >= 0 ? pos : neg); }

  function closeCell() {
    if (ui.cell && !ui.cell.hidden) { ui.cell.hidden = true; state.cell = null; }
  }

  function showCell(cell, at) {
    var card = ui.cell;
    if (!card) return;
    card.textContent = '';
    card.appendChild(el('p', 'cell-title', cell.name));
    var dl = el('dl', 'cell-rows');
    function row(k, val, cls) {
      dl.appendChild(el('dt', null, k));
      dl.appendChild(el('dd', cls || null, val));
    }
    row('Change', fmtSlope(cell.slope) + ' ' + cell.units, 'cell-slope');
    row('p-value', String(cell.p) + ' (raw)');
    var level = typeof cell.fdr === 'number' ? ' (FDR ' + Math.round(cell.fdr * 100) + '%)' : ' (FDR)';
    row('Significant', (cell.significant ? 'Yes' : 'No') + level, cell.significant ? 'cell-yes' : 'cell-no');
    row('Grid cell', cell.dlat + '° × ' + cell.dlon + '° (about ' + Math.round(cell.kmNS) + ' × ' +
        Math.round(cell.kmEW) + ' km)');
    row('Centre', fmtDeg(cell.lat, 'N', 'S') + ', ' + fmtDeg(cell.lon, 'E', 'W'));
    card.appendChild(dl);
    card.hidden = false;
    // next to the click, inside the stage
    var stage = ui.box.parentNode, sw = stage.clientWidth, sh = stage.clientHeight;
    var cw = card.offsetWidth, ch = card.offsetHeight;
    var x = ui.box.offsetLeft + at.x + 16, y = ui.box.offsetTop + at.y + 16;
    if (x + cw > sw - 8) x = Math.max(8, ui.box.offsetLeft + at.x - cw - 16);
    if (y + ch > sh - 8) y = Math.max(8, sh - ch - 8);
    card.style.left = x + 'px';
    card.style.top = y + 'px';
    state.cell = {lon: cell.lon, lat: cell.lat, slope: cell.slope, p: cell.p, significant: cell.significant};
  }

  function setupCellCard() {
    var card = ui.cell = el('div', 'cell-card');
    card.id = 'cellCard';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Grid cell');
    card.hidden = true;
    ui.box.parentNode.appendChild(card);
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') closeCell(); });
    // a click anywhere but the card or the globe (the globe decides for itself) closes it
    document.addEventListener('pointerdown', function (ev) {
      if (card.hidden || card.contains(ev.target) || ui.box.contains(ev.target)) return;
      closeCell();
    }, true);
  }

  // one example cell for the guide to point at: the significant cell with the largest change
  function exampleCell(cells) {
    var at = cells._at || (cells._at = cellIndex(cells)), best = -1, bestAbs = -1;
    for (var i = 0; i < at.length; i++) {
      if (at[i] < 0 || cells.flag.charAt(i) !== '1') continue;
      var a = Math.abs(cells.slope[at[i]]);
      if (a > bestAbs) { bestAbs = a; best = i; }
    }
    if (best < 0) return null;
    var row = Math.floor(best / cells.nlon), col = best % cells.nlon;
    var dlat = Math.abs(cells.lat[1] - cells.lat[0]) / 2, dlon = Math.abs(cells.lon[1] - cells.lon[0]) / 2;
    var lat = cells.lat[row], lon = cells.lon[col];
    return [lon - dlon, lat - dlat, lon + dlon, lat + dlat];
  }

  function setupCellTracker(C, v) {
    var cache = {key: null, corners: null};
    track(C, v, $('globeCell'), function () {
      if (!trend.show || !trend.key) return null;
      var x = trend.variables.filter(function (y) { return y.key === trend.key; })[0];
      if (!x || !x.cells) return null;
      if (cache.key !== trend.key) {
        var b = exampleCell(x.cells);
        cache.key = trend.key;
        cache.corners = b ? bboxCorners(C, b, 0) : null;
      }
      return cache.corners;
    }, 28);
  }

  // ------------------------------------------------------------------ per-cell trend maps (data/maps/)
  //
  // Everything about a map (bounds, scale, units, caveat, description, method) is read from
  // /maps/index.json (data/maps/index.yml) and each variable's /maps/<key>.json at runtime; nothing
  // about the data is written in this file. A variable whose JSON has a "caveat" is experimental
  // (known data artefacts) and is hidden until the viewer asks for it. If any of these files fails
  // to load, the globe works as before and a small note replaces the panel.

  var MAPS_URL = '/maps/';
  var DEFAULT_MAP = 'T2M';                 // the layer shown first; falls back to the first stable one
  var MAP_OPACITY = 0.85;
  var MAPS_NOTE = 'Trend maps could not be loaded; the globe and the regions still work.';
  var FADED_TEXT = 'Faded cells are not statistically significant (FDR 10%): we can\u2019t tell their ' +
                   'change from natural variation.';
  // colour bars by the colormap name in each JSON's scale (matplotlib RdBu_r: blue = min, red = max)
  var COLORMAPS = {
    RdBu_r: ['#053061', '#2166ac', '#4393c3', '#92c5de', '#d1e5f0', '#f7f7f7',
             '#fddbc7', '#f4a582', '#d6604d', '#b2182b', '#67001f']
  };

  var trend = state.trend = {
    status: 'idle', show: true, opacity: MAP_OPACITY, key: null, showExperimental: false,
    variables: [], layer: null, layerFor: layerFor
  };

  // the imagery-layer options for one variable, from its JSON only (also read by the tests)
  function layerFor(C, meta) {
    var b = meta.bounds;
    return {
      url: MAPS_URL + meta.image,
      rectangle: C.Rectangle.fromDegrees(b.west, b.south, b.east, b.north),
      options: {
        alpha: trend.opacity, show: trend.show,
        // one pixel per grid cell: never smooth between cells
        minificationFilter: C.TextureMinificationFilter.NEAREST,
        magnificationFilter: C.TextureMagnificationFilter.NEAREST
      }
    };
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function fmt(x) {
    var a = Math.abs(x);
    return (a === 0 ? '0' : a >= 10 ? x.toFixed(0) : a >= 1 ? x.toFixed(1) : x.toPrecision(2)).replace(/^-/, '\u2212');
  }

  function unitsOf(meta) {
    // the scale is in slope units ("°C per decade"); the legend title already says "per decade"
    return String(meta.slope_units || meta.display_units || '').replace(/\s*per decade\s*$/, '');
  }

  function trendNote(text) {
    state.trend.status = 'failed';
    flag('trend', 'failed');
    if (ui.trendPanel) ui.trendPanel.hidden = true;
    if (ui.trendLegend) ui.trendLegend.hidden = true;
    ui.globeNote.textContent = ui.globeNote.hidden ? text : ui.globeNote.textContent + ' \u00b7 ' + text;
    ui.globeNote.hidden = false;
  }

  function setupTrendMaps(C, v) {
    trend.status = 'loading';
    getJson(MAPS_URL + 'index.json').then(function (index) {
      var entries = (index && index.variables) || [];
      if (!entries.length) throw new Error('no variables');
      return Promise.all(entries.map(function (e) { return getJson(MAPS_URL + e.metadata); }));
    }).then(function (metas) {
      if (v.isDestroyed()) return;
      trend.variables = metas.map(function (m) {
        return {key: m.key, name: m.name, meta: m, experimental: !!(m.caveat && String(m.caveat).trim())};
      });
      buildTrendPanel(C, v);
      setupCellCard();
      setupCellTracker(C, v);
      // online imagery added later (terrain mode) must stay under the trend map
      v.imageryLayers.layerAdded.addEventListener(function (layer) {
        if (trend.layer && layer !== trend.layer && !v.isDestroyed()) v.imageryLayers.raiseToTop(trend.layer);
      });
      var stable = trend.variables.filter(function (x) { return !x.experimental; });
      var first = stable.filter(function (x) { return x.key === DEFAULT_MAP; })[0] || stable[0] || trend.variables[0];
      selectMap(C, v, first.key);
      trend.status = 'ready';
      flag('trend', 'ready');
    }).catch(function () { trendNote(MAPS_NOTE); });
  }

  function buildTrendPanel(C, v) {
    var p = ui.trendPanel = el('div', 'trend-panel');
    p.id = 'trendPanel';
    p.setAttribute('role', 'region');
    p.setAttribute('aria-label', 'Trend map');

    var head = el('label', 'trend-switch');
    head.id = 'trendSwitch';
    var on = el('input');
    on.type = 'checkbox'; on.id = 'trendOn'; on.checked = trend.show;
    head.appendChild(on);
    head.appendChild(el('span', null, 'Trend map'));
    p.appendChild(head);

    var body = el('div', 'trend-body');
    p.appendChild(body);

    var list = el('div', 'trend-list');
    list.id = 'trendList';
    list.setAttribute('role', 'radiogroup');
    list.setAttribute('aria-label', 'Variable');
    trend.variables.forEach(function (x) {
      var row = el('label', 'trend-var' + (x.experimental ? ' trend-experimental' : ''));
      var r = el('input');
      r.type = 'radio'; r.name = 'trendVar'; r.value = x.key;
      row.appendChild(r);
      row.appendChild(el('span', null, x.name));
      row.hidden = x.experimental && !trend.showExperimental;
      list.appendChild(row);
    });
    body.appendChild(list);

    var expRow = el('label', 'trend-exp-toggle');
    var exp = el('input');
    exp.type = 'checkbox'; exp.id = 'trendExperimental'; exp.checked = trend.showExperimental;
    expRow.appendChild(exp);
    expRow.appendChild(el('span', null, 'Show experimental layers (known data artefacts)'));
    expRow.hidden = !trend.variables.some(function (x) { return x.experimental; });
    body.appendChild(expRow);

    var opRow = el('label', 'trend-opacity');
    opRow.appendChild(el('span', null, 'Opacity'));
    var op = el('input');
    op.type = 'range'; op.min = '0'; op.max = '1'; op.step = '0.05'; op.value = String(trend.opacity);
    op.setAttribute('aria-label', 'Trend map opacity');
    opRow.appendChild(op);
    body.appendChild(opRow);

    // the legend card (bottom-right of the stage): caveat, colour bar, description, method
    var card = ui.trendLegend = el('div', 'trend-card');
    card.id = 'trendLegend';
    card.setAttribute('role', 'region');
    card.setAttribute('aria-label', 'Trend map legend');
    var caveat = el('p', 'trend-caveat');
    caveat.setAttribute('role', 'note');
    caveat.hidden = true;
    card.appendChild(caveat);

    var legend = el('div', 'trend-legend');
    legend.appendChild(el('div', 'trend-legend-title', 'Change per decade'));
    var bar = el('div', 'trend-bar');
    legend.appendChild(bar);
    var ticks = el('div', 'trend-ticks');
    var tMin = el('span'), tMid = el('span', null, '0'), tMax = el('span');
    ticks.appendChild(tMin); ticks.appendChild(tMid); ticks.appendChild(tMax);
    legend.appendChild(ticks);
    var units = el('div', 'trend-units');
    legend.appendChild(units);
    legend.appendChild(el('p', 'trend-faded', FADED_TEXT));
    card.appendChild(legend);

    var desc = el('p', 'trend-desc');
    var info = el('button', 'trend-info', 'i');
    info.type = 'button';
    info.setAttribute('aria-expanded', 'false');
    info.setAttribute('aria-label', 'How this map was made');
    info.title = 'How this map was made';
    var descText = el('span');
    desc.appendChild(descText);
    desc.appendChild(document.createTextNode(' '));
    desc.appendChild(info);
    card.appendChild(desc);
    var method = el('p', 'trend-method');
    method.hidden = true;
    card.appendChild(method);

    ui.trend = {on: on, body: body, list: list, exp: exp, op: op, caveat: caveat, bar: bar,
                tMin: tMin, tMax: tMax, units: units, desc: descText, info: info, method: method};

    on.addEventListener('change', function () {
      trend.show = on.checked;
      body.hidden = card.hidden = !on.checked;
      if (trend.layer) trend.layer.show = trend.show;
      if (!trend.show) closeCell();
      v.scene.requestRender();
    });
    op.addEventListener('input', function () {
      trend.opacity = Number(op.value);
      if (trend.layer) trend.layer.alpha = trend.opacity;
      v.scene.requestRender();
    });
    list.addEventListener('change', function (ev) {
      if (ev.target && ev.target.name === 'trendVar') selectMap(C, v, ev.target.value);
    });
    exp.addEventListener('change', function () { setExperimental(C, v, exp.checked); });
    info.addEventListener('click', function () {
      method.hidden = !method.hidden;
      info.setAttribute('aria-expanded', String(!method.hidden));
    });

    ui.box.parentNode.appendChild(p);
    ui.box.parentNode.appendChild(card);
  }

  function setExperimental(C, v, shown) {
    trend.showExperimental = shown;
    [].forEach.call(ui.trend.list.querySelectorAll('.trend-experimental'), function (row) { row.hidden = !shown; });
    var cur = trend.variables.filter(function (x) { return x.key === trend.key; })[0];
    if (!shown && cur && cur.experimental) {
      var stable = trend.variables.filter(function (x) { return !x.experimental; });
      var back = stable.filter(function (x) { return x.key === DEFAULT_MAP; })[0] || stable[0];
      if (back) selectMap(C, v, back.key);
    }
  }

  function selectMap(C, v, key) {
    var x = trend.variables.filter(function (y) { return y.key === key; })[0];
    if (!x || v.isDestroyed()) return;
    var m = x.meta, t = ui.trend;
    trend.key = key;
    [].forEach.call(t.list.querySelectorAll('input[name="trendVar"]'), function (r) { r.checked = r.value === key; });

    // legend and texts, all from the variable's JSON
    t.caveat.textContent = x.experimental ? 'Experimental: ' + m.caveat : '';
    t.caveat.hidden = !x.experimental;
    var stops = COLORMAPS[m.scale && m.scale.colormap] || COLORMAPS.RdBu_r;
    t.bar.style.background = 'linear-gradient(to right, ' + stops.join(', ') + ')';
    t.tMin.textContent = fmt(m.scale.min);
    t.tMax.textContent = fmt(m.scale.max);
    t.units.textContent = unitsOf(m);
    t.desc.textContent = m.description || '';
    t.method.textContent = m.method || '';

    // the heatmap: one imagery layer, swapped on change
    if (trend.layer) { v.imageryLayers.remove(trend.layer, true); trend.layer = null; }
    var cfg = layerFor(C, m);
    var layer = C.ImageryLayer.fromProviderAsync(
      C.SingleTileImageryProvider.fromUrl(cfg.url, {rectangle: cfg.rectangle}), cfg.options);
    quiet(layer.errorEvent);
    layer.errorEvent.addEventListener(function () {
      if (trend.layer === layer) trendNote(MAPS_NOTE);
    });
    trend.layer = layer;
    v.imageryLayers.add(layer);
    closeCell();
    cellsFor(key).catch(function () { /* no readout for this variable; the map still shows */ });
    v.scene.requestRender();
  }

  // ------------------------------------------------------------------ start

  try {
    if (build()) setView('classic');
  } catch (e) { /* the page works without the globe */ }
})();
