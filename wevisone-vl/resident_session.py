"""A server-owned, lazy, single-model worker. No torch imports in the server."""
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import select

from resource_metrics import read_system_command, parse_swap_used_mb, parse_memory_free_percent


def resources():
    return (parse_memory_free_percent(read_system_command('memory_pressure', '-Q')),
            parse_swap_used_mb(read_system_command('sysctl', 'vm.swapusage')))


class ResidentSession:
    def __init__(self, python, shared):
        self.python, self.shared = str(python), Path(shared)
        self.process = None
        self.size = None
        self.directory = None
        self.lock = threading.RLock()
        self.reason = None

    def status(self):
        with self.lock:
            alive = self.process is not None and self.process.poll() is None
            state = {}
            if alive:
                try:
                    state = json.loads((Path(self.directory.name) / 'status.json').read_text())
                except (OSError, ValueError):
                    pass
            return {'running': alive, 'loaded': alive and state.get('loaded', False),
                    'model_size': self.size if alive else None, 'pid': self.process.pid if alive else None,
                    'reason': self.reason, **state}

    def environment(self, size):
        with self.lock:
            if self.process is not None and self.process.poll() is None and self.size == size:
                return self._environment()
            self.close()
            try:
                free, swap = resources()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                raise ValueError('Contrôle mémoire indisponible ; aucun modèle chargé.') from error
            if free < 30:
                raise ValueError(f'Chargement refusé : mémoire disponible {free} %, minimum 30 %.')
            self.directory = tempfile.TemporaryDirectory(prefix='pcb-wv-')
            location = Path(self.directory.name)
            handles = []
            try:
                # The worker inherits these locks and keeps them even while idle.
                root = self.shared.parents[1] / 'outputs/wevisone-vl'
                for path in (root / 'jobs/.batch.lock', root / 'inference.lock'):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    handle = path.open('a+')
                    handles.append(handle)
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                env = {**os.environ, 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                       'HF_HUB_DISABLE_TELEMETRY': '1', 'PYTORCH_ENABLE_MPS_FALLBACK': '0',
                       'HF_HOME': os.environ.get('HF_HOME', str(Path.home() / '.cache/huggingface')),
                       'PYTHONDONTWRITEBYTECODE': '1'}
                with (location / 'service.log').open('w') as log:
                    self.process = subprocess.Popen(
                        [self.python, str(self.shared / 'worker.py'), '--serve', str(location), size, str(os.getpid())],
                        env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                        pass_fds=tuple(handle.fileno() for handle in handles))
                self.size, self.reason = size, None
                process = self.process
                threading.Thread(target=self._monitor, args=(process, swap), daemon=True).start()
                deadline = time.monotonic() + 20
                while not (location / 'worker.sock').exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        detail = (location / 'service.log').read_text(errors='replace')[-2000:]
                        raise ValueError('Session WeVisOne indisponible ; aucune relance. ' + detail)
                    time.sleep(.05)
                return self._environment()
            except BaseException:
                self.close()
                raise
            finally:
                for handle in handles:
                    handle.close()

    def _environment(self):
        return {'PCB_WEVISONE_SESSION': str(Path(self.directory.name) / 'worker.sock'),
                'PCB_WEVISONE_SESSION_PID': str(self.process.pid)}

    def _monitor(self, process, baseline_swap):
        while process.poll() is None:
            time.sleep(2)
            if process.poll() is not None:
                break
            try:
                free, swap = resources()
                rss = int(read_system_command('ps', '-o', 'rss=', '-p', str(process.pid)).strip()) * 1024
                reason = ('Mémoire disponible <15 %' if free < 15 else
                          'Swap augmenté de plus de 2 Gio' if swap - baseline_swap > 2048 else
                          'RSS du modèle >12 Gio' if rss > 12 * 1024**3 else None)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                reason = 'Supervision mémoire indisponible'
            if reason:
                with self.lock:
                    if self.process is process:
                        self.reason = reason
                        self.close()
                break

    def close(self):
        with self.lock:
            process = self.process
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            self.process, self.size = None, None
            if self.directory is not None:
                self.directory.cleanup()
                self.directory = None


def serve(directory, size, parent_pid, predict):
    """Sequential local IPC; disconnects and server exit never trigger retries."""
    directory = Path(directory)
    def parent_watch():
        while True:
            time.sleep(1)
            if os.getppid() != parent_pid:
                os._exit(130)
    threading.Thread(target=parent_watch, daemon=True).start()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(directory / 'worker.sock'))
        os.chmod(directory / 'worker.sock', 0o600)
        listener.listen(1)
        while True:
            with listener.accept()[0] as connection:
                connection.settimeout(5)
                with connection.makefile('rwb') as stream:
                    path = Path(json.loads(stream.readline(16384))['request']).resolve()
                    stream.write((json.dumps({'pid': os.getpid()}) + '\n').encode());stream.flush()
                    try:
                        predict(path, size, directory / 'status.json')
                        message = {'complete': True}
                    except Exception as error:
                        message = {'error': str(error) or type(error).__name__}
                    try:
                        stream.write((json.dumps(message) + '\n').encode());stream.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        # The requesting controller was stopped. Discard the session.
                        return


def supervised_request(request, baseline_swap, *, memory_fn, swap_fn, command):
    """Use the resident worker with the same per-request resource ceilings."""
    request = Path(request)
    pid = int(os.environ['PCB_WEVISONE_SESSION_PID'])
    started, sampled = time.monotonic(), 0
    samples, reason, complete = [], None, False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(os.environ['PCB_WEVISONE_SESSION'])
            connection.sendall((json.dumps({'request': str(request)}) + '\n').encode())
            pending, acknowledged = b'', False
            while True:
                if select.select([connection], [], [], .2)[0]:
                    block = connection.recv(65536)
                    if not block:
                        raise RuntimeError('Session WeVisOne interrompue ; aucune relance automatique.')
                    pending += block
                    while b'\n' in pending:
                        line, pending = pending.split(b'\n', 1)
                        value = json.loads(line)
                        if not acknowledged:
                            if value.get('pid') != pid:
                                raise RuntimeError('Identité du processus WeVisOne incohérente.')
                            acknowledged = True
                        elif value.get('complete') is True:
                            complete = True
                            return
                        else:
                            raise RuntimeError(value.get('error', 'Réponse WeVisOne invalide.'))
                elapsed = time.monotonic() - started
                if elapsed - sampled >= 2:
                    sampled = elapsed
                    rss = int(command('ps', '-o', 'rss=', '-p', str(pid)).strip()) * 1024
                    free, swap = memory_fn(), swap_fn()
                    samples.append({'elapsed_s': round(elapsed, 2), 'rss_bytes': rss,
                                    'memory_free_percent': free, 'swap_used_mb': swap})
                    reason = ('300 second request limit' if elapsed > 300 else
                              '12 GiB child RSS limit' if rss > 12*1024**3 else
                              'system available memory below 15%' if free < 15 else
                              'swap grew more than 2 GiB' if swap-baseline_swap > 2048 else None)
                    if reason:
                        raise RuntimeError('Stopped: ' + reason)
    except BaseException as error:
        reason = reason or str(error) or type(error).__name__
        # A stopped/failed operation never leaves inference running in the background.
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        raise
    finally:
        (request.parent / 'supervision.json').write_text(json.dumps(
            {'child_pid': pid, 'resident': True, 'returncode': 0 if complete else None,
             'stop_reason': reason, 'samples': samples}, indent=2) + '\n')
