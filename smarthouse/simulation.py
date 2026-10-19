"""Local scenario inputs and a repeating classroom clock, separate from MQTT controls."""
import math
from smarthouse.devices import BooleanSensor, ContactSensor, DeviceValidation, MotionSensor, NumericSensor


class SimulationClock:
    """Advance a time of day without publishing a date or simulation internals."""

    def __init__(self, settings):
        self._settings = settings
        hours, minutes = map(int, settings.start_time.split(":"))
        self._start_minutes = hours * 60 + minutes
        self._elapsed_minutes = 0.0
        self._publication_elapsed = 0.0
        self._dirty = True

    @property
    def time_text(self):
        minute = math.floor(self._start_minutes + self._elapsed_minutes + 1e-9) % 1440
        return f"{minute // 60:02d}:{minute % 60:02d}"

    def advance(self, real_dt):
        seconds = DeviceValidation.number(real_dt, "Elapsed time", 0, 1e12)
        simulated_minutes = seconds * 1440 / self._settings.real_seconds_per_day
        self._elapsed_minutes = (self._elapsed_minutes + simulated_minutes) % 1440
        self._publication_elapsed += simulated_minutes

    def state(self):
        return {"value": self.time_text}

    def publication_due(self, force=False):
        if force or self._dirty:
            self._publication_elapsed = 0.0
            self._dirty = False
            return True
        interval = self._settings.publish_interval_minutes
        periods = math.floor((self._publication_elapsed + 1e-9) / interval)
        if periods:
            self._publication_elapsed = max(0.0, self._publication_elapsed - periods * interval)
            return True
        return False


class SimulationController:
    """Local-only inputs change the environment; students receive measured sensor data."""

    def __init__(self, house):
        self.house = house

    def set_sensor(self, area, device, value):
        sensor = self.house.devices.get((area, device))
        if isinstance(sensor, ContactSensor):
            raise ValueError("Contact sensors follow their physical opening.")
        if isinstance(sensor, MotionSensor):
            sensor.detect(DeviceValidation.boolean(value))
        elif isinstance(sensor, (BooleanSensor, NumericSensor)):
            sensor.inject(value)
        else:
            raise ValueError("Unknown simulated sensor.")
        return sensor

    def set_opening(self, name, opened):
        return self.house.set_opening(name, opened)

    def update(self, dt):
        self.house.motion_sensor.update(dt)
        self.house.car_sensor.update(dt)
        for opening in self.house.openings.values():
            opening.update(dt)
        for room in self.house.rooms.values():
            room.update(dt)
        self.house.irrigation.update()
        self.house.moisture_sensor.update(dt, watering=self.house.irrigation.is_on)
