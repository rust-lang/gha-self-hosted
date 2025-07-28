import socket
import json


# QMP (QEMU Machine Protocol) is a way to control VMs spawned with QEMU, and
# to receive events from them. An introduction to the protocol is available at:
#
#    https://wiki.qemu.org/Documentation/QMP
#
# A full list of commands and events is available at:
#
#    https://www.qemu.org/docs/master/qemu-qmp-ref.html#Commands-and-Events-Index
#
class QMPClient:
    def __init__(self, unix_path):
        self._read_buffer = b""

        self._conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._conn.connect(str(unix_path))

        # When starting the connection, QEMU sends a greeting message
        # containing the `QMP` key. To finish the handshake, the command
        # `qmp_capabilities` then needs to be sent.
        greeting = self._read_message()
        if "QMP" not in greeting:
            raise RuntimeError("didn't receive a greeting from the QMP server")
        self._write_message({"execute": "qmp_capabilities"})
        self._read_success()

    def shutdown_vm(self):
        self._write_message({"execute": "system_powerdown"})
        self._read_success()

    def _read_success(self):
        while True:
            result = self._read_message()
            if "return" in result:
                return result
            elif "event" in result:
                # We don't care about any event, so let's discard them.
                continue
            else:
                raise RuntimeError("QMP returned an error: " + repr(result))

    def _write_message(self, message):
        self._conn.sendall(json.dumps(message).encode("utf-8") + b"\r\n")

    def _read_message(self):
        # Ensure we buffer enough data to receive a whole message
        while b"\r\n" not in self._read_buffer:
            self._read_buffer += self._conn.recv(4096)
        message, self._read_buffer = self._read_buffer.split(b"\r\n", 1)

        return json.loads(message.decode("utf-8"))
