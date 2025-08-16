# Create a single-use HTTP server to inject a credential into the VM.
#
# Our self-hosted runners setup relies on systemd credentials to inject parameters and secrets into
# the running VM. In August 2025 we discovered a bug though: when a credential was too long, systemd
# would truncate it when loading it. This was a systemd problem, as with `dmidecode -t 11` we could
# clearly see the credential was passed in the VM untruncated.
#
# Some credentials (like just-in-time runner configurations) are fairly long, and given that bug we
# cannot pass them to the VM with systemd. To work around that, this module spawns an HTTP server
# returning the actual credential, and inject its URL into the VM with a systemd credential.
#
# To ensure other processes running on the system cannot easily grab the credential too, the server:
#
# - Listens to a random, unpredictable port.
# - Only serves the credential when a long, random authorization token is included in the URL.
# - Locks itself up after the credential has been retrieved, preventing further retrievals.

from .utils import log
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import secrets


# IP of the host machine in QEMU-based VMs, under the default settings.
GUEST_IP = "10.0.2.2"


class CredentialServer:
    def __init__(self, name, value):
        token = secrets.token_urlsafe(64)
        already_requested = False

        class ServerHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                # The nonlocal keyword binds to the variable in the outer scope.
                nonlocal already_requested

                if self.path.lstrip("/") != token:
                    log(
                        f"warning: attempted to retrieve credential {name} with invalid token"
                    )
                    self._respond(403, "error: invalid token")
                elif already_requested:
                    log(
                        f"warning: attempted to retrieve credential {name} multiple times"
                    )
                    self._respond(400, "error: credential already requested")
                else:
                    log(f"credential {name} retrieved through the HTTP server")
                    self._respond(200, value)

                    # Only allow the credential to be retrieved once.
                    already_requested = True

            def _respond(self, code, message):
                self.send_response(code)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(message.encode("utf-8") + b"\n")

            def log_message(*args, **kwargs):
                # Suppress the builtin logging, we do our own logging.
                pass

        server = HTTPServer(("127.0.0.1", 0), ServerHandler)

        self._port = server.server_port
        self._name = name
        self._token = token

        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()

    def configure_qemu(self, qemu):
        # Here we are passing the systemd credential containing the URL through the command-line
        # params. This is not ideal, because the URL contains the access token, and the CLI params
        # are widely accessible on a Linux system.
        #
        # QEMU does support passing the contents of a file through SMBIOS, which would solve the
        # problem nicely (as long as the file permissions are correctly setup), but unfortunately
        # that is broken before QEMU 10.0.0 due to a buffer overflow:
        #
        #     https://github.com/qemu/qemu/commit/a7a05f5f6a4085afbede315e749b1c67e78c966b
        #
        # Ubuntu 24.04 doesn't include QEMU 10 yet, so we have to fall back to passing credentials
        # through CLI params.
        #
        # Note that this is not the *worst* thing security wise, as the URL can only be accessed
        # once, the VM accesses it as soon as it boots, and someone having access to the host system
        # can also gain access to the private key used to generate GitHub Actions tokens.
        qemu.smbios_11.append(
            f"value=io.systemd.credential:{self._name}="
            f"http://{GUEST_IP}:{self._port}/{self._token}"
        )
