/* Camera hand gestures for the helmet HUD.
 *
 * Gestures only drive the HUD's own controls (the health sidebar and on-screen
 * buttons). They never change a verdict or a reading. Hand tracking runs on this
 * device with the vendored MediaPipe Gesture Recognizer (../js/vendor/mediapipe);
 * no camera frame leaves the page and nothing is fetched from the network.
 *
 *   Point (index finger)        -> moves a cursor ring drawn on your fingertip
 *   Pinch (thumb to index)      -> presses the button under the cursor; with no
 *                                  button there, collapses or opens the sidebar
 *   Swipe right / left, flat open hand -> collapse / open the sidebar
 *   Open palm, held still       -> expand the sidebar
 *   Fist, held still            -> normal sidebar
 *
 * The tracked hand is drawn over the camera image (skeleton, fingertip cursor,
 * and a hint of what a pinch would do) so control can be precise.
 */

const VENDOR = new URL('../js/vendor/mediapipe/', import.meta.url).href;

// Interpretation constants (project decisions, tuned for a laptop webcam at arm's length).
export const TUNING = {
  swipeDistance: 0.22,   // fraction of the frame width the wrist must travel
  swipeWindowMs: 450,    // ... within this time
  swipeMaxDrift: 0.18,   // max vertical travel, so a wave up or down is not a swipe
  holdMs: 600,           // a pose must be held this long
  holdMaxDrift: 0.06,    // and the wrist must stay this still
  minScore: 0.6,         // canned-gesture confidence
  cooldownMs: 1000,      // ignore new swipe/hold gestures this long after one fires
  maxFrameGapMs: 250,    // a longer gap between frames restarts swipe tracking
  pinchPress: 0.28,      // thumb-index gap / palm size below which a pinch starts
  pinchRelease: 0.42,    // ... and above which it ends (hysteresis: no chatter)
  pinchMinReach: 1.2,    // index tip must be this much further from the wrist than its knuckle
                         // (an extended finger), so a fist never reads as a pinch
  pinchCooldownMs: 350,  // minimum time between two pinches
  aimLagMs: 120,         // a pinch acts where the fingertip was this long before it closed
};

const POSE_COMMAND = { Open_Palm: 'expand', Closed_Fist: 'normal' };

/* Turns a stream of per-frame hand observations into commands. Pure: no camera,
 * no DOM, so it can be tested with synthetic frames.
 *   frame = { t: ms, hand: null | { x, y, gesture, score, pinch?, reach? } }
 * x and y are the wrist position, 0..1, x already mirrored so that moving the
 * hand to the wearer's right increases x. pinch is the thumb-index gap divided
 * by palm size; reach is index-tip-to-wrist over index-knuckle-to-wrist. */
export class GestureInterpreter {
  constructor(tuning = TUNING) {
    this.k = tuning;
    this.track = [];
    this.hold = null;
    this.quietUntil = 0;
    this.pinched = false;
    this.pinchQuietUntil = 0;
  }

