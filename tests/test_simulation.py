"""Local configuration, accelerated clock, and environment scenario behavior."""
import json
import pytest
from smarthouse.configuration import SimulationConfiguration
from smarthouse.model import SmartHouse
from smarthouse.simulation import SimulationClock


class TestSimulationClock:
    def test_complete_simulated_day_wraps_without_date_or_day(self):
        clock = SimulationClock(SimulationConfiguration.load().clock)
        assert clock.time_text == "08:00"
        clock.advance(120)
        assert clock.time_text == "20:00"
        clock.advance(120)
        assert clock.state() == {"value":"08:00"}

    def test_midnight_wraps_in_hh_mm_format(self):
        data = SimulationConfiguration.load().to_dict()
        data["clock"]["start_time"] = "23:59"
        clock = SimulationClock(SimulationConfiguration.from_dict(data).clock)
        clock.advance(1 / 6)
        assert clock.time_text == "00:00"
        clock.advance(1 / 6)
        assert clock.time_text == "00:01"

    def test_six_clock_updates_per_real_second_at_default_speed(self):
        clock = SimulationClock(SimulationConfiguration.load().clock)
        assert clock.publication_due()
        times = []
        for _ in range(6):
            clock.advance(1 / 6)
            assert clock.publication_due()
            times.append(clock.state()["value"])
        assert times == ["08:01","08:02","08:03","08:04","08:05","08:06"]
        assert not clock.publication_due()

    def test_clock_publication_preserves_fractional_minute_overshoot(self):
        clock = SimulationClock(SimulationConfiguration.load().clock)
        clock.publication_due()
        publication_frames = []
        for frame in range(1, 11):
            clock.advance(0.1)
            if clock.publication_due():
                publication_frames.append(frame)
        assert publication_frames == [2,4,5,7,9,10]
        assert clock.time_text == "08:06"

    def test_clock_and_physical_animation_advance_independently(self):
        house = SmartHouse()
        house.set_opening("bedroom_door", True)
        house.advance_clock(120)
        assert house.clock.time_text == "20:00"
        assert house.openings["bedroom_door"].position == 0
        house.update(0.5)
        assert house.clock.time_text == "20:00"
        assert house.openings["bedroom_door"].position == pytest.approx(0.5)

    @pytest.mark.parametrize("topic,payload", [
        ("house/clock/set", "12:00"),
        ("house/clock/config/set", '{"real_seconds_per_day":1}'),
        ("house/clock/time/set", "12:00"),
        ("house/clock/time/config/set", '{"publish_interval":1}'),
    ])
    def test_clock_cannot_be_changed_over_mqtt(self, topic, payload):
        house = SmartHouse()
        with pytest.raises(ValueError):
            house.handle_command(topic, payload)
        assert house.clock.state() == {"value":"08:00"}


class TestSimulationConfiguration:
    @pytest.mark.parametrize("group,key,value", [
        ("clock","real_seconds_per_day",0),
        ("clock","real_seconds_per_day","240"),
        ("clock","start_time","24:00"),
        ("clock","start_time","8:00"),
        ("clock","publish_interval_minutes",False),
        ("devices","read_interval",0),
        ("devices","publish_interval",float("inf")),
        ("environment","car_present",1),
        ("environment","initial_moisture",101),
        ("environment","ambient_temperature",float("nan")),
        ("environment","motion_timeout",0),
        ("environment","drying_rate",-1),
        ("openings","manual_travel_time",0.1),
    ])
    def test_invalid_typed_presets_fail_before_house_initialization(self, group, key, value):
        data = SimulationConfiguration.load().to_dict()
        data[group][key] = value
        with pytest.raises(ValueError):
            SimulationConfiguration.from_dict(data)

    def test_unknown_fields_are_rejected_instead_of_silently_ignored(self):
        data = SimulationConfiguration.load().to_dict()
        data["environment"]["automatic_watering"] = True
        with pytest.raises(ValueError, match="Environment settings"):
            SimulationConfiguration.from_dict(data)

    def test_missing_file_reports_the_configuration_path(self, tmp_path):
        missing = tmp_path / "missing-simulation.json"
        with pytest.raises(ValueError, match="missing-simulation.json"):
            SimulationConfiguration.load(missing)

    def test_malformed_json_is_reported_before_simulation_starts(self, tmp_path):
        path = tmp_path / "simulation.json"
        path.write_text('{"clock":', encoding="utf-8")
        with pytest.raises(ValueError, match="Unable to read simulation configuration"):
            SimulationConfiguration.load(path)

    def test_local_file_controls_environment_and_animation_without_mqtt_exposure(self, tmp_path):
        data = SimulationConfiguration.load().to_dict()
        data["clock"].update(real_seconds_per_day=120, start_time="06:30")
        data["environment"].update(initial_moisture=40, drying_rate=2, watering_rate=3,
                                   initial_temperature=28, ambient_temperature=28, motion_timeout=3)
        data["openings"]["manual_travel_time"] = 2
        data["devices"].update(read_interval=0.5, publish_interval=4)
        path = tmp_path / "simulation.json"
        path.write_text(json.dumps(data),encoding="utf-8")
        house = SmartHouse(SimulationConfiguration.load(path))
        house.simulation.set_sensor("garage", "motion", True)
        house.set_opening("front_door", True)
        house.update(0.5)
        house.advance_clock(0.5)
        assert house.moisture_sensor.value == 39
        assert house.motion_sensor.remaining == 2.5
        assert house.openings["front_door"].position == pytest.approx(0.25)
        assert house.clock.time_text == "06:36"
        assert house.rooms["bedroom"].air_conditioner.temperature.value == 28
        assert house.car_sensor.config == {"read_interval":0.5,"publish_interval":4.0}
        for payload in house.telemetry().values():
            assert "drying_rate" not in payload
            assert "real_seconds_per_day" not in payload
            assert "motion_timeout" not in payload
            assert "travel_time" not in payload
