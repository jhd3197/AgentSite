"""Live preview watching — passive friction detection injected into previews.

After a build finishes, the user browses the site in the preview iframe.
A tiny watcher script (injected server-side into every HTML response from
the preview routes) records what actually happens while they click around:

- uncaught JS errors, unhandled promise rejections, ``console.error`` calls
- failed network requests (fetch/XHR status >= 400 or rejected)
- broken assets (img/script/link elements that fire resource errors)
- **dead clicks** — the user clicked something that *looks* clickable
  (pointer cursor, button/link semantics) but nothing happened within the
  observation window: no navigation, no DOM mutation, no network activity,
  no focus change. "The user expected this to do something."
- **frustrated clicks** — repeated clicks (>= 3) on an element that does not
  look interactive at all: an affordance failure worth surfacing.
- **accessibility violations** — when ``a11y_scan_enabled`` is set, the
  vendored axe-core is lazily loaded and run against the page shortly after
  load (plus debounced rescans on real DOM churn): WCAG 2.x A/AA violations
  join the same event stream.

Events are batched and relayed to the parent app via ``postMessage``
(sandboxed iframes can't fetch same-origin APIs, but they CAN talk to their
parent). The frontend aggregates them, shows an issues pill over the
preview, and can hand them back to the pipeline as structured feedback
(``watch_feedback``), rendered here into a deterministic markdown block the
developer agent receives alongside its task.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..config import settings

_MARKER = "__asWatch"

_DEAD_CLICK_MS = 1200  # observation window after a click
_FLUSH_MS = 1500  # batch interval for postMessage to the parent
_MAX_EVENTS = 200  # per-page-session cap so a broken site can't spam forever

# Accessibility scanning (axe-core, lazily loaded from /_agentsite/axe.min.js)
_A11Y_TAGS = ["wcag2a", "wcag2aa", "best-practice"]
_A11Y_MAX_VIOLATIONS = 20  # per scan
_A11Y_MAX_SCANS = 8  # per page session (initial + SPA route changes)
_A11Y_RESCAN_MUTATIONS = 30  # DOM churn needed before a rescan
_A11Y_SCAN_DELAY_MS = 1800  # debounce after load / churn
_A11Y_FLAG = "__AS_A11Y__"  # replaced per-request by inject_watch_script

_WATCH_SCRIPT = f"""<script data-agentsite-watch data-a11y="{_A11Y_FLAG}">(function() {{
  if ("{_MARKER}" in window) {{ window.{_MARKER} = true; return; }}
  window.{_MARKER} = true;
  var MAX_EVENTS = {_MAX_EVENTS};
  var DEAD_MS = {_DEAD_CLICK_MS};
  var FLUSH_MS = {_FLUSH_MS};
  var buf = [];
  var sent = 0;

  function ev(type, data) {{
    if (sent >= MAX_EVENTS) return;
    sent++;
    data = data || {{}};
    data.type = type;
    data.url = location.href;
    data.t = Date.now();
    buf.push(data);
  }}

  // ---- signal counters (what counts as "something happened") ----
  var mutCount = 0, netCount = 0, navCount = 0;
  try {{
    new MutationObserver(function(muts) {{ mutCount += muts.length; }})
      .observe(document.documentElement, {{childList: true, subtree: true, attributes: true}});
  }} catch (e) {{}}
  setInterval(function() {{ if (lastHref !== location.href) {{ lastHref = location.href; navCount++; }} }}, 250);
  var lastHref = location.href;

  // ---- error capture ----
  window.addEventListener('error', function(e) {{
    try {{
      if (e.target && e.target !== window && (e.target.src || e.target.href)) {{
        ev('failed_resource', {{
          message: 'Resource failed to load: ' + (e.target.src || e.target.href),
          tag: e.target.tagName ? e.target.tagName.toLowerCase() : '',
          selector: cssPath(e.target),
        }});
        return;
      }}
      ev('js_error', {{
        message: String(e.message || e.error || 'Unknown error'),
        detail: e.filename ? (e.filename + ':' + (e.lineno || 0)) : '',
      }});
    }} catch (err) {{}}
  }}, true);
  window.addEventListener('unhandledrejection', function(e) {{
    try {{
      var r = e.reason;
      ev('promise_rejection', {{
        message: r && r.message ? String(r.message) : String(r).slice(0, 200),
      }});
    }} catch (err) {{}}
  }});
  try {{
    var origError = console.error.bind(console);
    console.error = function() {{
      try {{
        var parts = Array.prototype.slice.call(arguments).map(function(a) {{
          try {{ return typeof a === 'object' ? JSON.stringify(a).slice(0, 200) : String(a); }}
          catch (e) {{ return '[object]'; }}
        }});
        ev('console_error', {{ message: parts.join(' ').slice(0, 300) }});
      }} catch (e) {{}}
      origError.apply(console, arguments);
    }};
  }} catch (e) {{}}

  // ---- network wrappers ----
  try {{
    var origFetch = window.fetch;
    if (origFetch) {{
      window.fetch = function(input, init) {{
        netCount++;
        var url = typeof input === 'string' ? input : (input && input.url) || '';
        var method = (init && init.method) || (input && input.method) || 'GET';
        return origFetch.apply(this, arguments).then(function(res) {{
          if (res && res.status >= 400) ev('failed_request', {{ message: method + ' ' + url + ' -> ' + res.status }});
          return res;
        }}, function(err) {{
          ev('failed_request', {{ message: method + ' ' + url + ' -> network error: ' + (err && err.message ? err.message : 'failed') }});
          throw err;
        }});
      }};
    }}
    var OrigXHR = window.XMLHttpRequest;
    if (OrigXHR) {{
      function WrappedXHR() {{
        var xhr = new OrigXHR();
        var _url = '', _method = 'GET';
        var origOpen = xhr.open;
        xhr.open = function(method, url) {{
          _method = method; _url = url; netCount++;
          return origOpen.apply(xhr, arguments);
        }};
        xhr.addEventListener('loadend', function() {{
          if (xhr.status >= 400) ev('failed_request', {{ message: _method + ' ' + _url + ' -> ' + xhr.status }});
        }});
        return xhr;
      }}
      WrappedXHR.prototype = OrigXHR.prototype;
      window.XMLHttpRequest = WrappedXHR;
    }}
  }} catch (e) {{}}

  // ---- element description ----
  function cssPath(el) {{
    try {{
      var parts = [];
      var node = el;
      while (node && node.nodeType === 1 && parts.length < 5) {{
        var seg = node.tagName ? node.tagName.toLowerCase() : '';
        if (seg === 'html' || seg === 'body') break;
        if (node.id) {{ seg += '#' + node.id; parts.unshift(seg); break; }}
        if (node.classList && node.classList.length) seg += '.' + String(node.classList[0]).slice(0, 30);
        var sib = node, nth = 1;
        while ((sib = sib.previousElementSibling)) {{ if (sib.tagName === node.tagName) nth++; }}
        if (nth > 1) seg += ':nth-of-type(' + nth + ')';
        parts.unshift(seg);
        node = node.parentElement;
      }}
      return parts.join(' > ') || (el.tagName ? el.tagName.toLowerCase() : 'unknown');
    }} catch (e) {{ return 'unknown'; }}
  }}
  function describe(el) {{
    var d = {{ selector: cssPath(el), tag: el.tagName ? el.tagName.toLowerCase() : '' }};
    try {{
      d.text = (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 80);
      if (el.getAttribute) {{
        d.href = el.getAttribute('href') || '';
        d.id = el.id || '';
      }}
    }} catch (e) {{}}
    return d;
  }}
  var INTERACTIVE = 'a[href], button, input, select, textarea, label, summary, [contenteditable], [role=\\"button\\"], [role=\\"link\\"], [role=\\"tab\\"], [role=\\"menuitem\\"], [onclick], [jsaction], [data-action]';
  function looksInteractive(el) {{
    try {{
      if (!el || el === document.body || el === document.documentElement) return false;
      if (el.closest && el.closest(INTERACTIVE)) return true;
      var node = el;
      for (var i = 0; i < 3 && node; i++) {{
        var cs = window.getComputedStyle(node);
        if (cs && cs.cursor === 'pointer') return true;
        node = node.parentElement;
      }}
    }} catch (e) {{}}
    return false;
  }}

  // ---- click analysis ----
  var clickLog = {{}};  // selector -> recent timestamps (non-interactive frustration)
  document.addEventListener('click', function(e) {{
    try {{
      var el = e.target;
      if (!el || el.nodeType !== 1) return;
      var info = describe(el);
      var interactive = looksInteractive(el);

      if (!interactive) {{
        // Frustration heuristic: same non-interactive spot clicked repeatedly.
        var now = Date.now();
        var arr = (clickLog[info.selector] = (clickLog[info.selector] || [])).filter(function(t) {{ return now - t < 8000; }});
        arr.push(now);
        clickLog[info.selector] = arr;
        if (arr.length === 3) {{
          ev('repeat_click', {{
            message: 'User clicked "' + (info.text || info.selector) + '" 3 times in quick succession — it is not interactive but they expected it to be.',
            selector: info.selector, tag: info.tag, text: info.text,
          }});
        }}
        return;
      }}

      var before = {{ mut: mutCount, net: netCount, nav: navCount, focus: document.activeElement ? cssPath(document.activeElement) : '' }};
      setTimeout(function() {{
        try {{
          if (!document.contains(el)) return;  // removed from DOM => something happened
          // Focus moving INTO the clicked element is just the browser's
          // default (buttons get focus on click) — not evidence of action.
          var ae = document.activeElement;
          var focusIntoClicked = !!(ae && (ae === el || el.contains(ae)));
          var focusMoved = !focusIntoClicked && ae ? cssPath(ae) !== before.focus : false;
          var acted =
            mutCount > before.mut ||
            netCount > before.net ||
            navCount > before.nav ||
            location.href !== lastHref ||
            focusMoved;
          if (acted) return;
          ev('dead_click', {{
            message: 'Clicked "' + (info.text || info.selector) + '"' + (info.href ? ' (href=' + info.href + ')' : '') + ' but nothing happened.',
            selector: info.selector, tag: info.tag, text: info.text, href: info.href,
          }});
        }} catch (err) {{}}
      }}, DEAD_MS);
    }} catch (err) {{}}
  }}, true);

  // ---- accessibility scanning (axe-core, optional) ----
  var A11Y = false;
  try {{ A11Y = document.currentScript && document.currentScript.dataset.a11y === '1'; }} catch (e) {{}}
  if (A11Y) {{
    var scansLeft = {_A11Y_MAX_SCANS};
    var mutAtScan = 0, scanTimer = null;
    function loadAxe(cb) {{
      try {{
        if (window.axe && window.axe.run) return cb();
        var s = document.createElement('script');
        s.src = '/_agentsite/axe.min.js';
        s.onload = function() {{ cb(); }};
        s.onerror = function() {{ scansLeft = 0; }};  // asset missing — stop trying
        document.head.appendChild(s);
      }} catch (e) {{ scansLeft = 0; }}
    }}
    function runA11yScan() {{
      if (scansLeft <= 0 || !document.body) return;
      scansLeft--;
      mutAtScan = mutCount;
      loadAxe(function() {{
        try {{
          window.axe.run(document, {{
            runOnly: {{ type: 'tag', values: {_A11Y_TAGS} }},
            resultTypes: ['violations'],
          }}).then(function(res) {{
            if (!res || !res.violations) return;
            res.violations.slice(0, {_A11Y_MAX_VIOLATIONS}).forEach(function(v) {{
              var sel = v.nodes && v.nodes[0] && v.nodes[0].target ? v.nodes[0].target.join(' ') : '';
              ev('a11y_violation', {{
                message: '[' + (v.impact || 'minor') + '] ' + v.id + ': ' + (v.help || '').slice(0, 140),
                selector: String(sel).slice(0, 140),
                nodes: v.nodes ? v.nodes.length : 1,
                detail: v.helpUrl || '',
              }});
            }});
          }}).catch(function() {{}});
        }} catch (e) {{}}
      }});
    }}
    function scheduleA11yScan() {{
      if (scansLeft <= 0) return;
      clearTimeout(scanTimer);
      scanTimer = setTimeout(runA11yScan, {_A11Y_SCAN_DELAY_MS});
    }}
    setTimeout(scheduleA11yScan, 400);
    // Rescan on real DOM churn (SPA route changes etc.), debounced and capped.
    setInterval(function() {{
      if (mutCount - mutAtScan >= {_A11Y_RESCAN_MUTATIONS}) scheduleA11yScan();
    }}, 2500);
  }}

  // ---- batching to the parent app ----
  setInterval(function() {{
    if (!buf.length) return;
    var batch = buf.splice(0, buf.length);
    try {{ window.parent.postMessage({{ __asWatch: batch, v: 1 }}, '*'); }} catch (e) {{}}
  }}, FLUSH_MS);
  window.addEventListener('pagehide', function() {{
    if (!buf.length) return;
    try {{ window.parent.postMessage({{ __asWatch: buf.splice(0, buf.length), v: 1 }}, '*'); }} catch (e) {{}}
  }});
}})();</script>"""


def watch_enabled() -> bool:
    return bool(settings.watch_enabled)


def inject_watch_script(html: str, *, a11y: bool | None = None) -> str:
    """Insert the watcher <script> into an HTML document (idempotent).

    Prefers injecting right before ``</head>``; falls back to prepending to
    the document when no head/body markers exist. ``a11y`` overrides
    ``settings.a11y_scan_enabled`` for this response.
    """
    if not settings.watch_enabled or _MARKER in html:
        return html
    flag = "1" if (settings.a11y_scan_enabled if a11y is None else a11y) else "0"
    script = _WATCH_SCRIPT.replace(_A11Y_FLAG, flag)
    match = re.search(r"</head\s*>", html, flags=re.IGNORECASE)
    if match:
        idx = match.start()
        return html[:idx] + script + html[idx:]
    return script + html


_TYPE_LABELS = {
    "js_error": "Uncaught JS error",
    "promise_rejection": "Unhandled promise rejection",
    "console_error": "console.error",
    "failed_request": "Failed request",
    "failed_resource": "Broken asset",
    "dead_click": "Dead click (looked clickable, nothing happened)",
    "repeat_click": "Repeated clicks on a non-interactive element",
    "a11y_violation": "Accessibility violation",
}

_MAX_FEEDBACK_LINES = 40


def render_watch_feedback(events: Iterable[dict]) -> str:
    """Render raw watch events into a deterministic markdown block for agents."""
    seen: dict[tuple[str, str, str], dict] = {}
    order: list[tuple[str, str, str]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        etype = str(raw.get("type", "")).strip()
        if etype not in _TYPE_LABELS:
            continue
        message = str(raw.get("message", "")).strip().replace("\n", " ")[:220]
        selector = str(raw.get("selector", "")).strip()[:160]
        key = (etype, selector, message)
        if key in seen:
            seen[key]["_count"] += 1
        else:
            entry = dict(raw, _count=1)
            seen[key] = entry
            order.append(key)

    if not order:
        return ""

    lines = [
        "While exploring the live preview, a human tester triggered the issues "
        "below. Each one is a real interaction that felt broken or confusing:",
    ]
    for shown, key in enumerate(order):
        if shown >= _MAX_FEEDBACK_LINES:
            lines.append(f"- …and {len(order) - shown} more observations")
            break
        entry = seen[key]
        label = _TYPE_LABELS[key[0]]
        line = f"- **{label}:** {key[2]}"
        if key[1]:
            line += f" (element: `{key[1]}`)"
        if entry["_count"] > 1:
            line += f" x{entry['_count']}"
        lines.append(line)

    lines.append(
        "Fix these so the interactions work as the tester expected. "
        "Prefer targeted edits."
    )
    if any(key[0] == "a11y_violation" for key in order):
        lines.append(
            "Accessibility violations are present — consider "
            'delegate_to_specialist("accessibility") for a focused pass.'
        )
    return "\n".join(lines)


def append_watch_feedback(prompt: str, events: Iterable[dict]) -> str:
    """Fold rendered watch feedback into a generation prompt."""
    block = render_watch_feedback(events)
    if not block:
        return prompt
    rendered = (
        f"{prompt}\n\n---\n\n"
        "## Issues observed while a human used the live preview\n\n"
        f"{block}"
    )
    return rendered
