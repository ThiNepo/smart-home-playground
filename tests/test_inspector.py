"""Real native controls, resizing, endpoint containment, and simulation boundaries."""
import json
import pytest
from smarthouse.application import SmartHouseApplication


class ConnectionDetails:
    url = "wss://a-very-long-classroom-hostname-with-several-parts-and-no-spaces.trycloudflare.com/mqtt"
    credentials = {"username": "classroom", "password": "A1B2C3"}


@pytest.mark.gui
class TestDeviceInspector:
    @pytest.fixture
    def window(self):
        from smarthouse.view import SmartHouseWindow
        window = SmartHouseWindow(SmartHouseApplication(infrastructure=ConnectionDetails()), visible=False)
        try:
            yield window
        finally:
            window.close()

    @staticmethod
    def resize(window, width, height):
        window.set_size(width, height)
        window.dispatch_events()
        window.on_resize(window.width, window.height)
        window.switch_to()
        window.on_draw()

    def test_reference_size_and_time_only_header(self, window):
        assert window.get_size() == (1920, 1080)
        assert window.layout.panel_width == 480
        assert window.clock_label.text == "08:00"
        window.update(1 / 6)
        assert window.clock_label.text == "08:01"
        assert "Day" not in window.clock_label.text
        assert window.resizeable

    def test_sensor_interface_has_settings_without_remote_input_controls(self, window):
        for selection in (("garden", "moisture"), ("bedroom", "temperature")):
            window.inspector.select(selection)
            assert set(window.inspector.fields) == {"read_interval", "publish_interval"}
            assert window.inspector.device.state().keys() == {"value", "config"}
            assert not window.command(*selection, 20)
            assert not any(getattr(control, "label", None) and "Simulate" in control.label.text
                           for control in window.inspector.controls)

    def test_contact_settings_apply_only_to_selected_real_sensor(self, window):
        window.inspector.select(("garage", "door_contact"))
        inspector = window.inspector
        inspector.fields["read_interval"].adjust(-.5)
        inspector.fields["publish_interval"].adjust(1)
        inspector.apply_settings()
        opening = window.application.house.openings["garage_door"]
        assert opening.contact.config["read_interval"] == .5
        assert opening.contact.config["publish_interval"] == 3
        assert opening.config["publish_interval"] == 2
        assert inspector.message.text == "Settings applied"

    @pytest.mark.parametrize("room", ["living_room", "kitchen", "bedroom", "garage"])
    def test_real_air_conditioner_controls_and_configuration(self, window, room):
        inspector = window.inspector
        inspector.select((room, "air_conditioner"))
        inspector.action("ON")
        inspector.fields["setpoint"].adjust(-1)
        inspector.apply_settings()
        window.update(.1)
        ac = window.application.house.rooms[room].air_conditioner
        assert ac.is_on
        assert ac.setpoint == 21
        inspector.cycle_mode()
        assert ac.mode == "HEAT"
        payload = json.loads(window.application.house.telemetry()[f"house/{room}/air_conditioner/state"])
        assert payload["config"]["setpoint"] == 21

    def test_no_automation_widgets_or_sprinkler_startup_policy(self, window):
        house = window.application.house
        window.inspector.select(("garden", "irrigation"))
        assert set(window.inspector.fields) == {"publish_interval"}
        house.simulation.set_sensor("garden", "moisture", 0)
        house.simulation.set_sensor("garage", "motion", True)
        for _ in range(4):
            window.update(.5)
        assert not house.irrigation.is_on
        assert not house.rooms["garage"].light.is_on
        window.inspector.select(("garage", "light"))
        assert set(window.inspector.fields) == {"publish_interval"}

    @pytest.mark.parametrize("size", [(1920,1080), (1600,900), (1280,800), (1100,760)])
    def test_endpoint_and_controls_stay_inside_panel_after_resize(self, window, size):
        self.resize(window, *size)
        inspector, layout = window.inspector, window.layout
        label = inspector.endpoint_label
        assert label.x >= layout.panel_x
        assert label.x + label.content_width <= window.width - layout.padding + 2
        assert "\n" in label.text
        assert label.content_height <= layout.y(60)
        for control in inspector.controls:
            x, y, width, height = control.bounds
            assert x >= layout.panel_x
            assert x + width <= window.width
            assert y >= 0
            assert y + height <= window.height - layout.header_height
        point = window.floor_plan.switch_positions["kitchen"]
        converted = window.screen_to_plan(window.plan_to_screen(point))
        assert converted == pytest.approx(point)

    def test_copy_preserves_full_endpoint_and_shared_credentials(self, window, monkeypatch):
        copied = []
        monkeypatch.setattr(window, "set_clipboard_text", copied.append)
        window.copy_connection()
        details = json.loads(copied[-1])
        assert details["url"] == ConnectionDetails.url
        assert details["username"] == "classroom"
        assert details["password"] == "A1B2C3"

    def test_resizing_keeps_pending_sensor_settings(self, window):
        window.inspector.select(("garden", "moisture"))
        window.inspector.fields["read_interval"].adjust(3)
        self.resize(window, 1280, 800)
        assert window.inspector.fields["read_interval"].value == 4
        window.inspector.apply_settings()
        assert window.application.house.moisture_sensor.config["read_interval"] == 4

    def test_activity_defocuses_configuration_editing(self, window):
        window.inspector.select(("garden", "moisture"))
        field = window.inspector.fields["read_interval"]
        window.focus_field(field)
        window.on_text("3")
        window.toggle_activity()
        assert window.focused_field is None
        window.on_text("5")
        assert field.value == 3
        window.activity.refresh()
        assert window.activity.open
        window.toggle_activity()

    def test_garage_waits_for_power_and_resumes_from_actual_position(self, window):
        inspector = window.inspector
        inspector.action("OPEN")
        window.update(.5)
        position = inspector.device.position
        window.command("power", "breaker", False)
        window.update(.3)
        window.refresh(0)
        assert inspector.device.position == position
        assert inspector.state_label.text == "Waiting for power"
        window.command("power", "breaker", True)
        window.update(.1)
        window.refresh(0)
        assert inspector.device.position > position
        assert inspector.state_label.text == "Opening"
