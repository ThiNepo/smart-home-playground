"""Behavioral coverage for manual actuators and read-only measured sensors."""
import json
import pytest
from smarthouse.model import SmartHouse


class TestSmartHouse:
    @pytest.fixture
    def house(self):
        return SmartHouse()

    def test_breaker_gates_power_without_discarding_requested_states(self, house):
        house.handle_command("house/power/breaker/set", "OFF")
        house.handle_command("house/living_room/light/set", "ON")
        house.handle_command("house/bedroom/air_conditioner/set", "ON")
        house.handle_command("house/garden/irrigation/set", "ON")
        house.handle_command("house/garage/door/set", "OPEN")
        house.update(1)
        assert not house.rooms["living_room"].light.is_on
        assert not house.rooms["bedroom"].air_conditioner.is_on
        assert not house.irrigation.is_on
        assert house.openings["garage_door"].position == 0
        house.handle_command("house/power/breaker/set", "ON")
        assert house.rooms["living_room"].light.is_on
        assert house.rooms["bedroom"].air_conditioner.is_on
        assert house.irrigation.is_on
        house.update(1)
        assert house.openings["garage_door"].position == pytest.approx(0.5)

    def test_sensor_changes_never_control_lights_or_irrigation(self, house):
        house.simulation.set_sensor("garage", "motion", True)
        house.simulation.set_sensor("garden", "moisture", 5)
        house.update(1)
        assert house.motion_sensor.value is True
        assert house.moisture_sensor.value < 5
        assert not house.rooms["garage"].light.is_on
        assert not house.irrigation.is_on
        house.handle_command("house/garden/irrigation/set", "ON")
        house.simulation.set_sensor("garden", "moisture", 90)
        house.update(1)
        assert house.irrigation.is_on
        house.handle_command("house/garden/irrigation/set", "OFF")
        house.simulation.set_sensor("garden", "moisture", 5)
        house.update(1)
        assert not house.irrigation.is_on

    @pytest.mark.parametrize("area,device,value", [
        ("garage", "motion", "ON"), ("garage", "car_presence", "false"),
        ("garden", "moisture", "20"), ("bedroom", "temperature", "21"),
        ("living_room", "door_contact", "false"), ("laundry", "door_contact", "false"),
        ("garage", "door_contact", "false"), ("bedroom", "window_contact", "false"),
    ])
    def test_sensor_action_topics_are_read_only(self, house, area, device, value):
        before = house.telemetry()
        with pytest.raises(ValueError, match="read-only"):
            house.handle_command(f"house/{area}/{device}/set", value)
        assert house.telemetry() == before

    @pytest.mark.parametrize("topic,payload", [
        ("house/living_room/light/set", '"maybe"'),
        ("house/garden/moisture/set", "NaN"),
        ("house/living_room/light/set", '{"other":true}'),
        ("house/attic/light/set", "ON"),
        ("house/garden/automatic/set", "ON"),
        ("house/garage/automatic/set", "ON"),
    ])
    def test_invalid_messages_do_not_change_state(self, house, topic, payload):
        before = house.telemetry()
        with pytest.raises((ValueError, TypeError)):
            house.handle_command(topic, payload)
        assert house.telemetry() == before

    def test_json_and_plain_action_values(self, house):
        house.handle_command("house/living_room/light/set", '{"value":true}')
        assert house.rooms["living_room"].light.is_on
        house.handle_command("house/living_room/light/set", "off")
        assert not house.rooms["living_room"].light.is_on

    def test_local_environment_input_waits_for_sensor_read(self, house):
        sensor = house.car_sensor
        house.simulation.set_sensor("garage", "car_presence", False)
        assert sensor.physical_value is False
        assert sensor.value is True
        house.update(0.9)
        assert sensor.value is True
        house.update(0.1)
        assert sensor.value is False

    @pytest.mark.parametrize("value", [True, -1, 101, float("nan"), float("inf"), "invalid"])
    def test_invalid_local_numeric_input_is_atomic(self, house, value):
        previous = house.moisture_sensor.physical_value
        with pytest.raises(ValueError):
            house.simulation.set_sensor("garden", "moisture", value)
        assert house.moisture_sensor.physical_value == previous

    def test_irrigation_changes_soil_only_when_explicitly_enabled(self, house):
        house.simulation.set_sensor("garden", "moisture", 20)
        house.update(2)
        assert house.moisture_sensor.value == pytest.approx(18.9)
        assert not house.irrigation.is_on
        house.handle_command("house/garden/irrigation/set", "ON")
        house.update(2)
        assert house.moisture_sensor.value == pytest.approx(28.9)


