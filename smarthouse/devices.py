"""Modular simulated devices with validated configuration and independent clocks."""
from abc import ABC, abstractmethod
import math


class DeviceValidation:
    @staticmethod
    def number(value, name, minimum, maximum):
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a number.")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"{name} must be a finite number.") from error
        if not math.isfinite(result) or not minimum <= result <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return result

    @staticmethod
    def boolean(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.upper() in ("ON", "OFF", "TRUE", "FALSE", "0", "1"):
            return value.upper() in ("ON", "TRUE", "1")
        raise ValueError("Send ON/OFF, true/false, or 1/0.")


class Device(ABC):
    """An addressable device that owns its state and publication schedule."""

    def __init__(self):
        self._config = {"publish_interval": 2.0}
        self._publication_elapsed = 0.0
        self._dirty = True

    @property
    def config(self):
        return dict(self._config)

    def _validated_config(self, candidate):
        result = dict(candidate)
        result["publish_interval"] = DeviceValidation.number(result["publish_interval"], "Publish interval", 0.1, 300)
        return result

    def configure(self, changes):
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Configuration must be a nonempty JSON object.")
        unknown = set(changes) - set(self._config)
        if unknown:
            raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}.")
        candidate = dict(self._config)
        candidate.update(changes)
        validated = self._validated_config(candidate)
        self._config = validated
        self._publication_elapsed = 0.0
        self.mark_dirty()
        self._configuration_applied()

    def _configuration_applied(self):
        pass

    def mark_dirty(self):
        self._dirty = True

    def publication_due(self, dt=0.0, force=False):
        self._publication_elapsed += dt
        if force or self._dirty:
            self._publication_elapsed = 0.0
            self._dirty = False
            return True
        interval = self._config["publish_interval"]
        periods = math.floor((self._publication_elapsed + 1e-9) / interval)
        if periods:
            self._publication_elapsed = max(0.0, self._publication_elapsed - periods * interval)
            return True
        return False

    @abstractmethod
    def state(self):
        raise NotImplementedError


class Sensor(Device):
    """A sampled sensor, separate from its continuously simulated physical input."""

    def __init__(self, initial):
        super().__init__()
        self._config["read_interval"] = 1.0
        self._physical_value = initial
        self._value = initial
        self._read_elapsed = 0.0
        self.samples = 1

    @property
    def value(self):
        return self._value

    @property
    def physical_value(self):
        return self._physical_value

    def read(self):
        return self.value

    def sample(self):
        self._value = self._physical_value
        self.samples += 1

    def update(self, dt):
        self._read_elapsed += dt
        interval = self._config["read_interval"]
        periods = math.floor((self._read_elapsed + 1e-9) / interval)
        if periods:
            self._read_elapsed = max(0.0, self._read_elapsed - periods * interval)
            self.sample()

    def _validated_config(self, candidate):
        result = super()._validated_config(candidate)
        result["read_interval"] = DeviceValidation.number(result["read_interval"], "Read interval", 0.1, 60)
        return result

    def _configuration_applied(self):
        self._read_elapsed = 0.0

    def state(self):
        return {"value": self.value, "config": self.config}


class BooleanSensor(Sensor):
    def __init__(self, initial=False):
        super().__init__(bool(initial))

    def inject(self, value):
        self._physical_value = DeviceValidation.boolean(value)

    def set_physical(self, value):
        self._physical_value = bool(value)


class ContactSensor(BooleanSensor):
    """True means the monitored opening is fully closed."""

    def __init__(self):
        super().__init__(True)

    def sample(self):
        previous = self.value
        super().sample()
        if self.value != previous:
            self.mark_dirty()


class CarPresenceSensor(BooleanSensor):
    """Vehicle occupancy is independent from the garage door and motion sensor."""


