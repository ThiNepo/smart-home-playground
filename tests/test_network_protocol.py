"""Network contracts without Docker or a graphical display."""
import json
import re
from types import SimpleNamespace
import pytest
import paho.mqtt.client as mqtt
from examples.student import StudentClient
from smarthouse.infrastructure import DockerInfrastructure
from smarthouse.messaging import MqttController


class TestMqttProtocol:
    def test_subscribes_actions_and_configuration_but_ignores_retained_requests(self):
        controller = MqttController({"username": "classroom", "password": "A7K2M9"})
        subscriptions = []
        client = SimpleNamespace(subscribe=lambda filters: subscriptions.extend(filters), publish=lambda *args, **kwargs: None)
        controller._on_connect(client, None, None, SimpleNamespace(is_failure=False), None)
        assert ("house/+/+/set", 1) in subscriptions
        assert ("house/+/+/config/set", 1) in subscriptions
        message = SimpleNamespace(topic="house/garden/moisture/config/set", payload=b'{"read_interval": 1}', retain=True)
        controller._on_message(client, None, message)
        assert controller.commands.empty()
        message.retain = False
        controller._on_message(client, None, message)
        assert controller.commands.get_nowait() == (message.topic, message.payload.decode())

    def test_force_publishes_unchanged_periodic_state(self):
        controller = MqttController({"username": "classroom", "password": "A7K2M9"})
        publications = []
        controller.client = SimpleNamespace(publish=lambda *args, **kwargs: publications.append(args) or SimpleNamespace(rc=mqtt.MQTT_ERR_SUCCESS))
        controller.connected = True
        values = {"house/garden/moisture/state": '{"value": 42}'}
        controller.publish(values)
        controller.publish(values)
        controller.publish(values, force=True)
        assert len(publications) == 2
        assert not controller.snapshot_required
        controller._snapshot_required.set()
        controller.client.publish = lambda *args, **kwargs: SimpleNamespace(rc=mqtt.MQTT_ERR_NO_CONN)
        controller.publish(values, force=True)
        assert controller.snapshot_required

    def test_long_existing_credential_migrates_once_without_modifying_another_runtime(self, tmp_path, monkeypatch):
        credential_path = tmp_path / "credentials.json"
        credential_path.write_text(json.dumps({"username": "classroom", "password": "old-password-that-is-too-long"}), encoding="utf-8")
        infrastructure = DockerInfrastructure(remote=False, runtime_dir=tmp_path)
        monkeypatch.setattr(infrastructure, "compose", lambda *args, **kwargs: None)
        infrastructure.prepare()
        password = infrastructure.credentials["password"]
        assert re.fullmatch(r"[A-Za-z0-9]{6}", password)
        infrastructure.prepare()
        assert infrastructure.credentials == {"username": "classroom", "password": password}
        manifest = infrastructure.compose_file.read_text(encoding="utf-8")
        assert (tmp_path / "mosquitto").resolve().as_posix() in manifest
        assert "./.runtime/mosquitto:" not in manifest

    @pytest.mark.parametrize("url,transport", [("mqtt://127.0.0.1:18883", "tcp"), ("ws://127.0.0.1:19001/mqtt", "websockets"), ("wss://classroom.example/mqtt", "websockets")])
    def test_student_transports_and_json_state(self, url, transport):
        client = StudentClient(url, "classroom", "A7K2M9", quiet=True)
        assert client.client.transport == transport
        client._on_message(client.client, None, SimpleNamespace(topic="house/bedroom/window_contact/state", payload=b'{"value":true,"config":{"publish_interval":2,"read_interval":1}}'))
        assert client.state("bedroom", "window_contact")["value"] is True
        assert client.state("garden", "moisture") is None
        client.close()


    @pytest.mark.parametrize("topic,value", [
        ("house/garden/moisture/set", 20),
        ("house/garage/motion/set", True),
        ("house/garage/car_presence/set", False),
        ("house/bedroom/temperature/set", 25),
        ("house/living_room/door/set", "OPEN"),
        ("house/laundry/door/set", "OPEN"),
        ("house/bedroom/window/set", "OPEN"),
        ("house/living_room/door_contact/set", False),
        ("house/clock/time/set", "12:00"),
        ("house/clock/time/config/set", {"seconds_per_day": 1}),
        ("house/garden/irrigation/config/set", {"automatic": True}),
        ("house/garage/motion/config/set", {"timeout": 5}),
        ("house/garage/door/config/set", {"travel_time": 1}),
    ])
    def test_student_rejects_simulation_inputs_and_local_physics_settings(self, topic, value):
        with pytest.raises(ValueError):
            StudentClient.validate_request(topic, value)

    @pytest.mark.parametrize("topic,value", [
        ("house/bathroom/light/set", "ON"),
        ("house/garage/door/set", "OPEN"),
        ("house/garden/irrigation/set", "OFF"),
        ("house/garden/moisture/config/set", {"read_interval": 1, "publish_interval": 5}),
        ("house/bedroom/air_conditioner/config/set", {"setpoint": 23, "mode": "COOL"}),
    ])
    def test_student_accepts_actuators_and_real_device_settings(self, topic, value):
        StudentClient.validate_request(topic, value)

    def test_student_receives_read_only_clock_by_default(self):
        client = StudentClient("mqtt://127.0.0.1:18883", "classroom", "A7K2M9", quiet=True)
        assert client.topics == ("house/+/+/state", "house/clock/state", "house/status")
        client._on_message(client.client, None, SimpleNamespace(topic="house/clock/state", payload=b'{"value":"08:15"}'))
        assert client.state("clock") == {"value": "08:15"}
        client.close()

    def test_infrequent_sensor_state_survives_clock_history_eviction(self):
        client = StudentClient("mqtt://127.0.0.1:18883", "classroom", "A7K2M9", quiet=True)
        client._on_message(client.client, None, SimpleNamespace(topic="house/garden/moisture/state", payload=b'{"value":42,"config":{"publish_interval":300}}'))
        for _ in range(501):
            client._on_message(client.client, None, SimpleNamespace(topic="house/clock/state", payload=b'{"value":"09:00"}'))
        assert len(client.received) == 500
        assert client.state("garden", "moisture")["value"] == 42
        client.close()
