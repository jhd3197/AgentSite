import { useEffect, useMemo, useRef, useState } from "react";
import { BotEngine } from "../../bloub/bot/engine";
import { STATE_BY_ID } from "../../bloub/bot/states";
import { EXPRESSION_BY_ID, DEFAULT_EXPRESSION } from "../../bloub/bot/expressions";
import { mixHex } from "../../bloub/bot/skins";
import { NOTIF_BLUE } from "../../bloub/bot/decor";
import { RAYON, DEMI_VIEWBOX } from "../../bloub/bot/repere";
import { clamp, easings } from "../../bloub/bot/math";

/**
 * React port of bloub's avatar (vendored engine in src/bloub/, MIT — see
 * src/bloub/LICENSE). The engine is a pure function of time, so this
 * component is only a clock + an SVG renderer: `engine.sample(t)` returns
 * everything to draw.
 *
 * Props:
 *   - size: px
 *   - state: bloub StateId ("idle" | "thinking" | "orbit" | "swirl" | "wide"
 *     | "alert" | "exclaim" | "burst" | "wink" | "play" | "notify" | "sleep" ...)
 *   - animate: false renders a single frozen frame (no rAF loop) — use for
 *     historical/chat-scrollback avatars so they cost nothing
 *   - frozenAt: the date sampled when animate is false
 *   - follow: eyes track the pointer (only on rest-face states, like bloub)
 *   - gradient: [from, to] hex pair used to fill the body
 *   - paper: hex of the surface behind the avatar, or "auto" to read the
 *     nearest opaque ancestor background (the eyes are mask holes, so this
 *     only feeds particle depth-fading and the opaque backing disc)
 */
