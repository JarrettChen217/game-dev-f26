// Independent direct-export observer, deliberately no production bridge import.
import fs from 'node:fs';
const [artifact, seedText] = process.argv.slice(2);
const actions = JSON.parse(fs.readFileSync(0, 'utf8'));
const {instance: {exports: e}} = await WebAssembly.instantiate(fs.readFileSync(artifact), {});
const handle = e.kf_new(Number(seedText), 1); // Original viewer: Laika0, human1.
const render = () => Array.from(new Float32Array(e.memory.buffer,
  e.kf_render_ptr(handle), e.kf_render_len(handle)));
const states = [render()];
try {
  for (const [throttle, turn, fire] of actions) {
    e.kf_set_input(handle, 1, throttle > 0 ? 1 : 0, throttle < 0 ? 1 : 0,
      turn < 0 ? 1 : 0, turn > 0 ? 1 : 0, fire ? 1 : 0, 1);
    e.kf_step(handle);
    states.push(render());
    if (states.at(-1)[14] > .5) break; // Host stops at source freeze, before auto next round.
  }
  process.stdout.write(JSON.stringify(states));
} finally { e.kf_free(handle); }
