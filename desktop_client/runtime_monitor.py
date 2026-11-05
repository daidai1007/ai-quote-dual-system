"""Native, optional runtime heartbeat; no business hooks and no OS inspection.

Installed after name-login wrapping. Network and credential work stay off the Qt
thread. An absent configuration never enables collection. The local identity
receipt lets the operator enroll this application without copying business tokens.
"""
import json
import os
from pathlib import Path
import threading
from datetime import datetime, timezone

from monitor_settings import atomic_json, configuration, default_path
from quote_monitor import LocalMonitor

_controller = None


class RuntimeController:
    def __init__(self, path, version, identity):
        self.path = Path(path).resolve()
        self.version, self.identity = version, identity
        self.stop = threading.Event()
        self.runtime = None
        self.state = 'awaiting_identity'
        self.thread = threading.Thread(target=self.run, daemon=True, name='quote-runtime-controller')
        self.thread.start()

    def record(self, state, person):
        self.state = state
        atomic_json(self.path.parent/'runtime-state.json', {
            'state': state, 'app_version': self.version,
            'user_id': person.get('user_id'), 'updated_at': datetime.now(timezone.utc).isoformat(),
            'collection_scope': 'runtime_heartbeat_only',
        })

    def run(self):
        previous = None
        try:
            while not self.stop.is_set():
                try:
                    person = self.identity() or {}
                    user = person.get('user_id')
                    if not user:
                        state = 'awaiting_identity'
                    elif not self.path.is_file():
                        state = 'awaiting_configuration'
                    else:
                        settings = configuration(self.path)
                        if settings['user_id'] != user:
                            state = 'identity_mismatch'
                        elif not settings['enabled']:
                            state = 'disabled'
                        else:
                            state = 'active'
                    if user and previous != user:
                        atomic_json(self.path.parent/'identity.json', {
                            'app_id': 'ai_quote', 'user_id': user,
                            'display_name': person.get('display_name', ''),
                            'identity_mode': person.get('identity_mode'), 'app_version': self.version,
                        })
                        previous = user
                    if self.runtime and (state != 'active' or self.runtime.base['user_id'] != user):
                        self.runtime.close()
                        self.runtime = None
                    if state == 'active' and self.runtime is None:
                        self.runtime = LocalMonitor(self.path, lambda: (self.identity() or {}).get('user_id'), self.version)
                    self.record(state, person)
                except Exception:
                    if self.runtime:
                        self.runtime.close()
                        self.runtime = None
                    try: self.record('configuration_unavailable', {})
                    except OSError: pass
                self.stop.wait(.5)
        finally:
            if self.runtime: self.runtime.close()

    def close(self):
        self.stop.set()
        self.thread.join(4)


def install_runtime_monitoring(namespace):
    """Preserve the existing name-login initializer and all business behavior."""
    cls = namespace['MainWindow']
    if getattr(cls, '_runtime_monitor_installed', False): return
    original = cls.__init__

    def init(window, *args, **kwargs):
        original(window, *args, **kwargs)
        global _controller
        if _controller is not None: return
        try:
            import name_login
            from quote_scheme_center import CLIENT_VERSION
            from PySide6.QtWidgets import QApplication
            def identity(): return (name_login.session() or {}).get('person')
            _controller = RuntimeController(os.getenv('AI_QUOTE_MONITOR_CONFIG') or default_path(), CLIENT_VERSION, identity)
            app = QApplication.instance()
            if app: app.aboutToQuit.connect(_controller.close)
        except Exception:
            # The optional monitor never takes down a working quotation window.
            pass

    cls.__init__ = init
    cls._runtime_monitor_installed = True
