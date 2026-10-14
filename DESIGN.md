---
name: "Sideband"
description: "An independent listening journal: familiar music leads to new discoveries."
colors:
  paper: "#f7f8f3"
  paper-raised: "#fffefa"
  paper-sunk: "#edf0e8"
  ink: "#202e27"
  ink-2: "#46584d"
  muted: "#637067"
  line: "#dce2d7"
  line-strong: "#829384"
  accent: "#315d48"
  accent-hover: "#244735"
  rail: "#183e30"
  rail-ink: "#f3f4e8"
  rail-muted: "#becfc1"
  rail-active: "#325541"
  sticker: "#e4ebda"
  sticker-ink: "#33543d"
  button-ink: "#fffefa"
  pos: "#347754"
  neg: "#b64c32"
  pos-wash: "#e8f0e4"
  neg-wash: "#faeee8"
  focus: "#487958"
  error-ink: "#a53f29"
  dark-paper: "#121d19"
  dark-paper-raised: "#192620"
  dark-paper-sunk: "#223129"
  dark-ink: "#edf1e7"
  dark-ink-2: "#c4d0c6"
  dark-muted: "#a1b2a6"
  dark-line: "#34463a"
  dark-line-strong: "#657a69"
  dark-accent: "#b6d5a8"
  dark-accent-hover: "#d0e9c7"
  dark-rail: "#0c2118"
  dark-rail-active: "#284734"
  dark-sticker: "#304b37"
  dark-sticker-ink: "#c4dfb5"
  dark-button-ink: "#16221a"
  dark-pos: "#91c49e"
  dark-neg: "#ef9c83"
  dark-pos-wash: "#243c2b"
  dark-neg-wash: "#3c2923"
  dark-focus: "#b6d5a8"
  dark-error-ink: "#ef9c83"
typography:
  display:
    fontFamily: "Fraunces,Georgia,serif"
    fontSize: "2.625rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-.03em"
  headline:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "-.025em"
  title:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: "1.25rem"
    fontWeight: 500
    lineHeight: 1.2
  artist:
    fontFamily: "Fraunces,Georgia,serif"
    fontSize: "1.875rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-.025em"
  body:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  button:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: ".875rem"
    fontWeight: 500
    lineHeight: 1.3
  button-primary:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: ".875rem"
    fontWeight: 600
    lineHeight: 1.3
  navigation:
    fontFamily: "\"DM Sans\",\"Helvetica Neue\",sans-serif"
    fontSize: ".9375rem"
    fontWeight: 400
    lineHeight: 1.55
  table-number:
    fontFamily: "ui-monospace,\"SFMono-Regular\",Menlo,monospace"
    fontSize: ".75rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  control: "8px"
  radius: "12px"
  radius-pill: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
  s8: "72px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.button-ink}"
    typography: "{typography.button-primary}"
    rounded: "{rounded.control}"
    padding: "11px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
  button-secondary-hover:
    backgroundColor: "{colors.paper-sunk}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.muted}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "9px 15px"
  input-search:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  navigation-item:
    textColor: "{colors.rail-muted}"
    typography: "{typography.navigation}"
    rounded: "{rounded.control}"
    padding: "10px 16px"
  navigation-item-current:
    backgroundColor: "{colors.rail-active}"
    textColor: "{colors.rail-ink}"
  pick-chip:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.radius-pill}"
    padding: "8px 12px"
  starting-point:
    backgroundColor: "{colors.paper-sunk}"
    textColor: "{colors.ink}"
    rounded: "{rounded.radius}"
    padding: "26px 24px"
  artist-choice:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "14px 4px"
  artist-choice-selected:
    backgroundColor: "{colors.pos-wash}"
    textColor: "{colors.accent}"
  recommendation-row:
    textColor: "{colors.ink}"
    padding: "26px 0"
  evidence-details:
    textColor: "{colors.ink-2}"
  match-percentile:
    backgroundColor: "{colors.sticker}"
    textColor: "{colors.sticker-ink}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
---

# Design System: Sideband

## Overview

**Creative North Star: "The independent listening journal"**

Sideband pairs a deep forest navigation rail with a warm, light work surface. Fraunces gives music names and page titles an editorial voice; DM Sans keeps controls, explanations, and dense data direct. Dark mode preserves the same hierarchy for evening listening.

