"""Small native controls with consistent typography and explicit interaction states."""

INK = (30, 45, 55)
MUTED = (109, 124, 133)
TEAL = (13, 151, 143)
BORDER = (219, 227, 229)
WHITE = (255, 255, 255)


class Button:
    def __init__(self, window, text, x, y, width, callback, height=36, secondary=False, font_size=12):
        self.window = window
        self.bounds = (x, y, width, height)
        self.callback = callback
        self.secondary = secondary
        self.enabled = True
        self.hovered = False
        self.back = window.rounded(x, y, width, height, BORDER if secondary else TEAL, radius=6, layer=12)
        if secondary:
            window.rounded(x + 1, y + 1, width - 2, height - 2, WHITE, radius=5, layer=13)
        self.label = window.label(text, round(x + width / 2), round(y + height / 2), font_size,
                                  INK if secondary else WHITE, layer=14,
                                  anchor_x="center", anchor_y="center")

    def contains(self, x, y):
        bx, by, width, height = self.bounds
        return bx <= x <= bx + width and by <= y <= by + height

    def click(self):
        if self.enabled:
            self.callback()

    def hover(self, active):
        self.hovered = active
        self.back.color = ((176, 200, 204) if active else BORDER) if self.secondary else ((8, 127, 120) if active else TEAL)


class Toggle:
    def __init__(self, window, text, x, y, width, getter, callback, scale=1, font_size=12):
        self.window = window
        self.getter = getter
        self.callback = callback
        self.bounds = (x, y - 17 * scale, width, 34 * scale)
        window.label(text, x, y, font_size, INK, layer=14, anchor_y="center")
        self.x = x + width - 48 * scale
        self.scale = scale
        self.track = window.rounded(self.x, y - 13 * scale, 48 * scale, 26 * scale, TEAL, radius=13 * scale, layer=12)
        self.thumb = window.circle(self.x + 35 * scale, y, 10 * scale, WHITE, layer=14)
        self.refresh()

    def contains(self, x, y):
        bx, by, width, height = self.bounds
        return bx <= x <= bx + width and by <= y <= by + height

    def click(self):
        self.callback()
        self.refresh()

    def hover(self, active):
        pass

    def refresh(self):
        enabled = bool(self.getter())
        self.track.color = TEAL if enabled else (193, 204, 207)
        self.thumb.x = self.x + (35 if enabled else 13) * self.scale


class NumericField:
    def __init__(self, window, name, label, x, y, value, minimum, maximum, step=1, unit="",
                 width=424, height=36, font_size=12):
        self.window = window
        self.name = name
        self.minimum, self.maximum, self.step = minimum, maximum, step
        self.unit = unit
        self.value = float(value)
        self.buffer = self.format(self.value)
        self.dirty = False
        self.focused = False
        label_width = width * .49
        field_x, field_width = x + label_width, width - label_width
        self.bounds = (field_x, y - height / 2, field_width, height)
        window.label(label, x, y, font_size, MUTED, layer=14, anchor_y="center")
        self.back = window.rounded(field_x, y - height / 2, field_width, height, BORDER, radius=5, layer=12)
        window.rounded(field_x + 1, y - height / 2 + 1, field_width - 2, height - 2, WHITE, radius=4, layer=13)
        self.text = window.label("", field_x + 10, y, font_size, INK, layer=14, anchor_y="center")
        button_size = min(30, height - 4)
        self.minus = Button(window, "-", x + width - button_size * 2 - 7, y - button_size / 2,
                            button_size, self.decrease, height=button_size, secondary=True, font_size=font_size)
        self.plus = Button(window, "+", x + width - button_size - 3, y - button_size / 2,
                           button_size, self.increase, height=button_size, secondary=True, font_size=font_size)
        self.refresh()

    @staticmethod
    def format(value):
        return f"{value:g}"

    def contains(self, x, y):
        bx, by, width, height = self.bounds
        return bx <= x <= bx + width and by <= y <= by + height

    def click(self):
        self.window.focus_field(self)

    def hover(self, active):
        pass

    def focus(self, active):
        self.focused = active
        if active:
            self.buffer = ""
        elif self.buffer:
            self.commit()
        else:
            self.buffer = self.format(self.value)
        self.refresh()

    def commit(self):
        try:
            value = float(self.buffer)
        except ValueError:
            self.buffer = self.format(self.value)
            return
        self.value = max(self.minimum, min(self.maximum, value))
        self.buffer = self.format(self.value)
        self.dirty = True

    def input(self, text):
        if all(character in "0123456789.-" for character in text) and len(self.buffer) < 7:
            candidate = self.buffer + text
            if candidate.count(".") <= 1 and candidate.count("-") <= 1 and "-" not in candidate[1:]:
                self.buffer = candidate
        self.refresh()

    def backspace(self):
        self.buffer = self.buffer[:-1]
        self.refresh()

    def decrease(self):
        self.adjust(-self.step)

    def increase(self):
        self.adjust(self.step)

    def adjust(self, amount):
        self.window.focus_field(None)
        self.value = round(max(self.minimum, min(self.maximum, self.value + amount)), 2)
        self.buffer = self.format(self.value)
        self.dirty = True
        self.refresh()

    def sync(self, value):
        if not self.dirty and not self.focused:
            self.value = float(value)
            self.buffer = self.format(self.value)
            self.refresh()

    def refresh(self):
        self.text.text = (self.buffer if self.focused else self.format(self.value)) + (" |" if self.focused else self.unit)
        self.back.color = TEAL if self.focused else BORDER


class ActivityOverlay:
    def __init__(self, window):
        self.window = window
        self.open = False
        self.items = []
        scale = window.layout.scale
        width = min(900, window.layout.panel_x - 100)
        height = 510 * scale
        x = (window.layout.panel_x - width) / 2
        y = (window.height - height) / 2
        window.capture = self.items
        window.drawing_batch = window.ui_batch
        window.rounded(x + 4, y - 4, width, height, (208, 219, 220), radius=12, layer=10)
        window.rounded(x, y, width, height, WHITE, radius=12, layer=11)
        window.label("Activity", x + 28, y + height - 43 * scale, max(18, 22 * scale), INK, layer=14, weight="bold")
        window.label("Recent commands and connection events", x + 28, y + height - 75 * scale,
                     max(10, 12 * scale), MUTED, layer=14)
        self.close_button = Button(window, "Close", x + width - 128, y + height - 58 * scale,
                                   100, self.toggle, height=36 * scale, secondary=True, font_size=max(10, 12 * scale))
        self.labels = [window.label("", x + 28, y + height - (122 + index * 52) * scale,
                                    max(10, 11 * scale), INK, layer=14, width=width - 56, multiline=True)
                       for index in range(7)]
        self.text_width = width - 56
        window.capture = None
        window.drawing_batch = None
        self.set_visible(False)

    def destroy(self):
        for item in self.items:
            item.delete()
        self.items.clear()

    def set_visible(self, visible):
        for item in self.items:
            item.visible = visible

    def toggle(self):
        self.open = not self.open
        self.set_visible(self.open)

    def refresh(self):
        if self.open:
            application = self.window.application
            events = application.messaging.recent(7) if application.messaging else application.events[:7]
            for index, label in enumerate(self.labels):
                message = f"{events[index][0]}   {events[index][1]}" if index < len(events) else ""
                label.text = self.window.wrap_text(message, self.text_width, label.font_size, 2)
