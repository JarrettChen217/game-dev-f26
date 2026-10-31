"""Bounded local transport to the single original engine instance."""
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

ASSETS = Path(__file__).resolve().parent


class OriginalEngineError(RuntimeError):
    pass


class EngineBridge:
    def __init__(self, *, node_command=None, timeout=3):
        manifest = json.loads((ASSETS/'manifest.json').read_text())
        if hashlib.sha256((ASSETS/'engine.wasm').read_bytes()).hexdigest() != manifest['wasm_sha256']:
            raise OriginalEngineError('Original Laika artifact hash does not match its manifest')
        node = node_command or shutil.which('node')
        if node is None:
            raise OriginalEngineError('The optional original Laika profile requires Node on PATH')
        self.timeout, self._sequence, self._closed = timeout, 0, False
        self._replies = Queue()
        try:
            self.process = subprocess.Popen(
                [node, str(ASSETS/'service.mjs')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
        except OSError as error:
            raise OriginalEngineError('Cannot start the optional original Laika engine') from error
        self._reader = Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self._replies.put(line)
        finally:
            self._replies.put(None)

    def call(self, op, **data):
        if self._closed:
            raise OriginalEngineError('Original Laika engine is closed')
        self._sequence += 1
        try:
            self.process.stdin.write(json.dumps({'id': self._sequence, 'op': op, **data})+'\n')
            self.process.stdin.flush()
            line = self._replies.get(timeout=self.timeout)
            if line is None:
                raise OriginalEngineError('Original Laika engine exited unexpectedly')
            response = json.loads(line)
            if response.get('id') != self._sequence:
                raise OriginalEngineError('Original Laika reply identity mismatch')
            if 'error' in response:
                raise OriginalEngineError(response['error'])
            return response['result']
        except OriginalEngineError:
            self.close()
            raise
        except (OSError, Empty, ValueError) as error:
            self.close()
            raise OriginalEngineError('Original Laika transport failed or timed out') from error

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.process.poll() is None:
                self._sequence += 1
                try:
                    self.process.stdin.write(json.dumps({'id': self._sequence, 'op': 'close'})+'\n')
                    self.process.stdin.flush()
                    self.process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.kill()
                    self.process.wait(timeout=1)
        finally:
            self._reader.join(timeout=1)
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass  # Broken stdin must not prevent closing the other pipes.
