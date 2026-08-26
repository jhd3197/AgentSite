// Temporary visual harness: import this module from the dev server to mount
// a board of BloubAvatar states over the app. Not referenced by the router.
import React from "react";
import { createRoot } from "react-dom/client";
import BloubAvatar from "../components/shared/BloubAvatar";

const STATES = ["idle", "thinking", "orbit", "swirl", "wide", "alert", "exclaim", "burst", "play", "wink"];

const host = document.createElement("div");
host.id = "bloub-board";
host.style.cssText =
  "position:fixed;inset:0;z-index:99999;background:#0f172a;display:flex;flex-wrap:wrap;gap:24px;align-items:center;justify-content:center;padding:40px;";
document.body.appendChild(host);

createRoot(host).render(
  React.createElement(
    React.Fragment,
    null,
    STATES.map((s) =>
      React.createElement(
        "div",
        { key: s, style: { textAlign: "center", color: "#94a3b8", fontSize: 12 } },
        React.createElement(BloubAvatar, { size: 120, state: s }),
        React.createElement("div", null, s),
      ),
    ),
  ),
);