class MotionSensor(BooleanSensor):
    def __init__(self, timeout=8.0):
        super().__init__(False)
        self._timeout = DeviceValidation.number(timeout, "Motion timeout", 0.1, 300)
        self.remaining = 0.0

    @property
    def timeout(self):
        return self._timeout

    def detect(self, active):
        active = DeviceValidation.boolean(active)
        self.remaining = self.timeout if active else 0.0
        self.inject(active)

    def update(self, dt):
        remaining = self.remaining - dt
        self.remaining = remaining if remaining > 1e-9 else 0.0
        self.set_physical(self.remaining > 0)
        super().update(dt)


class NumericSensor(Sensor):
    def __init__(self, initial, minimum, maximum, name):
        self.minimum = minimum
        self.maximum = maximum
        self.name = name
        super().__init__(DeviceValidation.number(initial, name, minimum, maximum))

    def inject(self, value):
        self._physical_value = DeviceValidation.number(value, self.name, self.minimum, self.maximum)

    def state(self):
        result = super().state()
        result["value"] = round(result["value"], 2)
        return result


class SoilMoistureSensor(NumericSensor):
    def __init__(self, initial=55.0, drying_rate=0.55, watering_rate=5.0):
        super().__init__(initial, 0, 100, "Soil moisture")
        self.drying_rate = drying_rate
        self.watering_rate = watering_rate

    def update(self, dt, watering=False):
        rate = self.watering_rate if watering else -self.drying_rate
        self._physical_value = min(100.0, max(0.0, self._physical_value + rate * dt))
        super().update(dt)


class TemperatureSensor(NumericSensor):
    def __init__(self, initial=24.0):
        super().__init__(initial, -20, 60, "Temperature")

    def advance(self, dt, target=26.0, conditioning=False, ambient_rate=0.025, conditioning_rate=0.3):
        rate = conditioning_rate if conditioning else ambient_rate
        distance = target - self._physical_value
        self._physical_value += math.copysign(min(abs(distance), dt * rate), distance)
        super().update(dt)


class CircuitBreaker(Device):
    def __init__(self, enabled=True):
        super().__init__()
        self.enabled = bool(enabled)

    @property
    def is_on(self):
        return self.enabled

    def set_enabled(self, enabled):
        self.enabled = DeviceValidation.boolean(enabled)
        self.mark_dirty()

    def state(self):
        return {"value": "ON" if self.enabled else "OFF", "config": self.config}


class Light(Device):
    """A light changes only in response to an explicit control command."""

    def __init__(self, power):
        super().__init__()
        self.power = power
        self.requested_on = False
        self._previous_on = self.is_on

    @property
    def is_on(self):
        return self.power.enabled and self.requested_on

    def set_enabled(self, enabled):
        self.requested_on = DeviceValidation.boolean(enabled)
        self.mark_dirty()

    def update(self):
        if self._previous_on != self.is_on:
            self._previous_on = self.is_on
            self.mark_dirty()

    def state(self):
        return {"value": "ON" if self.is_on else "OFF", "requested_on": self.requested_on,
                "config": self.config}


class AirConditioner(Device):
    MODES = ("AUTO", "COOL", "HEAT", "FAN")

    def __init__(self, power, environment=None):
        super().__init__()
        self.power = power
        self.enabled = False
        self.ambient_temperature = environment.ambient_temperature if environment else 26.0
        self.ambient_rate = environment.ambient_rate if environment else 0.025
        self.conditioning_rate = environment.conditioning_rate if environment else 0.3
        self.temperature = TemperatureSensor(environment.initial_temperature if environment else 24.0)
        self._config.update({"setpoint": 22.0, "mode": "COOL"})
        self._previous_on = self.is_on

    @property
    def is_on(self):
        return self.power.enabled and self.enabled

    @property
    def setpoint(self):
        return self._config["setpoint"]

    @property
    def mode(self):
        return self._config["mode"]

    def set_enabled(self, enabled):
        self.enabled = DeviceValidation.boolean(enabled)
        self.mark_dirty()

    def _validated_config(self, candidate):
        result = super()._validated_config(candidate)
        result["setpoint"] = DeviceValidation.number(result["setpoint"], "Temperature setpoint", 16, 30)
        if not isinstance(result["mode"], str) or result["mode"].upper() not in self.MODES:
            raise ValueError("Mode must be AUTO, COOL, HEAT, or FAN.")
        result["mode"] = result["mode"].upper()
        return result

    def update(self, dt):
        current = self.temperature.physical_value
        active = self.is_on and self.mode != "FAN"
        target = self.setpoint if active else self.ambient_temperature
        if active and self.mode == "COOL":
            target = min(current, target)
        elif active and self.mode == "HEAT":
            target = max(current, target)
        self.temperature.advance(dt, target, active, self.ambient_rate, self.conditioning_rate)
        if self._previous_on != self.is_on:
            self._previous_on = self.is_on
            self.mark_dirty()

    def state(self):
        return {"value": "ON" if self.is_on else "OFF", "enabled": self.enabled,
                "temperature": round(self.temperature.value, 2), "setpoint": self.setpoint,
                "mode": self.mode, "config": self.config}


