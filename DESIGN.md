---
name: "Sideband"
description: "An independent listening journal in record-sleeve ivory, wine, and amber."
colors:
  paper: "#faf7f0"
  paper-raised: "#fffdf7"
  paper-sunk: "#f0e9de"
  ink: "#30252a"
  ink-2: "#57494e"
  muted: "#6d6065"
  line: "#ded3cf"
  line-strong: "#928087"
  accent: "#7a304b"
  accent-hover: "#5e2039"
  rail: "#331c2a"
  rail-ink: "#fff3dc"
  rail-muted: "#d9bfcc"
  rail-active: "#593247"
  rail-current: "#eec36d"
  rail-current-ink: "#392332"
  record-label: "#eec36d"
  selection: "#f3e4ea"
  sticker: "#f4dfa5"
  sticker-ink: "#634514"
  button-ink: "#fffdf7"
  pos: "#27715e"
  neg: "#ac4149"
  pos-wash: "#e5f0eb"
  neg-wash: "#fae9e8"
  focus: "#a64b69"
  error-ink: "#a13240"
  dark-paper: "#19151a"
  dark-paper-raised: "#231c23"
  dark-paper-sunk: "#2d242b"
  dark-ink: "#f6eee6"
  dark-ink-2: "#dbccd2"
  dark-muted: "#baa7b1"
  dark-line: "#493840"
  dark-line-strong: "#8b727f"
  dark-accent: "#f3b4ca"
  dark-accent-hover: "#ffd2e0"
  dark-rail: "#21121e"
  dark-rail-active: "#4d2c40"
  dark-selection: "#432c3b"
  dark-sticker: "#513f27"
  dark-sticker-ink: "#f1cf8b"
  dark-button-ink: "#341526"
  dark-pos: "#8dcebb"
  dark-neg: "#f1a195"
  dark-pos-wash: "#253c36"
  dark-neg-wash: "#43262b"
  dark-focus: "#f3b4ca"
  dark-error-ink: "#f1a195"
typography:
  display:
    fontFamily: "Fraunces,Georgia,serif"
    fontSize: "2.375rem"
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
    fontSize: "1.75rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-.025em"
  listening-artist:
    fontFamily: "Fraunces,Georgia,serif"
    fontSize: "2.75rem"
    fontWeight: 500
    lineHeight: 1.08
    letterSpacing: "-.03em"
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
    fontSize: ".875rem"
    fontWeight: 400
    lineHeight: 1.55
  table-number:
    fontFamily: "ui-monospace,\"SFMono-Regular\",Menlo,monospace"
    fontSize: ".75rem"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  square: "0px"
  label: "3px"
  percentile: "4px"
  masthead-control: "6px"
  control: "8px"
  radius: "10px"
  surface: "12px"
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
    rounded: "{rounded.square}"
    padding: "12px 0"
  navigation-item-current:
    backgroundColor: "transparent"
    textColor: "{colors.rail-current}"
  pick-chip:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.radius-pill}"
    padding: "8px 12px"
  starting-point:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "28px"
  artist-choice:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    padding: "14px 4px"
  artist-choice-selected:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.accent}"
  recommendation-row:
    textColor: "{colors.ink}"
    padding: "26px 0"
  evidence-details:
    textColor: "{colors.ink-2}"
  match-percentile:
    backgroundColor: "{colors.sticker}"
    textColor: "{colors.sticker-ink}"
    rounded: "{rounded.percentile}"
    padding: "10px 12px"
  button-pressed:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.accent}"
  listening-card:
    backgroundColor: "{colors.paper-raised}"
    textColor: "{colors.ink}"
    rounded: "{rounded.surface}"
    padding: "34px 36px 24px"
  queue-item:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.square}"
    padding: "10px 12px"
  queue-item-current:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.accent}"
  saved-choice-filter:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
---

# Design System: Sideband

## Overview

**Creative North Star: "The independent listening journal"**

Sideband takes its colors from record sleeves and independent music publishing: an ivory work surface, a deep aubergine masthead, wine-colored actions, and amber wayfinding. Fraunces gives music names and page titles an editorial voice; DM Sans keeps controls, explanations, and dense data direct. Dark mode uses aubergine surfaces and pale rose accents while retaining the amber wayfinding.

