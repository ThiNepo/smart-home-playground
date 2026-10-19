"""SmartHouse coordinates a modular registry of rooms, sensors, and actuators."""
from dataclasses import dataclass
import json
import math
from smarthouse.configuration import SimulationConfiguration
from smarthouse.devices import (AirConditioner, CarPresenceSensor, CircuitBreaker, DeviceValidation,
                                IrrigationSystem, Light, MotionSensor, Opening, Room, Sensor, SoilMoistureSensor)
from smarthouse.simulation import SimulationClock, SimulationController


@dataclass(frozen=True)
class HouseCommand:
    area: str
    device: str
    value: object
    action: str = "set"


class CommandParser:
    @staticmethod
    def _reject_constant(value):
        raise ValueError(f"Nonfinite JSON number is not allowed: {value}.")

    @classmethod
    def parse(cls, topic, payload):
        parts = topic.split("/")
        if len(parts) == 4 and parts[0] == "house" and parts[3] == "set":
            action = "set"
        elif len(parts) == 5 and parts[0] == "house" and parts[3:] == ["config", "set"]:
            action = "config"
        else:
            raise ValueError("Unknown command topic.")
        if not parts[1] or not parts[2]:
            raise ValueError("Unknown command topic.")
        try:
            value = json.loads(payload, parse_constant=cls._reject_constant)
        except json.JSONDecodeError:
            value = payload.strip()
        if action == "config":
            if not isinstance(value, dict):
                raise ValueError("Configuration must be a JSON object.")
        elif isinstance(value, dict):
            if set(value) != {"value"}:
                raise ValueError('Use a scalar value or {"value": value}.')
            value = value["value"]
        return HouseCommand(parts[1], parts[2], value, action)

    @staticmethod
    def boolean(value):
        return DeviceValidation.boolean(value)


class SmartHouse:
    ROOM_NAMES = ("living_room", "kitchen", "bedroom", "bathroom", "laundry", "hall", "garage")
    AIR_CONDITIONED_ROOMS = ("living_room", "kitchen", "bedroom", "garage")
    INTERIOR_OPENINGS = ("bedroom_door", "bathroom_door", "laundry_door", "living_hall_door",
                         "kitchen_hall_door", "garage_hall_door")

    def __init__(self, configuration=None):
        self.configuration = configuration if configuration is not None else SimulationConfiguration.load()
        if not isinstance(self.configuration, SimulationConfiguration):
            raise TypeError("Use a validated SimulationConfiguration instance.")
        environment = self.configuration.environment
        timings = self.configuration.openings
        self.breaker = CircuitBreaker()
        self.motion_sensor = MotionSensor(environment.motion_timeout)
        self.moisture_sensor = SoilMoistureSensor(environment.initial_moisture,
                                                 environment.drying_rate, environment.watering_rate)
        self.car_sensor = CarPresenceSensor(environment.car_present)
        self.rooms = {name: Room(name, self.breaker,
                                 self.motion_sensor if name == "garage" else None,
                                 name in self.AIR_CONDITIONED_ROOMS, environment) for name in self.ROOM_NAMES}
        self.irrigation = IrrigationSystem(self.breaker, self.moisture_sensor)
        self.openings = {
            "front_door": Opening("front_door", travel_time=timings.manual_travel_time),
            "garage_door": Opening("garage_door", self.breaker, timings.garage_travel_time),
            "bedroom_window": Opening("bedroom_window", travel_time=timings.window_travel_time),
            "rear_door": Opening("rear_door", travel_time=timings.manual_travel_time),
        }
        self.openings.update({name: Opening(name, travel_time=timings.manual_travel_time, monitored=False)
                              for name in self.INTERIOR_OPENINGS})
        self.parser = CommandParser()
        self.devices = {("power", "breaker"): self.breaker,
                        ("garage", "motion"): self.motion_sensor,
                        ("garage", "car_presence"): self.car_sensor,
                        ("garden", "moisture"): self.moisture_sensor,
                        ("garden", "irrigation"): self.irrigation,
                        ("garage", "door"): self.openings["garage_door"]}
        for name, room in self.rooms.items():
            self.devices[name, "light"] = room.light
            if room.air_conditioner is not None:
                self.devices[name, "air_conditioner"] = room.air_conditioner
                self.devices[name, "temperature"] = room.air_conditioner.temperature
        for name, area, kind in (("front_door", "living_room", "door_contact"),
                                 ("garage_door", "garage", "door_contact"),
                                 ("bedroom_window", "bedroom", "window_contact"),
                                 ("rear_door", "laundry", "door_contact")):
            self.devices[area, kind] = self.openings[name].contact
        defaults = self.configuration.devices
        for device in self.devices.values():
            changes = {"publish_interval": defaults.publish_interval}
            if isinstance(device, Sensor):
                changes["read_interval"] = defaults.read_interval
            device.configure(changes)
        self.clock = SimulationClock(self.configuration.clock)
        self.simulation = SimulationController(self)

    def update(self, dt):
        if not isinstance(dt, (int, float)) or isinstance(dt, bool) or not math.isfinite(dt) or dt < 0:
            raise ValueError("Elapsed time must be a nonnegative finite number.")
        self.simulation.update(dt)

    def advance_clock(self, real_dt):
        self.clock.advance(real_dt)

    def set_opening(self, name, opened):
        opening = self.openings.get(name)
        if opening is None:
            raise ValueError("Unknown opening.")
        opening.set_open(opened)
        return opening

    def _refresh_power(self):
        for room in self.rooms.values():
            room.light.update()
            if room.air_conditioner is not None:
                room.air_conditioner.update(0)
        self.irrigation.update()
        self.openings["garage_door"].mark_dirty()

    def handle_command(self, topic, payload):
        command = self.parser.parse(topic, payload)
        device = self.devices.get((command.area, command.device))
        if device is None:
            raise ValueError("Unknown device.")
        if command.action == "config":
            device.configure(command.value)
        elif isinstance(device, Sensor):
            raise ValueError("Sensors are read-only. Change the local simulation instead.")
        elif isinstance(device, Opening):
            device.set_open(command.value)
        elif isinstance(device, (Light, AirConditioner, CircuitBreaker, IrrigationSystem)):
            device.set_enabled(self.parser.boolean(command.value))
        else:
            raise ValueError("This device does not accept action commands.")
        if device is self.breaker:
            self._refresh_power()

    def telemetry(self):
        values = {f"house/{area}/{name}/state": json.dumps(device.state(), separators=(",", ":"), allow_nan=False)
                  for (area, name), device in self.devices.items()}
        values["house/clock/state"] = json.dumps(self.clock.state(), separators=(",", ":"))
        return values

    def publications(self, dt=0.0, force=False):
        if not isinstance(dt, (int, float)) or isinstance(dt, bool) or not math.isfinite(dt) or dt < 0:
            raise ValueError("Elapsed time must be a nonnegative finite number.")
        values = {f"house/{area}/{name}/state": json.dumps(device.state(), separators=(",", ":"), allow_nan=False)
                  for (area, name), device in self.devices.items() if device.publication_due(dt, force)}
        if self.clock.publication_due(force):
            values["house/clock/state"] = json.dumps(self.clock.state(), separators=(",", ":"))
        return values
