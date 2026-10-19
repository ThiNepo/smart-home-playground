# Smart House Lab

An object-oriented Python playground for exploring a smart home through a
2D floor plan, animated devices, sensor readings, and MQTT. The house
and every student share one MQTT account. Source code, comments, interface
text, and documentation are English.

## Start on Windows

Requirements: Python 3.11+ and Docker Desktop running with Linux containers.

```powershell
.\Start.ps1
```

Startup prepares `.venv`, installs the dependencies, starts an authenticated
Mosquitto broker, and opens a public Cloudflare Quick Tunnel. The program
checks a real MQTT login before announcing the public WSS address. The
connection details appear in the right panel and `.runtime/connection.json`.

The shared username is `classroom`. The password is six random alphanumeric
characters and persists in `.runtime/credentials.json`. An older long
password is replaced with the six-character format at the next startup;
students must then use the new password shown in the application.

Quick Tunnels require no account or domain. Their hostname changes between
sessions, and they have no uptime guarantee. Startup waits up to 90 seconds
for public DNS and MQTT. If the tunnel is unavailable, the house continues
with local MQTT and reports the reason in its activity feed.

Other startup modes:

```powershell
.\Start.ps1 -Local    # Docker and local MQTT, without a public tunnel
.\Start.ps1 -Offline  # The visual simulation, without Docker or networking
```

If PowerShell blocks scripts, use Python directly:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Closing the window or pressing Ctrl+C stops this application's containers
and tunnel. If the process is forcibly terminated, clean up its stack with:

```powershell
docker compose -p smart-house-demo --profile remote down
```

## Explore the playground

The 1920 x 1080 reference layout places a continuous 2D house plan beside a
wide right-hand control panel. The window opens maximized to fit the desktop,
can be resized, and keeps the plan proportions. Long endpoints wrap within
the panel; Copy connection preserves the full address. The
front entrance opens directly into the living room; the kitchen and hall
connect the other rooms. The garden is behind the house, and the garage
faces a clear front driveway.

- Every indoor room has an independent light, including the bathroom,
  laundry, and hall. Illumination changes across the room when it is lit.
- The living room, kitchen, bedroom, and garage have air conditioning.
  The bathroom, laundry, and hall do not.
- Front, rear, and interior doors and the bedroom window can be opened
  locally in the scene. They are manual physical objects, without remote
  door or window actuator topics. Contact sensors monitor the front door,
  rear laundry door, bedroom window, and garage door.
- The garage door is motorized and accepts remote open/close commands.
  Door position, vehicle presence, and garage motion are independent.
- Irrigation waters both raised beds. Soil dries gradually and its sampled
  moisture is published. Lights and watering only change when commanded;
  motion and dry soil do not trigger built-in automation.
- Main power affects lights, air conditioners, irrigation, and the garage
  motor. Sensors and the simulation clock continue when power is off.
- The right panel presents the selected device's controls, readings, and
  real device settings. Local simulation controls change the environment
  used to generate readings. Students receive those readings through MQTT.
- Classroom access can be paused while local interaction and telemetry
  continue. Students can implement their own control logic in Python.

The header clock shows time only, without a day or date. By default one
24-hour simulation cycle takes 240 real seconds. The read-only clock topic
publishes once per simulated minute, approximately six messages per real
second. Sensor sampling, device publication intervals, motion timeouts,
physical movement, and environment rates continue to use real seconds.

## Local simulation configuration

`config/simulation.json` configures the simulation before startup:

| Group | Settings |
| --- | --- |
| `clock` | `real_seconds_per_day` (240), `start_time` (`08:00`), `publish_interval_minutes` (1) |
| `devices` | Default `read_interval` (1) and `publish_interval` (2), in real seconds |
| `environment` | Initial moisture and temperature, soil drying/watering rates, ambient temperature and rates, initial car presence, motion timeout |
| `openings` | Manual door, window, and garage travel times, in real seconds |

These clock and physical environment settings belong to the local
configuration file. They are not MQTT device configuration fields.
Configuration is validated before the application starts; restart the
application after changing the file.

## Connect a student program

Students on other computers use the public `wss://HOST/mqtt` URL provided
by the teacher, the username `classroom`, and the shared password. Each
student connection has a unique client ID, so shared credentials do not
cause clients to disconnect one another.

```powershell
python -m pip install paho-mqtt==2.1.0
python examples/student.py --url wss://YOUR-CLASSROOM.trycloudflare.com/mqtt --user classroom --topic house/living_room/light/set --value ON
```

The example prompts for the password, sends the command, and prints incoming
messages for 30 seconds. The MQTT endpoint is for MQTT clients; it is not a
web control page.

`StudentClient` also supports native MQTT on the host computer:

| Transport | Local URL | Intended use |
| --- | --- | --- |
| Native MQTT/TCP | `mqtt://127.0.0.1:18883` | The house and local Python programs |
| MQTT over WebSocket | `ws://127.0.0.1:19001/mqtt` | Local WebSocket clients |
| MQTT over secure WebSocket | Public `wss://HOST/mqtt` | Remote students through the tunnel |