Music names, familiar connections, and listening actions establish the identity. One raised listening surface anchors the weekly workspace; numbered selections and collections remain flat. Thin dividers, native controls, and compact disclosures keep the product approachable without hiding its evidence. Artist photographs appear only when supplied by lookup results; the interface does not invent album artwork.

The frontmatter records the implemented tokens. `musicfinder/web/style.css` supplies the shared base; `listening-desk.css` and `taste-filters.css` load afterward and govern the final shell, weekly workspace, and saved-choice filters. `index.html` and `app.js` supply the components and behavior. `PRODUCT.md` holds product constraints, `.impeccable/surfaces/listening-space.md` holds surface strategy, and `.impeccable/design.json` adds preview snippets, motion, breakpoints, and shadows.

**Key Characteristics:**

- A horizontal aubergine masthead with six destinations, amber active underlines, and shared service and appearance controls.
- One artist in focus beside a numbered weekly queue, followed by keepers and reversible decisions.
- Editorial music typography paired with compact native controls.
- Ivory and aubergine surface tones, thin dividers, and shadows reserved for floating content.
- Visible keyboard focus, textual state labels, and progressively disclosed evidence.

## Colors

Ivory, wine, aubergine, and amber connect Sideband to record sleeves, liner notes, and record labels. The palette remains distinct from Milo's chalk, carbon, and burnt-orange training identity.

### Primary

- **Wine accent** (`accent`, `accent-hover`): primary actions, links, range controls, progress, and taste bars. The CSS `--button` aliases `--accent`; dark mode uses pale rose for this role.
- **Aubergine masthead** (`rail`, `rail-ink`, `rail-muted`, `rail-active`): the horizontal navigation ground, foregrounds, and divider/select edges. The established variable names are retained even though the fixed rail is gone.
- **Rose selection** (`selection`): pressed controls, selected artist choices, and the current weekly queue entry. It stays distinct from positive-feedback washes.
- **Rose focus** (`focus`): keyboard outlines on the work surface. Masthead controls use the light `rail-ink` outline.

### Secondary

- **Amber destination** (`rail-current`): current navigation text and its three-pixel underline. `rail-current-ink` remains a compatibility token; current masthead navigation uses no filled amber tab.
- **Amber record label** (`record-label`): the established token for wordmark hover. It does not recolor the white-and-pink record logo.
- **Amber information** (`sticker`, `sticker-ink`): close-match/wildcard labels and candidate-percentile badges.

### Tertiary

- **Positive evidence** (`pos`, `pos-wash`): supporting meter segments and liked feedback.
- **Negative evidence** (`neg`, `neg-wash`, `error-ink`): opposing signals, disliked choices, and error text.

### Neutral

- **Record-sleeve ivory** (`paper`, `paper-raised`, `paper-sunk`): page, focused/editable/floating surfaces, and recessed controls. Dark mode translates these layers into aubergine neutrals.
- **Wine ink** (`ink`, `ink-2`, `muted`): primary text, connections and explanations, secondary metadata.
- **Edges** (`line`, `line-strong`): quiet row boundaries and stronger group/field edges.
- **Action text** (`button-ink`): foreground paired with the primary-action fill.

System follows `prefers-color-scheme`; Light and Dark set the root theme and persist under `mf.theme`. Dark-prefixed frontmatter entries record actual overrides. Masthead foregrounds, amber navigation, and the record-label hover token remain shared across themes. Components use semantic CSS variables so these changes propagate together.

**The Signal Color Rule.** Reserve green for positive evidence and liked feedback. Use wine and rose for selections, actions, and taste data; use amber for current navigation and compact information labels.

## Typography

**Display font:** Fraunces with Georgia and serif fallbacks.

**Body and control font:** DM Sans with Helvetica Neue and sans-serif fallbacks.

**Numeric font:** the system monospace stack for tables and chart ticks; queue numbers and other compact data use tabular figures in DM Sans.

Page titles use the `display` role; the weekly title changes tracking to -.025em. The focused weekly artist uses `listening-artist`, while ranked recommendations use `artist`. Sans-serif headlines and titles distinguish task structure from the music. Body paragraphs usually stop at 70 characters; the weekly connection stops at 60 characters.

