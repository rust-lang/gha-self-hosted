import json
import telnetlib


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
    def __init__(self, port):
        self._conn = telnetlib.Telnet("127.0.0.1", port)

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

    def eject(self, device, *, force=False):
        self._write_message(
            {
                "execute": "eject",
                "arguments": {
                    "device": device,
                    "force": force,
                },
            }
        )
        self._read_success()

    def wait_for_event(self, event):
        while True:
            message = self._read_message()
            if "event" in message and message["event"] == event:
                return message["data"]

    def _read_success(self):
        result = self._read_message()
        if "return" not in result:
            raise RuntimeError("QMP returned an error: " + repr(result))

    def _write_message(self, message):
        self._conn.write(json.dumps(message).encode("utf-8") + b"\r\n")

    def _read_message(self):
        return json.loads(self._conn.read_until(b"\n").decode("utf-8").strip())
