/* Camera hand gestures for the helmet HUD.
 *
 * Gestures only move the HUD's own panels (dock, normal, expand). They never
 * touch a verdict, a reading or the backend. Hand tracking runs on this device
 * with the vendored MediaPipe Gesture Recognizer (../js/vendor/mediapipe); no
 * camera frame leaves the page and nothing is fetched from the network.
 *
 *   Swipe right  -> "dock"    push the health panels to the side
 *   Swipe left   -> "normal"  bring them back
 *   Open palm, held still -> "expand"  larger text and values
 *   Fist, held still      -> "normal"
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
  cooldownMs: 1000,      // ignore new gestures this long after one fires
  maxFrameGapMs: 250,    // a longer gap between frames restarts swipe tracking
};

const POSE_COMMAND = { Open_Palm: 'expand', Closed_Fist: 'normal' };

/* Turns a stream of per-frame hand observations into commands. Pure: no camera,
 * no DOM, so it can be tested with synthetic frames.
 *   frame = { t: ms, hand: null | { x, y, gesture, score } }
 * x and y are the wrist position, 0..1, x already mirrored so that moving the
 * hand to the wearer's right increases x. */
export class GestureInterpreter {
  constructor(tuning = TUNING) {
    this.k = tuning;
    this.track = [];
    this.hold = null;
    this.quietUntil = 0;
  }

  push(frame) {
    const k = this.k, t = frame.t, hand = frame.hand;
    if (!hand) { this.track = []; this.hold = null; return null; }
    // During the cooldown nothing is tracked, so the end of one gesture can never
    // become the start of the next.
    if (t < this.quietUntil) { this.track = []; this.hold = null; return null; }

    // Swipe: wrist travel across the frame within a short window. A gap in the
    // frames (hand briefly lost, tab paused) starts a new track.
    const last = this.track[this.track.length - 1];
    if (last && t - last.t > k.maxFrameGapMs) this.track = [];
    this.track.push({ t, x: hand.x, y: hand.y });
    while (this.track.length && t - this.track[0].t > k.swipeWindowMs) this.track.shift();
    const first = this.track[0];
    const dx = hand.x - first.x, dy = Math.abs(hand.y - first.y);
    if (Math.abs(dx) >= k.swipeDistance && dy <= k.swipeMaxDrift) {
      return this.fire(t, dx > 0 ? { command: 'dock', gesture: 'Swipe right' } : { command: 'normal', gesture: 'Swipe left' });
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

/* Starts the camera and the recognizer. Calls onCommand({command, gesture}) for
 * each recognised gesture and onHand(bool) when a hand appears or disappears.
 * Returns { stop }. Throws if the camera or the model cannot start. */
export async function startGestures(video, { onCommand, onHand } = {}) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new Error('This browser gives no camera access here (camera needs https or localhost).');
  }
  const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false });
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

  const interp = new GestureInterpreter();
  let running = true, lastFrame = -1, handSeen = false, timer = null;
  const FRAME_MS = 66;   // about 15 recognitions a second is plenty for these gestures

  function step() {
    if (!running) return;
    const now = performance.now();
    if (video.readyState >= 2 && video.currentTime !== lastFrame) {
      lastFrame = video.currentTime;
      const res = recognizer.recognizeForVideo(video, now);
      const lm = res.landmarks && res.landmarks[0];
      const g = res.gestures && res.gestures[0] && res.gestures[0][0];
      const hand = lm ? { x: 1 - lm[0].x, y: lm[0].y, gesture: g ? g.categoryName : 'None', score: g ? g.score : 0 } : null;
      if (!!hand !== handSeen) { handSeen = !!hand; if (onHand) onHand(handSeen); }
      const out = interp.push({ t: now, hand });
      if (out && onCommand) onCommand(out);
    }
    timer = setTimeout(step, FRAME_MS);
  }
  step();

  return {
    stop() {
      running = false;
      clearTimeout(timer);
      stream.getTracks().forEach((tr) => tr.stop());
      video.srcObject = null;
      try { recognizer.close(); } catch (e) { /* already closed */ }
    },
  };
}
