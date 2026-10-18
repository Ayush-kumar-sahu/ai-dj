"""Little celebrations: a confetti burst (with flying vinyl) when a set is ready."""

from __future__ import annotations

import streamlit as st

_CONFETTI_JS = r"""
export default function (component) {
  const { data } = component;
  if (!data || !data.id) return;
  const key = "aidj-confetti-" + data.id;
  try { if (sessionStorage.getItem(key)) return; sessionStorage.setItem(key, "1"); } catch (e) {}
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const c = document.createElement("canvas");
  Object.assign(c.style, { position: "fixed", inset: "0", width: "100vw", height: "100vh",
                           pointerEvents: "none", zIndex: "999999" });
  document.body.appendChild(c);
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  c.width = innerWidth * dpr; c.height = innerHeight * dpr;
  const g = c.getContext("2d"); g.scale(dpr, dpr);
  const colors = ["#ff3dcb", "#8f6bff", "#2ee6ff", "#b8ff4d", "#ffe14d"];
  const bits = Array.from({ length: 170 }, () => ({
    x: innerWidth * (0.25 + Math.random() * 0.5), y: innerHeight * 0.38,
    vx: (Math.random() - 0.5) * 15, vy: -7 - Math.random() * 12,
    r: 4 + Math.random() * 6, a: Math.random() * 6.3, va: (Math.random() - 0.5) * 0.3,
    c: colors[(Math.random() * colors.length) | 0], record: Math.random() < 0.18 }));
  const t0 = performance.now();
  let raf = 0;
  const tick = (now) => {
    const t = (now - t0) / 1000;
    g.clearRect(0, 0, innerWidth, innerHeight);
    for (const p of bits) {
      p.vy += 0.34; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.a += p.va;
      g.save(); g.globalAlpha = Math.max(0, 1 - t / 3.2); g.translate(p.x, p.y); g.rotate(p.a);
      if (p.record) {  // a tiny spinning record
        g.fillStyle = "#0b0815"; g.beginPath(); g.arc(0, 0, p.r * 1.25, 0, 6.3); g.fill();
        g.fillStyle = p.c; g.beginPath(); g.arc(0, 0, p.r * 0.5, 0, 6.3); g.fill();
      } else { g.fillStyle = p.c; g.fillRect(-p.r, -p.r * 0.4, p.r * 2, p.r * 0.8); }
      g.restore();
    }
    if (t < 3.4) raf = requestAnimationFrame(tick); else c.remove();
  };
  raf = requestAnimationFrame(tick);
  return () => { cancelAnimationFrame(raf); c.remove(); };
}
"""

_CONFETTI = st.components.v2.component("aidj_confetti", js=_CONFETTI_JS)


def confetti(burst_id: str) -> None:
    """Fire once per burst id per browser tab — reruns don't replay it."""
    _CONFETTI(data={"id": burst_id}, key=f"confetti-{burst_id}")