### Hierarchy and responsive type

- **Page title:** 2.375rem on desktop. At 760px and below, secondary-page titles become 2rem and the weekly title becomes 1.75rem.
- **Focused artist:** 2.75rem on wide screens, 2.25rem at 1050px and below, and 2rem at 760px and below. The name wraps at 17 characters rather than truncating.
- **Other music headings:** ranked artist names use 1.75rem; territory headings use 1.75rem, territory artists 1.5rem, and collection headings 1.5rem.
- **Body and controls:** body text is 1rem; connections use .9375rem on desktop and .875rem on phones. Buttons use .875rem with a stronger primary weight. Navigation uses .875rem, becoming .8125rem on phones.
- **Metadata:** queue and date metadata uses .6875rem–.8125rem. Numerical tables use `table-number`; chart ticks use 11px monospace.

The source keeps its shared .875rem/1rem/1.25rem/1.5rem/2rem/2.625rem scale; component-specific music and phone sizes are deliberate overrides.

### Local font assets

`musicfinder/web/dm-sans-regular.ttf` supplies weight 400. `musicfinder/web/dm-sans-semibold.ttf` is declared for weights 500–700. `musicfinder/web/fraunces-medium.ttf` is declared for weights 400–600. All three use `font-display: swap`. Retain `dm-sans-OFL.txt` and `fraunces-OFL.txt` beside the assets; both record SIL Open Font License 1.1 attribution. There are no external font requests.

**The Music Voice Rule.** Use Fraunces for page titles, discovery artist names, territory headings, and key editorial summaries. Keep form controls and song rows in DM Sans.

## Layout

The masthead is in normal document flow at every width. Its first row carries the record wordmark, short brand line when space permits, and shared Listen on and Appearance selects. A divider separates the six-link navigation row. The first three discovery destinations sit together; Your taste, Accuracy, and Setup align toward the right on wider screens.

The centered work area and footer have a 1240px maximum width. Main content has 40px top and 64px bottom padding on desktop. Shared spacing tokens preserve the 4/8/12/16/24/32/48/72px rhythm; component-specific dimensions reflect the implemented layouts.

The weekly introduction and date precede a progress line. The workspace pairs flexible artist content with a 338px queue and 42px gap. The active artist has one raised surface with 34px 36px 24px padding and a 425px minimum content height. Previous/Next and selection details sit below. Queue rows are flat, numbered, and internally scroll after 590px. Your keepers and Sorted this week form two equal columns below a stronger divider, with independently scrolling lists after 360px.

Setup pairs the artist grid with a 330px starting point across a 48px gap. The starting point sticks 32px from the top on desktop. Search and verdict filters in Your taste share a flat two-column index above their list. Tables scroll inside their own containers.

### Responsive thresholds

| Width | Implemented behavior |
| --- | --- |
| 1320px and below | Main/footer gain 36px side margins; queue becomes 310px with a 30px gap. |
| 1180px and below | Legacy unequal secondary-page splits stack. The listening-desk shell overrides the former rail layout. |
| 1050px and below | Brand line hides; queue becomes 270px with a 26px gap. Focused content uses 26px 24px 20px padding. Setup summary becomes 270px, and artist choices use two columns. |
| 900px and below | Secondary-page even splits and song recommendation actions stack. |
| 760px and below | Weekly artist, queue, and collections stack in reading order. Navigation stays one horizontally scrollable row with all six labels; icons hide. Main uses 22px side margins and 24px top padding. Queue scrolling begins after 310px. Setup stacks. Weekly decisions use a two-column button grid. |
| 650px and below | Saved-choice filters stack, with three equally sized scope buttons. Setup's discovery action becomes fixed 12px from the sides and bottom; the footer reserves 150px for it. |
| 420px and below | Side margins become 18px, masthead controls tighten, the decorative progress ticks hide, and collection headings stack. |

Phone artist padding is 22px 20px 18px. Masthead selects remain at least 44px high; the two leading weekly decisions are at least 46px high. Toasts sit 20px above the phone viewport bottom, or 140px above it on Setup. Native disclosures keep detail available without extending the initial listening surface.

