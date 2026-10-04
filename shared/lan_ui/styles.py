"""Full LAN stylesheet: tokens + layout + components.

Technical ops dashboard: flat cool surfaces, near-square panels, status
badges with left borders, monospace for paths/IDs, clear section rules.
"""

from __future__ import annotations

from .tokens import ROOT_VARS

_COMPONENT_CSS = """
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  font: var(--fs)/var(--lh) var(--font);
  margin: 0;
  color: var(--fg);
  background:
    linear-gradient(90deg, transparent 0, transparent calc(100% - 1px), rgba(18, 22, 28, 0.04) 0) 0 0 / 1.25rem 1.25rem,
    linear-gradient(var(--bg), var(--bg));
  min-height: 100vh;
  overflow-x: hidden;
}
body.svc-cam { --accent: var(--cam); --on-accent: #fff; }
body.svc-pipe { --accent: var(--pipe); --on-accent: #fff; }

main {
  max-width: var(--main-max);
  margin: 0 auto;
  padding: var(--space-5) var(--space-4) var(--space-6);
  width: 100%;
}
h1 {
  font-size: 1.2rem;
  font-weight: 650;
  margin: 0 0 var(--space-1);
  word-wrap: break-word;
  letter-spacing: 0.02em;
  text-transform: none;
}
h2 {
  font-size: 0.78rem;
  font-weight: 700;
  margin: 0;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
}
h2.h-inline {
  font-size: 0.78rem;
  margin: 0 0 var(--space-1);
}
.page-header {
  margin: 0 0 var(--space-5);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-strong);
}
.page-header h1 { margin-bottom: var(--space-1); }
.page-header .lead { margin-bottom: 0; max-width: 40rem; }
.lead {
  color: var(--muted);
  margin: 0 0 var(--space-4);
  font-size: var(--fs-sm);
}
.muted { color: var(--muted); font-size: var(--fs-sm); }
.kicker {
  display: block;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 var(--space-1);
}
.empty-state {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  color: var(--muted);
  font-size: var(--fs-sm);
  text-align: left;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
  font-family: var(--font-mono);
}

/* —— Nav —— */
.nav {
  display: flex;
  flex-direction: column;
  gap: 0;
  padding: 0;
  background: var(--card);
  width: 100%;
  border-bottom: 2px solid var(--border-strong);
  position: relative;
  z-index: 30;
}
.nav-bar {
  display: none;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 0.4rem 0.7rem;
  min-height: calc(var(--tap) + 0.3rem);
  background: var(--card);
}
.nav-identity {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex: 1 1 auto;
  min-width: 0;
}
.nav-chip {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 0.3rem 0.45rem;
  border-radius: var(--radius-sm);
  color: #fff;
  line-height: 1;
  min-height: 1.65rem;
  display: inline-flex;
  align-items: center;
}
.nav-chip-cam { background: var(--cam); }
.nav-chip-pipe { background: var(--pipe); }
.nav-toggle {
  font: inherit;
  font-size: 0.85rem;
  font-weight: 600;
  min-height: var(--tap);
  min-width: var(--tap);
  padding: 0.3rem 0.75rem;
  margin: 0;
  cursor: pointer;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
  color: var(--fg);
  touch-action: manipulation;
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
}
.nav-toggle::before {
  content: "";
  width: 1rem;
  height: 0.65rem;
  background:
    linear-gradient(currentColor, currentColor) 0 0 / 100% 2px no-repeat,
    linear-gradient(currentColor, currentColor) 0 50% / 100% 2px no-repeat,
    linear-gradient(currentColor, currentColor) 0 100% / 100% 2px no-repeat;
  opacity: 0.75;
}
.nav-toggle[aria-expanded="true"] {
  border-color: var(--info-border);
  background: var(--info-bg);
}
.nav-toggle[aria-expanded="true"]::before { display: none; }
.nav-panels {
  display: flex;
  flex-wrap: wrap;
  width: 100%;
}
.nav-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem 0.65rem;
  padding: 0.45rem 0.75rem;
  flex: 1 1 var(--nav-min);
  min-width: 0;
  position: relative;
  border-bottom: 3px solid transparent;
}
.nav-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.15rem 0.45rem;
  flex: 1 1 auto;
  min-width: 0;
}
.nav-group.nav-cam {
  background: var(--cam-bg);
  border-bottom-color: var(--cam);
}
.nav-group.nav-pipe {
  background: var(--pipe-bg);
  border-bottom-color: var(--pipe);
}
.nav-port {
  font-family: var(--font-mono);
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 0.18rem 0.4rem;
  border-radius: var(--radius-sm);
  opacity: 0.95;
  flex: 0 0 auto;
}
.nav-cam .nav-port { background: var(--cam); color: #fff; }
.nav-pipe .nav-port { background: var(--pipe); color: #fff; }
.nav a {
  text-decoration: none;
  font-size: 0.88rem;
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  padding: 0.3rem 0.35rem;
  border-bottom: 2px solid transparent;
  touch-action: manipulation;
  border-radius: 0;
}
.nav-cam a { color: var(--cam-ink); }
.nav-pipe a { color: var(--pipe-ink); }
.nav a:hover { text-decoration: underline; text-underline-offset: 0.2em; }
.nav-cam a.active {
  color: var(--cam-active);
  font-weight: 700;
  border-bottom-color: var(--cam-active);
}
.nav-pipe a.active {
  color: var(--pipe-active);
  font-weight: 700;
  border-bottom-color: var(--pipe-active);
}

/* —— Nav More dropdown (JSON / debug endpoints) —— */
.nav-more {
  position: relative;
  flex: 0 0 auto;
  margin-left: 0.1rem;
}
.nav-more-btn {
  font: inherit;
  font-size: 0.88rem;
  min-height: var(--tap);
  padding: 0.3rem 0.5rem;
  margin: 0;
  cursor: pointer;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  touch-action: manipulation;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.nav-more-btn::after {
  content: "";
  width: 0;
  height: 0;
  border-left: 0.25rem solid transparent;
  border-right: 0.25rem solid transparent;
  border-top: 0.3rem solid currentColor;
  opacity: 0.7;
}
.nav-cam .nav-more-btn { color: var(--cam-ink); }
.nav-pipe .nav-more-btn { color: var(--pipe-ink); }
.nav-more-btn:hover { text-decoration: underline; text-underline-offset: 0.2em; }
.nav-more-btn[aria-expanded="true"] {
  font-weight: 600;
  border-color: var(--border-strong);
  background: rgba(255, 255, 255, 0.55);
}
.nav-more-menu {
  position: absolute;
  top: calc(100% + 0.15rem);
  left: 0;
  z-index: 40;
  min-width: 12rem;
  max-width: min(20rem, calc(100vw - 1.5rem));
  padding: 0.2rem 0;
  margin: 0;
  background: var(--card);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: 0 4px 12px rgba(18, 22, 28, 0.12);
}
.nav-cam .nav-more-menu { border-top: 2px solid var(--cam); }
.nav-pipe .nav-more-menu { border-top: 2px solid var(--pipe); }
.nav-more-menu[hidden] { display: none !important; }
.nav-more-menu a {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: var(--tap);
  padding: 0.35rem 0.75rem;
  margin: 0;
  border-bottom: 0;
  border-radius: 0;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.nav-cam .nav-more-menu a { color: var(--cam-ink); }
.nav-pipe .nav-more-menu a { color: var(--pipe-ink); }
.nav-more-menu a:hover,
.nav-more-menu a:focus-visible {
  background: var(--neutral-bg);
  text-decoration: none;
}
.nav-more-menu a:focus-visible {
  outline: none;
  box-shadow: inset var(--focus);
}

/* —— Pills & links —— */
.pill {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  padding: 0.12rem 0.35rem;
  border-radius: var(--radius-sm);
  margin-left: 0.25rem;
  color: #fff;
  font-weight: 700;
  letter-spacing: 0.04em;
  vertical-align: middle;
}
.pill-cam { background: var(--cam); }
.pill-pipe { background: var(--pipe); }
.pill-brand { background: var(--brand); color: #fff; }

a { color: var(--accent); }
a:hover { text-decoration: underline; text-underline-offset: 0.15em; }
a.link-cam { color: var(--cam); }
a.link-pipe { color: var(--pipe); }
a.link-brand { color: var(--brand); }
code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  word-break: break-word;
  background: var(--neutral-bg);
  padding: 0.05em 0.28em;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}

/* —— Cards / panels —— */
section, .card {
  background: var(--card);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  padding: 0;
  margin: 0 0 var(--space-4);
  box-shadow: none;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0.55rem var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--neutral-bg);
  min-height: 2.4rem;
}
.panel-head h2 { flex: 1 1 auto; }
.panel-body {
  padding: 0.75rem var(--space-4) 0.85rem;
}
section.card-cam { border-left: 3px solid var(--cam); }
section.card-pipe { border-left: 3px solid var(--pipe); }
ul { margin: var(--space-1) 0 0; padding-left: 1.15rem; }
li { margin: 0.3rem 0; }

/* —— Buttons —— */
button, .btn {
  font: inherit;
  min-height: var(--tap);
  padding: 0.5rem var(--space-4);
  cursor: pointer;
  border-radius: var(--radius-sm);
  touch-action: manipulation;
  border: 1px solid var(--border-strong);
  background: var(--card);
  color: var(--fg);
  transition: background var(--transition), border-color var(--transition), opacity var(--transition);
}
button:hover:not(:disabled), .btn:hover:not(:disabled) {
  border-color: var(--fg);
  background: var(--bg-elevated);
}
button:disabled, .btn:disabled { opacity: 0.55; cursor: wait; }
button.primary, .btn.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--on-accent);
  font-weight: 650;
}
button.primary:hover:not(:disabled), .btn.primary:hover:not(:disabled) {
  filter: brightness(0.94);
}
button.danger, .btn.danger {
  background: var(--card);
  border-color: var(--err-border);
  color: var(--pipe-ink);
  font-weight: 650;
}
button.danger:hover:not(:disabled), .btn.danger:hover:not(:disabled) {
  background: var(--err-bg);
}
button.ghost, .btn.ghost {
  background: transparent;
  border-color: var(--border);
  color: var(--muted);
}
button.on {
  background: var(--cam);
  color: #fff;
  border-color: var(--cam);
}
button.off {
  background: var(--card);
  border: 1px solid var(--border-strong);
  color: var(--fg);
}
button.err {
  background: var(--err-bg);
  border: 1px solid var(--err-border);
  color: var(--fg);
}
/* Live preview Start — prominent green CTA when idle/expired */
button.live-start, .btn.live-start {
  background: var(--cam);
  border-color: var(--cam);
  color: #fff;
  font-weight: 700;
  font-size: 1.05rem;
  min-width: 12rem;
  padding: 0.65rem var(--space-5);
  box-shadow: 0 0 0 2px var(--cam-bg);
}
button.live-start:hover:not(:disabled), .btn.live-start:hover:not(:disabled) {
  background: var(--cam-active);
  border-color: var(--cam-active);
  filter: none;
}
/* Live preview Stop — clear red while session runs */
button.live-stop, .btn.live-stop {
  background: var(--err);
  border-color: var(--err);
  color: #fff;
  font-weight: 700;
  font-size: 1.05rem;
  min-width: 12rem;
  padding: 0.65rem var(--space-5);
}
button.live-stop:hover:not(:disabled), .btn.live-stop:hover:not(:disabled) {
  background: var(--pipe-active);
  border-color: var(--pipe-active);
  filter: none;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin: var(--space-3) 0;
  align-items: center;
}
/* Live preview countdown / status meter */
.live-preview-meter {
  margin: var(--space-3) 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border-strong);
  border-left: 4px solid var(--info-border);
  border-radius: var(--radius-sm);
  background: var(--info-bg);
}
.live-preview-meter.is-on {
  border-left-color: var(--cam);
  background: var(--cam-bg);
}
.live-preview-meter.is-off {
  border-left-color: var(--warn-border);
  background: var(--warn-bg);
}
.live-preview-meter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}
.live-preview-label {
  font-size: var(--fs-sm);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--cam-ink);
}
.live-preview-meter.is-off .live-preview-label {
  color: var(--warn);
}
.live-preview-time {
  font-family: var(--font-mono);
  font-size: 1.85rem;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: 0.02em;
  color: var(--fg);
  font-variant-numeric: tabular-nums;
}
.live-preview-meter.is-off .live-preview-time {
  font-size: 1rem;
  font-weight: 650;
  color: var(--muted);
}
.live-preview-track {
  height: 0.7rem;
  border-radius: var(--radius-sm);
  background: rgba(18, 22, 28, 0.12);
  overflow: hidden;
  margin-bottom: var(--space-2);
}
.live-preview-fill {
  height: 100%;
  width: 0%;
  background: var(--cam);
  border-radius: var(--radius-sm);
  transition: width 0.4s linear;
}
.live-preview-meter.is-off .live-preview-fill {
  width: 0% !important;
  background: transparent;
}
.live-preview-hint {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--muted);
}
.actions-sticky {
  position: sticky;
  bottom: 0;
  z-index: 20;
  margin: var(--space-4) 0 0;
  padding: var(--space-3) var(--space-4);
  background: color-mix(in srgb, var(--card) 94%, transparent);
  border: 1px solid var(--border-strong);
  border-bottom: 0;
  backdrop-filter: blur(6px);
  box-shadow: 0 -2px 8px rgba(18, 22, 28, 0.06);
}

/* Collapsible advanced blocks (Variants overlays, etc.) */
details.advanced-panel {
  margin: var(--space-3) 0;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--card);
}
details.advanced-panel > summary {
  cursor: pointer;
  list-style: none;
  font-weight: 650;
  font-size: var(--fs-sm);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--fg);
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.55rem;
  min-height: var(--tap);
  padding: 0.45rem var(--space-3);
  background: var(--neutral-bg);
  border-bottom: 1px solid transparent;
}
details.advanced-panel[open] > summary {
  border-bottom-color: var(--border);
}
details.advanced-panel > summary::-webkit-details-marker { display: none; }
details.advanced-panel > summary::before {
  content: "+";
  font-family: var(--font-mono);
  color: var(--muted);
  font-size: 0.95em;
  width: 1em;
}
details.advanced-panel[open] > summary::before { content: "−"; }
details.advanced-panel > summary:focus-visible {
  outline: 2px solid var(--info-border);
  outline-offset: 1px;
}
details.advanced-panel > .fieldset-help,
details.advanced-panel > fieldset {
  margin: var(--space-3);
}

/* —— Media —— */
img, img.thumb, img.preview {
  display: block;
  max-width: 100%;
  height: auto;
  margin-top: 0.55rem;
  background: #0e1116;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
}
img.thumb, img.preview { width: 100%; max-width: var(--preview-max); }

/* Fixed aspect box — reload/decode must not collapse layout */
.preview-frame {
  position: relative;
  width: 100%;
  max-width: var(--preview-max);
  margin-top: 0.55rem;
  background: #0e1116;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
  overflow: hidden;
}
.preview-frame.is-loading {
  opacity: 0.9;
}
.preview-frame.is-sharp {
  max-width: 100%;
}
.focus-region {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid #ffe14a;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.75);
  color: #ffe14a;
  pointer-events: auto;
  cursor: grab;
  touch-action: none;
  z-index: 2;
}
.focus-region:active { cursor: grabbing; }
.focus-region.is-back { border-color: #ffb020; color: #ffb020; }
.focus-region.is-peak { border-color: #8dff6a; color: #8dff6a; }
.focus-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  z-index: 4;
  width: 18px;
  height: 18px;
  cursor: nwse-resize;
  touch-action: none;
}
.focus-handle::after {
  content: "";
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 8px;
  height: 8px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
}
.focus-readout {
  position: absolute;
  top: 0.15rem;
  left: 0.15rem;
  z-index: 3;
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  margin: 0;
  padding: 0.05rem 0.28rem 0.08rem;
  background: rgba(0, 0, 0, 0.55);
  color: #ffe14a;
  pointer-events: none;
}
.focus-region.is-back .focus-readout { color: #ffc14a; }
.focus-region.is-peak .focus-readout { color: #b6ff9a; }
.focus-cue { display: inline-flex; }
.focus-cue svg { display: block; width: 0.85rem; height: 0.85rem; }
.focus-score {
  margin: 0;
  color: inherit;
  font-weight: 700;
  font-size: 0.8rem;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  text-shadow: none;
  pointer-events: none;
}
.mask-layer {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
}
.mask-box {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid #ffe14a;
  background: rgba(255, 225, 74, 0.16);
  color: #ffe14a;
  cursor: grab;
  pointer-events: auto;
  touch-action: none;
}
.mask-box.is-selected {
  z-index: 3;
  border-color: #8dff6a;
  color: #8dff6a;
  background: rgba(141, 255, 106, 0.16);
}
.mask-box:active { cursor: grabbing; }
.mask-tag {
  position: absolute;
  top: 0;
  left: 0;
  max-width: 100%;
  overflow: hidden;
  padding: 0 0.25rem;
  background: rgba(0, 0, 0, 0.55);
  font-size: 0.7rem;
  line-height: 1.35;
  white-space: nowrap;
  pointer-events: none;
}
.mask-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  z-index: 4;
  width: 18px;
  height: 18px;
  cursor: nwse-resize;
  touch-action: none;
}
.mask-handle::after {
  content: "";
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 8px;
  height: 8px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
}
.mask-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 0.75rem;
  align-items: flex-end;
  margin: 0.35rem 0 0.45rem;
}
.mask-tools .mask-label-field { flex: 1 1 10rem; min-width: 8rem; }
.mask-edit-stage,
.crop-edit-stage {
  margin: var(--space-3) 0 var(--space-2);
}
.mask-edit-stage .preview-frame,
.crop-edit-stage .preview-frame {
  margin-top: var(--space-2);
  max-width: 100%;
}
.mask-edit-stage .preview-frame.is-sharp,
.crop-edit-stage .preview-frame.is-sharp {
  max-width: 100%;
}
.crop-layer {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
  overflow: hidden;
}
.crop-box {
  position: absolute;
  box-sizing: border-box;
  border: 2px solid #5ec8ff;
  background: rgba(94, 200, 255, 0.1);
  color: #5ec8ff;
  cursor: grab;
  pointer-events: auto;
  touch-action: none;
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42);
}
.crop-box:active { cursor: grabbing; }
.crop-tag {
  position: absolute;
  top: 0;
  left: 0;
  max-width: 100%;
  overflow: hidden;
  padding: 0 0.25rem;
  background: rgba(0, 0, 0, 0.55);
  font-size: 0.7rem;
  line-height: 1.35;
  white-space: nowrap;
  pointer-events: none;
}
.crop-handle {
  position: absolute;
  right: 0;
  bottom: 0;
  z-index: 4;
  width: 18px;
  height: 18px;
  cursor: nwse-resize;
  touch-action: none;
}
.crop-handle::after {
  content: "";
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 8px;
  height: 8px;
  border-right: 2px solid currentColor;
  border-bottom: 2px solid currentColor;
}
.crop-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem 0.75rem;
  align-items: flex-end;
  margin: 0.35rem 0 0.45rem;
}
.preview-secondary {
  margin-top: var(--space-2);
  max-width: min(var(--preview-max), 100%);
}
.preview-secondary .preview-frame {
  margin-top: var(--space-2);
}
.preview-frame img,
.preview-frame img.thumb,
.preview-frame img.preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  max-width: none;
  margin: 0;
  object-fit: contain;
  object-position: center;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.preview-hint {
  /* Full-width above dry-run Preview — Edit crop / Edit masks canvases sit earlier. */
  min-height: 2.6em;
  margin: var(--space-3) 0 var(--space-1);
  line-height: 1.35;
}
.preview-hint.is-quiet {
  visibility: hidden;
}

/* —— Status / banners (technical chips + left border) —— */
.status-box, .banner {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: 0.55rem var(--space-3);
  border-radius: var(--radius-sm);
  margin: var(--space-2) 0;
  border: 1px solid var(--border);
  border-left: 3px solid var(--border-strong);
  background: var(--neutral-bg);
  word-wrap: break-word;
}
/* Author display:flex beats UA [hidden]{display:none} — force collapse. */
.status-box[hidden], .banner[hidden],
.status-box:empty, .banner:empty {
  display: none !important;
  margin: 0;
  padding: 0;
  border: 0;
}
.status-box.is-loading {
  color: var(--muted);
  font-style: normal;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
.status-box.ok, .banner.ok {
  background: var(--ok-bg);
  border-color: var(--border);
  border-left-color: var(--ok-border);
}
.status-box.warn, .banner.warn {
  background: var(--warn-bg);
  border-color: var(--border);
  border-left-color: var(--warn-border);
}
.status-box.bad, .banner.bad {
  background: var(--err-bg);
  border-color: var(--border);
  border-left-color: var(--err-border);
}
.status-box.info, .banner.info {
  background: var(--info-bg);
  border-color: var(--border);
  border-left-color: var(--info-border);
}
.status-badge {
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 0.22rem 0.4rem;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--card);
  color: var(--fg);
  line-height: 1.1;
  min-width: 3.4rem;
  text-align: center;
}
.status-badge-ok {
  border-color: var(--ok-border);
  color: var(--ok);
}
.status-badge-warn {
  border-color: var(--warn-border);
  color: var(--warn);
}
.status-badge-bad {
  border-color: var(--err-border);
  color: var(--err);
}
.status-badge-info {
  border-color: var(--info-border);
  color: var(--info);
}
.status-body {
  flex: 1 1 auto;
  min-width: 0;
}
.status-box strong, .banner strong,
.status-body strong {
  display: block;
  margin-bottom: 0.15rem;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.status-kv {
  display: grid;
  gap: 0.15rem 0;
  margin: 0.35rem 0 0;
  padding: 0;
}
.status-kv-row {
  display: grid;
  grid-template-columns: minmax(4.5rem, auto) 1fr;
  gap: 0.15rem var(--space-3);
  align-items: baseline;
}
.status-kv dt {
  margin: 0;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.status-kv dd {
  margin: 0;
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}
.stale-hint {
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--muted);
  margin: 0.3rem 0 0;
}
.stale-hint.stale { color: var(--warn); }

/* —— Debug grid —— */
dl.debug-grid {
  display: grid;
  grid-template-columns: minmax(7rem, auto) 1fr;
  gap: 0.15rem var(--space-3);
  margin: var(--space-2) 0 0;
  font-size: var(--fs-sm);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}
dl.debug-grid dt {
  color: var(--muted);
  margin: 0;
  font-family: var(--font-mono);
  font-size: 0.78rem;
}
dl.debug-grid dd {
  margin: 0;
  word-break: break-word;
  font-family: var(--font-mono);
  font-size: 0.82rem;
}

/* —— Recent journal peek (Pipeline home) —— */
pre.log-peek {
  margin: var(--space-2) 0 0;
  padding: var(--space-3);
  max-height: 18rem;
  overflow: auto;
  font-family: var(--font-mono);
  font-size: 0.72rem;
  line-height: 1.35;
  white-space: pre-wrap;
  word-break: break-word;
  background: #eceff3;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--fg);
}

/* —— Forms —— */
label {
  display: block;
  margin: var(--space-3) 0 var(--space-1);
  font-weight: 650;
  font-size: var(--fs-sm);
  letter-spacing: 0.02em;
}
label.inline {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 650;
  min-height: var(--tap);
  margin: var(--space-2) 0;
}
label.inline input { width: auto; max-width: none; margin: 0; }
input, select, textarea {
  font: inherit;
  padding: 0.5rem 0.6rem;
  min-height: var(--tap);
  width: 100%;
  max-width: var(--control-max);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  background: #fff;
  color: var(--fg);
}
input:focus-visible, select:focus-visible, textarea:focus-visible,
button:focus-visible, .btn:focus-visible, a:focus-visible {
  outline: none;
  box-shadow: var(--focus);
}
input[type="file"] {
  max-width: 100%;
  padding: 0.35rem 0;
  min-height: auto;
  border: 0;
  background: transparent;
  color: var(--muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
}
input[type="checkbox"] {
  width: 1.1rem;
  height: 1.1rem;
  min-height: 0;
  max-width: none;
  padding: 0;
  accent-color: var(--accent);
}
.row { display: flex; gap: var(--space-4); flex-wrap: wrap; }
.row > div { flex: 1 1 10rem; min-width: 0; }
.row > div input, .row > div select { max-width: 100%; }
.variant-gallery {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.variant-row {
  display: flex;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  background: var(--bg);
  transition: border-color var(--transition), background var(--transition);
  text-align: left;
  width: 100%;
  font: inherit;
  color: inherit;
  min-height: var(--tap);
}
.variant-row:hover { border-color: var(--pipe); }
.variant-row:focus-visible {
  outline: none;
  box-shadow: var(--focus);
  border-color: var(--pipe);
}
.variant-row.is-active {
  border-color: var(--pipe);
  background: var(--pipe-bg);
}
.variant-row.is-public-live {
  border-color: var(--brand);
  box-shadow: inset 3px 0 0 var(--brand);
}
.variant-row.is-private {
  border-style: dashed;
  background: var(--neutral-bg);
  box-shadow: inset 3px 0 0 var(--muted);
}
.variant-row.is-private:hover { border-color: var(--muted); }
.variant-row.is-private.is-active {
  border-color: var(--pipe);
  border-style: solid;
  background: var(--pipe-bg);
}
.variant-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
.live-badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.12rem 0.4rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--brand);
  background: transparent;
  color: var(--fg);
}
.private-badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.12rem 0.4rem;
  border-radius: var(--radius-sm);
  background: var(--neutral-bg);
  color: var(--muted);
  border: 1px solid var(--border-strong);
}
.variant-live-actions {
  margin-top: var(--space-2);
}
.variant-live-actions button {
  font-size: 0.85rem;
}
.variant-thumb {
  width: 7.5rem;
  height: 4.25rem;
  object-fit: cover;
  border-radius: var(--radius-sm);
  background: #0e1116;
  flex: 0 0 auto;
  border: 1px solid var(--border);
}
.variant-info { min-width: 0; flex: 1 1 auto; }
.variant-info code {
  display: block;
  margin-top: 0.2rem;
  font-size: 0.78em;
  color: var(--muted);
  background: transparent;
  border: 0;
  padding: 0;
}
#variantUrl { font-family: var(--font-mono); font-size: 0.86em; }
fieldset {
  border: 1px solid var(--border-strong);
  margin: var(--space-4) 0;
  padding: var(--space-3) var(--space-4);
  min-width: 0;
  border-radius: var(--radius);
  background: var(--neutral-bg);
}
legend {
  padding: 0 var(--space-1);
  color: var(--muted);
  font-size: var(--fs-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-family: var(--font-mono);
}
.field-help {
  margin: 0.12rem 0 0;
  color: var(--muted);
  font-size: 0.76rem;
  line-height: 1.35;
  max-width: var(--control-max);
}
.fieldset-help {
  margin: 0 0 var(--space-2);
  color: var(--muted);
  font-size: var(--fs-sm);
  line-height: 1.4;
}
.stack-gap { margin-top: var(--space-3); }
.mode-panel[hidden] { display: none !important; }
fieldset.is-dimmed {
  opacity: 0.55;
  pointer-events: none;
}
.preview-pair {
  display: flex;
  gap: var(--space-4);
  flex-wrap: wrap;
  margin-top: var(--space-2);
  align-items: flex-start; /* keep image tops level when column headers differ */
}
.preview-pair > div {
  flex: 1 1 12rem;
  min-width: 0;
}
.preview-pair .preview-frame {
  margin-top: var(--space-2);
}
.preview-pair img.preview {
  margin-top: 0;
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
  }
}

/* Phone / narrow: compact bar + expandable stacked port clusters */
@media (max-width: 480px) {
  main { padding: var(--space-4) var(--space-3) var(--space-6); }
  h1 { font-size: 1.1rem; }
  .nav-bar { display: flex; }
  .nav-panels {
    display: none;
    flex-direction: column;
    flex-wrap: nowrap;
    border-top: 1px solid var(--border);
  }
  .nav.is-open .nav-panels { display: flex; }
  .nav-group {
    flex: 1 1 100%;
    flex-direction: column;
    align-items: stretch;
    gap: 0.3rem;
    padding: 0.5rem 0.7rem 0.6rem;
  }
  .nav-port {
    align-self: flex-start;
    padding: 0.28rem 0.5rem;
  }
  .nav-links {
    flex-direction: column;
    align-items: stretch;
    gap: 0.12rem;
    width: 100%;
  }
  .nav a {
    width: 100%;
    font-size: 0.9rem;
    padding: 0.4rem 0.6rem;
    border-bottom: 0;
    border-left: 3px solid transparent;
  }
  .nav-cam a.active {
    border-left-color: var(--cam-active);
    background: rgba(255, 255, 255, 0.45);
  }
  .nav-pipe a.active {
    border-left-color: var(--pipe-active);
    background: rgba(255, 255, 255, 0.45);
  }
  .nav-more {
    width: 100%;
    margin-left: 0;
    margin-top: 0.12rem;
  }
  .nav-more-btn {
    width: 100%;
    justify-content: space-between;
    font-size: 0.9rem;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.4);
  }
  .nav-more-menu {
    position: static;
    top: auto;
    left: auto;
    right: auto;
    width: 100%;
    max-width: none;
    min-width: 0;
    margin-top: 0.2rem;
    box-shadow: none;
  }
  .nav-more-menu a {
    white-space: normal;
    word-break: break-all;
  }
  input, select { max-width: 100%; }
  .row > div { flex: 1 1 100%; }
  .actions-sticky {
    margin-left: 0;
    margin-right: 0;
    padding-left: var(--space-3);
    padding-right: var(--space-3);
  }
  .actions-sticky button, .actions-sticky .btn {
    flex: 1 1 auto;
    min-width: calc(50% - var(--space-2));
  }
  dl.debug-grid { grid-template-columns: 1fr; gap: 0.08rem 0; }
  dl.debug-grid dt { margin-top: 0.3rem; }
  .status-box, .banner {
    flex-wrap: wrap;
  }
}

@media (min-width: 481px) {
  .nav-bar { display: none !important; }
  .nav-panels { display: flex !important; }
}
""".strip()


def css() -> str:
    return f"{ROOT_VARS}\n{_COMPONENT_CSS}"
