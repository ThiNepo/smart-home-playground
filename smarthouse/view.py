"""Responsive native floor plan and contextual device inspector."""
from pathlib import Path
import json
import pyglet

pyglet.options.win32_gdi_font = True
pyglet.options.text_shaping = False

from pyglet import shapes
from pyglet.math import Mat4
from pyglet.window import key, mouse
from smarthouse.floorplan import FloorPlanView
from smarthouse.widgets import ActivityOverlay, BORDER, Button, INK, MUTED, NumericField, TEAL, Toggle, WHITE


class WindowLayout:
    """A 1920 by 1080 reference with a fluid canvas and readable inspector."""
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.scale = height / 1080
        self.panel_width = min(480, max(360, width / 4))
        self.panel_x = width - self.panel_width
        self.padding = 28 if self.panel_width >= 420 else 24
        self.inner_x = self.panel_x + self.padding
        self.inner_width = self.panel_width - self.padding * 2
        self.header_height = 80 * self.scale

    def y(self, reference):
        return reference * self.scale

    def font(self, reference=12):
        return max(10, round(reference * self.scale))


class PlanViewport:
    """Keep the house proportions and invert the same transform for mouse input."""
    def __init__(self, layout):
        self.layout = layout
        available_width = layout.panel_x
        available_height = layout.height - layout.header_height - 44 * layout.scale
        self.scale = min(available_width / 1010, available_height / 810)
        self.x = (available_width - 1010 * self.scale) / 2
        self.y = (available_height - 810 * self.scale) / 2
        self.projection = Mat4.orthogonal_projection(-self.x / self.scale,
            (layout.width - self.x) / self.scale, -self.y / self.scale,
            (layout.height - self.y) / self.scale, -255, 255)

    def to_screen(self, point):
        return self.x + point[0] * self.scale, self.y + point[1] * self.scale

    def to_plan(self, point):
        return (point[0] - self.x) / self.scale, (point[1] - self.y) / self.scale


