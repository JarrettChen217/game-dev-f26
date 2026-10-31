"""Desktop process isolation; imported only by the native adapter."""
import multiprocessing
from copy import deepcopy
from time import monotonic, perf_counter


def _policy_loop(connection, policy, send_ready=False):
    try:
        if send_ready:
            connection.send(('ready', monotonic()))
        while True:
            scene = connection.recv()
            start = perf_counter()
            try:
                result = policy.decide(scene)
            except Exception:  # noqa: BLE001 -- contain arbitrary trusted policy failures
                result = None
            connection.send((result, perf_counter()-start))
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class ProcessWorker:
    """One pending request, bounded wall time, no UI-thread policy execution."""

    def __init__(self, policy, *, timeout=.1, startup_timeout=None):
        self.policy = policy
        self.timeout = timeout
        self.pending = None
        self.discarding = False
        self.disabled = False
        self.startup_timeout = startup_timeout
        self.ready = startup_timeout is None
        self.startup_seconds = None
        self.started = monotonic()
        context = multiprocessing.get_context('spawn')
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_policy_loop,
                                       args=(child, policy, startup_timeout is not None),
                                       daemon=True)
        self.process.start()
        child.close()

    def submit(self, scene):
        if self.disabled or self.pending is not None:
            return False
        original = deepcopy(scene)
        try:
            self.connection.send(deepcopy(original))
        except (BrokenPipeError, EOFError, OSError):
            self.disabled = True
            return False
        self.pending = original, monotonic()
        return True

    def discard_pending(self):
        self.discarding = self.pending is not None

    def poll(self):
        if self.pending is None:
            return None
        scene, start = self.pending
        try:
            if self.connection.poll():
                message = self.connection.recv()
                if not self.ready and message[0] == 'ready':
                    # Use the child's ready time, not time spent waiting in a menu.
                    self.startup_seconds = message[1]-self.started
                    if self.startup_seconds <= self.startup_timeout:
                        self.ready = True
                        self.pending = scene, monotonic()
                        return self.poll()
                    self.disabled = True
                else:
                    request, duration = message
                    self.pending = None
                    if self.discarding:
                        self.discarding = False
                        return None
                    if self.ready and monotonic()-start <= self.timeout and duration <= self.timeout:
                        return scene, request, duration
                    self.disabled = True
        except (BrokenPipeError, EOFError, OSError):
            self.disabled = True
        expired = (monotonic()-start > self.timeout if self.ready
                   else monotonic()-self.started > self.startup_timeout)
        if self.disabled or expired:
            self.pending = None
            self.disabled = True
            self.process.terminate()
            self.process.join(timeout=0)
            return scene, None, monotonic()-start
        return None

    def close(self):
        self.disabled = True
        self.pending = None
        self.connection.close()
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=.1)