Music names, familiar connections, and listening actions establish the identity. Thin dividers and tonal areas organize the workspace; photographic artist results appear only when provided by the lookup service. The interface does not invent album artwork. Native controls and compact disclosures keep the product approachable without hiding its evidence.

This document records the implemented system in `musicfinder/web/style.css`, `musicfinder/web/index.html`, and `musicfinder/web/app.js`. The frontmatter is the portable token layer; the stylesheet implements these values. Theme overrides use `dark-` keys here because the source reassigns the same CSS variables. `PRODUCT.md` holds product constraints; `.impeccable/surfaces/listening-space.md` holds the redesign direction and surface strategy. `.impeccable/design.json` extends this document with motion, breakpoints, shadows, and component previews.

**Key Characteristics:**

- A persistent forest rail, with all six destinations retained on mobile.
- Editorial music typography paired with plain, compact controls.
- Warm tonal surfaces, thin dividers, and restrained floating shadows.
- Readable light and dark themes with visible keyboard focus.
- Supporting evidence revealed through native disclosures.

## Colors

Forest greens and warm paper neutrals create a quiet listening workspace. The palette is shared across the six routes; evidence and feedback introduce a restrained clay negative tone.

### Primary

- **Forest accent** (`accent`, `accent-hover`): primary actions, text links, selection, range controls, and progress. The CSS `--button` variable aliases `--accent`.
- **Forest rail** (`rail`, `rail-active`, `rail-ink`, `rail-muted`): the permanent navigation surface, active destination, brand, and supporting navigation text.
- **Sage percentile** (`sticker`, `sticker-ink`): the candidate-percentile badge. Its visual weight is lower than the artist name.
- **Focus** (`focus`): the keyboard outline on work surfaces; the rail uses `rail-ink` for focus contrast.

### Secondary

- **Positive evidence** (`pos`, `pos-wash`): supporting meter segments, taste bars, selected buttons, and liked rows.
- **Negative evidence** (`neg`, `neg-wash`, `error-ink`): opposing meter segments, disliked rows and chips, and error text. The wash is a state surface, not a decorative accent.

### Neutral

- **Warm paper** (`paper`, `paper-raised`, `paper-sunk`): the page, editable/floating surfaces, and recessed groups such as the starting point and tuning controls.
- **Forest ink** (`ink`, `ink-2`, `muted`): primary text, explanations, and secondary metadata.
- **Dividers and control edges** (`line`, `line-strong`): quiet row boundaries and stronger field/button outlines.
- **Primary-action text** (`button-ink`): the text paired with the accent fill.

### Theme behavior

The System option follows `prefers-color-scheme`; Light and Dark set `data-theme` on the root and persist under `mf.theme`. The dark-prefixed frontmatter entries record the actual overrides. Rail foregrounds (`rail-ink`, `rail-muted`) remain shared across themes. Use the semantic variables in components instead of copying a light value into a dark surface.

**The Signal Color Rule.** Use positive and negative colors for evidence, selection, and feedback states; keep ordinary navigation and primary actions in the accent family.

## Typography

**Display font:** Fraunces with Georgia and serif fallbacks.
**Body and control font:** DM Sans with Helvetica Neue and sans-serif fallbacks.
**Numeric font:** the system monospace stack for tables and chart ticks; other numeric labels use tabular figures in DM Sans.

The pairing gives artist discovery a literary character while keeping repeated actions compact and legible. Page titles use the frontmatter `display` role; recommendation artist names use `artist`. Headline and title roles remain sans serif. Paragraphs are limited to 70 characters where the layout permits; the model explanation allows 75 characters.

### Hierarchy and responsive type

- **Display:** page titles use `display`, with a 22-character maximum width. At 1180px and below they become 2.25rem; at 650px and below they become 2.125rem. Setup's title allows 24 characters on desktop and 20 on mobile.
- **Headline / title:** section headings use `headline`; smaller headings use `title`. Starting-point headings use Fraunces at 1.5rem with a 1.2 line height.
- **Artist:** discovery names use `artist`; at 650px and below they become 1.625rem. Explore territory rows use 1.5rem.
- **Body:** default text uses `body`. Secondary explanations commonly use .875rem or .8125rem; supporting metadata commonly uses .75rem.
- **Controls:** `button` and `button-primary` share size and line height; the primary role increases weight. Navigation uses `navigation`, rising to weight 600 for the current destination.
- **Data:** `table-number` uses tabular figures. Chart ticks use 11px monospace; chart labels use 13px DM Sans.