## Elevation & Depth

Depth comes mainly from paper tones and borders. The focused weekly artist and Setup summary use the raised tone without a shadow. Queues, saved collections, ranked recommendations, and tables remain flat. The shared shadow is `0 8px 28px #3014211c` in light mode and `0 8px 28px #0005` in dark mode, used for tooltips, toasts, and the fixed mobile discovery action.

Buttons transition background and border colors over 160ms. Recommendation feedback backgrounds and progress widths transition over 200ms. Both use `cubic-bezier(.16,1,.3,1)`. The loading line breathes over 1.5s with `ease-in-out`. Reduced-motion mode disables animations, transitions, and smooth scrolling.

**The Floating Surface Rule.** Keep ordinary sections, queues, and recommendation rows flat. Use the shared shadow for tooltips, toasts, and the mobile discovery action.

## Shapes

Default controls use an 8px radius. Masthead selects use 6px, compact selection labels 3px, and percentile badges 4px. Notes, tuning, and ordinary empty states use 10px; the focused artist and Setup summary use 12px. Toasts use 8px. Removable picks and style filters remain pill-shaped. Navigation and queue entries use square edges; current navigation is an underline, and the active queue indicator is a small circle. Artist-search portraits and initial fallbacks are circular. Import areas retain dashed outlines.

## Components

### Buttons and fields

Primary actions use the wine/pale-rose fill and contrasting action text. Secondary actions use a transparent surface and strong outline; quiet actions use a transparent border and muted text. Hover applies a recessed surface and ink edge, or the primary hover fill. Default action height is 44px. Disabled actions use .5 opacity and a not-allowed cursor. Pressed controls combine rose wash, accent text/edge, and `aria-pressed`.

Text/search fields, native selects, and textareas use the raised tone, strong edge, 8px radius, and 10px 14px padding. Default field height is 46px; prominent artist search is 50px. Placeholder text is muted; carets, ranges, and radio controls use the accent. Keyboard focus is a 3px outline with 4px offset and 4px radius, switching to ivory in the masthead.

### Masthead and navigation

The horizontal aubergine masthead contains the record wordmark, six destinations, and shared native selectors. Links use 17px stroked SVGs and at least 53px height on desktop; phone links omit icons and use 50px height. Current navigation uses amber text, weight 600, a 3px underline, and `aria-current="page"`. Hover changes text to ivory. The destinations are This week, Songs, Explore, Your taste, Accuracy, and Setup; For you remains available through the full ranked-list link in This week.

Listen on updates all artist/song links, including keepers and cards available for Undo, and persists under `mf.listenOn`. Appearance offers System, Light, and Dark. The skip link targets the main region. Route changes update the title and current destination.

### Focused weekly artist and queue

One artist is visible at a time. Its large serif name, selection number, tags, and close-match/wildcard labels lead into The connection, preview/service access, More songs, and Keep / Pass / Know them / Not now. Supporting evidence uses a native disclosure. Preview controls use a recessed tone and accent text; external service links have a small stroked arrow.

Queue selection and Previous/Next change the active artist and preserve position per week under `mf.focus.<week>`. Changing artists stops the prior preview; keyboard selection moves focus to the artist heading, and phone selection brings that card into view. Current queue rows use rose wash, accent text, and a dot. Sorted rows retain their number, a textual verdict, and a check, and cease to be selectable. A decision advances to the next open artist; Sorted this week provides Undo. Restoring an artist returns it to the open set. Add 5 more and the completed-selection action extend the batch with explicit loading/exhausted states.

Your keepers remains directly below the workspace, with preferred-service links and Share list. Sharing uses the native share sheet when available, then clipboard, then a text download. More songs expands/collapses a full-width song list, retains `aria-expanded`, and reports loading, empty, and retryable error states.

### Saved choices and filters

Your taste uses a flat search/filter index above saved decisions. Search covers artist or song text; a native verdict select distinguishes Any choice, Liked, Not for me, and Already know. All choices / Artists / Songs are pressed-state scope buttons. Results update while typing and in batches of 30, with a live textual count, a Clear filters recovery, and focus moved into newly revealed rows. Filtering reads current saved verdicts so changing a filter does not restore an undone choice. Filter values are local to the current view; saved decisions persist.

