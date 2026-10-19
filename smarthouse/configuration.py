"""Typed local settings for simulation timing and physical environment presets."""
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re


class SettingsValidation:
    @staticmethod
    def group(data, fields, name):
        if not isinstance(data, dict) or set(data) != set(fields):
            raise ValueError(f"{name} must contain exactly: {', '.join(fields)}.")
        return data

    @staticmethod
    def number(value, name, minimum, maximum):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a JSON number.")
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be between {minimum} and {maximum}.")
        return float(value)

    @staticmethod
    def boolean(value, name):
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a JSON boolean.")
        return value

    @staticmethod
    def time(value):
        if not isinstance(value, str) or re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) is None:
            raise ValueError("Clock start_time must use the 24-hour HH:MM format.")
        return value

    @staticmethod
    def reject_constant(value):
        raise ValueError(f"Nonfinite JSON number is not allowed: {value}.")


@dataclass(frozen=True)
class ClockSettings:
    real_seconds_per_day: float
    start_time: str
    publish_interval_minutes: float

    @classmethod
    def from_dict(cls, data):
        SettingsValidation.group(data, cls.__dataclass_fields__, "Clock settings")
        return cls(SettingsValidation.number(data["real_seconds_per_day"], "Real seconds per day", 1, 86400),
                   SettingsValidation.time(data["start_time"]),
                   SettingsValidation.number(data["publish_interval_minutes"], "Clock publish interval", 0.1, 1440))


@dataclass(frozen=True)
class DeviceSettings:
    read_interval: float
    publish_interval: float

    @classmethod
    def from_dict(cls, data):
        SettingsValidation.group(data, cls.__dataclass_fields__, "Device defaults")
        return cls(SettingsValidation.number(data["read_interval"], "Read interval", 0.1, 60),
                   SettingsValidation.number(data["publish_interval"], "Publish interval", 0.1, 300))


@dataclass(frozen=True)
class EnvironmentSettings:
    initial_moisture: float
    drying_rate: float
    watering_rate: float
    initial_temperature: float
    ambient_temperature: float
    ambient_rate: float
    conditioning_rate: float
    car_present: bool
    motion_timeout: float

    @classmethod
    def from_dict(cls, data):
        SettingsValidation.group(data, cls.__dataclass_fields__, "Environment settings")
        return cls(SettingsValidation.number(data["initial_moisture"], "Initial moisture", 0, 100),
                   SettingsValidation.number(data["drying_rate"], "Drying rate", 0, 100),
                   SettingsValidation.number(data["watering_rate"], "Watering rate", 0, 100),
                   SettingsValidation.number(data["initial_temperature"], "Initial temperature", -20, 60),
                   SettingsValidation.number(data["ambient_temperature"], "Ambient temperature", -20, 60),
                   SettingsValidation.number(data["ambient_rate"], "Ambient temperature rate", 0, 10),
                   SettingsValidation.number(data["conditioning_rate"], "Conditioning rate", 0, 10),
                   SettingsValidation.boolean(data["car_present"], "Car present"),
                   SettingsValidation.number(data["motion_timeout"], "Motion timeout", 0.1, 300))


@dataclass(frozen=True)
class OpeningSettings:
    manual_travel_time: float
    window_travel_time: float
    garage_travel_time: float

    @classmethod
    def from_dict(cls, data):
        SettingsValidation.group(data, cls.__dataclass_fields__, "Opening settings")
        return cls(*(SettingsValidation.number(data[name], name.replace("_", " ").title(), 0.2, 10)
                     for name in cls.__dataclass_fields__))


@dataclass(frozen=True)
class SimulationConfiguration:
    clock: ClockSettings
    devices: DeviceSettings
    environment: EnvironmentSettings
    openings: OpeningSettings

    @classmethod
    def from_dict(cls, data):
        SettingsValidation.group(data, cls.__dataclass_fields__, "Simulation configuration")
        return cls(ClockSettings.from_dict(data["clock"]), DeviceSettings.from_dict(data["devices"]),
                   EnvironmentSettings.from_dict(data["environment"]), OpeningSettings.from_dict(data["openings"]))

    @classmethod
    def load(cls, path=None):
        location = Path(path) if path is not None else Path(__file__).resolve().parent.parent / "config" / "simulation.json"
        try:
            data = json.loads(location.read_text(encoding="utf-8"), parse_constant=SettingsValidation.reject_constant)
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to read simulation configuration at {location}: {error}") from error
        return cls.from_dict(data)

    def to_dict(self):
        return asdict(self)