The CSS declares a type scale of .875rem, 1rem, 1.25rem, 1.5rem, 2rem, and 2.625rem. Component-specific music, metadata, and mobile sizes are intentional rather than an enforced mathematical ratio.

### Local font assets

`musicfinder/web/dm-sans-regular.ttf` supplies weight 400. `musicfinder/web/dm-sans-semibold.ttf` is declared for weights 500–700. `musicfinder/web/fraunces-medium.ttf` is declared for weights 400–600. All three use `font-display: swap`. Keep `musicfinder/web/dm-sans-OFL.txt` and `musicfinder/web/fraunces-OFL.txt` with the assets; both record SIL Open Font License 1.1 attribution.

**The Music Voice Rule.** Use Fraunces for page titles, discovery artist names, territory headings, and key editorial summaries. Keep form controls and song rows in DM Sans.

## Layout

The desktop shell has a fixed left rail and a centered work area with a maximum outer width of 1350px. The rail is 212px wide by default; the work area has 48px top, 44px horizontal, and 72px bottom padding. At widths of at least 1550px, top padding grows to 60px. Shared spacing tokens run from `s1` through `s8`; use their 4/8/12/16/24/32/48/72px rhythm for new work while respecting existing control-specific dimensions.

The Setup workspace pairs a flexible artist grid with a 280px starting-point area, separated by 36px. The summary sticks 32px from the top. Artist choices form three flat columns on wide screens. Recommendation rows use rank, flexible music content, and an 80px percentile area, with 16px gaps. Explanatory tables scroll within their own container instead of widening the page.

### Responsive thresholds

| Width | Implemented behavior |
| --- | --- |
| 1180px and below | Rail becomes 186px; main padding becomes 36px 30px 60px. Starting point becomes 240px with a 24px gap. Artist choices use two columns. Unequal split sections stack. |
| 900px and below | Rail becomes an in-flow header, navigation runs horizontally, and Appearance sits at the top right. Main padding becomes 32px 28px 56px. Setup still uses a 260px summary column. Even split sections and song recommendation actions stack. |
| 650px and below | All six destinations form a three-column, two-row grid. Main padding becomes 28px 20px 48px. Setup stacks; artist choices remain two columns. Recommendation rank is hidden, leaving a flexible music column and 66px percentile area. |

On small Setup screens, the discovery action is fixed 12px from both sides and the bottom. It shows the selected count, action, and supporting status; the footer reserves 150px below its content. Toasts sit 132px above the bottom on small screens. The starting-point summary itself is in normal flow. Navigation, style choices, selected chips, and song actions have at least 44px mobile height. Tuning is open by default when the view is created above 650px and collapsed by default at narrower widths.

## Elevation & Depth

Most depth comes from paper tones and borders. Recommendation rows, artist choices, accuracy tables, and summary metrics are flat. Starting-point and tuning groups use the recessed tone without shadows. The shared `--shadow` is `0 8px 28px #142c241c` in light mode and `0 8px 28px #0005` in dark mode; it is used on tooltips, toasts, and the mobile discovery action. Those values live in the sidecar's shadow extension because the frontmatter schema does not accept shadow tokens.

Buttons transition background and border colors over 160ms. Recommendation feedback backgrounds and progress widths transition over 200ms. Both use `cubic-bezier(.16,1,.3,1)`. The loading indicator breathes over 1.5s with `ease-in-out`. Reduced-motion mode disables animations, transitions, and smooth scrolling; tag exploration also checks that preference before scrolling.

**The Floating Surface Rule.** Keep ordinary sections and recommendation rows flat. Use the shared shadow for content that floats above the workspace: tooltips, toasts, and the mobile discovery action.

## Shapes

Controls and navigation use the gently curved `control` radius; recessed groups, empty states, toasts, and the mobile action use `radius`. Selected-artist chips and style filters use `radius-pill`. Recommendation and artist-choice rows use square, flat edges and a single divider. Mobile navigation uses a 6px radius. Real artist-search portraits and initial fallbacks are circular. Import areas use a dashed outline, and inline navigation symbols are simple stroked SVGs.

## Components

### Buttons

