/**
 * SVG device chrome wrapping the preview iframe.
 *
 * Each entry in FRAMES carries the SVG's viewBox + the screen safe-area
 * rectangle (x, y, w, h) so we can absolutely-position the iframe inside.
 */

const FRAMES = {
  iphone: {
    src: "/frames/iphone-15-pro.svg",
    viewBox: { w: 390, h: 844 },
    screen: { x: 14, y: 14, w: 362, h: 816 },
  },
  android: {
    src: "/frames/android-pixel.svg",
    viewBox: { w: 412, h: 900 },
    screen: { x: 14, y: 14, w: 384, h: 872 },
  },
  ipad: {
    src: "/frames/ipad-pro.svg",
    viewBox: { w: 834, h: 1194 },
    screen: { x: 28, y: 28, w: 778, h: 1138 },
  },
  macbook: {
    src: "/frames/macbook.svg",
    viewBox: { w: 1440, h: 940 },
    screen: { x: 60, y: 40, w: 1320, h: 800 },
  },
};

export default function DeviceFrame({ frame, children, maxHeight = 700 }) {
  const f = FRAMES[frame];
  if (!f) return children;

  const aspectRatio = f.viewBox.w / f.viewBox.h;
  const screenLeftPct = (f.screen.x / f.viewBox.w) * 100;
  const screenTopPct = (f.screen.y / f.viewBox.h) * 100;
  const screenWPct = (f.screen.w / f.viewBox.w) * 100;
  const screenHPct = (f.screen.h / f.viewBox.h) * 100;

  return (
    <div
      className="relative"
      style={{
        maxHeight,
        aspectRatio,
        height: "100%",
      }}
    >
      <img
        src={f.src}
        alt={`${frame} frame`}
        className="absolute inset-0 w-full h-full pointer-events-none select-none"
      />
      <div
        className="absolute overflow-hidden"
        style={{
          left: `${screenLeftPct}%`,
          top: `${screenTopPct}%`,
          width: `${screenWPct}%`,
          height: `${screenHPct}%`,
        }}
      >
        {children}
      </div>
    </div>
  );
}
