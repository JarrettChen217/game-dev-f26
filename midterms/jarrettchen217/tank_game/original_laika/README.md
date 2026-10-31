# Unchanged original Laika profile

`engine.wasm` is copied byte-for-byte from the already-cached original Killfield viewer asset. `manifest.json` pins its SHA256 and the unmodified source-module blobs retained in `source/`. It has not been rebuilt locally. MIT copyright2026 Cichlider: see `LICENSE` and the repository third-party notice.

The optional profile requires an existing Node executable on PATH. Ordinary native gameplay imports/starts no Node process. `service.mjs` instantiates this module with no imports and mask1: original Laika seat0, external human seat1, matching the original viewer. All simulation and bot decisions happen in that one module. `bridge.py` only transports commands; `world.py` only adapts public snapshots, input validation and host lifecycle.

Original generated mazes,25Hz physics/AI, hull+barrel hit geometry, point bullets, trigger edges, ricochets, settlement and RNG are retained. Native custom maps are not accepted by this profile. A retained render slot is not a stable projectile ID; the profile explicitly labels this limitation and uses a separate observation schema. It must not silently enter the native340/18 learning ABI.

`tests/fixtures/original_laika_oracle.mjs` independently invokes original exports without importing production transport. The adapter is compared against it frame-for-frame under identical seeds/inputs. These checks validate the integration; they do not claim an independent reimplementation or a reconstructed author build.