The Docker ports bind to localhost. Remote students use WSS rather than the
host's `127.0.0.1` addresses. WSS and TCP carry the same MQTT topics and
payloads; WSS is used remotely because the current public tunnel carries
HTTP/WebSocket traffic. The client additionally accepts `mqtts://` for a
separately configured native TLS broker; this demo does not expose one.

## MQTT device contract

Students subscribe to readings and send commands to actuators. They cannot
publish sensor input values or change the simulation clock through the
application's command API.

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

The underlying simulated input is not included in telemetry. A contact
sensor's boolean `value` is `true` when fully closed and `false` when open
or moving.

### Read-only topics

| Area | Sensor | Reading |
| --- | --- | --- |
| `living_room`, `kitchen`, `bedroom`, `garage` | `temperature` | Sampled temperature, in degrees C |
| `garage` | `motion` | Boolean motion reading |
| `garage` | `car_presence` | Boolean vehicle-presence reading |
| `garden` | `moisture` | Sampled soil moisture, from 0 to 100 |
| `living_room`, `garage`, `laundry` | `door_contact` | Boolean fully-closed reading |
| `bedroom` | `window_contact` | Boolean fully-closed reading |

For example, subscribe to `house/garden/moisture/state` or
`house/garage/car_presence/state`. All sensor `/set` requests are rejected.
Sensor values are generated by the local simulation and sampled at the
configured interval.

The clock uses its own read-only topic:

```text
house/clock/state
```

```json
{"value": "08:15"}
```

The clock exposes no MQTT setter or configuration topic. It wraps at
midnight without adding a day or date.

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
`{"value": true}`. Front, rear, and interior manual doors and the bedroom
window have no remote actuator topics.

A motor command requests a destination. Its state reports physical progress
rather than immediately confirming the destination:

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
sensor reading. Opening the garage does not imply that a vehicle appears
or leaves.

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
important actuator transitions can publish sooner. Local environment
changes do not bypass the sensor's sampling clock.

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

The device's `/state` message confirms its applied settings. Invalid
configuration is rejected as a whole and reported in the application's
activity feed. The previous settings remain applied. There are no MQTT
`automatic`, moisture threshold, motion timeout, or movement-speed fields.
Students can implement automation in their own Python programs by reading
sensors and commanding actuators.

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
`house/status` by default. Its command helpers and CLI reject sensor
setters, manual-opening setters, and simulation-only configuration fields.
Custom MQTT clients are also validated by the house when requests arrive.

`house/status` reports `online` or `offline`. State messages use QoS 1 and
are retained, giving new subscribers the most recently published snapshot.
Commands must use `retain=False`; stale retained commands are ignored after
subscribing or reconnecting. All students control the same house, with the
last valid processed command taking effect. Concurrent classroom capacity
has not been load-tested.

## Object model

`SmartHouse` composes `Room` instances and an addressable device registry.
Each `Device` owns its configuration and publication schedule. `Sensor`
adds an independent sampling clock. `SimulationController` changes local
environment inputs, and the simulation clock supplies the read-only time. Concrete classes implement lights,
air conditioners, openings and their contacts, motion, temperature, soil
moisture, vehicle presence, irrigation, and the circuit breaker.

`SmartHouseApplication` applies both local and remote commands through the
same model. `SmartHouseWindow` and `FloorPlanView` render the simulation;
network callbacks only queue commands. `MqttController` manages MQTT,
`DockerInfrastructure` manages this application's stack, and `StudentClient`
is the reusable student-facing Python client.

Implemented previews: [1920 x 1080](design/playground-v2.png) and
[compact layout](design/playground-v2-compact.png). The compact preview uses
illustrative connection details.

## Tests and preview

The tests use pytest. The default suite does not need Docker:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Graphical checks require a working display:

```powershell
.\.venv\Scripts\python.exe -m pytest -m gui -q
```

Real MQTT integration tests use their own temporary runtime, free localhost
ports, and unique Docker Compose project. They do not replace the running
application's credentials or shut down its stack:

```powershell
.\.venv\Scripts\python.exe -m pytest -m integration -q
```

Optionally test a real public WSS connection as well:

```powershell
$env:SMART_HOUSE_REMOTE_TEST = '1'
.\.venv\Scripts\python.exe -m pytest -m integration -q -s
Remove-Item Env:\SMART_HOUSE_REMOTE_TEST
```

The network tests cover shared credentials, unique clients, WebSocket and
native TCP clients, command/state round trips, configuration confirmation,
periodic readings, independent sampling, local simulation readings,
read-only sensor and clock enforcement, garage movement, vehicle presence,
power, classroom pause, rejected passwords, and stale retained commands.

Render a hidden preview frame:

```powershell
.\.venv\Scripts\python.exe main.py --offline --screenshot .runtime/preview.png
```

## References

- [Pyglet](https://docs.pyglet.org/en/latest/programming_guide/quickstart.html)
- [Paho MQTT](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html)
- [Mosquitto configuration](https://mosquitto.org/man/mosquitto-conf-5.html)
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- [pytest](https://docs.pytest.org/en/stable/)
