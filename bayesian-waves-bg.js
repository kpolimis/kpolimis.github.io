/**
 * bayesian-waves-bg.js  [PRIMARY]
 * Animated Bayesian posterior distribution waves for Kivan Polimis's Quarto site.
 * Layered probability density curves shift and update — Stan/MCMC aesthetic.
 * Colour palette matches custom.scss navy/slate theme.
 *
 * Usage in _quarto.yml:
 *   format:
 *     html:
 *       theme: [cosmo, custom.scss]
 *       include-after-body: bayesian-waves-bg.js
 */
(function () {
  // Respect the user's motion preference — skip animation entirely if reduced motion is set.
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  const CONFIG = {
    iterations:   7,       // number of layered curves
    speed:        0.012,   // animation speed
    // opacity is applied via CSS on #network-canvas in custom.scss
  };

  const canvas = document.createElement('canvas');
  canvas.id = 'network-canvas';
  canvas.style.pointerEvents = 'none';  // never intercept clicks or hover events
  document.body.insertBefore(canvas, document.body.firstChild);
  const ctx = canvas.getContext('2d');
  let W, H;
  let dpr = window.devicePixelRatio || 1;

  function resize() {
    dpr = window.devicePixelRatio || 1;
    const cssW = window.innerWidth;
    const cssH = window.innerHeight;
    // Scale the backing buffer to the device pixel ratio for crisp rendering on HiDPI screens.
    canvas.width  = cssW * dpr;
    canvas.height = cssH * dpr;
    canvas.style.width  = cssW + 'px';
    canvas.style.height = cssH + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    W = cssW;
    H = cssH;
  }
  window.addEventListener('resize', resize);
  resize();

  let t = 0;
  let rafId = null;

  function residual(x, iter, time) {
    const phase = time * 0.4 + iter * 1.1;
    const decay = Math.exp(-iter * 0.38);
    return (
      Math.sin(x * 3.2 + phase)        * 0.50 * decay +
      Math.sin(x * 7.0 + phase * 1.4)  * 0.25 * decay +
      Math.sin(x * 1.8 + phase * 0.7)  * 0.30 * decay
    );
  }

  function tick() {
    ctx.clearRect(0, 0, W, H);

    const baseline = H * 0.52;

    // subtle grid lines
    ctx.strokeStyle = 'rgba(45, 106, 159, 0.08)';
    ctx.lineWidth   = 0.8;
    for (let gx = 0; gx < W; gx += W / 10) {
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, H); ctx.stroke();
    }
    for (let gy = 0; gy < 6; gy++) {
      const y = H * 0.1 + gy * (H * 0.8 / 5);
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
    }

    // baseline axis
    ctx.strokeStyle = 'rgba(74, 159, 212, 0.12)';
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(0, baseline); ctx.lineTo(W, baseline); ctx.stroke();

    // draw curves back-to-front (lowest iteration = broadest/most faded)
    for (let iter = CONFIG.iterations - 1; iter >= 0; iter--) {
      const alpha     = 0.12 + iter * 0.10;
      const fillAlpha = alpha * 0.28;
      const scale     = H * 0.34 * Math.exp(-iter * 0.38);

      // filled area
      ctx.beginPath();
      for (let px = 0; px <= W; px += 2) {
        const xn = (px / W) * Math.PI * 2;
        const y  = baseline + residual(xn, iter, t) * scale * 2.5;
        px === 0 ? ctx.moveTo(px, y) : ctx.lineTo(px, y);
      }
      ctx.lineTo(W, baseline);
      ctx.lineTo(0, baseline);
      ctx.closePath();
      ctx.fillStyle = `rgba(45, 106, 159, ${fillAlpha})`;
      ctx.fill();

      // stroke line
      ctx.beginPath();
      for (let px = 0; px <= W; px += 2) {
        const xn = (px / W) * Math.PI * 2;
        const y  = baseline + residual(xn, iter, t) * scale * 2.5;
        px === 0 ? ctx.moveTo(px, y) : ctx.lineTo(px, y);
      }
      ctx.strokeStyle = `rgba(74, 159, 212, ${alpha})`;
      ctx.lineWidth   = 1.0 + (CONFIG.iterations - iter) * 0.18;
      ctx.stroke();
    }

    t += CONFIG.speed;
    rafId = requestAnimationFrame(tick);
  }

  // Pause the rAF loop when the tab is hidden to avoid burning CPU in the background.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; }
    } else {
      if (rafId === null) rafId = requestAnimationFrame(tick);
    }
  });

  rafId = requestAnimationFrame(tick);
})();