The primary action has an accent fill, contrasting action text, and the `button-primary` role. Secondary buttons use a transparent surface and strong outline; quiet buttons keep a transparent border and muted text. Default controls are at least 44px high. Hover uses the recessed surface and ink outline for secondary controls, and the accent hover fill for primary controls. Disabled buttons use .5 opacity and a not-allowed cursor. Pressed buttons combine a positive wash, positive outline, and `aria-pressed`.

Keyboard focus is a 3px outline with a 4px offset and 4px radius. In the rail it switches to the rail's light foreground. Native focus, hover, disabled, and selected semantics are retained.

### Inputs and native controls

Text fields, search, selects, and textareas use a raised surface, strong outline, control radius, and 10px 14px padding. Their default minimum height is 46px; the prominent artist search is 50px. Search fields stretch within their grid. Textareas allow vertical resizing and start at 150px high. Placeholder text uses `muted`; the caret, ranges, and radio controls use the accent. Appearance remains a native select with System, Light, and Dark options.

### Navigation

The forest rail contains the record-groove wordmark and six labeled SVG destinations. Desktop links are at least 46px high, with 19px icons. Hover and current states share the rail-active surface and rail-ink text; the current destination also has weight 600 and `aria-current="page"`. The header preserves all six labeled links at smaller widths. A keyboard skip link moves focus to the main region, and route changes update the document title and current destination.

### Artist choices, chips, and starting point

Artist choices are text-first, divider-separated buttons, with a name and Pick/Picked marker. A selection changes the background and label, updates `aria-pressed`, and adds a check icon. They are at least 93px high on desktop and 86px on mobile. Style filters sit inside a native Browse by style disclosure; the active style uses ink over paper.

Saved picks appear as removable pills in the starting-point area. Loved picks use the raised surface; disliked picks use the negative wash and strike-through. The chip area wraps and scrolls vertically after 300px. The starting point shows selection count, save status, and the state-dependent discovery action; its sticky desktop and fixed mobile behaviors are defined in Layout.

### Recommendation rows and progressive evidence

Music names and the “Because of” connection lead each row. A compact sage badge is explicitly labeled percentile. Preview, external music, and feedback actions wrap below. A rating leaves the row in place, applies the corresponding wash, and exposes a saved message and Undo. Refreshed results apply the changed taste.

The native “Why this match” disclosure contains the supporting/opposing signal meter, an ink net-score mark, a textual legend, and a table of signed effects. The table gives the evidence without depending on color or pointer tooltips. Provisional like estimates and simulated truth, when present in the data, are separately labeled. Model explanations and tuning use their own disclosures so they do not compete with the list.

### Songs and playback states

Song names use compact DM Sans hierarchy with the artist beneath. The action group is right-aligned on wide screens and stacks below on narrower ones. A preview initially says it is being checked; a play button appears only after a matching clip is available. Unavailable, check-failed, playback-failed, retry, cancel, and pause states retain explicit text. Preview controls use the recessed surface and accent text.

### Data, feedback, and recovery

Accuracy charts use subdued grid lines, tabular labels, and clear foreground marks. Tables sit inside horizontal scrolling containers. Empty and error states use a recessed area with readable explanation and a concrete next action where available. Loading has a text status and a small progress treatment. Service, job, save, rating, and toast messages use status semantics; synthetic demo data has a visible banner. Import, backup, and data management stay in native Setup disclosures.

## Do's and Don'ts

### Do:

- Do use the existing semantic CSS variables so theme changes apply to every component.
- Do keep artist names and familiar connections prominent, with supporting model detail in disclosures.
- Do retain visible focus, native controls, textual state labels, and reduced-motion behavior.
- Do keep feedback in its existing row with a saved message and Undo until the listener refreshes.
- Do preserve all six navigation destinations and the fixed discovery action on small Setup screens.
- Do label candidate percentile, provisional estimates, and synthetic demo evidence distinctly.

### Don't:

- Don't add fabricated artwork, testimonials, listening counts, or accuracy claims.
- Don't turn ordinary recommendation rows into stacked raised cards.
- Don't use color alone to communicate selected artists, ratings, errors, or signal direction.
- Don't replace native selects, ranges, radio buttons, or disclosure semantics with decorative imitations.
- Don't introduce external font requests; use the local font files and retain their licenses.
- Don't change a candidate percentile into a like probability or present unavailable previews as playable.