  push(frame) {
    const k = this.k, t = frame.t, hand = frame.hand;
    if (!hand) { this.track = []; this.hold = null; this.pinched = false; return null; }

    // Pinch: a press edge with hysteresis. While pinched, nothing else fires.
    if (hand.pinch != null) {
      if (this.pinched) {
        if (hand.pinch > k.pinchRelease) this.pinched = false;
        this.track = []; this.hold = null;
        return null;
      }
      if (hand.pinch < k.pinchPress && (hand.reach == null || hand.reach >= k.pinchMinReach) &&
          hand.gesture !== 'Closed_Fist' && t >= this.pinchQuietUntil) {
        this.pinched = true;
        this.pinchQuietUntil = t + k.pinchCooldownMs;
        this.track = []; this.hold = null;
        return { command: 'pinch', gesture: 'Pinch' };
      }
    }

    // During the cooldown nothing is tracked, so the end of one gesture can never
    // become the start of the next.
    if (t < this.quietUntil) { this.track = []; this.hold = null; return null; }

    // Swipe: a flat open hand travelling across the frame within a short window.
    // Requiring an open palm keeps pointing movements from ever reading as swipes.
    // A gap in the frames (hand briefly lost, tab paused) starts a new track.
    const last = this.track[this.track.length - 1];
    if (hand.gesture !== 'Open_Palm' || (last && t - last.t > k.maxFrameGapMs)) this.track = [];
    if (hand.gesture === 'Open_Palm') this.track.push({ t, x: hand.x, y: hand.y });
    while (this.track.length && t - this.track[0].t > k.swipeWindowMs) this.track.shift();
    const first = this.track[0];
    if (first) {
      const dx = hand.x - first.x, dy = Math.abs(hand.y - first.y);
      if (Math.abs(dx) >= k.swipeDistance && dy <= k.swipeMaxDrift) {
        return this.fire(t, dx > 0 ? { command: 'dock', gesture: 'Swipe right' } : { command: 'normal', gesture: 'Swipe left' });
      }
    }

    // Held pose: same canned gesture, confident, wrist nearly still.
    const command = hand.score >= k.minScore ? POSE_COMMAND[hand.gesture] : undefined;
    if (!command) { this.hold = null; return null; }
    if (!this.hold || this.hold.gesture !== hand.gesture ||
        Math.hypot(hand.x - this.hold.x, hand.y - this.hold.y) > k.holdMaxDrift) {
      this.hold = { gesture: hand.gesture, since: t, x: hand.x, y: hand.y };
      return null;
    }
    if (t - this.hold.since >= k.holdMs) {
      return this.fire(t, { command, gesture: hand.gesture === 'Open_Palm' ? 'Open palm' : 'Fist' });
    }
    return null;
  }

  fire(t, result) {
    this.quietUntil = t + this.k.cooldownMs;
    this.track = []; this.hold = null;
    return result;
  }
}

/* ---------- geometry ---------- */

// Hand landmark connections (MediaPipe hand model, 21 points).
const BONES = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];

/* Maps a normalised landmark to screen pixels for a video drawn with
 * object-fit: cover and mirrored, so overlay and cursor sit on the visible hand. */
export function makeProjector(videoW, videoH, screenW, screenH) {
  const scale = Math.max(screenW / videoW, screenH / videoH);
  const dw = videoW * scale, dh = videoH * scale;
  const ox = (screenW - dw) / 2, oy = (screenH - dh) / 2;
  return (p) => ({ x: ox + (1 - p.x) * dw, y: oy + p.y * dh });
}

function dist(a, b, aspect) { return Math.hypot((a.x - b.x) * aspect, a.y - b.y); }

/* Pinch gap and finger reach from the 21 landmarks (aspect-corrected). */
export function handMetrics(lm, aspect) {
  const palm = dist(lm[0], lm[9], aspect) || 1e-6;
  return {
    pinch: dist(lm[4], lm[8], aspect) / palm,
    reach: dist(lm[8], lm[0], aspect) / (dist(lm[5], lm[0], aspect) || 1e-6),
  };
}

