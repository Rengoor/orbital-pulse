# Vendored MediaPipe Gesture Recognizer

These files are vendored so the helmet HUD's camera gestures (`frontend/hud/gestures.mjs`)
run fully offline. The page fetches nothing from the network.

| File | Source | SHA-256 |
|---|---|---|
| `vision_bundle.mjs` | npm `@mediapipe/tasks-vision@1.2.0` (published 2026-10-27; tarball integrity checked against the registry's sha512) | `870da5cfc43bfcf2a8b0f14e8152dae8c7e701722e1191b0e592b94b81b4127a` |
| `wasm/vision_wasm_internal.js` | same package | `85c1a342be70427987f900969a5f26e17557351111364e6585e97fb03e93e108` |
| `wasm/vision_wasm_internal.wasm` | same package | `bcc13df22d3d69ec8cbe8e280989356d844ae00f4523eb82072d2484f44134dc` |
| `gesture_recognizer.task` | `https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task` (MD5 matched the server's `x-goog-hash`) | `97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482` |

License: Apache-2.0 (MediaPipe, Google). Only the SIMD wasm build is included. Every
current Chrome, Edge, Firefox and Safari supports WebAssembly SIMD.

To upgrade, download the new package and model, check their hashes, then replace
these files and update this table. `backend/tests/test_frontend_integration.py`
pins the hashes, so an unreviewed change fails the tests.
