---
name: Earth System Trend Detective
colors:
  surface: '#fff8f6'
  surface-dim: '#ffd0bb'
  surface-bright: '#fff8f6'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#fff1eb'
  surface-container: '#ffeae1'
  surface-container-high: '#ffe2d6'
  surface-container-highest: '#ffdbcb'
  on-surface: '#2d1509'
  on-surface-variant: '#3e494b'
  inverse-surface: '#462a1b'
  inverse-on-surface: '#ffede6'
  outline: '#6e797b'
  outline-variant: '#bdc8cb'
  surface-tint: '#006876'
  primary: '#006673'
  on-primary: '#ffffff'
  primary-container: '#078090'
  on-primary-container: '#f8feff'
  inverse-primary: '#78d4e5'
  secondary: '#275fa5'
  on-secondary: '#ffffff'
  secondary-container: '#81b2fe'
  on-secondary-container: '#004383'
  tertiary: '#a23900'
  on-tertiary: '#ffffff'
  tertiary-container: '#c4511b'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#9eefff'
  primary-fixed-dim: '#78d4e5'
  on-primary-fixed: '#001f24'
  on-primary-fixed-variant: '#004e59'
  secondary-fixed: '#d5e3ff'
  secondary-fixed-dim: '#a8c8ff'
  on-secondary-fixed: '#001b3c'
  on-secondary-fixed-variant: '#004689'
  tertiary-fixed: '#ffdbce'
  tertiary-fixed-dim: '#ffb599'
  on-tertiary-fixed: '#370e00'
  on-tertiary-fixed-variant: '#7f2b00'
  background: '#fff8f6'
  on-background: '#2d1509'
  surface-variant: '#ffdbcb'
typography:
  display-lg:
    fontFamily: Nunito Sans
    fontSize: 48px
    fontWeight: '800'
    lineHeight: 56px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Nunito Sans
    fontSize: 36px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Nunito Sans
    fontSize: 32px
    fontWeight: '700'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Nunito Sans
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-sm:
    fontFamily: Nunito Sans
    fontSize: 20px
    fontWeight: '700'
    lineHeight: 28px
  body-lg:
    fontFamily: Nunito Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Nunito Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-lg:
    fontFamily: Nunito Sans
    fontSize: 15px
    fontWeight: '600'
    lineHeight: 20px
  label-md:
    fontFamily: Nunito Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  metric-display:
    fontFamily: Nunito Sans
    fontSize: 40px
    fontWeight: '800'
    lineHeight: 44px
    letterSpacing: -0.02em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 2.5rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system channels the tactile, wonder-filled authority of an interactive science museum paired with the precision of a high-trust data dashboard. The emotional signature is warm, scholarly, curious, and welcoming—firmly resisting both dystopian dark-mode sci-fi tropes and dry, intimidating institutional enterprise software.

### Tone & Character
- **Inquisitive & Inviting:** Interfaces balance discovery with rigorous clarity. Micro-copy and data calls read as engaging findings rather than raw database dumps.
- **Museum-Grade Credibility:** Visual warmth is never synonymous with imprecision. Editorial rigor, high-contrast typography, and explicit data sourcing elevate user trust.
- **Tactile Warmth:** Surfaces mimic textured vellum, warm exhibit placards, and physical specimens, offset by a focused, deep-sea/night-sky globe observation theater.

## Colors

The palette establishes an earthy, archival base punctuated by crisp environmental accents.

### Core Canvas & Surfaces
- **Page Background:** `#FBF3E4` (Warm Cream). Replaces stark digital white with a rich, paper-like exhibition foundation.
- **Panel Surface:** `#FFFFFF` with a structural `1px` border of `#EAD9BC`.
- **Subtle / Secondary Sections:** `#F3E4C8` for nested sub-panels, tool shelves, and callout wells.

### Ink & Hierarchy
- **Text Primary:** `#3A2218` (Deep Brown-Ink), ensuring robust AAA accessibility (> 7:1 contrast) against warm cream and white surfaces.
- **Text Secondary:** `#6B4A3A` for metadata, captions, and secondary metric labels.

### Interactive & Semantic Accents
- **Brand Primary:** `#1F8A9A` (Teal), shifting to `#176E7B` on active hover states. Text on primary is pure `#FFFFFF`.
- **Trend Positive / Increase:** `#E0652F` (Warm Terra Cotta/Orange). Non-significant state: `#F5BAA2`.
- **Trend Negative / Decrease:** `#3B6FB6` (Scientific Cerulean). Non-significant state: `#A8C4E6`.
- **Mascot & Discovery Accent:** `#D9552B` (Fox-Orange). Reserved strictly for gamified discovery flags, badge highlights, and mascot elements; never used directly on trend plots.

### Stage Environment (Globe & Spatial Views)
- **Map / Globe Stage:** `#0B2530` (Deep Teal-Navy) creates an isolated, high-contrast viewport.
- **Atmospheric Glow:** `#3CE0D0` (Bioluminescent Cyan) highlighting vector tracks and orbital edges.
- **Stage Label Chips:** `#FBF3E4` background with `#3A2218` ink for effortless readability over deep stage depths.

## Typography

Typography relies on **Nunito Sans** throughout to marry organic geometry with high technical clarity across data displays.

