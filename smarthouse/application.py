"""python main.py | --local | --offline | --headless --duration 10"""
import argparse
from queue import Empty
import sys
import time
from smarthouse.model import SmartHouse
from smarthouse.configuration import SimulationConfiguration


class SmartHouseApplication:
    def __init__(self, messaging=None, infrastructure=None, configuration=None):
        self.house = SmartHouse(configuration)
        self.messaging = messaging
        self.infrastructure = infrastructure
        self.students_enabled = True
        self.elapsed = 0.0
        self.events = []

    def log(self, text):
        if self.messaging:
            self.messaging.log(text)
        else:
            self.events.insert(0, (time.strftime("%H:%M:%S"), text))
            del self.events[100:]

    def command(self, topic, payload, source="LOCAL"):
        try:
            self.house.handle_command(topic, payload)
            self.log(f"{source}  {topic}  {payload}")
            return True
        except (ValueError, TypeError, OverflowError) as exc:
            self.log(f"REJECTED  {topic}: {exc}")
            return False

    def tick(self, dt):
        if self.messaging:
            for _ in range(100):
                try:
                    topic, payload = self.messaging.commands.get_nowait()
                except Empty:
                    break
                if self.students_enabled:
                    self.command(topic, payload, "MQTT")
                else:
                    self.log("Classroom command ignored: controls are paused.")
        elapsed = float(dt)
        if not 0 <= elapsed < float("inf"):
            raise ValueError("Elapsed time must be a nonnegative finite number.")
        self.house.advance_clock(elapsed)
        simulation_elapsed = min(elapsed, 2.0)
        remaining = simulation_elapsed
        while remaining > 0.000001:
            step = min(remaining, 0.05)
            self.house.update(step)
            remaining -= step
        self.elapsed += elapsed
        force = bool(self.messaging and self.messaging.connected and self.messaging.snapshot_required)
        values = self.house.publications(elapsed, force=force)
        if self.messaging:
            self.messaging.publish(values, force=True)


    @classmethod
    def run_from_cli(cls):
        parser = argparse.ArgumentParser(description="Smart House Lab — interactive MQTT demo")
        parser.add_argument("--local", action="store_true", help="Local MQTT without a public tunnel")
        parser.add_argument("--offline", action="store_true", help="Simulation only, without Docker or networking")
        parser.add_argument("--headless", action="store_true", help="Run the simulation without a window")
        parser.add_argument("--duration", type=float, default=0, help="Exit after N seconds (0 = unlimited)")
        parser.add_argument("--screenshot", help="Save a rendered UI frame and exit")
        args = parser.parse_args()
        infrastructure = messaging = None
        try:
            configuration = SimulationConfiguration.load()
            if not args.offline:
                from smarthouse.infrastructure import DockerInfrastructure
                from smarthouse.messaging import MqttController
                print("Preparing MQTT in Docker...", flush=True)
                infrastructure = DockerInfrastructure(remote=not args.local)
                infrastructure.start()
                messaging = MqttController(infrastructure.credentials)
                messaging.start()
            demo = cls(messaging, infrastructure, configuration=configuration)
            if infrastructure and infrastructure.notice:
                demo.log(infrastructure.notice)
            if args.headless:
                started = time.monotonic()
                previous = started
                while not args.duration or time.monotonic() - started < args.duration:
                    now = time.monotonic()
                    demo.tick(now - previous)
                    previous = now
                    time.sleep(1 / 30)
            else:
                from smarthouse.view import SmartHouseWindow
                SmartHouseWindow.run(demo, duration=args.duration, screenshot=args.screenshot)
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print(f"Unable to start the demo: {exc}", file=sys.stderr)
            if not args.offline:
                print("Check Docker Desktop. To run the simulation only: python main.py --offline", file=sys.stderr)
            return 1
        finally:
            try:
                if messaging:
                    messaging.stop()
            finally:
                if infrastructure:
                    infrastructure.stop()
        return 0
