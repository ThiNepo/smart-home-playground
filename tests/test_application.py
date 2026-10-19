"""Application behavior without a broker, display, or graphics library."""
import json
from queue import Queue
import pytest
from smarthouse.application import SmartHouseApplication
from smarthouse.configuration import SimulationConfiguration


class RecordingMessaging:
    """Record outgoing snapshots while modeling connection and queue behavior."""

    def __init__(self):
        self.commands = Queue()
        self.connected = True
        self.snapshot_required = True
        self.last_values = {}
        self.logs = []
        self.publications = []

    def log(self, message):
        self.logs.append(message)

    def publish(self, values, force=False):
        if not self.connected:
            return
        if values:
            self.publications.append((dict(values), force))
            self.last_values.update(values)
            self.snapshot_required = False

    def received(self, topic, payload):
        self.commands.put_nowait((topic, payload))

    def reconnect(self):
        self.connected = True
        self.snapshot_required = True


class TestSmartHouseApplication:
    @pytest.fixture
    def application(self):
        return SmartHouseApplication(RecordingMessaging())

    def test_pausing_discards_remote_commands_and_resume_accepts_only_new_commands(self, application):
        messaging = application.messaging
        application.tick(0)
        application.students_enabled = False
        messaging.received("house/living_room/light/set", "ON")
        messaging.received("house/garden/moisture/config/set", '{"read_interval":5}')
        application.tick(0)
        assert not application.house.rooms["living_room"].light.is_on
        assert application.house.moisture_sensor.config["read_interval"] == 1
        assert messaging.commands.empty()
        assert len([entry for entry in messaging.logs if "paused" in entry]) == 2
        application.students_enabled = True
        application.tick(0)
        assert not application.house.rooms["living_room"].light.is_on
        messaging.received("house/living_room/light/set", "ON")
        application.tick(0)
        assert application.house.rooms["living_room"].light.is_on

    def test_pausing_classroom_does_not_disable_local_controls(self, application):
        application.students_enabled = False
        assert application.command("house/living_room/light/set", "ON") is True
        assert application.house.rooms["living_room"].light.is_on

    def test_rejected_command_preserves_state_and_next_queued_command_runs(self, application):
        before = application.house.telemetry()
        assert application.command("house/garden/irrigation/config/set", '{"low":80,"high":20}') is False
        assert application.house.telemetry() == before
        assert any("REJECTED" in entry for entry in application.messaging.logs)
        application.messaging.received("house/living_room/light/set", "invalid")
        application.messaging.received("house/bedroom/light/set", "ON")
        application.tick(0)
        assert application.house.rooms["bedroom"].light.is_on
        assert not application.house.rooms["living_room"].light.is_on

    def test_initial_connection_publishes_a_complete_snapshot(self, application):
        application.tick(0)
        values, forced = application.messaging.publications[-1]
        assert forced is True
        assert values == application.house.telemetry()
        assert application.messaging.snapshot_required is False

    def test_reconnection_uses_snapshot_request_even_with_cached_values(self, application):
        messaging = application.messaging
        application.tick(0)
        cached_topics = set(messaging.last_values)
        messaging.connected = False
        application.command("house/bedroom/light/set", "ON")
        application.tick(0.1)
        messaging.publications.clear()
        assert set(messaging.last_values) == cached_topics
        messaging.reconnect()
        application.tick(0)
        values, forced = messaging.publications[-1]
        assert forced is True
        assert set(values) == cached_topics
        assert json.loads(values["house/bedroom/light/state"])["value"] == "ON"

    def test_periodic_publication_repeats_unchanged_states(self, application):
        topic = "house/garage/car_presence/state"
        application.command("house/garage/car_presence/config/set", '{"publish_interval":1.5,"read_interval":5}')
        application.tick(0)
        initial = application.messaging.last_values[topic]
        application.messaging.publications.clear()
        application.tick(0.5)
        application.tick(0.5)
        assert not any(topic in values for values, _ in application.messaging.publications)
        application.tick(0.5)
        values, forced = application.messaging.publications[-1]
        assert values[topic] == initial
        assert forced is True
        assert application.house.car_sensor.samples == 1

    def test_action_publishes_state_before_long_periodic_interval(self, application):
        topic = "house/bedroom/light/state"
        application.command("house/bedroom/light/config/set", '{"publish_interval":300}')
        application.tick(0)
        application.messaging.publications.clear()
        application.messaging.received("house/bedroom/light/set", "ON")
        application.tick(0)
        values, forced = application.messaging.publications[-1]
        assert json.loads(values[topic])["value"] == "ON"
        assert forced is True

    def test_animation_advances_only_by_elapsed_time_and_preserves_intermediate_state(self, application):
        application.command("house/garage/door/set", "OPEN")
        opening = application.house.openings["garage_door"]
        application.tick(0)
        assert opening.position == 0
        application.tick(0.4)
        assert opening.position == pytest.approx(0.2)
        assert opening.status == "OPENING"
        state = json.loads(application.house.telemetry()["house/garage/door/state"])
        assert state["value"] == "OPENING"
        assert state["contact_closed"] is False
        application.tick(1.59)
        assert opening.position == pytest.approx(0.995)
        assert opening.status == "OPENING"
        application.tick(0.01)
        assert opening.status == "OPEN"
        assert application.elapsed == pytest.approx(2.0)

    def test_long_frame_is_bounded_without_instantly_completing_slow_door(self, application):
        data = SimulationConfiguration.load().to_dict()
        data["openings"]["garage_travel_time"] = 5
        application = SmartHouseApplication(configuration=SimulationConfiguration.from_dict(data))
        application.command("house/garage/door/set", "OPEN")
        application.tick(20)
        assert application.house.openings["garage_door"].position == pytest.approx(0.4)
        assert application.elapsed == 20.0
        assert application.house.clock.time_text == "10:00"

    def test_sensor_reads_and_publications_advance_independently(self, application):
        application.command("house/garden/moisture/config/set", '{"read_interval":3,"publish_interval":1}')
        application.tick(0)
        initial = application.house.moisture_sensor.value
        application.tick(1)
        application.tick(1)
        assert application.house.moisture_sensor.value == initial
        assert application.house.moisture_sensor.physical_value < initial
        readings = application.house.moisture_sensor.samples
        application.tick(1)
        assert application.house.moisture_sensor.samples == readings + 1
        assert application.house.moisture_sensor.value == pytest.approx(application.house.moisture_sensor.physical_value)


    def test_motion_expires_after_eight_seconds_without_controlling_the_light(self, application):
        application.house.simulation.set_sensor("garage", "motion", True)
        sensor = application.house.motion_sensor
        initial_samples = sensor.samples
        for _ in range(479):
            application.tick(1 / 60)
        assert sensor.value is True
        assert not application.house.rooms["garage"].light.is_on
        application.tick(1 / 60)
        assert sensor.remaining == 0
        assert sensor.physical_value is False
        assert sensor.value is False
        assert not application.house.rooms["garage"].light.is_on
        assert sensor.samples == initial_samples + 8

    @pytest.mark.parametrize("interval,expected_readings", [(0.1,80), (0.7,11), (1,8), (1.3,6)])
    def test_fractional_frames_do_not_duplicate_or_delay_sensor_reads(self, application, interval, expected_readings):
        application.command("house/garage/car_presence/config/set", json.dumps({"read_interval":interval}))
        sensor = application.house.car_sensor
        initial_samples = sensor.samples
        for _ in range(480):
            application.tick(1 / 60)
        assert sensor.samples == initial_samples + expected_readings

    def test_publication_clock_preserves_elapsed_overshoot(self, application):
        topic = "house/garage/car_presence/state"
        application.command("house/garage/car_presence/config/set", '{"publish_interval":1}')
        application.tick(0)
        publication_frames = []
        for frame in range(1, 11):
            application.messaging.publications.clear()
            application.tick(0.3)
            if any(topic in values for values, _ in application.messaging.publications):
                publication_frames.append(frame)
        assert publication_frames == [4, 7, 10]


    def test_remote_sensor_writes_are_rejected_without_blocking_actuator_commands(self, application):
        application.messaging.received("house/garden/moisture/set", "1")
        application.messaging.received("house/garden/irrigation/set", "ON")
        application.tick(0)
        assert application.house.moisture_sensor.value == 55
        assert application.house.irrigation.is_on
        assert any("read-only" in entry for entry in application.messaging.logs)

    def test_clock_publications_run_at_simulated_minutes_with_real_device_intervals(self, application):
        application.tick(0)
        application.messaging.publications.clear()
        application.tick(1 / 6)
        values, _ = application.messaging.publications[-1]
        assert json.loads(values["house/clock/state"]) == {"value":"08:01"}
        assert "house/garage/car_presence/state" not in values

    def test_invalid_elapsed_time_does_not_advance_clock_or_simulation(self, application):
        for elapsed in (-1, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                application.tick(elapsed)
        assert application.house.clock.time_text == "08:00"
        assert application.elapsed == 0


    def test_clock_progress_does_not_automate_motion_lighting_or_dry_soil_watering(self, application):
        application.house.simulation.set_sensor("garage", "motion", True)
        application.house.simulation.set_sensor("garden", "moisture", 5)
        application.tick(1)
        application.tick(1)
        assert application.house.clock.time_text == "08:12"
        assert application.house.motion_sensor.value is True
        assert application.house.moisture_sensor.value < 5
        assert not application.house.rooms["garage"].light.is_on
        assert not application.house.irrigation.is_on