class DeviceInspector:
    TITLES = {"light": "Light", "air_conditioner": "Air conditioner", "door": "Garage door",
              "door_contact": "Door contact", "window_contact": "Window contact",
              "car_presence": "Vehicle sensor", "motion": "Motion sensor", "moisture": "Soil moisture",
              "irrigation": "Irrigation", "breaker": "Main power", "temperature": "Temperature"}
    OPENING_TITLES = {"garage_door": "Garage door", "front_door": "Front door", "rear_door": "Garden door", "bedroom_window": "Bedroom window",
                      "bedroom_door": "Bedroom door", "bathroom_door": "Bathroom door", "laundry_door": "Laundry door",
                      "living_hall_door": "Living room door", "kitchen_hall_door": "Kitchen door",
                      "garage_hall_door": "Garage access door"}
    CONTACTS = {"front_door": ("living_room", "door_contact"), "rear_door": ("laundry", "door_contact"),
                "bedroom_window": ("bedroom", "window_contact"), "garage_door": ("garage", "door_contact")}

    def __init__(self, window):
        self.window = window
        self.items, self.controls, self.rows, self.toggles = [], [], [], []
        self.fields = {}
        self.selection = ("garage", "door")
        self.build()

    @property
    def device(self):
        house = self.window.application.house
        return house.openings[self.selection[1]] if self.selection[0] == "opening" else house.devices[self.selection]

    def select(self, selection, point=None):
        house = self.window.application.house
        valid = selection in house.devices or (selection[0] == "opening" and selection[1] in house.openings)
        if valid:
            self.window.focus_field(None)
            self.selection = selection
            self.build()
            self.window.floor_plan.select(selection, point=point)

    def clear(self):
        for item in self.items:
            item.delete()
        self.items.clear()
        self.controls.clear()
        self.fields.clear()
        self.rows.clear()
        self.toggles.clear()

    def text(self, text, y, size=12, color=INK, **kwargs):
        layout = self.window.layout
        return self.window.label(text, layout.inner_x, layout.y(y), layout.font(size), color, layer=14, **kwargs)

    def row(self, title, y, getter):
        layout = self.window.layout
        self.text(title, y, color=MUTED)
        label = self.window.label("", layout.inner_x + layout.inner_width, layout.y(y), layout.font(), INK,
                                  layer=14, anchor_x="right")
        self.rows.append((label, getter))
        return label

    def button(self, text, y, callback, column=0, columns=1, secondary=False):
        layout = self.window.layout
        width = (layout.inner_width - (columns - 1) * 12) / columns
        control = Button(self.window, text, layout.inner_x + column * (width + 12), layout.y(y), width,
                         callback, height=40 * layout.scale, secondary=secondary, font_size=layout.font())
        self.controls.append(control)
        return control

    def toggle(self, title, y, getter, callback):
        layout = self.window.layout
        control = Toggle(self.window, title, layout.inner_x, layout.y(y), layout.inner_width, getter, callback,
                         scale=layout.scale, font_size=layout.font())
        self.controls.append(control)
        self.toggles.append(control)
        return control

    def field(self, name, title, y, value, minimum, maximum, step=1, unit=""):
        layout = self.window.layout
        control = NumericField(self.window, name, title, layout.inner_x, layout.y(y), value, minimum, maximum,
                               step, unit, width=layout.inner_width, height=38 * layout.scale, font_size=layout.font())
        self.fields[name] = control
        self.controls.extend([control.minus, control.plus, control])
        return control

    def action(self, value):
        if self.selection[0] == "opening":
            self.window.set_opening(self.selection[1], value)
        else:
            self.window.command(*self.selection, value)

    def on_off_buttons(self):
        self.button("Turn on", 644, lambda: self.action("ON"), columns=2)
        self.button("Turn off", 644, lambda: self.action("OFF"), column=1, columns=2, secondary=True)

    def sensor_settings(self, top=599):
        self.text("SENSOR SETTINGS", top, 10, MUTED, weight="bold")
        self.field("read_interval", "Read interval", top - 43, self.device.config["read_interval"], .1, 60, .5, " s")
        self.field("publish_interval", "Publish interval", top - 91, self.device.config["publish_interval"], .1, 300, .5, " s")
        self.button("Apply settings", top - 158, self.apply_settings)

    def publication_settings(self, top=544):
        self.field("publish_interval", "Publish interval", top, self.device.config["publish_interval"], .1, 300, .5, " s")
        self.button("Apply settings", top - 67, self.apply_settings)

    def build(self, preserve_fields=False):
        saved = {name: field.value for name, field in self.fields.items() if preserve_fields and field.dirty}
        self.clear()
        w, layout = self.window, self.window.layout
        house = w.application.house
        w.capture, w.drawing_batch = self.items, w.ui_batch
        w.rect(layout.panel_x, 0, layout.panel_width, w.height - layout.header_height, WHITE, layer=10)
        w.line(layout.panel_x, 0, layout.panel_x, w.height - layout.header_height, BORDER, width=1, layer=11)
        self.text("Controls", 960, 20, weight="bold")
        self.toggle("Main power", 916, lambda: house.breaker.enabled, w.toggle_breaker)
        self.toggle("Classroom access", 872, lambda: w.application.students_enabled, w.toggle_students)
        w.line(layout.inner_x, layout.y(842), layout.inner_x + layout.inner_width, layout.y(842), BORDER, width=1, layer=11)
        self.text("SELECTED DEVICE", 814, 10, MUTED, weight="bold")
        area, kind = self.selection
        title = self.OPENING_TITLES[kind] if area == "opening" else self.TITLES.get(kind, kind.replace("_", " ").title())
        self.text(title, 776, 25, weight="bold")
        self.text("Manual opening" if area == "opening" else area.replace("_", " ").title(), 751, 12, MUTED)
        self.state_label = self.text("", 708, 18, TEAL, weight="bold")
        self.message = self.text("", 309, 10, TEAL)
        if area == "opening" or self.selection == ("garage", "door"):
            self.button("Open", 644, lambda: self.action("OPEN"), columns=2)
            self.button("Close", 644, lambda: self.action("CLOSE"), column=1, columns=2, secondary=True)
            self.row("Physical position", 620, lambda: f"{self.device.position * 100:.0f}% open")
            if self.device.contact is not None:
                self.row("Contact reading", 584, lambda: "Closed" if self.device.contact.value else "Open")
                opening_name = kind if area == "opening" else "garage_door"
                self.button("Contact sensor", 521, lambda: self.select(self.CONTACTS[opening_name]), secondary=True)
            else:
                self.row("Contact sensor", 584, lambda: "Not installed")
            if area != "opening":
                self.row("Vehicle", 475, lambda: "Present" if house.car_sensor.value else "Absent")
                self.publication_settings(427)
        elif kind == "air_conditioner":
            self.on_off_buttons()
            self.row("Room temperature", 620, lambda: f"{self.device.temperature.value:.1f} C")
            self.field("setpoint", "Target temperature", 574, self.device.setpoint, 16, 30, unit=" C")
            self.row("Mode", 532, lambda: self.device.mode.title())
            self.button("Change mode", 478, self.cycle_mode, secondary=True)
            self.publication_settings(427)
        elif kind == "irrigation":
            self.on_off_buttons()
            self.row("Soil moisture", 620, lambda: f"{house.moisture_sensor.value:.1f}%")
            self.button("Soil sensor", 558, lambda: self.select(("garden", "moisture")), secondary=True)
            self.publication_settings(493)
        elif kind in ("light", "breaker"):
            self.on_off_buttons()
            if kind == "light":
                self.row("Power supply", 620, lambda: "Available" if house.breaker.enabled else "Off")
            self.publication_settings(550)
        else:
            if kind == "car_presence":
                self.text("SCENE INTERACTION", 659, 10, MUTED, weight="bold")
                self.toggle("Car present", 620, lambda: house.car_sensor.physical_value,
                            lambda: w.scene_input("garage", "car_presence", not house.car_sensor.physical_value))
                self.sensor_settings(559)
            elif kind == "motion":
                self.text("SCENE INTERACTION", 659, 10, MUTED, weight="bold")
                self.button("Movement", 599, lambda: w.scene_input("garage", "motion", True), columns=2, secondary=True)
                self.button("Clear", 599, lambda: w.scene_input("garage", "motion", False), column=1, columns=2, secondary=True)
                self.sensor_settings(553)
            else:
                self.sensor_settings(629)
        self.connection()
        for name, value in saved.items():
            if name in self.fields:
                field = self.fields[name]
                field.value, field.dirty = value, True
                field.buffer = field.format(value)
                field.refresh()
        w.capture, w.drawing_batch = None, None
        self.refresh()

    def connection(self):
        w, layout = self.window, self.window.layout
        w.line(layout.inner_x, layout.y(285), layout.inner_x + layout.inner_width, layout.y(285), BORDER, width=1, layer=11)
        self.text("Connection", 256, 17, weight="bold")
        self.text("Endpoint", 230, 10, MUTED)
        infrastructure = w.application.infrastructure
        endpoint = infrastructure.url if infrastructure else "Offline simulation"
        font_size = layout.font(11)
        wrapped = w.wrap_text(endpoint, layout.inner_width, font_size, 2)
        self.endpoint_label = w.label(wrapped, layout.inner_x, layout.y(207), font_size, INK, layer=14,
                                     width=layout.inner_width, multiline=True)
        self.endpoint_text = endpoint
        credentials = infrastructure.credentials if infrastructure else {}
        self.row("Username", 140, lambda: credentials.get("username", "--"))
        self.row("Password", 110, lambda: credentials.get("password", "--"))
        self.button("Copy connection", 56, w.copy_connection, secondary=True)
        self.button("Activity", 9, w.toggle_activity, secondary=True)

    def apply_settings(self):
        self.window.focus_field(None)
        values = {name: field.value for name, field in self.fields.items()}
        if self.window.configure(*self.selection, values):
            for field in self.fields.values():
                field.dirty = False
            self.message.text = "Settings applied"
            self.message.color = (*TEAL, 255)
        else:
            self.message.text = "Invalid settings. Check the values."
            self.message.color = (184, 76, 64, 255)

    def cycle_mode(self):
        modes = ("AUTO", "COOL", "HEAT", "FAN")
        self.window.configure(*self.selection, {"mode": modes[(modes.index(self.device.mode) + 1) % len(modes)]})

    def refresh(self):
        state = self.device.state()
        kind = self.selection[1]
        if "moving" in state and state["value"] in ("OPENING", "CLOSING") and not state["moving"]:
            text = "Waiting for power"
        elif kind.endswith("_contact"):
            text = "Closed" if state["value"] else "Open"
        elif kind == "car_presence":
            text = "Present" if state["value"] else "Absent"
        elif kind == "motion":
            text = "Detected" if state["value"] else "Clear"
        elif kind == "moisture":
            text = f"{state['value']:.1f}% moisture"
        elif kind == "temperature":
            text = f"{state['value']:.1f} C"
        else:
            text = str(state["value"]).replace("_", " ").title()
        if self.state_label.text != text:
            self.state_label.text = text
        for label, getter in self.rows:
            text = getter()
            if label.text != text:
                label.text = text
        for toggle in self.toggles:
            toggle.refresh()
        for name, field in self.fields.items():
            if name in self.device.config:
                field.sync(self.device.config[name])


