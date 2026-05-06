/**
 * hero-coins.js — Optimised falling gold coin background (all pages)
 * Fixed-position canvas behind #app. Capped at 30 fps, adaptive detail.
 */
(function () {
  'use strict';

  const COIN_COUNT  = 14;
  const FRAME_MS    = 1000 / 30; // 30 fps cap
  const CANVAS_OPACITY = 0.65;

  function rand(min, max) { return min + Math.random() * (max - min); }

  /* ── Draw one coin ─────────────────────────────────────────────── */
  function drawCoin(ctx, x, y, r, tilt, spinAngle, alpha, depth) {
    if (alpha <= 0 || r < 4) return;
    const ry = r * Math.abs(tilt);
    if (ry < 2) return;

    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(x, y);
    ctx.rotate(spinAngle);

    // Adaptive reed count: fewer segments for distant/small coins
    const reeds = depth > 0.5 ? 40 : 22;
    for (let i = 0; i < reeds; i++) {
      const a0 = (i / reeds) * Math.PI * 2;
      const a1 = ((i + 0.55) / reeds) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(Math.cos(a0) * r, Math.sin(a0) * ry);
      ctx.arc(0, 0, r, a0, a1);
      ctx.lineTo(Math.cos(a1) * (r - 3), Math.sin(a1) * (ry - 3 * tilt));
      ctx.arc(0, 0, r - 3, a1, a0, true);
      ctx.closePath();
      const br = 55 + Math.sin(a0 * 4 + spinAngle * 2) * 18;
      ctx.fillStyle = `hsl(42,75%,${br}%)`;
      ctx.fill();
    }

    // Face
    ctx.beginPath();
    ctx.ellipse(0, 0, r - 3, ry - 3 * tilt, 0, 0, Math.PI * 2);
    const fg = ctx.createRadialGradient(-r * 0.3, -ry * 0.35, r * 0.05, r * 0.2, ry * 0.25, r * 1.05);
    fg.addColorStop(0,    'hsl(48,90%,82%)');
    fg.addColorStop(0.25, 'hsl(45,85%,68%)');
    fg.addColorStop(0.55, 'hsl(42,80%,55%)');
    fg.addColorStop(0.80, 'hsl(38,75%,44%)');
    fg.addColorStop(1,    'hsl(35,70%,34%)');
    ctx.fillStyle = fg;
    ctx.fill();

    // Clip inner details to face
    ctx.beginPath();
    ctx.ellipse(0, 0, r - 3, ry - 3 * tilt, 0, 0, Math.PI * 2);
    ctx.clip();

    // Inner border (near coins only)
    if (depth > 0.4) {
      ctx.beginPath();
      ctx.ellipse(0, 0, r - 5, ry - 5 * tilt, 0, 0, Math.PI * 2);
      ctx.strokeStyle = 'hsla(48,80%,78%,0.6)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // Dollar sign (medium+ depth)
    if (depth > 0.3 && ry > 8) {
      const fs = Math.max(6, r * 0.55);
      ctx.save();
      ctx.scale(1, ry / r);
      ctx.font = `900 ${fs}px Georgia,serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = 'hsla(35,70%,28%,0.7)';
      ctx.fillText('$', r * 0.025, r * 0.025 / (ry / r));
      const tg = ctx.createLinearGradient(0, -fs * 0.5, 0, fs * 0.5);
      tg.addColorStop(0,   'hsl(50,95%,90%)');
      tg.addColorStop(0.4, 'hsl(48,88%,78%)');
      tg.addColorStop(1,   'hsl(42,75%,55%)');
      ctx.fillStyle = tg;
      ctx.fillText('$', 0, 0);
      ctx.restore();
    }

    // LIBERTY arc (near/large coins only — raised threshold)
    if (depth > 0.65 && r > 24) {
      ctx.save();
      ctx.scale(1, ry / r);
      const fsA = Math.max(4, r * 0.155);
      ctx.font = `700 ${fsA}px Arial,sans-serif`;
      ctx.fillStyle = 'hsla(48,80%,80%,0.75)';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      const txt = 'LIBERTY';
      const arcR = r * 0.72;
      const span = Math.PI * 0.6;
      const s0 = -Math.PI / 2 - span / 2;
      for (let i = 0; i < txt.length; i++) {
        const a = s0 + (i / (txt.length - 1)) * span;
        ctx.save();
        ctx.translate(Math.cos(a) * arcR, Math.sin(a) * arcR);
        ctx.rotate(a + Math.PI / 2);
        ctx.fillText(txt[i], 0, 0);
        ctx.restore();
      }
      ctx.restore();
    }

    // Stars (near/large only)
    if (depth > 0.7 && r > 28) {
      [[-r * 0.52, ry * 0.55], [r * 0.52, ry * 0.55], [0, ry * 0.68]].forEach(([sx, sy]) => {
        drawStar(ctx, sx, sy, r * 0.065, 'hsla(48,85%,78%,0.7)');
      });
    }

    // Gloss
    ctx.beginPath();
    ctx.ellipse(-r * 0.1, -ry * 0.25, r * 0.55, ry * 0.3, -0.3, 0, Math.PI * 2);
    const gl = ctx.createLinearGradient(-r * 0.3, -ry * 0.55, r * 0.1, ry * 0.05);
    gl.addColorStop(0,   `rgba(255,255,255,${0.5 * depth})`);
    gl.addColorStop(0.6, `rgba(255,255,255,${0.1 * depth})`);
    gl.addColorStop(1,    'rgba(255,255,255,0)');
    ctx.fillStyle = gl;
    ctx.fill();

    ctx.restore();
  }

  function drawStar(ctx, x, y, r, color) {
    ctx.save();
    ctx.translate(x, y);
    ctx.beginPath();
    for (let i = 0; i < 5; i++) {
      const a = (i * 4 * Math.PI) / 5 - Math.PI / 2;
      const b = ((i * 4 + 2) * Math.PI) / 5 - Math.PI / 2;
      if (i === 0) ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r);
      else         ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
      ctx.lineTo(Math.cos(b) * r * 0.4, Math.sin(b) * r * 0.4);
    }
    ctx.closePath();
    ctx.fillStyle = color;
    ctx.fill();
    ctx.restore();
  }

  /* ── Coin particle ─────────────────────────────────────────────── */
  class Coin {
    constructor(canvas, initY) {
      this.canvas = canvas;
      this.spawn(true, initY);
    }

    spawn(init, forceY) {
      const W = this.canvas.width;
      const H = this.canvas.height;
      this.depth  = Math.pow(Math.random(), 0.6);
      this.radius = 18 + this.depth * 28;
      this.vy     = rand(0.5, 1.2) * (0.5 + this.depth * 0.7);
      this.vx     = rand(-0.15, 0.15);
      this.x      = rand(this.radius, W - this.radius);
      this.y      = init
        ? (forceY !== undefined ? forceY : rand(-H * 0.6, H * 0.1))
        : rand(-this.radius * 4, -this.radius);
      this.spinAngle = rand(0, Math.PI * 2);
      this.spinSpeed = rand(0.004, 0.014) * (Math.random() < 0.5 ? 1 : -1);
      this.tilt      = rand(0.2, 0.95);
      this.tiltSpeed = rand(0.001, 0.003) * (Math.random() < 0.5 ? 1 : -1);
      this.alpha     = 0;
      this.baseAlpha = 0.45 + this.depth * 0.35;
      this.settleY   = H * rand(0.84, 0.97);
      this.settling  = false;
      this.settled   = false;
      this.settleAge = 0;
    }

    update(H) {
      this.alpha = Math.min(this.alpha + 0.035, this.baseAlpha);

      if (this.settled) {
        this.settleAge++;
        if (this.settleAge > 80 + Math.random() * 60) {
          this.alpha -= 0.01;
          if (this.alpha <= 0) this.spawn(false);
        }
        return;
      }

      if (!this.settling) {
        this.x += this.vx;
        this.y += this.vy;
        this.spinAngle += this.spinSpeed;
        this.tilt += this.tiltSpeed;
        if (this.tilt > 0.98 || this.tilt < 0.12) this.tiltSpeed *= -1;
      }

      if (this.y >= this.settleY) {
        this.settling = true;
        this.vy *= 0.7;
        if (this.vy < 0.06) {
          this.settled   = true;
          this.settleAge = 0;
          this.y         = this.settleY;
        }
      }

      const W = this.canvas.width;
      if (this.x < -this.radius * 2) this.x = W + this.radius;
      if (this.x > W + this.radius * 2) this.x = -this.radius;
      if (this.y > H + this.radius * 3) this.spawn(false);
    }

    draw(ctx) {
      drawCoin(ctx, this.x, this.y, this.radius, this.tilt, this.spinAngle, this.alpha, this.depth);
    }
  }

  /* ── Bootstrap ─────────────────────────────────────────────────── */
  function init() {
    try {
      const old = document.getElementById('hero-coins-canvas');
      if (old) old.remove();

      const canvas = document.createElement('canvas');
      canvas.id = 'hero-coins-canvas';
      // Fixed behind #app (which has z-index:1) — visible on all pages
      canvas.style.cssText =
        'position:fixed;inset:0;width:100%;height:100%;' +
        'pointer-events:none;z-index:0;opacity:' + CANVAS_OPACITY;

      // Insert before #app so it sits underneath it in stacking order
      const app = document.getElementById('app');
      document.body.insertBefore(canvas, app || document.body.firstChild);

      const ctx = canvas.getContext('2d');

      function resize() {
        canvas.width  = window.innerWidth;
        canvas.height = window.innerHeight;
      }
      resize();
      window.addEventListener('resize', resize);

      // Spread coins across the initial viewport
      const coins = [];
      for (let i = 0; i < COIN_COUNT; i++) {
        coins.push(new Coin(canvas, rand(-canvas.height * 0.4, canvas.height * 0.8)));
      }
      // Render far coins first (painter's algorithm)
      coins.sort((a, b) => a.depth - b.depth);

      // Pause when tab is not visible — no point burning CPU
      let paused = false;
      document.addEventListener('visibilitychange', () => { paused = document.hidden; });

      let lastFrame = 0;
      function frame(ts) {
        requestAnimationFrame(frame);
        if (paused || ts - lastFrame < FRAME_MS) return;
        lastFrame = ts;
        try {
          const W = canvas.width;
          const H = canvas.height;
          ctx.clearRect(0, 0, W, H);
          for (const c of coins) { c.update(H); c.draw(ctx); }
        } catch (_) {}
      }
      requestAnimationFrame(frame);

    } catch (e) {
      console.warn('[hero-coins] init error:', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();