### Artist choices and starting point

Setup choices remain text-first buttons separated by dividers, with Pick/Picked text and a check for selection. They use the rose wash and accent text and have a 100px minimum height. Style filters sit in Browse by style. Removable favorite/disliked pills wrap and scroll after 300px; dislikes use the negative wash and strike-through. The raised starting-point summary contains selection count, save state, and the discovery action.

### Ranked results, songs, and evidence

Ranked recommendations remain flat rows with familiar connections and an explicitly labeled amber percentile. Ratings stay in their row with a saved message and Undo until results refresh. Song names use compact DM Sans hierarchy and actions stack below on narrower screens. A play button appears only after a matching preview exists; unavailable, check-failed, playback-failed, retry, cancel, and pause states retain explicit text.

Why this match holds supporting/opposing signal colors, an ink net-score mark, textual legend, and signed effects table. Percentile, provisional like estimates, and simulated truth remain distinct. Taste bars use wine; accuracy charts use subdued grids and tabular labels. Loading, empty, service, and error states explain what happened and expose recovery where available. Demo evidence retains its visible banner.

### Sideband logo and provenance

The logo is a plain record: a white disc, hot-pink label, and transparent spindle hole. It represents the music the listener already plays.

- **Master geometry:** `musicfinder/web/brand-mark.svg`, a 64-unit square with a 24-unit-radius disc, 8.5-unit label, and 2.6-unit masked spindle hole. Do not add grooves, waves, shadows, gradients, or animation.
- **Color:** logo-only coral `#ff5a3c`, pink `#ff3d7f`, and white. The dark-ground record is white with pink; the light lockup is coral with pink. Icons use white/pink on coral. These brights do not join the interface palette.
- **Wordmark:** capitalized Sideband in Fraunces Medium 500 with -.03em tracking. The live masthead uses selectable text beside a decorative image in one Sideband home link. `docs/brand/` contains outlined light/dark SVG lockups; the source font and OFL license remain in `musicfinder/web/`.
- **Size and space:** the masthead mark is a 36px square on desktop, 30px at 760px and below, and 27px at 420px and below. Wordmark gaps are 11px, then 8px on the smallest screens; the home target stays at least 44px high. Use at least a 16px box for an isolated mark and retain 8/64 clear space. Scale disc, label, and hole together.
- **Icons and provenance:** the 180/192/512px PNGs derive from `docs/brand/app-icon.svg`. Their opaque coral ground fills the image and the disc stays inside the central 80%-diameter safe circle. The favicon uses its own enlarged optical placement. The vectors and outlined lettering were authored locally; PNGs are raster exports with embedded provenance, not stock or generated artwork. Retain this provenance on replacement exports and let the OS apply its own corner mask.
- **Interaction:** the wordmark returns to This week, changes text to amber on hover, and uses the masthead's ivory focus outline. The This week destination's target icon is separate from the brand mark.

`docs/brand/README.md` records the existing logo export and verification history; its original header-size screenshots predate this listening-desk layout.

## Do's and Don'ts

### Do:

- Do use semantic CSS variables so light and dark themes apply to every component.
- Do reserve green for positive evidence and liked feedback, wine for taste data, and rose for selections.
- Do keep music names, familiar connections, and the next listening action prominent.
- Do preserve all six navigation destinations and shared service and appearance controls.
- Do keep weekly choices reversible through Sorted this week and ranked ratings reversible in their rows.
- Do retain native controls, visible focus, textual state labels, and reduced-motion behavior.
- Do keep queue and collection layouts flat around the single focused weekly artist.

### Don't:

- Don't substitute a generic green palette for the established ivory, wine, aubergine, and amber identity.
- Don't apply the logo's coral and pink brights to interface controls.
- Don't invent artwork, testimonials, listening counts, or accuracy claims.
- Don't use color alone for selections, verdicts, errors, or signal direction.
- Don't turn a candidate percentile into a like probability or make unavailable previews appear playable.
- Don't replace native selects, ranges, radio buttons, or disclosure semantics with decorative imitations.
- Don't introduce external font requests or remove the local font licenses and logo provenance.
