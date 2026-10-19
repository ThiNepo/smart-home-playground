# MQTT Reference

[Back to the project README](../README.md).

Run student examples from the cloned repository. The teacher provides the
current public URL and shared credentials from the connection panel. All
students share the MQTT account and can subscribe and publish to `house/#`.
Each client uses a unique connection ID.

| Transport | Endpoint | Use |
| --- | --- | --- |
| MQTT/TCP | `mqtt://127.0.0.1:18883` | Python clients on the host computer |
| MQTT/WebSocket | `ws://127.0.0.1:19001/mqtt` | WebSocket clients on the host computer |
| MQTT/WSS | `wss://HOST.trycloudflare.com/mqtt` | Remote students through the public tunnel |

Local clients use TCP or WebSocket on localhost. Remote students connect
their MQTT clients to the public WSS endpoint.

Students read sensor states, configure devices, and send commands to
actuators. The local simulation generates sensor inputs and the clock.

Every addressable device publishes retained JSON state on:

```text
house/<area>/<device>/state
```

The state contains its current `value` and applied `config`. For example,
a moisture sensor reports its sampled reading and independent intervals:

```json
{
  "value": 54.45,
  "config": {"publish_interval": 5.0, "read_interval": 1.0}
}
```

A contact sensor's boolean `value` is `true` when fully closed and `false`
when open or moving.

### Sensor readings

| Area | Sensor | Reading |
| --- | --- | --- |
| `living_room`, `kitchen`, `bedroom`, `garage` | `temperature` | Sampled temperature, in degrees C |
| `garage` | `motion` | Boolean motion reading |
| `garage` | `car_presence` | Boolean vehicle-presence reading |
| `garden` | `moisture` | Sampled soil moisture, from 0 to 100 |
| `living_room`, `garage`, `laundry` | `door_contact` | Boolean fully-closed reading |
| `bedroom` | `window_contact` | Boolean fully-closed reading |

For example, subscribe to `house/garden/moisture/state` or
`house/garage/car_presence/state`. Sensors sample their simulated inputs at
the configured reading interval.

The house publishes its clock on:

```text
house/clock/state
```

```json
{"value": "08:15"}
```

The clock uses `HH:MM` and wraps at midnight. Its settings are in
[config/simulation.json](../config/simulation.json).

### Actuator commands

Actions use `house/<area>/<device>/set`:

| Area | Actuator | Payload |
| --- | --- | --- |
| `power` | `breaker` | `ON` / `OFF` |
| `living_room`, `kitchen`, `bedroom`, `bathroom`, `laundry`, `hall`, `garage` | `light` | `ON` / `OFF` |
| `living_room`, `kitchen`, `bedroom`, `garage` | `air_conditioner` | `ON` / `OFF` |
| `garden` | `irrigation` | `ON` / `OFF` |
| `garage` | `door` | `OPEN` / `CLOSE` |

Boolean actions also accept JSON booleans, `1` / `0`, and
`{"value": true}`. Manual doors and the bedroom window are operated locally
in the scene.

A motor command requests a destination. Its state reports the movement's
physical progress:

```json
{
  "value": "OPENING",
  "position": 0.4,
  "target_open": true,
  "contact_closed": false,
  "moving": true,
  "config": {"publish_interval": 2.0}
}
```

Garage `position` ranges from 0 (closed) to 1 (open), while `target_open`
is the requested destination. `value` is `CLOSED`, `OPENING`, `OPEN`, or
`CLOSING`. The separate `house/garage/door_contact/state` is a sampled
sensor reading. Vehicle presence is a separate sensor.

### Device configuration

Use a separate topic to configure a real device:

```text
house/<area>/<device>/config/set
```

| Device | MQTT configuration fields |
| --- | --- |
| Every sensor | `read_interval`: 0.1 to 60 real seconds; `publish_interval`: 0.1 to 300 real seconds |
| Every actuator | `publish_interval`: 0.1 to 300 real seconds |
| Air conditioner | Also `setpoint`: 16 to 30 degrees C; `mode`: `AUTO`, `COOL`, `HEAT`, `FAN` |

Reading and publishing are independent. `read_interval` controls when a
sensor samples its input. `publish_interval` schedules MQTT messages,
including repeated unchanged readings. Configuration confirmations and
important actuator transitions can publish sooner.

To sample soil moisture every second and publish every five seconds:

```text
Topic:   house/garden/moisture/config/set
Payload: {"read_interval": 1, "publish_interval": 5}
```

To configure the bedroom air conditioner:

```text
Topic:   house/bedroom/air_conditioner/config/set
Payload: {"setpoint": 22, "mode": "COOL"}
```

The device's `/state` message confirms its applied settings. Configuration
errors appear in the application's activity feed. Environment settings are
in [config/simulation.json](../config/simulation.json). Students implement
automation in their own Python programs by reading sensors and commanding
actuators.

### Use the reusable Python client

```python
import getpass
from examples.student import StudentClient


class ClassroomExercise:
    @classmethod
    def run(cls):
        password = getpass.getpass("MQTT password: ")
        client = StudentClient(
            "wss://YOUR-CLASSROOM.trycloudflare.com/mqtt",
            "classroom",
            password,
        )
        try:
            client.connect()
            client.configure("garden", "moisture", read_interval=1, publish_interval=5)
            client.configure("bedroom", "air_conditioner", setpoint=22, mode="COOL")
            client.set("bedroom", "air_conditioner", "ON")
            client.set("garage", "door", "OPEN")
            client.observe(6)
            print(client.state("garden", "moisture"))
            print(client.state("clock"))
        finally:
            client.close()


if __name__ == "__main__":
    ClassroomExercise.run()
```

The client subscribes to `house/+/+/state`, `house/clock/state`, and
`house/status` by default. Its `set()` method sends actuator commands, and
`configure()` updates device settings.

`house/status` reports `online` or `offline`. State messages use QoS 1 and
are retained, giving new subscribers the most recently published snapshot.
Send commands with `retain=False`. All students control the same house,
with the last processed command taking effect.

Device configuration is held in memory and resets to startup defaults on
restart. Sampling and publication defaults come from
[config/simulation.json](../config/simulation.json); AC setpoint and mode
default to `22` and `COOL`. Clock settings, environment rates, motion timeout,
and movement duration belong to the local configuration file.

`StudentClient.state()` returns the last received state, or `None` before one
arrives. `observe()` keeps the program alive while its network thread receives
messages.
