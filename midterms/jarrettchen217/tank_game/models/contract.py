"""The Hybrid opponent's fixed game ABI; every swappable model must match it exactly.

The native60Hz play bridge writes 1028 float32 features (schema24) plus a
10-slot bullet mask and accepts one of 18 discrete actions. Changing any of
these is a game/observation change, not a model swap.
"""
ARCH = 'hybrid_schema24_reconstructed_v1'
SCHEMA = 24
OBSERVATION = 1028
BULLET_SLOTS = 10
ACTIONS = 18
ENVIRONMENT_CONTRACT_SHA256 = 'a5b28a10b4f65567c272b9307a6e68a5162c2ff8a06d35f2fba8a94155f96d75'
# Tensor name -> shape for the NumPy forward in research/killfield/tank_transfer/actor.py.
INFERENCE_SHAPES = {
    'map.0.weight': (16, 7, 3, 3), 'map.0.bias': (16,), 'map.2.weight': (32, 16, 3, 3), 'map.2.bias': (32,),
    'map.5.weight': (128, 960), 'map.5.bias': (128,), 'bullets.0.weight': (32, 10), 'bullets.0.bias': (32,),
    'bullets.2.weight': (32, 32), 'bullets.2.bias': (32,), 'scalars.0.weight': (128, 88), 'scalars.0.bias': (128,),
    'trunk.0.weight': (256, 320), 'trunk.0.bias': (256,), 'actor.weight': (18, 256), 'actor.bias': (18,),
    'dodge_delta.0.weight': (64, 256), 'dodge_delta.0.bias': (64,), 'dodge_delta.2.weight': (1, 64),
    'dodge_delta.2.bias': (1,), 'ammo_delta.0.weight': (64, 256), 'ammo_delta.0.bias': (64,),
    'ammo_delta.2.weight': (4, 64), 'ammo_delta.2.bias': (4,),
    'dodge_alpha_old': (), 'ammo_alpha_old': (4,), 'idle_logit_penalty': (),
}
INFERENCE_KEYS = frozenset(INFERENCE_SHAPES)
