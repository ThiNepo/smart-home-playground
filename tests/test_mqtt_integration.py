"""MQTT protocol checks and explicitly selected, isolated Docker tests."""
import json
import os
import re
import socket
import time
import uuid
import pytest
from examples.student import StudentClient
from smarthouse.application import SmartHouseApplication
from smarthouse.infrastructure import DockerInfrastructure
from smarthouse.messaging import MqttController


class MqttTestSession:
    def __init__(self, runtime_dir, remote=False):
        mqtt_port, websocket_port = self.free_ports()
        self.infrastructure = DockerInfrastructure(
            remote=remote, runtime_dir=runtime_dir,
            project_name="smart-house-test-" + uuid.uuid4().hex[:10],
            mqtt_port=mqtt_port, websocket_port=websocket_port,
        )
        self.messaging = None
        self.application = None
        self.clients = []

    @staticmethod
    def free_ports():
        with socket.socket() as native, socket.socket() as websocket:
            native.bind(("127.0.0.1", 0))
            websocket.bind(("127.0.0.1", 0))
            return native.getsockname()[1], websocket.getsockname()[1]

    def start(self):
        self.infrastructure.start()
        self.messaging = MqttController(self.infrastructure.credentials, port=self.infrastructure.mqtt_port)
        self.messaging.start()
        self.application = SmartHouseApplication(self.messaging, self.infrastructure)
        self.pump()
        return self

    def connect_student(self, remote=False, password=None, native=False):
        credentials = self.infrastructure.credentials
        url = self.infrastructure.url if remote else f"ws://127.0.0.1:{self.infrastructure.websocket_port}/mqtt"
        if native:
            url = f"mqtt://127.0.0.1:{self.infrastructure.mqtt_port}"
        client = StudentClient(url, credentials["username"], password or credentials["password"], quiet=True)
        client.connect()
        self.clients.append(client)
        return client

    @staticmethod
    def send_raw(client, topic, value):
        payload = value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        result = client.client.publish(topic, payload, qos=1, retain=False)
        result.wait_for_publish(timeout=5)
        assert result.is_published()

    def pump(self, seconds=0.8):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.application.tick(0.025)
            time.sleep(0.025)

    def close(self):
        for client in self.clients:
            client.close()
        try:
            if self.messaging:
                self.messaging.stop()
        finally:
            self.infrastructure.stop()