/* ---------- drawing ---------- */

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function drawOverlay(ctx, view) {
  const { width: W, height: H } = ctx.canvas;
  ctx.clearRect(0, 0, W, H);
  if (!view.points) return;
  const holo = cssVar('--holo', '#4fe0d0'), ink = cssVar('--ink', '#e8eef3'), voidc = cssVar('--void', '#070b10');
  const dpr = view.dpr, P = view.points.map((p) => ({ x: p.x * dpr, y: p.y * dpr }));

  // Skeleton: dark under-stroke so it reads on any background, then holo.
  ctx.lineCap = 'round';
  for (const [w, c] of [[6 * dpr, voidc], [3 * dpr, holo]]) {
    ctx.lineWidth = w; ctx.strokeStyle = c; ctx.beginPath();
    for (const [a, b] of BONES) { ctx.moveTo(P[a].x, P[a].y); ctx.lineTo(P[b].x, P[b].y); }
    ctx.stroke();
  }
  for (const p of P) {
    ctx.beginPath(); ctx.arc(p.x, p.y, 4 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = ink; ctx.fill(); ctx.lineWidth = 2 * dpr; ctx.strokeStyle = voidc; ctx.stroke();
  }

  // Cursor ring on the index fingertip; filled while pinched.
  const c = { x: view.cursor.x * dpr, y: view.cursor.y * dpr }, r = 16 * dpr;
  ctx.beginPath(); ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
  ctx.lineWidth = 7 * dpr; ctx.strokeStyle = voidc; ctx.stroke();
  ctx.lineWidth = 3 * dpr; ctx.strokeStyle = view.target ? ink : holo; ctx.stroke();
  if (view.pinched) { ctx.globalAlpha = 0.55; ctx.fillStyle = holo; ctx.fill(); ctx.globalAlpha = 1; }
  ctx.beginPath(); ctx.arc(c.x, c.y, 2.5 * dpr, 0, Math.PI * 2); ctx.fillStyle = ink; ctx.fill();

  // Hint plate: what is recognised, and what a pinch would do here.
  const lines = [view.gestureLabel, view.hint].filter(Boolean);
  if (!lines.length) return;
  ctx.font = `600 ${16 * dpr}px ${cssVar('--font-sans', 'system-ui, sans-serif')}`;
  const pad = 8 * dpr, lh = 22 * dpr;
  const w = Math.max(...lines.map((s) => ctx.measureText(s).width)) + pad * 2, h = lines.length * lh + pad;
  let x = c.x + r + 10 * dpr, y = c.y - h / 2;
  if (x + w > W - 8 * dpr) x = c.x - r - 10 * dpr - w;
  y = Math.max(8 * dpr, Math.min(H - h - 8 * dpr, y));
  ctx.globalAlpha = 0.85; ctx.fillStyle = voidc; ctx.fillRect(x, y, w, h); ctx.globalAlpha = 1;
  ctx.fillStyle = ink; ctx.textBaseline = 'top';
  lines.forEach((s, i) => ctx.fillText(s, x + pad, y + pad / 2 + i * lh + 2 * dpr));
}

/* ---------- recognizer ---------- */

async function createRecognizer() {
  const { GestureRecognizer } = await import(VENDOR + 'vision_bundle.mjs');
  const fileset = {
    wasmLoaderPath: VENDOR + 'wasm/vision_wasm_internal.js',
    wasmBinaryPath: VENDOR + 'wasm/vision_wasm_internal.wasm',
  };
  const options = (delegate) => ({
    baseOptions: { modelAssetPath: VENDOR + 'gesture_recognizer.task', delegate },
    runningMode: 'VIDEO',
    numHands: 1,
  });
  try {
    return await GestureRecognizer.createFromOptions(fileset, options('GPU'));
  } catch (e) {
    return GestureRecognizer.createFromOptions(fileset, options('CPU'));
  }
}

const GESTURE_WORD = { Open_Palm: 'Open palm', Closed_Fist: 'Fist', Pointing_Up: 'Pointing', Thumb_Up: 'Thumb up',
  Thumb_Down: 'Thumb down', Victory: 'Victory', ILoveYou: 'I love you', None: 'Hand' };

/* Starts the camera and the recognizer.
 *   canvas          full-screen overlay to draw the hand on (optional)
 *   onCommand(c)    { command: 'pinch'|'dock'|'normal'|'expand', gesture, x?, y? }
 *                   pinch carries the screen point it was aimed at
 *   onHand(bool)    a hand appeared or disappeared
 *   describe(x, y)  returns the hint for a pinch at that screen point
 *   showHand()      return false to hide the overlay drawing
 * Returns { stop }. Throws if the camera or the model cannot start. */
export async function startGestures(video, { canvas, onCommand, onHand, describe, showHand } = {}) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('This browser gives no camera access here (camera needs https or localhost).');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720, facingMode: 'user' }, audio: false });
  let recognizer;
  try {
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    await video.play();
    recognizer = await createRecognizer();
  } catch (e) {
    stream.getTracks().forEach((tr) => tr.stop());
    throw e;
  }

  const ctx = canvas ? canvas.getContext('2d') : null;
  const interp = new GestureInterpreter();
  let running = true, lastFrame = -1, handSeen = false, raf = 0;
  let cursor = null;            // smoothed fingertip, screen px
  let drawn = false;            // something is on the canvas that needs clearing
  function clear() { if (ctx && drawn) { drawOverlay(ctx, { points: null }); drawn = false; } }
  const aimHistory = [];        // recent cursor positions, for aiming a pinch

  function sizeCanvas() {
    if (!canvas) return 1;
    const dpr = window.devicePixelRatio || 1, w = Math.round(innerWidth * dpr), h = Math.round(innerHeight * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    return dpr;
  }

  function step() {
    if (!running) return;
    raf = requestAnimationFrame(step);
    if (video.readyState < 2 || video.currentTime === lastFrame) return;
    lastFrame = video.currentTime;
    const now = performance.now();
    const res = recognizer.recognizeForVideo(video, now);
    const lm = res.landmarks && res.landmarks[0];
    const g = res.gestures && res.gestures[0] && res.gestures[0][0];
    const dpr = sizeCanvas();

    if (!lm) {
      if (handSeen) { handSeen = false; if (onHand) onHand(false); }
      cursor = null; aimHistory.length = 0;
      interp.push({ t: now, hand: null });
      clear();
      return;
    }
    if (!handSeen) { handSeen = true; if (onHand) onHand(true); }

    const aspect = (video.videoWidth || 16) / (video.videoHeight || 9);
    const project = makeProjector(video.videoWidth, video.videoHeight, innerWidth, innerHeight);
    const points = lm.map(project);
    const tip = points[8];
    // Light smoothing: steady enough to aim, quick enough to follow.
    cursor = cursor ? { x: cursor.x + (tip.x - cursor.x) * 0.5, y: cursor.y + (tip.y - cursor.y) * 0.5 } : tip;
    aimHistory.push({ t: now, x: cursor.x, y: cursor.y });
    while (aimHistory.length && now - aimHistory[0].t > 600) aimHistory.shift();

    const m = handMetrics(lm, aspect);
    const gesture = g ? g.categoryName : 'None';
    const out = interp.push({ t: now, hand: { x: 1 - lm[0].x, y: lm[0].y, gesture, score: g ? g.score : 0, pinch: m.pinch, reach: m.reach } });
    if (out) {
      if (out.command === 'pinch') {
        // Act where the fingertip was just before the fingers closed.
        const aim = aimHistory.find((a) => now - a.t <= TUNING.aimLagMs) || cursor;
        out.x = aim.x; out.y = aim.y;
      }
      if (onCommand) onCommand(out);
    }

    if (ctx) {
      if (showHand && showHand() === false) { clear(); return; }
      drawn = true;
      drawOverlay(ctx, {
        dpr, points, cursor, pinched: interp.pinched,
        gestureLabel: interp.pinched ? 'Pinch' : (GESTURE_WORD[gesture] || gesture),
        hint: describe ? describe(cursor.x, cursor.y) : null,
      });
    }
  }
  raf = requestAnimationFrame(step);

  return {
    stop() {
      running = false;
      cancelAnimationFrame(raf);
      drawn = true; clear();
      stream.getTracks().forEach((tr) => tr.stop());
      video.srcObject = null;
      try { recognizer.close(); } catch (e) { /* already closed */ }
    },
  };
}
