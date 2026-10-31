# Third-party notices

AI-use disclosure: Codex ported the following source under Hao's direction.

## Killfield / Laika

The optional `laika-original-v1` profile includes the **unchanged** cached original `kf_engine.wasm` and source modules in `tank_game/original_laika/source/`, all from Cichlider/killfield. Its artifact SHA256 is `7aea2a29bef93c6339fe38b7948cf3d2253757dd4b0c5d70624a8265ce58541d`; provenance/source blobs are pinned in `tank_game/original_laika/manifest.json`, and the MIT text is also included beside the artifact. The local Node transport, Simulator snapshot/action adapter and Pyxel presentation do not rewrite the Laika brain. This is an opt-in original-engine backend, not a claimed local rebuild of the author's binary.

Native Laika adapts Cichlider's `engine/src/laika.rs`, `ballistics.rs` and `maze.rs` from https://github.com/Cichlider/killfield, reference fork commit `8ccc530f70216553f5146872a2cc3864446df0dd`. The Rust source identifies its predecessor JavaScript files. Adapted files: `tank_game/laika.py` and `tank_game/laika_geometry.py`; `tank_game/hull.py` uses the reference81:61 base-hull dimensions normalized to native radius, with independently written native-clock geometry. Differences and validation are recorded in `docs/evidence/native-laika.md`.

MIT License

Copyright (c) 2026 Cichlider

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
