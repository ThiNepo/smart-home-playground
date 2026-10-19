"""Start and stop only the containers belonging to this project."""
from pathlib import Path
import json
import os
import re
import secrets
import string
import subprocess
import time
import uuid
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / ".runtime"


class DockerInfrastructure:
    def __init__(self, remote=True, runtime_dir=None, project_name="smart-house-demo", mqtt_port=18883, websocket_port=19001):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project_name):
            raise ValueError("The Compose project name must use lowercase letters, numbers, underscores, or hyphens.")
        for port in (mqtt_port, websocket_port):
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                raise ValueError("Local MQTT ports must be integers from 1 to 65535.")
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else RUNTIME
        self.project_name = project_name
        self.mqtt_port = mqtt_port
        self.websocket_port = websocket_port
        self.compose_file = ROOT / "compose.yaml"
        self.remote = remote
        self.started = False
        self.url = f"ws://127.0.0.1:{websocket_port}/mqtt"
        self.notice = ""
        self.credentials = {}

    def prepare_compose(self):
        """Give isolated test instances their own mounts, ports, and project."""
        if self.runtime_dir == RUNTIME and self.mqtt_port == 18883 and self.websocket_port == 19001:
            return
        manifest = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        config_path = (self.runtime_dir / "mosquitto").resolve().as_posix()
        replacements = {
            "./.runtime/mosquitto:/mosquitto/config:rw": json.dumps(config_path + ":/mosquitto/config:rw"),
            "./.runtime/mosquitto:/mosquitto/config:ro": json.dumps(config_path + ":/mosquitto/config:ro"),
            "127.0.0.1:18883:1883": f"127.0.0.1:{self.mqtt_port}:1883",
            "127.0.0.1:19001:9001": f"127.0.0.1:{self.websocket_port}:9001",
        }
        for previous, replacement in replacements.items():
            if manifest.count(previous) != 1:
                raise RuntimeError("The Compose template no longer matches the isolated runtime configuration.")
            manifest = manifest.replace(previous, replacement)
        self.compose_file = self.runtime_dir / "compose.yaml"
        self.compose_file.write_text(manifest, encoding="utf-8")

    def compose(self, *args, timeout=180, check=True):
        result = subprocess.run(
            ["docker", "compose", "-p", self.project_name, "--project-directory", str(ROOT), "-f", str(self.compose_file), *args],
            cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if check and result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-2500:])
        return result

    def prepare(self):
        config_dir = self.runtime_dir / "mosquitto"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.prepare_compose()
        credential_path = self.runtime_dir / "credentials.json"
        if credential_path.exists():
            try:
                self.credentials = json.loads(credential_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                self.credentials = {}
        valid = (
            isinstance(self.credentials, dict)
            and set(self.credentials) == {"username", "password"}
            and self.credentials["username"] == "classroom"
            and isinstance(self.credentials["password"], str)
            and re.fullmatch(r"[A-Za-z0-9]{6}", self.credentials["password"])
        )
        if not valid:
            alphabet = string.ascii_letters + string.digits
            self.credentials = {"username": "classroom", "password": "".join(secrets.choice(alphabet) for _ in range(6))}
            credential_path.write_text(json.dumps(self.credentials, indent=2), encoding="utf-8")
        # Only this temporary file is modified by the password hashing utility.
        password_file = config_dir / "passwords"
        password_file.write_text(f"{self.credentials['username']}:{self.credentials['password']}\n", encoding="utf-8")
        config = "\n".join([
            "allow_anonymous false", "password_file /mosquitto/config/passwords",
            "acl_file /mosquitto/config/acl", "persistence false", "log_dest stdout",
            "max_packet_size 1024", "max_inflight_messages 20",
            "listener 1883", "protocol mqtt", "max_connections 100",
            "listener 9001", "protocol websockets", "max_connections 100", "",
        ])
        (config_dir / "mosquitto.conf").write_text(config, encoding="utf-8")
        acl = [f"user {self.credentials['username']}", "topic readwrite house/#", ""]
        (config_dir / "acl").write_text("\n".join(acl), encoding="utf-8")
        try:
            # The broker mount is read-only; only the hashing job can write to it.
            self.compose("--profile", "setup", "run", "--rm", "--no-deps", "password-init")
        except BaseException:
            password_file.unlink(missing_ok=True)
            raise

    def start(self):
        self.started = True  # Clean up even when Compose starts only some services.
        self.prepare()
        self.compose("up", "-d", "broker")
        end = time.monotonic() + 20
        connected = []
        probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="startup-" + uuid.uuid4().hex[:8])
        probe.username_pw_set(self.credentials["username"], self.credentials["password"])
        probe.on_connect = lambda client, userdata, flags, reason, props: connected.append(not reason.is_failure)
        while time.monotonic() < end:
            try:
                probe.connect("127.0.0.1", self.mqtt_port, keepalive=15)
                attempt_end = time.monotonic() + 2
                while not connected and time.monotonic() < attempt_end:
                    probe.loop(timeout=0.2)
                if connected and connected[-1]:
                    break
            except OSError:
                pass
            finally:
                probe.disconnect()
            connected.clear()
            time.sleep(0.3)
        else:
            logs = self.compose("logs", "--tail", "20", "broker", check=False)
            raise RuntimeError("The broker did not accept an authenticated connection.\n" + logs.stdout + logs.stderr)
        if self.remote:
            self.start_tunnel()
        handout = {
            "url": self.url, **self.credentials,
            "local_mqtt_url": f"mqtt://127.0.0.1:{self.mqtt_port}",
            "local_websocket_url": f"ws://127.0.0.1:{self.websocket_port}/mqtt",
        }
        (self.runtime_dir / "connection.json").write_text(json.dumps(handout, indent=2), encoding="utf-8")
        print(f"Classroom MQTT: {self.url}\nConnection file: {self.runtime_dir / 'connection.json'}", flush=True)
        return self

    def probe_mqtt(self, host, port, websocket=False, timeout=3):
        result = []
        probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="probe-" + uuid.uuid4().hex[:8], transport="websockets" if websocket else "tcp")
        probe.username_pw_set(self.credentials["username"], self.credentials["password"])
        probe.connect_timeout = 3
        probe.on_connect = lambda client, userdata, flags, reason, props: result.append(not reason.is_failure)
        if websocket:
            probe.ws_set_options(path="/mqtt")
            probe.tls_set()
        try:
            probe.connect(host, port, keepalive=15)
            deadline = time.monotonic() + timeout
            while not result and time.monotonic() < deadline:
                probe.loop(timeout=0.2)
            return bool(result and result[-1])
        except OSError:
            return False
        finally:
            probe.disconnect()

    def start_tunnel(self):
        print("Starting the classroom tunnel...", flush=True)
        try:
            self.compose("--profile", "remote", "up", "-d", "tunnel")
            deadline = time.monotonic() + 90
            announced = False
            while time.monotonic() < deadline:
                logs = self.compose("logs", "--no-color", "--tail", "100", "tunnel", check=False)
                output = logs.stdout + logs.stderr
                match = re.search(r"https://([a-z0-9-]+\.trycloudflare\.com)", output)
                if match and "Registered tunnel connection" in output:
                    if not announced:
                        print("Tunnel registered; waiting for public DNS and MQTT...", flush=True)
                        announced = True
                    if self.probe_mqtt(match.group(1), 443, websocket=True):
                        self.url = "wss://" + match.group(1) + "/mqtt"
                        print("Public MQTT tunnel is ready.", flush=True)
                        return
                time.sleep(1)
            raise RuntimeError("The public tunnel did not accept an MQTT connection within 90 seconds.")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            self.notice = "Tunnel unavailable; local MQTT is still available. " + str(exc)[:150]
            print(self.notice, flush=True)
            self.compose("--profile", "remote", "stop", "tunnel", check=False, timeout=20)

    def stop(self):
        if self.started:
            self.compose("--profile", "remote", "down", "--remove-orphans", check=False, timeout=30)
            self.started = False
