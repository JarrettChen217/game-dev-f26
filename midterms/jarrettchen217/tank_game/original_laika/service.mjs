// Local transport only. AI, physics and their RNG execute inside unchanged WASM.
import fs from 'node:fs';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';

const path = fileURLToPath(new URL('./engine.wasm', import.meta.url));
const {instance: {exports: e}} = await WebAssembly.instantiate(fs.readFileSync(path), {});
if (e.kf_hybrid_schema_version() !== 24 || e.kf_hybrid_observation_len() !== 1038) {
  throw new Error('Pinned original-engine observation ABI mismatch');
}
let handle = null;
function snapshot() {
  const render = Array.from(new Float32Array(e.memory.buffer,
    e.kf_render_ptr(handle), e.kf_render_len(handle)));
  const ptr = e.kf_hybrid_observation(handle, 1);
  const obs = new Float32Array(e.memory.buffer, ptr, e.kf_hybrid_observation_len());
  // These are observed facts. Never read or replace Laika's goals/actions/RNG.
  return {render, status: Array.from(obs.slice(856, 880)),
    bullets: Array.from(obs.slice(900, 1000))};
}
const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
for await (const line of lines) {
  let request;
  try {
    request = JSON.parse(line);
    let result;
    if (request.op === 'init') {
      const candidate = e.kf_new(request.seed, 1);
      if (handle !== null) e.kf_free(handle);
      handle = candidate;
      result = snapshot();
    } else if (request.op === 'step') {
      const [throttle, turn, fire] = request.action;
      e.kf_set_input(handle, 1, throttle > 0 ? 1 : 0, throttle < 0 ? 1 : 0,
        turn < 0 ? 1 : 0, turn > 0 ? 1 : 0, fire ? 1 : 0, 1);
      const flags = e.kf_step(handle);
      result = {...snapshot(), flags};
    } else if (request.op === 'snapshot') {
      result = snapshot();
    } else if (request.op === 'close') {
      if (handle !== null) e.kf_free(handle);
      handle = null;
      process.stdout.write(JSON.stringify({id: request.id, result: null})+'\n');
      break;
    } else {
      throw new Error('unknown original-engine operation');
    }
    process.stdout.write(JSON.stringify({id: request.id, result})+'\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({id: request?.id, error: String(error)})+'\n');
  }
}
if (handle !== null) e.kf_free(handle);
lines.close();