export default function BloubAvatar({
  size = 32,
  state = "idle",
  animate = true,
  frozenAt = 0,
  follow = false,
  gradient = ["#6366f1", "#9333ea"],
  paper = "auto",
  expression = DEFAULT_EXPRESSION,
  className = "",
}) {
  const svgRef = useRef(null);
  const uid = useRef(Math.random().toString(36).slice(2, 8)).current;

  const engineRef = useRef(null);
  if (!engineRef.current) {
    engineRef.current = new BotEngine(
      RAYON,
      STATE_BY_ID.has(state) ? state : "idle",
      null,
      EXPRESSION_BY_ID.get(expression) ?? null,
    );
  }
  const engine = engineRef.current;

  // Scene clock: advances only inside the rAF loop, with a clamped delta so a
  // hidden tab doesn't jump forward on return (same rule as bloub).
  const clockRef = useRef(0);
  const [frame, setFrame] = useState(() => engine.sample(frozenAt));

  const [autoPaper, setAutoPaper] = useState("#0f172a");
  const paperColor = paper === "auto" ? autoPaper : paper;
  // Particles fade toward the page as they recede; with a gradient body their
  // base ink is the gradient midpoint.
  const inkSolid = useMemo(() => mixHex(gradient[0], gradient[1], 0.5), [gradient]);

  // Resolve "auto" paper from the nearest ancestor that paints a background.
  useEffect(() => {
    if (paper !== "auto" || !svgRef.current) return;
    let el = svgRef.current.parentElement;
    while (el) {
      const bg = getComputedStyle(el).backgroundColor;
      const hex = cssColorToHex(bg);
      if (hex) {
        setAutoPaper(hex);
        return;
      }
      el = el.parentElement;
    }
  }, [paper]);

  // State changes morph from the current composite frame (the engine handles
  // continuity); frozen avatars just resample.
  useEffect(() => {
    const id = STATE_BY_ID.has(state) ? state : "idle";
    if (engine.state !== id) engine.setState(id, clockRef.current);
    if (!animate) setFrame(engine.sample(frozenAt));
  }, [engine, state, animate, frozenAt]);

  useEffect(() => {
    const expr = EXPRESSION_BY_ID.get(expression) ?? null;
    engine.setExpression(expr, clockRef.current);
    if (!animate) setFrame(engine.sample(frozenAt));
  }, [engine, expression, animate, frozenAt]);

  // The animation loop, plus optional pointer-following gaze.
  useEffect(() => {
    if (!animate) {
      setFrame(engine.sample(frozenAt));
      return;
    }
    let raf = 0;
    let last = 0;
    let pointer = null;
    let aiming = false;
    let aimSince = 0;

    const onPointerMove = (e) => {
      if (e.pointerType === "touch") return;
      pointer = { x: e.clientX, y: e.clientY };
    };
    const onPointerLeave = () => {
      pointer = null;
    };

    const release = () => {
      if (!aiming) return;
      engine.setLook(null, clockRef.current);
      aiming = false;
    };

    const aim = () => {
      // Gaze only drives rest-face states; elsewhere the eye pose IS the
      // recorded animation (orbit already sends the eyes around the sphere).
      if (!STATE_BY_ID.get(engine.state)?.baseFace) {
        release();
        return;
      }
      const box = svgRef.current?.getBoundingClientRect();
      // A zero-area box would put NaN into the engine's kept target forever.
      if (!box || box.width === 0 || box.height === 0) return;
      if (!aiming) aimSince = clockRef.current;
      const halfW = Math.max(1, window.innerWidth / 2);
      const halfH = Math.max(1, window.innerHeight / 2);
      const nx = pointer ? clamp((pointer.x - (box.left + box.width / 2)) / halfW, -1, 1) : 0;
      const ny = pointer ? clamp((pointer.y - (box.top + box.height / 2)) / halfH, -1, 1) : 0;
      const grip = easings.easeOutQuint(clamp((clockRef.current - aimSince) / 0.8));
      engine.setLook(
        {
          yaw: nx * 16,
          // positive pitch looks up while screen y grows downward
          pitch: 10 - ny * 13,
          mix: grip,
          spin: 0,
          wander: pointer ? 0 : 1,
        },
        clockRef.current,
      );
      aiming = true;
    };

    const tick = (ms) => {
      raf = requestAnimationFrame(tick);
      const dt = last ? Math.min((ms - last) / 1000, 0.064) : 0;
      last = ms;
      clockRef.current += dt;
      if (follow) aim();
      setFrame(engine.sample(clockRef.current));
    };

    if (follow) {
      window.addEventListener("pointermove", onPointerMove);
      document.addEventListener("pointerleave", onPointerLeave);
    }
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (follow) {
        window.removeEventListener("pointermove", onPointerMove);
        document.removeEventListener("pointerleave", onPointerLeave);
        release();
      }
    };
  }, [engine, animate, follow, frozenAt]);

  const VB = DEMI_VIEWBOX;
  const maskId = `bloub-mask-${uid}`;
  const inkId = `bloub-ink-${uid}`;

  const dotAttrs = (dot) => {
    const fill =
      dot.color ?? (dot.depth === undefined ? inkSolid : mixHex(paperColor, inkSolid, dot.depth));
    return dot.d
      ? {
          fill,
          opacity: dot.opacity,
          d: dot.d,
          transform: `translate(${dot.x} ${dot.y}) rotate(${dot.rot ?? 0}) scale(${RAYON})`,
        }
      : { fill, opacity: dot.opacity, cx: dot.x, cy: dot.y, r: dot.r };
  };

  return (
    <svg
      ref={svgRef}
      width={size}
      height={size}
      viewBox={`${-VB} ${-VB} ${VB * 2} ${VB * 2}`}
      role="img"
      aria-label="AgentSite assistant"
      className={className}
    >
      <defs>
        <linearGradient id={inkId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor={gradient[0]} />
          <stop offset="100%" stopColor={gradient[1]} />
        </linearGradient>
        {/* Eyes are holes punched through the body, so they self-clip against
            the silhouette when they slide toward the edge. */}
        <mask id={maskId} maskUnits="userSpaceOnUse" x={-VB} y={-VB} width={VB * 2} height={VB * 2}>
          <path d={frame.bodyPath} fill="#fff" />
          {frame.eyes.map((eye, i) => (
            <path key={i} d={eye.d} transform={eye.matrix} opacity={eye.alpha} fill="#000" />
          ))}
          {frame.notch && (
            <circle cx={frame.notch.x} cy={frame.notch.y} r={frame.notch.r} fill="#000" />
          )}
        </mask>
        {frame.arcs.map((arc) => (
          <linearGradient
            key={arc.id}
            id={`${uid}-${arc.id}`}
            gradientUnits="userSpaceOnUse"
            x1={arc.grad.x1}
            y1={arc.grad.y1}
            x2={arc.grad.x2}
            y2={arc.grad.y2}
          >
            {arc.grad.stops.map((c, i) => (
              <stop key={i} offset={i / (arc.grad.stops.length - 1)} stopColor={c} />
            ))}
          </linearGradient>
        ))}
      </defs>

      {/* back half of the orbit rings: drawn before the body, so occluded */}
      <g fill="none" strokeLinecap="round">
        {frame.arcs.map((arc) => (
          <path
            key={`b${arc.id}`}
            d={arc.back}
            stroke={`url(#${uid}-${arc.id})`}
            strokeWidth={arc.width}
            opacity={arc.opacity}
          />
        ))}
      </g>

      {frame.dotsBehind &&
        frame.dots.map((dot, i) =>
          dot.d ? <path key={`pb${i}`} {...dotAttrs(dot)} /> : <circle key={`pb${i}`} {...dotAttrs(dot)} />,
        )}

      <g opacity={frame.bodyAlpha}>
        {/* Opaque backing in the page color: the eye holes must show the page,
            not the ring halves drawn behind the body. */}
        <path d={frame.bodyPath} fill={paperColor} />
        <g mask={`url(#${maskId})`}>
          <rect x={-VB} y={-VB} width={VB * 2} height={VB * 2} fill={`url(#${inkId})`} />
        </g>
      </g>

      {!frame.dotsBehind &&
        frame.dots.map((dot, i) =>
          dot.d ? <path key={`pf${i}`} {...dotAttrs(dot)} /> : <circle key={`pf${i}`} {...dotAttrs(dot)} />,
        )}

      {frame.notif && (
        <circle cx={frame.notif.x} cy={frame.notif.y} r={frame.notif.r} fill={NOTIF_BLUE} />
      )}

      {/* front half of the orbit rings */}
      <g fill="none" strokeLinecap="round">
        {frame.arcs.map((arc) => (
          <path
            key={`f${arc.id}`}
            d={arc.front}
            stroke={`url(#${uid}-${arc.id})`}
            strokeWidth={arc.width}
            opacity={arc.opacity}
          />
        ))}
      </g>
    </svg>
  );
}

// getComputedStyle returns rgb()/rgba(); the engine's color mixing wants hex.
function cssColorToHex(css) {
  const m = /rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+))?\s*\)/.exec(css || "");
  if (!m) return null;
  if (m[4] !== undefined && parseFloat(m[4]) === 0) return null; // transparent
  const hex = (n) => Number(n).toString(16).padStart(2, "0");
  return `#${hex(m[1])}${hex(m[2])}${hex(m[3])}`;
}