class TestModularDevices:
    def test_all_rooms_have_lights_and_only_four_have_air_conditioning(self):
        house = SmartHouse()
        assert set(house.rooms) == {"living_room", "kitchen", "bedroom", "bathroom", "laundry", "hall", "garage"}
        for name, room in house.rooms.items():
            house.handle_command(f"house/{name}/light/set", "ON")
            assert room.light.is_on
            assert (room.air_conditioner is not None) is (name in {"living_room", "kitchen", "bedroom", "garage"})

    def test_garage_command_does_not_confirm_before_animation_finishes(self):
        house = SmartHouse()
        opening = house.openings["garage_door"]
        house.handle_command("house/garage/door/set", "OPEN")
        assert opening.status == "OPENING"
        assert opening.position == 0
        assert opening.contact.value is True
        house.update(1)
        assert opening.position == pytest.approx(0.5)
        assert opening.status == "OPENING"
        assert opening.contact.value is False
        house.update(1)
        assert opening.status == "OPEN"
        house.handle_command("house/garage/door/set", "CLOSE")
        house.update(1)
        assert opening.status == "CLOSING"
        assert opening.contact.value is False
        house.update(1)
        assert opening.position == 0
        assert opening.status == "CLOSED"
        assert opening.contact.value is True

    def test_reversing_a_manual_door_preserves_physical_position(self):
        house = SmartHouse()
        opening = house.set_opening("front_door", True)
        house.update(0.4)
        assert opening.position == pytest.approx(0.4)
        house.set_opening("front_door", False)
        assert opening.position == pytest.approx(0.4)
        assert opening.status == "CLOSING"
        house.update(0.4)
        assert opening.status == "CLOSED"

    @pytest.mark.parametrize("area,device", [("living_room","door"),("laundry","door"),("bedroom","window")])
    def test_manual_openings_have_contacts_but_no_mqtt_actuator(self, area, device):
        house = SmartHouse()
        assert (area, device) not in house.devices
        contact = f"{device}_contact"
        assert (area, contact) in house.devices
        for suffix, payload in (("set", "OPEN"), ("config/set", '{"publish_interval":1}')):
            with pytest.raises(ValueError, match="Unknown device"):
                house.handle_command(f"house/{area}/{device}/{suffix}", payload)

    def test_interior_doors_are_locally_animated_without_invented_contacts(self):
        house = SmartHouse()
        assert len(house.openings) == 10
        for name in house.INTERIOR_OPENINGS:
            opening = house.set_opening(name, True)
            assert opening.contact is None
        house.update(0.5)
        for name in house.INTERIOR_OPENINGS:
            assert house.openings[name].position == pytest.approx(0.5)
        house.update(0.5)
        assert all(house.openings[name].status == "OPEN" for name in house.INTERIOR_OPENINGS)

    def test_garage_door_vehicle_and_motion_are_independent(self):
        house = SmartHouse()
        house.handle_command("house/garage/door/set", "OPEN")
        house.update(2)
        assert house.car_sensor.value is True
        assert house.motion_sensor.value is False
        house.simulation.set_sensor("garage", "car_presence", False)
        house.simulation.set_sensor("garage", "motion", True)
        house.update(1)
        assert house.car_sensor.value is False
        assert house.motion_sensor.value is True
        assert house.openings["garage_door"].status == "OPEN"
        assert not house.rooms["garage"].light.is_on

    def test_power_loss_stops_garage_motor_until_power_returns(self):
        house = SmartHouse()
        house.handle_command("house/garage/door/set", "OPEN")
        house.update(0.5)
        opening = house.openings["garage_door"]
        house.handle_command("house/power/breaker/set", "OFF")
        house.update(3)
        assert opening.position == pytest.approx(0.25)
        assert opening.moving is False
        house.handle_command("house/power/breaker/set", "ON")
        house.update(1.5)
        assert opening.status == "OPEN"

    def test_air_conditioner_moves_temperature_and_obeys_power(self):
        house = SmartHouse()
        ac = house.rooms["bedroom"].air_conditioner
        house.handle_command("house/bedroom/air_conditioner/config/set", '{"setpoint":20,"mode":"COOL"}')
        house.handle_command("house/bedroom/air_conditioner/set", "ON")
        house.update(5)
        assert ac.is_on
        assert ac.temperature.value == pytest.approx(22.5)
        house.handle_command("house/power/breaker/set", "OFF")
        assert not ac.is_on
        assert ac.enabled
        house.update(4)
        assert ac.temperature.value > 22.5

    @pytest.mark.parametrize("topic,invalid", [
        ("house/garden/irrigation/config/set", '{"low":30,"high":60}'),
        ("house/garden/irrigation/config/set", '{"automatic":true}'),
        ("house/garage/light/config/set", '{"automatic":true}'),
        ("house/garage/door/config/set", '{"travel_time":1}'),
        ("house/garage/motion/config/set", '{"timeout":3}'),
        ("house/garden/moisture/config/set", '{"read_interval":0,"publish_interval":4}'),
        ("house/garden/moisture/config/set", '{"read_interval":2,"publish_interval":301}'),
        ("house/bedroom/air_conditioner/config/set", '{"setpoint":20,"mode":"INVALID"}'),
        ("house/garden/moisture/config/set", '{"read_interval":NaN}'),
        ("house/garden/moisture/config/set", '[]'),
    ])
    def test_invalid_or_simulation_config_is_atomic(self, topic, invalid):
        house = SmartHouse()
        before = house.telemetry()
        with pytest.raises(ValueError):
            house.handle_command(topic, invalid)
        assert house.telemetry() == before

    def test_read_clock_does_not_advance_when_publishing(self):
        house = SmartHouse()
        house.handle_command("house/garden/moisture/config/set", '{"read_interval":5,"publish_interval":1}')
        sensor = house.moisture_sensor
        initial = sensor.value
        samples = sensor.samples
        house.update(2)
        assert sensor.value == initial
        assert sensor.physical_value < initial
        for _ in range(8):
            house.publications(1)
        assert sensor.samples == samples
        house.update(3)
        assert sensor.value == sensor.physical_value
        assert sensor.samples == samples + 1

    def test_periodic_values_repeat_without_resampling(self):
        house = SmartHouse()
        topic = "house/garage/car_presence/state"
        house.handle_command("house/garage/car_presence/config/set", '{"publish_interval":3,"read_interval":5}')
        initial = house.publications(0)
        assert topic not in house.publications(2.9)
        assert house.publications(0.1)[topic] == initial[topic]
        assert house.car_sensor.samples == 1

    def test_mqtt_states_contain_only_measured_data_and_device_configuration(self):
        house = SmartHouse()
        for topic, payload in house.telemetry().items():
            decoded = json.loads(payload)
            assert "value" in decoded
            assert "physical_value" not in payload
            assert "automatic" not in payload
            assert "travel_time" not in payload
            assert "timeout" not in payload
            if topic != "house/clock/state":
                assert "config" in decoded
            assert len(payload.encode()) < 512
        contact = json.loads(house.telemetry()["house/living_room/door_contact/state"])
        assert contact == {"value":True,"config":{"publish_interval":2.0,"read_interval":1.0}}

    def test_local_controller_cannot_inject_contact_sensor(self):
        house = SmartHouse()
        with pytest.raises(ValueError, match="physical opening"):
            house.simulation.set_sensor("living_room", "door_contact", False)
        assert house.openings["front_door"].contact.value is True
