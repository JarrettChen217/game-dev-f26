"""ctypes transport only; the source Rust library owns the complete game."""
import hashlib
import json
import platform
from pathlib import Path
from time import perf_counter_ns

ASSETS = Path(__file__).resolve().parent


class NativeBridge:
    def __init__(self):
        import ctypes
        if (platform.system(), platform.machine()) != ('Darwin', 'arm64'):
            raise RuntimeError('source60Hz local library requires macOS arm64; build the source for this platform')
        library = ASSETS/'engine.dylib'
        manifest = json.loads((ASSETS/'manifest.json').read_text())
        if hashlib.sha256(library.read_bytes()).hexdigest() != manifest['library_sha256']:
            raise RuntimeError('source60Hz library hash mismatch')
        self.lib = ctypes.CDLL(str(library))
        pointer, number, size = ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.c_size_t
        self.lib.kf60_new.argtypes = [ctypes.c_uint32]
        self.lib.kf60_new.restype = pointer
        self.lib.kf60_free.argtypes = [pointer]
        self.lib.kf60_free.restype = None
        self.lib.kf60_snapshot.argtypes = [pointer, number, size]
        self.lib.kf60_snapshot.restype = size
        self.lib.kf60_step.argtypes = [pointer, ctypes.c_int, ctypes.c_int, ctypes.c_int, number, size]
        self.lib.kf60_step.restype = size
        self.handle = None
        self.buffer = (ctypes.c_double*8192)()
        self.diagnostics = {}
        self.bridge_ns = 0

    def call(self, operation, **kwargs):
        start = perf_counter_ns()
        if operation == 'init':
            candidate = self.lib.kf60_new(kwargs['seed'])
            if not candidate:
                raise RuntimeError('source60Hz engine allocation failed')
            self.close()
            self.handle = candidate
            length = self.lib.kf60_snapshot(self.handle, self.buffer, len(self.buffer))
        elif operation == 'step' and self.handle:
            throttle, turn, fire = kwargs['action']
            length = self.lib.kf60_step(self.handle, throttle, turn, int(fire), self.buffer, len(self.buffer))
        else:
            raise RuntimeError('source60Hz bridge is closed or operation is invalid')
        if not 8 <= length <= len(self.buffer) or self.buffer[0] != 1:
            raise RuntimeError('source60Hz snapshot ABI mismatch')
        raw = list(self.buffer[:length])
        render_length, status_length = int(raw[1]), int(raw[2])
        base = 8+render_length
        packet = {'render': raw[8:base], 'status': raw[base:base+status_length],
                  'bullets': raw[base+status_length:]}
        self.bridge_ns += perf_counter_ns()-start
        self.diagnostics = {'laika_calls': int(raw[4]), 'laika_ns': int(raw[5]),
                            'world_steps': int(raw[6]), 'world_ns': int(raw[7]), 'bridge_ns': self.bridge_ns}
        return packet

    def close(self):
        if self.handle:
            self.lib.kf60_free(self.handle)
            self.handle = None