### Sizing Rules & Accessibility Safeguards
- **Minimum Thresholds:** Continuous reading body text must never drop below `16px`. Auxiliary tags, chart legends, and metadata chips bottom out at `14px`.
- **Tabular Figures:** All metrics, scientific intervals, and timestamp counters must strictly activate tabular figures (`font-variant-numeric: tabular-nums`) to prevent horizontal jitter during real-time data scrubbing.
- **Editorial Headings:** Larger headlines employ tight negative tracking (`-0.01em` to `-0.02em`) to retain structural presence and prevent rounded letterforms from feeling juvenile.

## Layout & Spacing

The layout model favors expansive exhibition framing with breathing room between complex analytical tools and interactive visualizers.

### Grid & Canvas Structure
- **Desktop (1024px+):** 12-column responsive fluid grid within a `1440px` maximum viewport constraint. Margins scale at `2.5rem` (`40px`), with `1.5rem` (`24px`) gutters.
- **Tablet (768px - 1023px):** 8-column grid with `1.5rem` margins and gutters.
- **Mobile (< 768px):** 4-column flow with `1.25rem` margins and `1rem` gutters. Metric comparison cards reflow from multi-column rows into vertically stacked inspection feeds.

### Spatial Rhythms
- **Information Enclosures:** Data cards use `space-lg` internal padding to prevent numeric density from overwhelming casual observers.
- **Metric Clustering:** Labels and their corresponding numbers maintain a tight `space-xs` gap to preserve immediate visual attribution.

## Elevation & Depth

Visual hierarchy abandons cold, desaturated dropshadows in favor of warm, low-slung ambient diffusion reminiscent of incandescent museum display case lighting.

### Elevation Levels
- **Level 0 (Flat/Substratum):** Page canvas (`#FBF3E4`) and recessed tool areas (`#F3E4C8`) with zero elevation.
- **Level 1 (Exhibition Placards & Cards):** Panel background (`#FFFFFF`) with a `1px` border of `#EAD9BC` combined with:
  `box-shadow: 0 4px 16px -2px rgba(107, 74, 58, 0.08), 0 2px 6px -1px rgba(107, 74, 58, 0.04)`.
- **Level 2 (Active Flyouts & Inspect Modals):**
  `box-shadow: 0 12px 32px -4px rgba(58, 34, 24, 0.12), 0 4px 12px -2px rgba(58, 34, 24, 0.06)`.
- **Level 3 (Dark Stage Globe Isolation):** Internal viewport depth achieved via inset containment:
  `box-shadow: inset 0 0 40px rgba(0, 0, 0, 0.45)`.
  Vector globe layers cast a radiant luminescence using `drop-shadow(0 0 12px rgba(60, 224, 208, 0.35))`.

## Shapes

The design system standardizes on generous, organic geometry to reinforce approachability and scientific handling comfort.

- **Standard Enclosures (Cards, Panels, Modals):** Feature `1rem` to `1.25rem` (16px to 20px) border radii, softening rigorous data charts.
- **Input Elements & Field Controls:** Fixed at `0.75rem` (12px) to match primary interactive targets.
- **Status Indicators, Tool Badges & Filter Pills:** Set to full circular pill radii (`9999px`) for quick scanning.
- **Stage Observation Windows:** Globe viewports adopt an outer `1.25rem` corner radius, harmonizing with adjacent light-toned dashboard modules.

## Components

### Buttons
- **Primary Action:** Solid `#1F8A9A` fill, white `#FFFFFF` text, `0.75rem` radius, bold label (`15px`). Hover: `#176E7B` with slight upward translation (`-1px`).
- **Secondary / Scientific Tool Button:** `#FFFFFF` background with `1.5px` border in `#EAD9BC`, text in `#3A2218`. Hover: background fills `#F3E4C8`.
- **Ghost/Tertiary:** No border, transparent background, text in `#1F8A9A`.

### Cards & Placards
- **Data Trend Card:** Pure `#FFFFFF` panel, `16px` radius, `1px` border of `#EAD9BC`. Includes a discrete header compartment with secondary brown text (`#6B4A3A`) and primary value display using tabular figures.
- **Hypothesis / Detective Card:** Subtle cream fill (`#F3E4C8`) with a left structural stroke (`4px`) in `#1F8A9A` to highlight curated anomalies.

### Chips & Filter Pills
- **Category Filter (Default):** `#FFFFFF` fill, `#EAD9BC` border, `#3A2218` text.
- **Category Filter (Active):** `#1F8A9A` fill, `#FFFFFF` text, no border.
- **Stage Label Chips (for Dark Map):** Background `#FBF3E4`, text `#3A2218`, `12px` padding, pill radius, paired with a `0 2px 8px rgba(0,0,0,0.3)` anchor shadow.

### Form Inputs & Selection
- **Text & Numeric Inputs:** White `#FFFFFF` background, `1.5px` border in `#EAD9BC`, text in `#3A2218`. Focus state introduces a crisp `2px` ring in `#1F8A9A` with no offset.
- **Checkboxes & Radios:** `20px` touch targets. Selected state filled with `#1F8A9A` featuring a crisp white geometric indicator.

### Data Trend Badges & Anomaly Indicators
- **Positive Delta:** Background tint `rgba(224, 101, 47, 0.12)`, text `#E0652F`, upward trend vector icon.
- **Negative Delta:** Background tint `rgba(59, 111, 182, 0.12)`, text `#3B6FB6`, downward trend vector icon.
- **Investigation / Detective Badges:** `#D9552B` (Fox-Orange) filled circular tags reserved for user-curated discoveries, bookmark bookmarks, and interactive quiz achievements.