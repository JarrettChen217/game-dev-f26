"""Serial preparation adapter for the existing pure-Laika DuelVec buffer API.

No frozen/MPC pool, fake opponent features, policy or training loop is supplied.
"""
import numpy as np

from tank_game.laika_60hz.training.environment import Source60HybridEnv


class Source60HybridVec:
    obs_dim, schema_version, actions = 1028, 24, 18
    episode_frames, grace_frames = 1800, 300

    def __init__(self, count, seed, weights=(1., 0., 0.), threads=0):
        if type(count) is not int or count <= 0 or type(seed) is not int or not 0 <= seed < 2**32:
            raise ValueError('positive count and uint32 seed required')
        if tuple(weights) != (1., 0., 0.) or threads not in (0, 1):
            raise ValueError('preparation supports pure Laika and a serial native adapter only')
        self.count, self.seed, self.weights = count, seed, tuple(weights)
        self.envs = []
        try:
            for _ in range(count):
                self.envs.append(Source60HybridEnv())
        except Exception:
            self.close()
            raise
        self.episodes = np.zeros(count, np.uint64)
        self.obs, self.masks = np.empty((count, 1028), np.float32), np.empty((count, 10), np.uint8)
        self.rewards = np.zeros(count, np.float32)
        self.dones, self.terminals, self.outcomes, self.opponents = (np.zeros(count, np.uint8) for _ in range(4))
        self.frames, self.action_changes, self.shots, self.hits = (np.zeros(count, np.uint32) for _ in range(4))
        self.needs_action = np.zeros(count, np.uint8)  # actual fixed internal Laika, no external policy
        for i in range(count):
            self._reset(i)

    def _reset(self, i):
        seed = (self.seed+i*0x9e3779b9+int(self.episodes[i])*0x85ebca6b) % 2**32
        obs, _ = self.envs[i].reset(seed=seed)
        self.obs[i], self.masks[i] = obs['features'], obs['mask']

    def step(self, actions, opponent_actions=None):
        values = np.asarray(actions)
        if (values.shape != (self.count,) or values.dtype.kind not in 'iu'
                or np.any(values < 0) or np.any(values >= 18) or opponent_actions is not None):
            raise ValueError('one valid source action per learner; no external opponent')
        self.terminals.fill(0)
        self.rewards.fill(0)
        self.shots.fill(0)
        self.hits.fill(0)
        for i, action in enumerate(values):
            if self.dones[i]:
                continue
            before = self.envs[i].state()
            obs, reward, term, trunc, info = self.envs[i].step(int(action))
            self.obs[i], self.masks[i] = obs['features'], obs['mask']
            self.rewards[i], self.dones[i], self.terminals[i] = reward, term or trunc, term
            self.outcomes[i] = ('running', 'win', 'loss', 'double', 'draw').index(info['outcome'])
            self.frames[i], self.action_changes[i] = info['tick'], info['action_changes']
            self.shots[i], self.hits[i] = info['shots']-before['shots'], info['hits']-before['hits']

    def reset_done(self):
        for i in np.flatnonzero(self.dones):
            self.episodes[i] += 1
            self._reset(int(i))
            self.dones[i] = 0

    def close(self):
        for env in self.envs:
            env.close()