@pytest.mark.integration
class TestMqttIntegration:
    @pytest.fixture(scope="class")
    @classmethod
    def session(cls, tmp_path_factory):
        session = MqttTestSession(tmp_path_factory.mktemp("mqtt-runtime"), remote=os.getenv("SMART_HOUSE_REMOTE_TEST") == "1")
        try:
            yield session.start()
        finally:
            session.close()

    def test_shared_credentials_commands_and_reconnection(self, session):
        app = session.application
        house = app.house
        student = session.connect_student()
        native = session.connect_student(native=True)
        assert session.messaging.connected
        assert student.client._client_id != native.client._client_id
        student.set("living_room", "light", "ON")
        session.pump()
        assert house.rooms["living_room"].light.is_on
        assert student.state("living_room", "light")["value"] == "ON"
        assert native.state("living_room", "light")["value"] == "ON"
        student.set("power", "breaker", "OFF")
        session.pump()
        assert not house.breaker.enabled
        assert student.state("living_room", "light")["value"] == "OFF"
        student.set("power", "breaker", "ON")
        session.pump()
        assert house.rooms["living_room"].light.is_on
        app.students_enabled = False
        student.set("living_room", "light", "OFF")
        session.pump()
        assert house.rooms["living_room"].light.is_on
        app.students_enabled = True
        with pytest.raises(ConnectionError):
            session.connect_student(password="wrong-password")
        student.send_command("house/living_room/light/set", "OFF", retain=True)
        session.pump()
        session.messaging.stop()
        app.command("house/living_room/light/set", "ON")
        session.messaging = MqttController(session.infrastructure.credentials, port=session.infrastructure.mqtt_port)
        app.messaging = session.messaging
        session.messaging.start()
        session.pump()
        assert house.rooms["living_room"].light.is_on

    def test_configuration_confirmation_and_periodic_sensor_publication(self, session):
        student = session.connect_student()
        student.configure("garden", "moisture", read_interval=0.1, publish_interval=0.2)
        session.pump(0.5)
        state = student.state("garden", "moisture")
        assert state["config"] == {"read_interval": 0.1, "publish_interval": 0.2}
        student.received.clear()
        session.pump(0.75)
        readings = [json.loads(payload) for topic, payload in student.received if topic == "house/garden/moisture/state"]
        assert len(readings) >= 3
        session.send_raw(student, "house/garden/moisture/config/set", {"read_interval": 0.2, "unknown_setting": 10})
        session.pump(0.4)
        assert student.state("garden", "moisture")["config"]["read_interval"] == 0.1

    def test_opening_transitions_and_independent_vehicle_presence(self, session):
        student = session.connect_student()
        student.set("garage", "door", "CLOSE")
        session.pump(3)
        student.configure("garage", "car_presence", read_interval=0.1, publish_interval=0.2)
        session.application.house.simulation.set_sensor("garage", "car_presence", False)
        student.set("garage", "door", "OPEN")
        session.pump(0.15)
        moving = student.state("garage", "door")
        assert moving["target_open"] is True
        assert moving["value"] == "OPENING"
        session.pump(3)
        assert student.state("garage", "door")["value"] == "OPEN"
        assert student.state("garage", "car_presence")["value"] is False

    def test_local_sensor_inputs_are_read_only_and_do_not_automate_actuators(self, session):
        house = session.application.house
        student = session.connect_student()
        student.set("power", "breaker", "ON")
        student.set("garage", "light", "OFF")
        student.set("garden", "irrigation", "OFF")
        for area, device in (("garden", "moisture"), ("garage", "motion"), ("garage", "car_presence"), ("bedroom", "temperature"), ("living_room", "door_contact")):
            student.configure(area, device, read_interval=0.1, publish_interval=0.2)
        house.simulation.set_sensor("garden", "moisture", 5)
        house.simulation.set_sensor("garage", "motion", True)
        house.simulation.set_sensor("garage", "car_presence", False)
        house.simulation.set_sensor("bedroom", "temperature", 25)
        session.pump(0.3)
        assert student.state("garden", "moisture")["value"] < 6
        assert student.state("garage", "motion")["value"] is True
        assert student.state("garage", "car_presence")["value"] is False
        assert not house.rooms["garage"].light.is_on
        assert not house.irrigation.is_on
        requests = (
            ("house/garden/moisture/set", 80),
            ("house/garage/motion/set", False),
            ("house/garage/car_presence/set", True),
            ("house/bedroom/temperature/set", 5),
            ("house/living_room/door_contact/set", False),
            ("house/living_room/door/set", "OPEN"),
            ("house/laundry/door/set", "OPEN"),
            ("house/bedroom/window/set", "OPEN"),
            ("house/hall/bedroom_door/set", "OPEN"),
            ("house/garage/light/config/set", {"automatic": True}),
            ("house/garden/irrigation/config/set", {"automatic": True, "low": 20, "high": 80}),
            ("house/garage/door/config/set", {"travel_time": 0.2}),
            ("house/garage/motion/config/set", {"timeout": 100}),
        )
        for topic, value in requests:
            session.send_raw(student, topic, value)
        session.pump(0.3)
        assert student.state("garden", "moisture")["value"] < 6
        assert student.state("garage", "motion")["value"] is True
        assert student.state("garage", "car_presence")["value"] is False
        assert student.state("bedroom", "temperature")["value"] > 20
        assert student.state("living_room", "door_contact")["value"] is True
        assert not house.openings["front_door"].target_open
        assert not house.openings["rear_door"].target_open
        assert not house.openings["bedroom_window"].target_open
        assert not house.rooms["garage"].light.is_on
        assert not house.irrigation.is_on
        assert any("REJECTED" in event for _, event in session.messaging.recent(50))
        states = [json.loads(payload) for topic, payload in list(student.received) if topic.endswith("/state")]
        assert states and all("physical_value" not in state for state in states)

    def test_sampling_and_publication_intervals_are_independent(self, session):
        student = session.connect_student()
        simulation = session.application.house.simulation
        simulation.set_sensor("garage", "car_presence", False)
        student.configure("garage", "car_presence", read_interval=0.5, publish_interval=0.1)
        session.pump(0.55)
        assert student.state("garage", "car_presence")["value"] is False
        student.received.clear()
        simulation.set_sensor("garage", "car_presence", True)
        session.pump(0.3)
        readings = [json.loads(payload) for topic, payload in list(student.received) if topic == "house/garage/car_presence/state"]
        assert len(readings) >= 2
        assert all(state["value"] is False for state in readings)
        session.pump(0.3)
        assert student.state("garage", "car_presence")["value"] is True

    def test_clock_is_read_only_and_reports_time_without_a_date(self, session):
        student = session.connect_student()
        student.received.clear()
        session.pump(0.55)
        readings = [json.loads(payload) for topic, payload in list(student.received) if topic == "house/clock/state"]
        assert len(readings) >= 2
        assert all(set(state) == {"value"} and re.fullmatch(r"[0-2][0-9]:[0-5][0-9]", state["value"]) for state in readings)
        before = student.state("clock")["value"]
        session.send_raw(student, "house/clock/time/set", "23:59")
        session.send_raw(student, "house/clock/time/config/set", {"seconds_per_day": 1})
        session.pump(0.3)
        after = student.state("clock")["value"]
        before_parts = [int(part) for part in before.split(":")]
        after_parts = [int(part) for part in after.split(":")]
        advanced_minutes = (after_parts[0] * 60 + after_parts[1] - before_parts[0] * 60 - before_parts[1]) % 1440
        assert 0 <= advanced_minutes <= 4
        assert set(student.state("clock")) == {"value"}
        assert any("REJECTED" in event for _, event in session.messaging.recent(20))

    @pytest.mark.skipif(os.getenv("SMART_HOUSE_REMOTE_TEST") != "1", reason="Set SMART_HOUSE_REMOTE_TEST=1 to test the public tunnel.")
    def test_public_wss_commands_and_telemetry(self, session):
        assert session.infrastructure.url.startswith("wss://"), session.infrastructure.notice
        student = session.connect_student(remote=True)
        student.set("kitchen", "light", "ON")
        session.pump(2)
        assert session.application.house.rooms["kitchen"].light.is_on
        assert student.state("kitchen", "light")["value"] == "ON"
