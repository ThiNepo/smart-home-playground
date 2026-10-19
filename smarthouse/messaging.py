"""Queue MQTT commands and publish retained device snapshots."""
from collections import deque
from datetime import datetime
from queue import Queue, Full
import threading
import uuid
import paho.mqtt.client as mqtt


class MqttController:
    def __init__(self, credentials, host="127.0.0.1", port=18883):
        self.host = host
        self.port = port
        self.commands = Queue(maxsize=500)
        self.events = deque(maxlen=150)
        self._lock = threading.Lock()
        self._snapshot_required = threading.Event()
        self._snapshot_required.set()
        self.connected = False
        self.last_values = {}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="house-" + uuid.uuid4().hex[:10])
        self.client.username_pw_set(credentials["username"], credentials["password"])
        self.client.will_set("house/status", "offline", qos=1, retain=True)
        self.client.reconnect_delay_set(1, 10)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    @property
    def snapshot_required(self):
        return self._snapshot_required.is_set()

    def log(self, text):
        with self._lock:
            self.events.appendleft((datetime.now().strftime("%H:%M:%S"), text[:160]))

    def recent(self, count=8):
        with self._lock:
            return list(self.events)[:count]

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        if self.connected:
            client.subscribe([("house/+/+/set", 1), ("house/+/+/config/set", 1)])
            client.publish("house/status", "online", qos=1, retain=True)
            self.last_values.clear()
            self._snapshot_required.set()
            self.log("Classroom connection ready.")
        else:
            self.log(f"Connection refused: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        self._snapshot_required.set()
        self.log("Connection lost; reconnecting.")

    def _on_message(self, client, userdata, message):
        if message.retain:
            self.log("Ignored a stale retained command.")
            return
        if len(message.payload) > 512:
            self.log("Command rejected: payload too large.")
            return
        try:
            payload = message.payload.decode("utf-8")
            self.commands.put_nowait((message.topic, payload))
        except (UnicodeDecodeError, Full):
            self.log("Command rejected: invalid encoding or full queue.")

    def start(self):
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        return self

    def publish(self, values, force=False):
        """Publish due readings, including unchanged periodic readings when forced."""
        if not self.connected:
            return
        published_all = True
        for topic, payload in values.items():
            if force or self.last_values.get(topic) != payload:
                result = self.client.publish(topic, payload, qos=1, retain=True)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    self.last_values[topic] = payload
                else:
                    published_all = False
        if values and published_all:
            self._snapshot_required.clear()

    def stop(self):
        if self.connected:
            self.client.publish("house/status", "offline", qos=1, retain=True).wait_for_publish(timeout=2)
        self.client.disconnect()
        self.client.loop_stop()
