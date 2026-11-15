// Configuration of the optional guide (web/guide/guide.js).
//
// The guide's name is defined HERE AND NOWHERE ELSE. Every label, tutorial line and tooltip
// is built from it; texts below use the placeholder {name}. To rename the guide, change this line.
const GUIDE_NAME = "Comet";

// The character's poses: one transparent picture each. neutral, talking and pointing are his everyday
// poses (if any of them fails to load, the guide falls back to a small drawn drone); cheer (arms up) and
// dance (mid-spin, a wider picture) are only for the idle dance, which is skipped if they fail to load.
const GUIDE_IMAGES = {
  "neutral": "/static/guide/assets/comet-neutral.webp",
  "talking": "/static/guide/assets/comet-talking.webp",
  "pointing": "/static/guide/assets/comet-pointing.webp",
  "cheer": "/static/guide/assets/comet-cheer.webp",
  "dance": "/static/guide/assets/comet-dance.webp"
};

// Each picture's size and feet_anchor_x (where his feet are, in picture pixels). Every pose is placed by
// lining its feet up with one fixed point at the bottom of his box, so he never jumps when poses swap.
const GUIDE_POSE_MANIFEST = "/static/guide/assets/comet-poses.json";

// The occasional idle dance (in place: neutral, cheer, dance, cheer, dance, neutral). Times in seconds:
//   idleSeconds       how long he must have been idle (no tutorial, no speech bubble, not dragged,
//                     tab visible, guide on and not tucked away) before the first dance
//   quietSeconds      and no mouse, key or scroll input on the page for at least this long
//   repeatMinSeconds, repeatMaxSeconds   after each dance, the next one waits a random time in this range
//   durationSeconds   length of one dance
// Off with ?calm=1 in the address, with the "Idle dance" header button, or with prefers-reduced-motion.
const GUIDE_DANCE = {"idleSeconds": 15, "quietSeconds": 10, "repeatMinSeconds": 45, "repeatMaxSeconds": 90, "durationSeconds": 4};

// What the guide says when he is clicked outside the tutorial.
const GUIDE_GREETING = "Hi, I'm {name}, your fox guide. Press any ? button and I'll explain that word, or use the replay button at the top for the tour.";

// The first-visit tutorial. Kept as plain JSON so tests/test_guide.py can read it.
//   target      CSS selector of the real page element(s) to highlight
//   fallback    highlighted instead when the target is not visible (optional)
//   needsResult true: the step talks about a result, so the guide runs the first demo if none is shown
//   text        one or two short sentences, written for students and the public
const GUIDE_STEPS = [
  {
    "id": "welcome",
    "target": "#appTitle",
    "text": "Hi, I'm {name}, your fox guide! This tool uses NASA satellite and model data to show how sunshine, wind, rain and more have changed over the years, and whether a trend is \"significant\"."
  },
  {
    "id": "demos",
    "target": "#demos",
    "fallback": "#go",
    "text": "Start with a demo scenario: each button picks a region and a matching lens. Press one now, or I'll pick the first one for us."
  },
  {
    "id": "lens",
    "target": "#lens",
    "text": "A lens translates a result into what it could mean for solar power, wind power, hydropower or farming. You can switch lens here at any time."
  },
  {
    "id": "chart",
    "target": "#chart",
    "needsResult": true,
    "text": "The thin line is the monthly average over the whole region. The thick line is the trend: the overall direction across the years."
  },
  {
    "id": "result",
    "target": "#card",
    "fallback": "#chart",
    "needsResult": true,
    "text": "The card shows the change per decade, a 95% range for it, and a p-value. \"Significant\" means the trend is unlikely to be chance; \"not significant yet\" does not mean \"no trend\"."
  },
  {
    "id": "meaning",
    "target": "#lensBlock",
    "fallback": "#card",
    "needsResult": true,
    "text": "This part says what the result could mean for energy providers and farmers. It is regional screening only: an average over a large area, not advice for one site."
  },
  {
    "id": "region",
    "target": "#w, #s, #e, #n",
    "text": "Try your own region: type West, South, East and North in degrees, then press Show trend. Custom regions need the full dataset; the demo regions always work. That's the tour, enjoy exploring!"
  }
];

// The Globe-view tutorial: a separate list, shown the first time Globe view is opened and replayed by
// the replay button while Globe view is active. Same fields as above, plus:
//   globeAction  name of a function of the globe (web/globe/globe.js) to call first, e.g. to turn the
//                globe so that the regions are in sight
// A step whose target is not in the page (the trend maps did not load, say) is skipped quietly.
const GUIDE_STEPS_GLOBE = [
  {
    "id": "globe",
    "target": "#globeBox",
    "text": "This is Earth. Drag to spin it and scroll to zoom."
  },
  {
    "id": "regions",
    "target": "#globeRegions",
    "fallback": "#globeBox",
    "globeAction": "showRegions",
    "text": "The cyan boxes are our demo regions. Click one to see its trend below."
  },
  {
    "id": "switch",
    "target": "#trendSwitch",
    "text": "Turn the trend map on or off here."
  },
  {
    "id": "variables",
    "target": "#trendList",
    "text": "Pick a variable here. Temperature is the clearest one."
  },
  {
    "id": "legend",
    "target": "#trendLegend",
    "text": "Warm colours mean an increase per decade, cool colours a decrease. Faded cells are not statistically significant, which is not the same as no trend."
  },
  {
    "id": "scenarios",
    "target": "#demos",
    "text": "Click a scenario to load its chart and what it means for solar, wind, hydro or farming."
  }
];

// The "?" buttons: <button class="tip" data-tip="KEY"> in web/index.html.
const GUIDE_TIPS = {
  "pvalue": {
    "label": "p-value",
    "text": "The p-value is the chance of seeing a trend this strong if there were really no trend, only random ups and downs. A small one (below 0.05) means chance is an unlikely explanation."
  },
  "ci95": {
    "label": "95% range",
    "text": "The 95% range shows how sure we are about the change per decade: the real value is very likely inside it. If the range includes zero, the trend could be up, down or flat."
  },
  "significant": {
    "label": "significant",
    "text": "\"Significant\" means the trend is unlikely to be chance (p-value below 0.05). \"Not significant yet\" does not mean \"no trend\": the record may be too short or too noisy to tell."
  },
  "variation": {
    "label": "not enough variation",
    "text": "Some regions have almost no snow, so most months read zero. With so little variation the test cannot be trusted, so the card gives no verdict instead of a misleading one."
  }
};