class SmartHouseWindow(pyglet.window.Window):
    def __init__(self, application, visible=True):
        self._ready = False
        width, height = 1920, 1080
        if visible:
            screen = pyglet.display.get_display().get_default_screen()
            width, height = min(width, screen.width - 24), min(height, screen.height - 72)
        super().__init__(width, height, caption="Smart House", resizable=True, visible=visible, vsync=True)
        self.set_minimum_size(1100, 760)
        self.application = application
        self.batch, self.ui_batch = pyglet.graphics.Batch(), pyglet.graphics.Batch()
        self.items, self.header_items, self.plan_labels = [], [], []
        self.capture, self.drawing_batch = None, None
        self.groups = [pyglet.graphics.Group(order=index) for index in range(16)]
        self.focused_field = None
        self.frame_time = 0.0
        self.font_cache = {}
        self.layout = WindowLayout(self.width, self.height)
        self.plan_viewport = PlanViewport(self.layout)
        self.floor_plan = FloorPlanView(self)
        self.inspector = None
        self.activity = None
        self._build_ui()
        self.floor_plan.select(self.inspector.selection)
        self._ready = True
        self.refresh(0)
        pyglet.clock.schedule_interval(self.update, 1 / 60)
        pyglet.clock.schedule_interval(self.refresh, 1 / 10)
        if visible:
            self.maximize()

    def _build_ui(self):
        self.focus_field(None)
        for item in self.header_items:
            item.delete()
        self.header_items.clear()
        if self.activity:
            self.activity.destroy()
        self.capture, self.drawing_batch = self.header_items, self.ui_batch
        layout = self.layout
        self.rect(0, self.height - layout.header_height, self.width, layout.header_height, WHITE, layer=10)
        self.line(0, self.height - layout.header_height, self.width, self.height - layout.header_height,
                  BORDER, width=1, layer=11)
        self.label("Smart House", 28, layout.y(1040), layout.font(28), INK, layer=14, weight="bold", anchor_y="center")
        self.label("Floor plan", 28, layout.y(976), layout.font(13), INK, layer=9, weight="bold")
        self.label("Select a device or a door", layout.panel_x - 28, layout.y(976), layout.font(11),
                   MUTED, layer=9, anchor_x="right")
        self.clock_label = self.label("", self.width - 225, layout.y(1040), layout.font(22), INK,
                                      layer=14, anchor_x="right", anchor_y="center", weight="bold")
        self.status_dot = self.circle(self.width - 174, layout.y(1040), 4, TEAL, layer=14)
        self.status_label = self.label("", self.width - 158, layout.y(1040), layout.font(12), MUTED,
                                       layer=14, anchor_y="center")
        self.capture, self.drawing_batch = None, None
        if self.inspector is None:
            self.inspector = DeviceInspector(self)
        else:
            self.inspector.build(preserve_fields=True)
        self.activity = ActivityOverlay(self)
        self.screen_projection = Mat4.orthogonal_projection(0, self.width, 0, self.height, -255, 255)

    def on_resize(self, width, height):
        super().on_resize(width, height)
        if getattr(self, "_ready", False):
            self.layout = WindowLayout(width, height)
            self.plan_viewport = PlanViewport(self.layout)
            self._update_plan_labels()
            self._build_ui()
            self.refresh(0)

    def keep(self, item):
        (self.capture if self.capture is not None else self.items).append(item)
        return item

    @property
    def active_batch(self):
        return self.drawing_batch if self.drawing_batch is not None else self.batch

    def rect(self, x, y, width, height, color, layer=0):
        return self.keep(shapes.Rectangle(x, y, width, height, color=color,
                                         batch=self.active_batch, group=self.groups[layer]))

    def rounded(self, x, y, width, height, color, radius=8, layer=0):
        return self.keep(shapes.RoundedRectangle(x, y, width, height, radius=max(2, radius), color=color,
                                                batch=self.active_batch, group=self.groups[layer]))

    def circle(self, x, y, radius, color, layer=2):
        return self.keep(shapes.Circle(x, y, radius, color=color, batch=self.active_batch, group=self.groups[layer]))

    def line(self, x, y, x2, y2, color, width=2, layer=3):
        return self.keep(shapes.Line(x, y, x2, y2, thickness=width, color=color,
                                    batch=self.active_batch, group=self.groups[layer]))

    def label(self, text, x, y, size=11, color=INK, layer=5, **kwargs):
        rgba = (*color, 255) if len(color) == 3 else color
        is_plan = self.drawing_batch is None
        screen_x, screen_y = self.plan_to_screen((x, y)) if is_plan else (x, y)
        font_size = max(8, round(size * self.plan_viewport.scale)) if is_plan else size
        item = self.keep(pyglet.text.Label(text, x=round(screen_x), y=round(screen_y), font_name="Segoe UI",
                                           font_size=font_size, color=rgba,
                                           batch=self.ui_batch if is_plan else self.active_batch,
                                           group=self.groups[layer], **kwargs))
        if is_plan:
            self.plan_labels.append((item, x, y, size))
        return item

    def _update_plan_labels(self):
        for label, x, y, size in self.plan_labels:
            screen_x, screen_y = self.plan_to_screen((x, y))
            label.x, label.y = round(screen_x), round(screen_y)
            label.font_size = max(8, round(size * self.plan_viewport.scale))

    def wrap_text(self, text, width, font_size, max_lines=2):
        """Explicitly wrap even a URL with no spaces, using actual glyph widths."""
        if font_size not in self.font_cache:
            self.font_cache[font_size] = pyglet.font.load("Segoe UI", font_size)
        font = self.font_cache[font_size]
        lines, current, used = [], "", 0.0
        for character in text:
            advance = font.get_glyphs(character)[0][0].advance if character != "\n" else 0
            if character == "\n" or (current and used + advance > width - 2):
                lines.append(current)
                current, used = "", 0.0
            if character != "\n":
                current += character
                used += advance
        lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines[-1] and sum(glyph.advance for glyph in font.get_glyphs(lines[-1] + "...")[0]) > width - 2:
                lines[-1] = lines[-1][:-1]
            lines[-1] += "..."
        return "\n".join(lines)

    def plan_to_screen(self, point):
        return self.plan_viewport.to_screen(point)

    def screen_to_plan(self, point):
        return self.plan_viewport.to_plan(point)

    def command(self, area, device, value):
        return self.application.command(f"house/{area}/{device}/set", json.dumps(value, allow_nan=False))

    def configure(self, area, device, values):
        return self.application.command(f"house/{area}/{device}/config/set", json.dumps(values, allow_nan=False))

    def set_opening(self, name, opened):
        try:
            self.application.house.set_opening(name, opened)
            self.application.log("Manual opening changed: " + name.replace("_", " "))
            return True
        except (ValueError, KeyError) as error:
            self.application.log("Scene interaction rejected: " + str(error))
            return False

    def scene_input(self, area, device, value):
        try:
            self.application.house.simulation.set_sensor(area, device, value)
            self.application.log("Scene interaction: " + area + "/" + device)
            return True
        except (ValueError, TypeError) as error:
            self.application.log("Scene interaction rejected: " + str(error))
            return False

    def toggle_light(self, room):
        self.command(room, "light", not self.application.house.rooms[room].light.is_on)

    def toggle_breaker(self):
        self.command("power", "breaker", not self.application.house.breaker.enabled)

    def toggle_students(self):
        self.application.students_enabled = not self.application.students_enabled
        self.application.log("Classroom controls " + ("enabled." if self.application.students_enabled else "paused."))

    def copy_connection(self):
        infrastructure = self.application.infrastructure
        if infrastructure:
            self.set_clipboard_text(json.dumps({"url": infrastructure.url, **infrastructure.credentials}, indent=2))
            self.inspector.message.text = "Connection copied"
        else:
            self.inspector.message.text = "Start with MQTT to share a connection"

    def toggle_activity(self):
        self.focus_field(None)
        self.activity.toggle()
        self.activity.refresh()

    def focus_field(self, field):
        if self.focused_field is not field:
            if self.focused_field:
                self.focused_field.focus(False)
            self.focused_field = field
            if field:
                field.focus(True)

    def update(self, dt):
        self.application.tick(dt)
        self.frame_time += dt
        self.floor_plan.update(self.application.house, dt)
        clock = self.application.house.clock.time_text
        if self.clock_label.text != clock:
            self.clock_label.text = clock

    def refresh(self, dt):
        self.floor_plan.refresh(self.application.house)
        self.inspector.refresh()
        self.activity.refresh()
        self.clock_label.text = self.application.house.clock.time_text
        connected = bool(self.application.messaging and self.application.messaging.connected)
        self.status_label.text = "Connected" if connected else ("Reconnecting" if self.application.messaging else "Offline")
        self.status_dot.color = TEAL if connected else (218, 167, 75)

    def on_draw(self):
        from pyglet import gl
        gl.glClearColor(246 / 255, 248 / 255, 247 / 255, 1)
        self.clear()
        self.projection = self.plan_viewport.projection
        self.batch.draw()
        self.projection = self.screen_projection
        self.ui_batch.draw()

    def on_mouse_press(self, x, y, button, modifiers):
        if button != mouse.LEFT:
            return
        if self.activity.open:
            if self.activity.close_button.contains(x, y):
                self.activity.close_button.click()
            return
        for control in self.inspector.controls:
            if control.contains(x, y):
                if not isinstance(control, NumericField):
                    self.focus_field(None)
                control.click()
                self.refresh(0)
                return
        self.focus_field(None)
        if x < self.layout.panel_x:
            point = self.screen_to_plan((x, y))
            selection = self.floor_plan.hit_test(*point)
            if selection:
                self.inspector.select(selection, point=point)
                self.refresh(0)

    def on_mouse_motion(self, x, y, dx, dy):
        controls = [self.activity.close_button] if self.activity.open else self.inspector.controls
        hovered = False
        for control in controls:
            active = control.contains(x, y)
            control.hover(active)
            hovered |= active
        if not hovered and not self.activity.open and x < self.layout.panel_x:
            hovered = self.floor_plan.hit_test(*self.screen_to_plan((x, y))) is not None
        self.set_mouse_cursor(self.get_system_mouse_cursor(self.CURSOR_HAND if hovered else self.CURSOR_DEFAULT))

    def on_text(self, text):
        if self.focused_field and not self.activity.open:
            self.focused_field.input(text)

    def on_key_press(self, symbol, modifiers):
        if self.focused_field:
            if symbol in (key.ENTER, key.TAB, key.ESCAPE):
                self.focus_field(None)
            elif symbol == key.BACKSPACE:
                self.focused_field.backspace()
            return
        if symbol == key.ESCAPE and self.activity.open:
            self.toggle_activity()
        elif symbol == key.SPACE and not self.activity.open:
            self.scene_input("garage", "motion", True)

    def close(self):
        pyglet.clock.unschedule(self.update)
        pyglet.clock.unschedule(self.refresh)
        super().close()

    @classmethod
    def run(cls, application, duration=0, screenshot=None):
        window = cls(application, visible=not screenshot)
        if screenshot:
            output = Path(screenshot)
            output.parent.mkdir(parents=True, exist_ok=True)
            window.switch_to()
            window.on_draw()
            pyglet.image.get_buffer_manager().get_color_buffer().save(str(output))
            window.close()
            print(f"Preview saved: {output}")
        else:
            if duration:
                pyglet.clock.schedule_once(lambda dt: window.close(), duration)
            pyglet.app.run()