class Opening(Device):
    """An opening has a requested destination and a separately animated physical state."""

    def __init__(self, name, power=None, travel_time=1.0, monitored=True):
        super().__init__()
        self.name = name
        self.power = power
        self.position = 0.0
        self.target_open = False
        self.contact = ContactSensor() if monitored else None
        self.travel_time = DeviceValidation.number(travel_time, "Travel time", 0.2, 10)
        self._previous_status = self.status

    @property
    def status(self):
        if self.position <= 0.0 and not self.target_open:
            return "CLOSED"
        if self.position >= 1.0 and self.target_open:
            return "OPEN"
        return "OPENING" if self.target_open else "CLOSING"

    @property
    def is_open(self):
        return self.position >= 1.0

    @property
    def moving(self):
        return self.position != float(self.target_open) and (self.power is None or self.power.enabled)

    def set_open(self, opened):
        if isinstance(opened, str) and opened.upper() in ("OPEN", "CLOSE", "CLOSED"):
            opened = opened.upper() == "OPEN"
        else:
            opened = DeviceValidation.boolean(opened)
        self.target_open = opened
        self.mark_dirty()

    def set_enabled(self, enabled):
        self.set_open(enabled)

    def update(self, dt):
        if self.moving:
            direction = 1.0 if self.target_open else -1.0
            self.position = max(0.0, min(1.0, self.position + direction * dt / self.travel_time))
            if abs(self.position - float(self.target_open)) < 1e-9:
                self.position = float(self.target_open)
        if self.contact is not None:
            self.contact.set_physical(self.position == 0.0)
            self.contact.update(dt)
        if self.status != self._previous_status:
            self._previous_status = self.status
            self.mark_dirty()

    def state(self):
        return {"value": self.status, "position": round(self.position, 4), "target_open": self.target_open,
                "contact_closed": self.position == 0.0, "moving": self.moving, "config": self.config}


class Room:
    def __init__(self, name, power, motion_sensor=None, air_conditioned=False, environment=None):
        self.name = name
        self.motion_sensor = motion_sensor
        self.light = Light(power)
        self.air_conditioner = AirConditioner(power, environment) if air_conditioned else None

    def set_light(self, enabled):
        self.light.set_enabled(enabled)

    def update(self, dt=0.0):
        self.light.update()
        if self.air_conditioner is not None:
            self.air_conditioner.update(dt)


class IrrigationSystem(Device):
    """The irrigation actuator has no built-in moisture policy."""

    def __init__(self, power, moisture_sensor=None):
        super().__init__()
        self.power = power
        self.moisture_sensor = moisture_sensor
        self.requested_on = False
        self._previous_on = self.is_on

    @property
    def is_on(self):
        return self.power.enabled and self.requested_on

    def set_manual(self, enabled):
        self.set_enabled(enabled)

    def set_enabled(self, enabled):
        self.requested_on = DeviceValidation.boolean(enabled)
        self.mark_dirty()

    def update(self):
        if self._previous_on != self.is_on:
            self._previous_on = self.is_on
            self.mark_dirty()

    def state(self):
        return {"value": "ON" if self.is_on else "OFF", "requested_on": self.requested_on,
                "config": self.config}
