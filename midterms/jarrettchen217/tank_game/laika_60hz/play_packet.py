"""Read-only validation/projection shared by native and browser transports."""
from math import isfinite


def decode_packet(raw, facts, *, calls, strategy, action):
    if (not 8 <= len(raw) <= 8192 or not 9 <= len(facts) <= 8192
            or not all(isfinite(x) for x in (*raw, *facts)) or raw[0] != 1 or facts[0] != 1):
        raise ValueError('play packet ABI mismatch')
    nr, ns, nb = raw[1:4]
    nf, nh, ne = facts[1:4]
    if any(x < 0 or x != int(x) for x in (nr, ns, nb, nf, nh, ne)):
        raise ValueError('play packet length mismatch')
    nr, ns, nb, nf, nh, ne = map(int, (nr, ns, nb, nf, nh, ne))
    if len(raw) != 8+nr+ns+nb or len(facts) != 9+nf*9+nh*4+ne:
        raise ValueError('play packet length mismatch')
    base, k = 8+nr, 9
    host = {'shots_fired': int(facts[4]), 'trigger_released': bool(facts[5]),
            'fixture': int(facts[6]), 'native_ai_seats': [bool(facts[7]), bool(facts[8])],
            'bullets': [facts[k+i*9:k+(i+1)*9] for i in range(nf)]}
    k += nf*9
    host['hits'] = [facts[k+i*4:k+(i+1)*4] for i in range(nh)]
    host['expired'] = [int(x) for x in facts[k+nh*4:k+nh*4+ne]]
    diagnostics = {'world_steps': int(raw[6]), 'laika_calls': int(raw[4]), 'laika_ns': int(raw[5]),
                   'model_calls': calls if strategy == 'hybrid' else 0,
                   'last_opponent_action': action, 'native_ai_seats': host['native_ai_seats']}
    return {'render': raw[8:base], 'status': raw[base:base+ns], 'bullets': raw[base+ns:]}, host, diagnostics
