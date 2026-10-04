"""Design tokens for LAN UIs (camera :8080 / pipeline :8090).

Technical ops dashboard palette — cool neutrals, tight radii, port identity
kept (green :8080 / red :8090) but toned for maintenance work, not consumer UI.
"""

from __future__ import annotations

# CSS custom properties injected into every page via styles.css().
ROOT_VARS = """
:root {
  /* Surfaces — cool technical neutrals */
  --bg: #e6e9ee;
  --bg-elevated: #dce0e6;
  --card: #f4f6f8;
  --fg: #12161c;
  --muted: #5a6470;
  --border: rgba(18, 22, 28, 0.16);
  --border-strong: rgba(18, 22, 28, 0.28);
  --brand: #8a7350;

  /* Port identity — ops-toned, not playful */
  --cam: #1f6b42;
  --cam-bg: #dde8e1;
  --cam-ink: #143d28;
  --cam-active: #155533;
  --cam-border: rgba(31, 107, 66, 0.4);
  --pipe: #a8342a;
  --pipe-bg: #eadfdd;
  --pipe-ink: #5c1c17;
  --pipe-active: #872820;
  --pipe-border: rgba(168, 52, 42, 0.4);

  /* Semantic status — left-border / chip, not marketing green fills */
  --ok: #2a6b45;
  --ok-bg: rgba(42, 107, 69, 0.08);
  --ok-border: #2a6b45;
  --warn: #8a6a28;
  --warn-bg: rgba(138, 106, 40, 0.1);
  --warn-border: #8a6a28;
  --err: #a8342a;
  --err-bg: rgba(168, 52, 42, 0.08);
  --err-border: #a8342a;
  --info: #3d4f63;
  --info-bg: rgba(61, 79, 99, 0.08);
  --info-border: #3d4f63;
  --neutral-bg: rgba(18, 22, 28, 0.035);

  /* Type & space — denser, readable */
  --font: system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --fs: 14px;
  --fs-sm: 0.86rem;
  --fs-xs: 0.72rem;
  --lh: 1.4;
  --space-1: 0.2rem;
  --space-2: 0.4rem;
  --space-3: 0.65rem;
  --space-4: 0.9rem;
  --space-5: 1.15rem;
  --space-6: 1.5rem;
  --radius-sm: 2px;
  --radius: 2px;
  --radius-lg: 3px;
  --tap: 44px;
  --focus: 0 0 0 2px var(--bg), 0 0 0 4px rgba(61, 79, 99, 0.55);
  --main-max: 44rem;
  --preview-max: 28rem;
  --control-max: 20rem;
  --nav-min: 12rem;
  --transition: 100ms ease;

  /* Service accent (set by body.svc-*) */
  --accent: var(--brand);
  --on-accent: #f4f6f8;
}
""".strip()
