"""An object-oriented classroom client. Install paho-mqtt==2.1.0."""
import argparse
from collections import deque
import getpass
import json
import threading
import time
from urllib.parse import urlparse
import uuid
import paho.mqtt.client as mqtt


class StudentClient:
    PORTS = {"mqtt": 1883, "mqtts": 8883, "ws": 80, "wss": 443}
    ROOMS = ("living_room", "kitchen", "bedroom", "bathroom", "laundry", "hall", "garage")
    AIR_CONDITIONED_ROOMS = ("living_room", "kitchen", "bedroom", "garage")
    ACTUATORS = frozenset(
        {("power", "breaker"), ("garden", "irrigation"), ("garage", "door")}
        | {(room, "light") for room in ROOMS}
        | {(room, "air_conditioner") for room in AIR_CONDITIONED_ROOMS}
    )
    SENSORS = frozenset(
        {("garage", "motion"), ("garage", "car_presence"), ("garden", "moisture"),
         ("living_room", "door_contact"), ("garage", "door_contact"),
         ("laundry", "door_contact"), ("bedroom", "window_contact")}
        | {(room, "temperature") for room in AIR_CONDITIONED_ROOMS}
    )

    def __init__(self, url, username, password, quiet=False, topics=None):
        self.address = urlparse(url)
        if self.address.scheme not in self.PORTS or not self.address.hostname:
            raise ValueError("Provide a complete mqtt://, mqtts://, ws://, or wss:// URL.")
        if self.address.scheme in ("mqtt", "mqtts") and self.address.path not in ("", "/"):
            raise ValueError("Native MQTT URLs do not have a WebSocket path.")
        self.quiet = quiet
        self.topics = tuple(topics) if topics is not None else ("house/+/+/state", "house/clock/state", "house/status")
        if not self.topics:
            raise ValueError("Subscribe to at least one topic.")
        self.received = deque(maxlen=500)
        self._state_payloads = {}
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.error = None
        websocket = self.address.scheme in ("ws", "wss")
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=username + "-" + uuid.uuid4().hex[:10],
            transport="websockets" if websocket else "tcp",
        )
        self.client.username_pw_set(username, password)
        if websocket:
            path = self.address.path or "/mqtt"
            if self.address.query:
                path += "?" + self.address.query
            self.client.ws_set_options(path=path)
        if self.address.scheme in ("wss", "mqtts"):
            self.client.tls_set()
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.error = str(reason_code)
        else:
            client.subscribe([(topic, 1) for topic in self.topics])
        self.connected.set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        if any(reason.is_failure for reason in reason_codes):
            self.error = "The broker rejected a topic subscription."
        self.subscribed.set()

    def _on_message(self, client, userdata, message):
        payload = message.payload.decode("utf-8", errors="replace")
        self.received.append((message.topic, payload))
        if message.topic.endswith("/state"):
            self._state_payloads[message.topic] = payload
        if not self.quiet:
            print(message.topic, "=", payload, flush=True)

    def connect(self):
        self.connected.clear()
        self.subscribed.clear()
        self.error = None
        try:
            self.client.connect(self.address.hostname, self.address.port or self.PORTS[self.address.scheme], keepalive=30)
            self.client.loop_start()
            if not self.connected.wait(12) or self.error:
                raise ConnectionError("MQTT connection failed: " + (self.error or "timed out"))
            if not self.subscribed.wait(5) or self.error:
                raise ConnectionError("MQTT subscription failed: " + (self.error or "timed out"))
            return self
        except BaseException:
            self.close()
            raise

    @classmethod
    def validate_request(cls, topic, value):
        parts = topic.split("/")
        if len(parts) == 4 and parts[0] == "house" and parts[3] == "set":
            if (parts[1], parts[2]) not in cls.ACTUATORS:
                raise ValueError("Only lights, air conditioners, irrigation, main power, and the garage motor accept commands.")
            return
        if len(parts) != 5 or parts[0] != "house" or parts[3:] != ["config", "set"]:
            raise ValueError("Use a device /set or /config/set topic. Sensors and the clock are read only.")
        key = (parts[1], parts[2])
        if key in cls.SENSORS:
            allowed = {"read_interval", "publish_interval"}
        elif key in cls.ACTUATORS:
            allowed = {"publish_interval"}
            if key[1] == "air_conditioner":
                allowed.update({"setpoint", "mode"})
        else:
            raise ValueError("This device does not accept MQTT configuration.")
        try:
            settings = json.loads(value) if isinstance(value, str) else value
        except json.JSONDecodeError as error:
            raise ValueError("Configuration must be a JSON object.") from error
        if not isinstance(settings, dict) or not settings:
            raise ValueError("Configuration must be a nonempty JSON object.")
        if set(settings) - allowed:
            raise ValueError("Unsupported configuration fields: " + ", ".join(sorted(set(settings) - allowed)))

    def send_command(self, topic, value, retain=False):
        self.validate_request(topic, value)
        payload = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        result = self.client.publish(topic, payload, qos=1, retain=retain)
        result.wait_for_publish(timeout=5)
        if not result.is_published():
            raise ConnectionError("The broker did not acknowledge the command.")
        return result

    def set(self, area, device, value):
        return self.send_command(f"house/{area}/{device}/set", value)

    def configure(self, area, device, **settings):
        return self.send_command(f"house/{area}/{device}/config/set", settings)

    def state(self, area, device=None):
        """Return a device state, or state("clock") for the read-only clock."""
        topic = f"house/{area}/{device}/state" if device is not None else f"house/{area}/state"
        payload = self._state_payloads.get(topic)
        if payload is not None:
            return json.loads(payload)
        return None

    def observe(self, seconds):
        time.sleep(max(0, seconds))

    def close(self):
        self.client.disconnect()
        self.client.loop_stop()

    @classmethod
    def run_from_cli(cls):
        parser = argparse.ArgumentParser(description="Control the smart house over MQTT")
        parser.add_argument("--url", required=True, help="Public wss://HOST/mqtt or local mqtt://127.0.0.1:18883")
        parser.add_argument("--user", default="classroom")
        parser.add_argument("--topic", help="Actuator command or device configuration, such as house/bedroom/light/set")
        parser.add_argument("--value", default="ON", help='Scalar command or JSON settings, such as {"publish_interval": 2}')
        parser.add_argument("--seconds", type=float, default=30, help="Seconds to observe state messages")
        args = parser.parse_args()
        if args.topic:
            try:
                cls.validate_request(args.topic, args.value)
            except ValueError as error:
                parser.error(str(error))
        password = getpass.getpass("MQTT password: ")
        client = cls(args.url, args.user, password)
        try:
            client.connect()
            if args.topic:
                client.send_command(args.topic, args.value)
                print("Request sent. The /state message confirms the applied state and settings.")
            client.observe(args.seconds)
        except KeyboardInterrupt:
            pass
        finally:
            client.close()


if __name__ == "__main__":
    StudentClient.run_from_cli()
