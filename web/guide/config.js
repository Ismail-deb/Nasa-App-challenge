// Configuration of the optional guide (web/guide/guide.js).
//
// The guide's name is defined HERE AND NOWHERE ELSE. Every label, tutorial line and tooltip
// is built from it; texts below use the placeholder {name}. To rename the guide, change this line.
const GUIDE_NAME = "Comet";

// The character's three poses: one transparent picture each, all on the same canvas size and with the
// feet in the same place, so swapping between them never makes him jump. If any of them fails to load,
// the guide falls back to a small drawn drone.
const GUIDE_IMAGES = {
  "neutral": "/static/guide/assets/comet-neutral.webp",
  "talking": "/static/guide/assets/comet-talking.webp",
  "pointing": "/static/guide/assets/comet-pointing.webp"
};

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
