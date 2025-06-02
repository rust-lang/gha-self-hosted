import sys
import threading
import time


def log(*args, **kwargs):
    print("==>", *args, **kwargs)
    sys.stdout.flush()


# Simple thread that executes a function after a timeout
class Timer(threading.Thread):
    def __init__(self, name, callback, timeout):
        super().__init__(name=name, daemon=True)

        self._name = name
        self._callback = callback
        self._timeout = timeout

    def run(self):
        log(f"started timer {self._name}, fires in {self._timeout} seconds")

        # The sleep is done in a loop to handle spurious wakeups
        started_at = time.time()
        while time.time() < started_at + self._timeout:
            time.sleep(self._timeout - (time.time() - started_at))

        log(f"timer {self._name} fired")
        self._callback()
