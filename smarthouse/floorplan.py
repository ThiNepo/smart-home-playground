"""Layered architectural illustration and animated device representations."""
import math
from pyglet import shapes


class ScenePalette:
    INK = (39, 53, 57)
    WALL = (65, 70, 69)
    WALL_EDGE = (105, 109, 103)
    TEAL = (0, 158, 153)
    MUTED = (113, 128, 128)
    WOOD = (188, 145, 96)


class RoomLighting:
    """Fade an entire room and its physical light fixture together."""

    def __init__(self, window, name, bounds, lamp):
        self.name = name
        self.level = 0.0
        self.target = 0.0
        self.bounds = bounds
        x, y, width, height = bounds
        self.shade = window.rect(x, y, width, height, (29, 45, 61), layer=5)
        self.shade.opacity = 53
        self.warmth = window.rect(x, y, width, height, (255, 217, 137), layer=5)
        self.warmth.opacity = 0
        px, py = lamp
        self.glows = [window.circle(px, py, radius, (255, 204, 82), layer=6) for radius in (42, 29, 19)]
        self.pin = window.circle(px, py, 12, (255, 254, 246), layer=7)
        self.pin.opacity = 200
        self.fixture = window.circle(px, py, 6, (216, 220, 212), layer=8)
        window.rounded(px - 3, py - 11, 6, 5, (100, 110, 105), radius=2, layer=8)
        self.switch = None
        self._last_enabled = None
        for glow in self.glows:
            glow.opacity = 0

    def update(self, enabled, dt):
        self.target = float(bool(enabled))
        if self._last_enabled == enabled and self.level == self.target:
            return
        self._last_enabled = enabled
        if dt > 0:
            self.level += (self.target - self.level) * min(1.0, dt * 7.5)
            if abs(self.level - self.target) < 0.005:
                self.level = self.target
        self.shade.opacity = round(53 * (1 - self.level))
        self.warmth.opacity = round(17 * self.level)
        for glow, alpha in zip(self.glows, (13, 23, 43)):
            glow.opacity = round(alpha * self.level)
        self.fixture.color = (255, 196, 54) if self.level > 0.5 else (161, 173, 176)
        if self.switch:
            self.switch.color = ScenePalette.TEAL if enabled else (135, 147, 148)


class DoorVisual:
    """A hinged leaf follows the physical actuator's continuous position."""

    def __init__(self, window, hinge, width, closed_angle=0, opened_angle=90):
        self.hinge = hinge
        self.width = width
        self.closed_angle = math.radians(closed_angle)
        self.opened_angle = math.radians(opened_angle)
        x, y = hinge
        self.shadow = window.line(x + 1, y - 2, x + width + 1, y - 2, (74, 65, 49), width=6, layer=6)
        self.shadow.opacity = 45
        self.leaf = window.line(x, y, x + width, y, (172, 125, 76), width=4, layer=7)
        self.edge = window.line(x, y, x + width, y, (225, 195, 155), width=1, layer=8)
        self.handle = window.circle(x + width - 7, y, 2, (78, 83, 80), layer=8)
        window.circle(x, y, 3, (93, 96, 86), layer=8)
        self.position = 0.0
        self._last_position = None
        self.update(0)

    def update(self, position):
        if self._last_position == position:
            return
        self._last_position = position
        self.position = max(0.0, min(1.0, position))
        angle = self.closed_angle + (self.opened_angle - self.closed_angle) * self.position
        x, y = self.hinge
        dx, dy = self.width * math.cos(angle), self.width * math.sin(angle)
        self.leaf.x2, self.leaf.y2 = x + dx, y + dy
        self.edge.x2, self.edge.y2 = x + dx, y + dy
        self.shadow.x2, self.shadow.y2 = x + dx + 1, y + dy - 2
        self.handle.x = x + (self.width - 7) * math.cos(angle)
        self.handle.y = y + (self.width - 7) * math.sin(angle)

    @property
    def bounds(self):
        x, y = self.hinge
        return (min(x, self.leaf.x2) - 5, min(y, self.leaf.y2) - 5,
                abs(self.leaf.x2 - x) + 10, abs(self.leaf.y2 - y) + 10)

    @property
    def outline(self):
        x, y = self.hinge
        dx, dy = self.leaf.x2 - x, self.leaf.y2 - y
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        px, py = -uy * 6, ux * 6
        sx, sy = x - ux * 4, y - uy * 4
        ex, ey = self.leaf.x2 + ux * 4, self.leaf.y2 + uy * 4
        return ((sx + px, sy + py), (ex + px, ey + py),
                (ex - px, ey - py), (sx - px, sy - py))

    @staticmethod
    def _distance_to_segment(x, y, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        length_squared = dx * dx + dy * dy
        progress = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_squared)) if length_squared else 0.0
        return math.hypot(x - x1 - progress * dx, y - y1 - progress * dy)

    def hit_test(self, x, y):
        hx, hy = self.hinge
        leaf_distance = self._distance_to_segment(x, y, hx, hy, self.leaf.x2, self.leaf.y2)
        frame_x = hx + self.width * math.cos(self.closed_angle)
        frame_y = hy + self.width * math.sin(self.closed_angle)
        frame_distance = self._distance_to_segment(x, y, hx, hy, frame_x, frame_y)
        return min(leaf_distance, frame_distance) <= 8


class GarageDoorVisual:
    """A roller shutter retracts completely from the vehicle's clear opening."""

    def __init__(self, window):
        self.position = 0.0
        self._last_position = None
        self._last_contact = None
        self.panel = window.rect(767, 179, 167, 15, (184, 194, 188), layer=7)
        self.slats = [window.line(767, 181 + index * 3, 934, 181 + index * 3, (112, 134, 131), width=1, layer=8) for index in range(5)]
        window.rect(757, 179, 6, 29, (115, 128, 121), layer=7)
        window.rect(938, 179, 6, 29, (115, 128, 121), layer=7)
        self.contact = window.circle(943, 204, 4, ScenePalette.TEAL, layer=8)
        self.status = window.label("Closed", 850, 216, 8, ScenePalette.MUTED, layer=9, anchor_x="center")

    def update(self, device):
        self.position = max(0.0, min(1.0, device.position))
        if self.position != self._last_position:
            self._last_position = self.position
            alpha = round(255 * (1 - self.position))
            self.panel.height = max(0.1, 15 * (1 - self.position))
            self.panel.opacity = alpha
            for index, slat in enumerate(self.slats):
                slat.y = slat.y2 = 180 + index * 3 * (1 - self.position)
                slat.opacity = alpha
        if self._last_contact != device.contact.value:
            self._last_contact = device.contact.value
            self.contact.color = ScenePalette.TEAL if device.contact.value else (198, 149, 64)
        if 0 < self.position < 1:
            text = f"Moving - {round(self.position * 100)}%"
        else:
            text = "Open" if self.position >= 1 else "Closed"
        if self.status.text != text:
            self.status.text = text

    @property
    def bounds(self):
        return (765, 177, 171, 18)

    def hit_test(self, x, y):
        threshold = 757 <= x <= 944 and 173 <= y <= 195
        jambs = (752 <= x <= 768 or 934 <= x <= 949) and 178 <= y <= 210
        return threshold or jambs


class AirConditionerVisual:
    """The unit and visible airflow animate independently of the room light."""

    def __init__(self, window, x, y):
        self.phase = 0.0
        self.active = None
        window.rounded(x - 1, y - 3, 65, 19, (67, 71, 67), radius=5, layer=3).opacity = 35
        window.rounded(x, y, 63, 17, (245, 246, 239), radius=4, layer=4)
        window.line(x + 5, y + 5, x + 57, y + 5, (87, 102, 106), width=3, layer=4)
        window.line(x + 5, y + 8, x + 57, y + 8, (211, 217, 212), width=1, layer=4)
        self.indicator = window.circle(x + 56, y + 13, 1.5, (168, 179, 168), layer=6)
        self.flow = []
        for index in range(4):
            line = window.line(x + 12 + index * 11, y - 2, x + 9 + index * 11, y - 12, (96, 185, 207), width=1.5, layer=6)
            line.opacity = 0
            self.flow.append((line, x + 12 + index * 11, y - 2, index))

    def update(self, device, dt):
        self.phase += dt
        enabled = bool(device and device.is_on)
        if not enabled and self.active is False:
            return
        if enabled != self.active:
            self.active = enabled
            self.indicator.color = ScenePalette.TEAL if enabled else (168, 179, 168)
        for line, x, y, index in self.flow:
            progress = (self.phase * 0.8 + index * 0.17) % 1
            line.x = x + math.sin(self.phase * 2 + index) * 2
            line.y = y - progress * 16
            line.x2 = line.x - 2
            line.y2 = line.y - 7
            line.opacity = round(150 * (1 - progress)) if enabled else 0


class PlantVisual:
    """Each plant owns a water landing point and a wet-soil halo."""

    def __init__(self, window, x, y, variety=0):
        self.x, self.y = x, y
        self.wet = window.circle(x, y, 13, (39, 76, 66), layer=3)
        self.wet.opacity = 0
        window.circle(x + 1, y - 2, 11, (51, 47, 29), layer=3).opacity = 75
        if variety % 3 == 0:
            for radius, color in ((11, (78, 119, 49)), (8, (113, 157, 65)), (5, (145, 179, 86))):
                for index in range(5):
                    angle = index * math.tau / 5
                    window.circle(x + math.cos(angle) * radius * 0.35, y + math.sin(angle) * radius * 0.35, radius * 0.57, color, layer=4)
        else:
            for index in range(6):
                angle = index * math.tau / 6
                leaf = window.keep(shapes.Ellipse(x + math.cos(angle) * 6, y + math.sin(angle) * 6, 6.5, 3.4, color=(101 + variety * 4, 145 + index * 3, 58 + index * 2), batch=window.batch, group=window.groups[4]))
                leaf.rotation = -math.degrees(angle)
            window.circle(x, y, 3, (82, 120, 48), layer=4)
            if variety % 3 == 2:
                for dx, dy in ((-4, 4), (5, 1), (0, -5)):
                    window.circle(x + dx, y + dy, 2.4, (194, 87, 45), layer=4)


class GardenBedVisual:
    """Every plant in both raised beds receives its own animated spray stream."""

    def __init__(self, window, x, y, width, height, variant=0):
        self.plants = []
        self.drops = []
        self.streams = []
        self.phase = variant * 0.41
        self.watering = False
        window.rounded(x + 3, y - 4, width, height, (53, 69, 42), radius=3, layer=2).opacity = 65
        window.rect(x, y, width, height, (148, 112, 69), layer=3)
        window.rect(x + 4, y + 4, width - 8, height - 8, (105, 77, 46), layer=3)
        window.rect(x + 8, y + 8, width - 16, height - 16, (88, 62, 40), layer=3)
        for index in range(22):
            sx = x + 10 + (index * 43) % int(width - 20)
            sy = y + 10 + (index * 29) % int(height - 20)
            window.circle(sx, sy, 1.2, (137, 104, 66), layer=3)
        window.line(x + 2, y + height - 2, x + width - 2, y + height - 2, (206, 168, 109), width=2, layer=4)
        window.line(x + 2, y + 2, x + width - 2, y + 2, (111, 83, 51), width=2, layer=4)
        self.sprinklers = [(x + width * 0.25, y + height * 0.5), (x + width * 0.75, y + height * 0.5)]
        for row in range(2):
            for column in range(6):
                px = x + 24 + column * (width - 48) / 5
                py = y + 23 + row * (height - 46)
                self.plants.append(PlantVisual(window, px, py, variant + column))
                source = self.sprinklers[0 if column < 3 else 1]
                line = window.line(source[0], source[1], px, py, (129, 207, 221), width=1, layer=6)
                line.opacity = 0
                self.streams.append(line)
                for drop_index in range(3):
                    drop = window.circle(source[0], source[1], 2, (183, 232, 245), layer=6)
                    drop.opacity = 0
                    self.drops.append((drop, source, (px, py), column * 0.11 + row * 0.19 + drop_index / 3))
        for sx, sy in self.sprinklers:
            window.circle(sx, sy, 4, (47, 70, 63), layer=6)
            window.circle(sx, sy, 2, (143, 180, 171), layer=6)

    def update(self, watering, dt):
        if not watering and not self.watering:
            return
        self.watering = watering
        self.phase += dt * 1.3
        for index, stream in enumerate(self.streams):
            stream.opacity = 28 + round(18 * math.sin(self.phase * 3 + index)) if watering else 0
        for drop, source, destination, offset in self.drops:
            progress = (self.phase + offset) % 1
            drop.x = source[0] + (destination[0] - source[0]) * progress
            drop.y = source[1] + (destination[1] - source[1]) * progress + math.sin(progress * math.pi) * 13
            drop.opacity = round(235 * (1 - progress * 0.4)) if watering else 0
        for plant in self.plants:
            plant.wet.opacity = 80 if watering else 0


class CarVisual:
    """A vehicle controlled only by its independent occupancy sensor."""

    def __init__(self, window):
        self.visible = True
        before = len(window.items)
        window.rounded(786, 289, 120, 227, (31, 40, 41), radius=31, layer=2).opacity = 48
        for x in (783, 893):
            for y in (326, 450):
                window.rounded(x, y, 13, 32, (38, 43, 44), radius=4, layer=3)
        window.rounded(790, 291, 112, 225, (177, 188, 188), radius=34, layer=3)
        window.rounded(793, 294, 106, 219, (230, 234, 229), radius=32, layer=3)
        window.rounded(797, 300, 98, 208, (244, 246, 239), radius=29, layer=4)
        window.line(799, 344, 800, 468, (159, 175, 177), width=2, layer=4)
        window.line(891, 344, 891, 468, (159, 175, 177), width=2, layer=4)
        window.rounded(806, 345, 80, 41, (49, 74, 84), radius=11, layer=4)
        window.line(811, 377, 879, 377, (107, 142, 151), width=2, layer=4)
        window.rounded(810, 389, 72, 66, (216, 224, 220), radius=11, layer=4)
        window.line(817, 400, 817, 444, (236, 241, 235), width=2, layer=4)
        window.rounded(808, 459, 76, 28, (56, 80, 88), radius=8, layer=4)
        window.line(814, 482, 878, 482, (110, 143, 148), width=2, layer=4)
        for x in (797, 888):
            window.rounded(x, 390, 5, 59, (64, 87, 94), radius=2, layer=4)
        for x in (788, 897):
            window.rounded(x, 361, 10, 12, (218, 226, 221), radius=4, layer=4)
        for x in (806, 872):
            window.rounded(x, 304, 14, 6, (236, 220, 145), radius=2, layer=4)
            window.rounded(x, 497, 14, 5, (176, 76, 66), radius=2, layer=4)
        window.line(817, 322, 875, 322, (176, 190, 187), width=1, layer=4)
        window.line(815, 492, 877, 492, (182, 196, 191), width=1, layer=4)
        window.rounded(830, 297, 30, 5, (126, 144, 147), radius=2, layer=4)
        self.parts = window.items[before:]
        self.original_opacity = [part.opacity for part in self.parts]

    def update(self, present):
        if self.visible == bool(present):
            return
        self.visible = bool(present)
        for item, alpha in zip(self.parts, self.original_opacity):
            item.opacity = alpha if present else 0


class FloorPlanView:
    """A continuous realistic property with individually animated components."""

    ROOM_BOUNDS = {
        "living_room": (65, 185, 347, 190),
        "kitchen": (418, 185, 322, 190),
        "bedroom": (65, 450, 265, 160),
        "bathroom": (335, 450, 170, 160),
        "laundry": (510, 450, 230, 160),
        "hall": (65, 380, 675, 65),
        "garage": (745, 177, 207, 433),
    }
    OFF_FLOORS = {
        "living_room": (193, 155, 111), "kitchen": (228, 221, 201),
        "bedroom": (197, 158, 112), "bathroom": (211, 218, 212),
        "laundry": (225, 219, 202), "hall": (196, 157, 111),
        "garage": (200, 204, 195),
    }
    ON_FLOORS = {name: tuple(min(255, channel + 14) for channel in color) for name, color in OFF_FLOORS.items()}

    def __init__(self, window):
        self.window = window
        self.hit_targets = []
        self.floors = {}
        self.lights = {}
        self.lamps = {}
        self.glows = {}
        self.switches = {}
        self.state_labels = {}
        self.air_conditioners = {}
        self.selection = None
        self.selection_target = None
        self.selection_bounds = None
        self.selection_outline = None
        self.opening_visuals = {}
        self.contact_targets = {}
        self.lamp_positions = {
            "living_room": (88, 349), "kitchen": (446, 349),
            "bedroom": (88, 582), "bathroom": (480, 583),
            "laundry": (711, 583), "hall": (676, 411), "garage": (925, 572),
        }
        self.switch_positions = {
            "living_room": (213, 195), "kitchen": (680, 365),
            "bedroom": (318, 462), "bathroom": (401, 460),
            "laundry": (581, 461), "hall": (359, 389), "garage": (755, 445),
        }
        self.motion_position = (925, 260)
        self.breaker_position = (712, 411)
        self.soil_probe_position = (339, 700)
        self.pump_position = (913, 705)
        self._build_site()
        self._build_rooms()
        self._build_furniture()
        self._build_walls()
        self._build_openings()
        self._build_devices()
        self._build_annotations()
        self._build_selection()
        for name, (x, y, width, height) in self.ROOM_BOUNDS.items():
            self.hit_targets.append((x + 7, y + 7, width - 14, height - 14, (name, "light")))

    def _ellipse(self, x, y, rx, ry, color, layer=3, rotation=0):
        shape = self.window.keep(shapes.Ellipse(x, y, rx, ry, color=color, batch=self.window.batch, group=self.window.groups[layer]))
        shape.rotation = rotation
        return shape

    def _plant(self, x, y, size=12, flower=False):
        w = self.window
        w.circle(x + 2, y - 2, size + 1, (51, 77, 45), layer=2).opacity = 70
        for index in range(7):
            angle = index * math.tau / 7
            self._ellipse(x + math.cos(angle) * size * 0.5, y + math.sin(angle) * size * 0.5, size * 0.65, size * 0.32, (68 + index * 6, 112 + index * 6, 49 + index * 3), rotation=-math.degrees(angle))
        w.circle(x, y, size * 0.3, (122, 158, 70), layer=4)
        if flower:
            for dx, dy in ((-5, 2), (4, 6), (2, -5)):
                w.circle(x + dx, y + dy, 2, (216, 158, 113), layer=4)

    def _hedge(self, x1, y1, x2, y2, spacing=13):
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length / spacing))
        for index in range(steps + 1):
            progress = index / steps
            self._plant(x1 + (x2 - x1) * progress, y1 + (y2 - y1) * progress, 9 + index % 3, index % 5 == 0)

    def _build_site(self):
        w = self.window
        w.rounded(35, 43, 948, 756, (55, 77, 65), radius=9, layer=0).opacity = 18
        w.rounded(40, 49, 936, 747, (225, 229, 216), radius=7, layer=0)
        w.rect(49, 73, 919, 714, (133, 161, 91), layer=1)
        for index in range(230):
            x = 56 + (index * 137) % 904
            y = 84 + (index * 211) % 695
            if y > 621 or y < 178:
                w.line(x, y, x + 3, y + 3, (154, 176, 107), width=1, layer=2).opacity = 90
        w.rect(59, 617, 894, 39, (216, 211, 188), layer=2)
        for x in range(62, 952, 34):
            w.line(x, 617, x, 655, (191, 189, 168), width=1, layer=2)
        w.line(59, 636, 953, 636, (191, 189, 168), width=1, layer=2)
        w.rect(756, 55, 190, 132, (210, 214, 203), layer=2)
        for x in range(759, 946, 38):
            w.line(x, 58, x, 183, (186, 193, 183), width=1, layer=2)
        for y in range(59, 179, 39):
            w.line(758, y, 944, y, (186, 193, 183), width=1, layer=2)
        for y in range(68, 182, 28):
            w.rect(148, y, 54, 23, (220, 217, 196), layer=2)
            w.line(149, y + 22, 200, y + 22, (240, 235, 215), width=1, layer=3)
        w.rect(40, 49, 936, 11, (190, 196, 190), layer=2)
        w.rect(40, 41, 936, 8, (170, 180, 175), layer=2)
        w.rect(40, 24, 936, 17, (130, 143, 143), layer=1)
        w.line(42, 47, 974, 47, (231, 234, 225), width=1, layer=3)
        w.label("STREET", 516, 29, 7, (232, 237, 233), layer=9, anchor_x="center")
        self._hedge(58, 775, 956, 775)
        self._hedge(56, 657, 56, 775)
        self._hedge(959, 657, 959, 775)
        self._hedge(57, 88, 57, 164)
        self._hedge(228, 86, 716, 86)
        self._hedge(960, 82, 960, 164)
        self._plant(93, 739, 22)
        self._plant(922, 753, 24)
        self._plant(107, 111, 22)
        self._plant(701, 127, 23)
        self._plant(271, 126, 17)
        for x in range(309, 679, 38):
            self._plant(x, 162, 9, True)
        self.beds = [GardenBedVisual(w, 108, 673, 270, 80), GardenBedVisual(w, 655, 673, 244, 80, variant=2)]
        for cx in (450, 489, 528):
            for cy in (671, 736):
                w.rounded(cx - 12, cy - 9, 24, 18, (120, 93, 60), radius=4, layer=3)
                w.line(cx - 10, cy + 5, cx + 10, cy + 5, (173, 137, 91), width=2, layer=4)
        w.rounded(423, 681, 138, 45, (111, 86, 54), radius=6, layer=3)
        w.rounded(425, 685, 134, 43, (180, 139, 86), radius=5, layer=4)
        for cy in (693, 702, 711, 720):
            w.line(430, cy, 554, cy, (152, 112, 67), width=1, layer=4)
        self._plant(492, 707, 9)
        w.label("Garden", 492, 757, 10, (45, 72, 47), layer=9, anchor_x="center", weight="bold")

    def _build_rooms(self):
        w = self.window
        w.rect(60, 177, 900, 443, (72, 75, 67), layer=2)
        w.rect(64, 181, 891, 434, (233, 224, 205), layer=2)
        for name, bounds in self.ROOM_BOUNDS.items():
            x, y, width, height = bounds
            self.floors[name] = w.rect(x, y, width, height, self.OFF_FLOORS[name], layer=2)
            if name in ("living_room", "bedroom", "hall"):
                for row, py in enumerate(range(y + 7, y + height, 15)):
                    w.line(x + 1, py, x + width - 1, py, (169, 130, 85), width=1, layer=2).opacity = 115
                    for px in range(x + 25 + row % 3 * 37, x + width, 97):
                        w.line(px, py - 7, px, py, (171, 134, 89), width=1, layer=2).opacity = 100
                for row in range(16):
                    px = x + 13 + row * 53 % max(1, width - 32)
                    py = y + 11 + row * 37 % max(1, height - 22)
                    w.line(px, py, min(x + width - 4, px + 33), py + 1, (218, 178, 123), width=1, layer=2).opacity = 110
            else:
                tile = 28 if name in ("bathroom", "laundry") else 38
                for px in range(x, x + width, tile):
                    w.line(px, y, px, y + height, (184, 189, 176), width=1, layer=2).opacity = 125
                for py in range(y, y + height, tile):
                    w.line(x, py, x + width, py, (184, 189, 176), width=1, layer=2).opacity = 125

    def _rug(self, x, y, width, height, color=(217, 207, 178)):
        w = self.window
        w.rect(x, y, width, height, color, layer=3)
        w.rect(x + 4, y + 4, width - 8, height - 8, (229, 220, 195), layer=3)
        for px in range(int(x + 9), int(x + width - 5), 13):
            w.line(px, y + 6, px, y + height - 6, (210, 200, 174), width=1, layer=3).opacity = 100
        for py in range(int(y + 10), int(y + height - 5), 16):
            w.line(x + 6, py, x + width - 6, py, (218, 208, 181), width=1, layer=3).opacity = 100

    def _sofa(self, x, y, width, height):
        w = self.window
        w.rounded(x + 2, y - 3, width, height, (97, 87, 68), radius=8, layer=3).opacity = 60
        w.rounded(x, y, width, height, (188, 184, 160), radius=8, layer=3)
        w.rounded(x + 7, y + 7, width - 14, height - 14, (231, 224, 199), radius=6, layer=4)
        w.rounded(x + 2, y + 3, 12, height - 6, (208, 200, 174), radius=5, layer=4)
        w.rounded(x + width - 14, y + 3, 12, height - 6, (208, 200, 174), radius=5, layer=4)
        cushions = max(1, int(height / 39))
        for index in range(cushions):
            cy = y + 12 + index * (height - 17) / cushions
            w.rounded(x + 17, cy, width - 34, (height - 23) / cushions, (238, 232, 209), radius=4, layer=4)
        w.line(x + 13, y + 11, x + 13, y + height - 11, (162, 158, 136), width=1, layer=4)


    def _build_furniture(self):
        w = self.window
        self._rug(113, 209, 252, 143)
        self._sofa(305, 229, 70, 110)
        self._sofa(126, 285, 59, 57)
        w.rounded(212, 249, 62, 55, (101, 78, 48), radius=24, layer=3)
        self._ellipse(243, 279, 31, 27, (173, 129, 76), layer=4)
        self._ellipse(244, 281, 25, 22, (192, 149, 92), layer=4)
        self._plant(243, 281, 8)
        w.rounded(79, 234, 19, 96, (139, 104, 65), radius=3, layer=3)
        w.rounded(78, 240, 8, 84, (39, 49, 49), radius=2, layer=4)
        w.line(78, 245, 78, 320, (109, 130, 131), width=1, layer=4)
        self._plant(90, 210, 12)
        self._rug(103, 466, 184, 128)
        w.rounded(108, 468, 34, 123, (130, 95, 57), radius=4, layer=3)
        w.rounded(127, 476, 124, 108, (236, 228, 205), radius=5, layer=3)
        w.rounded(140, 481, 108, 96, (251, 246, 225), radius=4, layer=4)
        for py in (488, 535):
            w.rounded(136, py, 29, 36, (219, 219, 194), radius=5, layer=4)
            w.line(140, py + 3, 160, py + 3, (195, 202, 176), width=1, layer=4)
        w.rect(174, 480, 58, 98, (148, 157, 122), layer=4)
        w.line(178, 484, 178, 574, (183, 190, 151), width=1, layer=4)
        for cy in (477, 583):
            w.rounded(86, cy - 8, 22, 19, (157, 115, 65), radius=2, layer=3)
            w.circle(97, cy + 1, 6, (235, 223, 172), layer=4)
            w.circle(97, cy + 1, 3, (255, 244, 204), layer=4)
        w.rect(300, 491, 23, 102, (160, 120, 71), layer=3)
        for cy in (512, 545, 578):
            w.line(301, cy, 322, cy, (124, 94, 60), width=1, layer=4)
            w.circle(304, cy - 9, 1.4, (70, 78, 70), layer=4)
        # Kitchen counters leave a broad passage to the living room.
        w.rect(690, 197, 43, 168, (168, 175, 163), layer=3)
        w.rect(694, 201, 36, 160, (237, 236, 218), layer=4)
        for cy in (226, 266, 307):
            w.line(695, cy, 729, cy, (194, 202, 188), width=1, layer=4)
        w.rounded(696, 306, 32, 49, (63, 74, 71), radius=2, layer=4)
        for px in (704, 721):
            for py in (316, 343):
                w.circle(px, py, 5, (122, 133, 122), layer=4)
                w.circle(px, py, 3, (74, 85, 78), layer=4)
        w.rounded(697, 262, 29, 29, (151, 170, 168), radius=5, layer=4)
        w.rounded(701, 266, 21, 21, (191, 211, 202), radius=4, layer=4)
        w.line(711, 288, 711, 296, (101, 126, 123), width=2, layer=4)
        w.rounded(688, 204, 46, 47, (201, 213, 205), radius=3, layer=4)
        w.line(691, 230, 730, 230, (157, 180, 172), width=1, layer=4)
        w.line(695, 210, 695, 224, (100, 125, 125), width=2, layer=4)
        for cx in (526, 571, 616):
            for cy in (239, 310):
                w.rounded(cx - 11, cy - 9, 22, 18, (131, 104, 69), radius=4, layer=3)
                w.line(cx - 8, cy + 6, cx + 8, cy + 6, (185, 147, 95), width=2, layer=4)
        w.rounded(504, 251, 132, 46, (106, 80, 47), radius=4, layer=3)
        w.rounded(506, 255, 128, 44, (184, 143, 87), radius=4, layer=4)
        for py in (263, 274, 285):
            w.line(510, py, 630, py, (160, 117, 70), width=1, layer=4)
        self._plant(570, 277, 8)
        # Bathroom: tiled shower, toilet, vanity, and basin.
        w.rect(341, 526, 61, 77, (160, 185, 184), layer=3)
        w.rect(345, 530, 53, 69, (179, 203, 199), layer=4)
        w.line(401, 529, 401, 601, (98, 145, 150), width=2, layer=4)
        w.line(345, 528, 399, 528, (119, 161, 165), width=1, layer=4)
        w.circle(372, 566, 4, (207, 217, 207), layer=4)
        w.circle(372, 566, 2, (115, 140, 135), layer=4)
        w.line(373, 599, 373, 586, (102, 132, 128), width=2, layer=4)
        w.circle(373, 586, 5, (160, 183, 177), layer=4)
        w.rounded(430, 574, 25, 22, (242, 243, 231), radius=3, layer=3)
        self._ellipse(442, 560, 12, 20, (239, 242, 229), layer=4)
        self._ellipse(442, 558, 7, 12, (200, 214, 204), layer=4)
        w.rect(473, 483, 26, 70, (163, 171, 153), layer=3)
        w.rect(475, 486, 23, 66, (235, 236, 218), layer=4)
        self._ellipse(486, 525, 10, 16, (181, 204, 195), layer=4)
        self._ellipse(486, 525, 7, 12, (216, 230, 218), layer=4)
        w.circle(486, 539, 2, (112, 143, 134), layer=4)
        self._plant(484, 469, 9)
        # Laundry equipment and the rear service door.
        w.rect(687, 464, 45, 135, (166, 178, 164), layer=3)
        for cy in (469, 515):
            w.rounded(691, cy, 37, 43, (235, 240, 226), radius=3, layer=4)
            w.circle(709, cy + 20, 13, (123, 153, 151), layer=4)
            w.circle(709, cy + 20, 9, (65, 101, 107), layer=4)
            w.circle(712, cy + 23, 5, (114, 153, 155), layer=4)
            w.line(695, cy + 36, 723, cy + 36, (179, 197, 180), width=1, layer=4)
            w.circle(721, cy + 39, 1.5, ScenePalette.TEAL, layer=4)
        w.rounded(691, 561, 37, 35, (217, 224, 208), radius=3, layer=4)
        w.rounded(696, 566, 27, 24, (165, 189, 179), radius=4, layer=4)
        w.line(709, 591, 709, 600, (102, 130, 126), width=2, layer=4)
        w.rounded(527, 562, 43, 37, (171, 143, 104), radius=4, layer=3)
        for px in range(532, 568, 6):
            w.line(px, 566, px, 593, (199, 175, 134), width=1, layer=4)
        w.rounded(530, 584, 36, 12, (191, 205, 194), radius=4, layer=4)
        # Garage shelves, bin, parking bay guides, and independent vehicle.
        w.line(778, 275, 778, 525, (222, 223, 203), width=2, layer=3)
        w.line(916, 275, 916, 525, (222, 223, 203), width=2, layer=3)
        for cy in (310, 375, 440):
            w.rect(928, cy, 18, 52, (165, 135, 88), layer=3)
            for px in (931, 939):
                w.rect(px, cy + 6, 5, 15 + px % 3 * 4, (120, 139, 96), layer=4)
            w.line(929, cy + 47, 945, cy + 47, (113, 95, 64), width=2, layer=4)
        w.rounded(914, 527, 30, 35, (50, 107, 78), radius=4, layer=3)
        w.rounded(916, 551, 26, 10, (38, 91, 68), radius=3, layer=4)
        self.car = CarVisual(w)

    def _wall(self, x1, y1, x2, y2, width=10):
        w = self.window
        w.line(x1 + 2, y1 - 3, x2 + 2, y2 - 3, (42, 51, 43), width=width + 3, layer=3).opacity = 45
        w.line(x1, y1, x2, y2, ScenePalette.WALL, width=width, layer=7)
        w.line(x1, y1 + 2, x2, y2 + 2, ScenePalette.WALL_EDGE, width=1, layer=8).opacity = 145

    def _window(self, x1, y1, x2, y2):
        w = self.window
        w.line(x1, y1, x2, y2, (230, 237, 226), width=10, layer=7)
        w.line(x1, y1, x2, y2, (157, 197, 202), width=5, layer=8)
        horizontal = y1 == y2
        length = math.hypot(x2 - x1, y2 - y1)
        for index in range(1, max(2, int(length / 24))):
            progress = index / max(2, int(length / 24))
            x, y = x1 + (x2 - x1) * progress, y1 + (y2 - y1) * progress
            w.line(x if horizontal else x - 5, y - 5 if horizontal else y, x if horizontal else x + 5, y + 5 if horizontal else y, (112, 147, 148), width=1, layer=8)
        if horizontal:
            w.line(x1, y1 - 5, x2, y2 - 5, (235, 239, 225), width=1, layer=8)
            w.line(x1, y1 + 5, x2, y2 + 5, (235, 239, 225), width=1, layer=8)
        else:
            w.line(x1 - 5, y1, x2 - 5, y2, (235, 239, 225), width=1, layer=8)
            w.line(x1 + 5, y1, x2 + 5, y2, (235, 239, 225), width=1, layer=8)


    def _build_walls(self):
        self._wall(60, 180, 60, 270)
        self._window(60, 270, 60, 338)
        self._wall(60, 338, 60, 505)
        self._window(60, 505, 60, 569)
        self._wall(60, 569, 60, 615)
        self._wall(60, 615, 126, 615)
        self._window(126, 615, 220, 615)
        self._wall(220, 615, 360, 615)
        self._window(360, 615, 403, 615)
        self._wall(403, 615, 533, 615)
        self._window(533, 615, 575, 615)
        self._wall(575, 615, 618, 615)
        self._wall(666, 615, 794, 615)
        self._window(794, 615, 902, 615)
        self._wall(902, 615, 958, 615)
        self._wall(958, 180, 958, 615)
        self._wall(60, 180, 149, 180)
        self._wall(201, 180, 237, 180)
        self._window(237, 180, 345, 180)
        self._wall(345, 180, 466, 180)
        self._window(466, 180, 677, 180)
        self._wall(677, 180, 761, 180)
        self._wall(941, 180, 958, 180)
        # Living room connects directly to kitchen and separately to the hall.
        self._wall(60, 378, 300, 378)
        self._wall(351, 378, 483, 378)
        self._wall(535, 378, 744, 378)
        self._wall(415, 180, 415, 224)
        self._wall(415, 334, 415, 378)
        self._wall(60, 447, 261, 447)
        self._wall(312, 447, 352, 447)
        self._wall(398, 447, 530, 447)
        self._wall(576, 447, 744, 447)
        self._wall(332, 447, 332, 615)
        self._wall(507, 447, 507, 615)
        self._wall(743, 180, 743, 392)
        self._wall(743, 439, 743, 615)
        # All interior leaves are independent local simulation objects.
        self.interior_doors = {}
        for name, hinge, width, closed, opened in (
            ("bedroom_door", (261, 447), 49, 0, 90),
            ("bathroom_door", (352, 447), 44, 0, 90),
            ("laundry_door", (530, 447), 44, 0, 90),
            ("living_hall_door", (300, 378), 49, 0, -90),
            ("kitchen_hall_door", (483, 378), 49, 0, -90),
            ("garage_hall_door", (743, 392), 46, 90, 180),
        ):
            self.interior_doors[name] = DoorVisual(self.window, hinge, width, closed, opened)
        self.opening_visuals.update(self.interior_doors)

    def _build_openings(self):
        w = self.window
        self.front_door = DoorVisual(w, (149, 180), 51, 0, 90)
        self.rear_door = DoorVisual(w, (618, 615), 47, 0, -90)
        self.bedroom_window = DoorVisual(w, (60, 505), 63, 90, 58)
        self.bedroom_window.leaf.color = (126, 181, 190)
        self.bedroom_window.leaf.thickness = 3
        self.bedroom_window.edge.color = (223, 243, 240)
        self.garage_door = GarageDoorVisual(w)
        self.opening_visuals.update({"front_door": self.front_door, "rear_door": self.rear_door,
                                     "bedroom_window": self.bedroom_window, "garage_door": self.garage_door})
        self.opening_selections = {name: ("opening", name) for name in self.opening_visuals}
        self.opening_selections["garage_door"] = ("garage", "door")
        self.selection_openings = {selection: name for name, selection in self.opening_selections.items()}
        self.opening_indicators = {}
        for key, x, y, target in (
            ("front_door", 212, 171, ("living_room", "door_contact")),
            ("rear_door", 679, 624, ("laundry", "door_contact")),
            ("bedroom_window", 74, 497, ("bedroom", "window_contact")),
            ("garage_door", 943, 204, ("garage", "door_contact")),
        ):
            self.opening_indicators[key] = w.circle(x, y, 4, ScenePalette.TEAL, layer=8)
            self.contact_targets[key] = (x, y, target)
            self.hit_targets.append((x - 6, y - 6, 12, 12, target))

    def _pin(self, x, y, color=ScenePalette.TEAL):
        w = self.window
        w.circle(x + 1, y - 2, 12, (41, 62, 61), layer=7).opacity = 35
        w.circle(x, y, 12, (248, 252, 248), layer=8)
        return w.circle(x, y, 8, color, layer=8)

    def _build_devices(self):
        w = self.window
        for name, bounds in self.ROOM_BOUNDS.items():
            lamp = self.lamp_positions[name]
            visual = RoomLighting(w, name, bounds, lamp)
            self.lights[name] = visual
            self.lamps[name] = visual.fixture
            self.glows[name] = visual.glows[0]
            sx, sy = self.switch_positions[name]
            w.rounded(sx - 5, sy - 8, 10, 16, (250, 249, 233), radius=2, layer=8)
            visual.switch = w.rect(sx - 2, sy - 4, 4, 8, (140, 153, 146), layer=8)
            self.switches[name] = visual.switch
            self.hit_targets.append((lamp[0] - 16, lamp[1] - 16, 32, 32, (name, "light")))
            self.hit_targets.append((sx - 10, sy - 13, 20, 26, (name, "light")))
        for name, x, y in (
            ("living_room", 253, 349), ("kitchen", 576, 349),
            ("bedroom", 241, 585), ("garage", 807, 582),
        ):
            self.air_conditioners[name] = AirConditionerVisual(w, x, y)
            self.hit_targets.insert(0, (x - 3, y - 6, 70, 29, (name, "air_conditioner")))
        px, py = self.motion_position
        self.motion_indicator = self._pin(px, py, (134, 151, 150))
        w.circle(px, py, 3, (242, 248, 235), layer=8)
        for offset in (5, 8):
            w.line(px - offset, py + 2, px - offset + 2, py + 6, (242, 248, 235), width=1, layer=8)
        self.hit_targets.insert(0, (px - 15, py - 15, 30, 30, ("garage", "motion")))
        bx, by = self.breaker_position
        w.rounded(bx - 15, by - 18, 30, 36, (118, 138, 133), radius=3, layer=7)
        w.rect(bx - 11, by - 13, 22, 26, (200, 214, 202), layer=8)
        self.breaker_indicator = w.rect(bx - 3, by - 8, 6, 16, ScenePalette.TEAL, layer=8)
        self.hit_targets.insert(0, (bx - 19, by - 22, 38, 44, ("power", "breaker")))
        sx, sy = self.soil_probe_position
        w.line(sx, sy - 10, sx, sy + 4, (172, 189, 161), width=3, layer=6)
        self.soil_probe_indicator = self._pin(sx, sy + 10)
        w.circle(sx, sy + 11, 3, (230, 251, 230), layer=8)
        self.moisture_label = w.label("55%", sx + 17, sy + 7, 8, (244, 251, 235), layer=9, weight="bold")
        self.hit_targets.insert(0, (sx - 15, sy - 7, 49, 38, ("garden", "moisture")))
        px, py = self.pump_position
        w.line(899, 712, px, 712, (107, 146, 147), width=3, layer=4)
        w.rounded(px - 11, py - 14, 22, 27, (97, 121, 116), radius=3, layer=7)
        self.pump_indicator = w.rounded(px - 7, py - 8, 14, 17, (160, 184, 174), radius=2, layer=8)
        w.circle(px, py + 1, 4, (227, 241, 225), layer=8)
        self.hit_targets.insert(0, (px - 17, py - 20, 34, 40, ("garden", "irrigation")))
        self.car_indicator = w.circle(920, 292, 4, ScenePalette.TEAL, layer=8)
        self.hit_targets.insert(0, (786, 287, 120, 231, ("garage", "car_presence")))

    def _build_annotations(self):
        w = self.window
        for name, x, y, title in (
            ("living_room", 243, 209, "Living room"),
            ("kitchen", 571, 207, "Kitchen"),
            ("bedroom", 212, 462, "Bedroom"),
            ("bathroom", 421, 495, "Bathroom"),
            ("laundry", 607, 492, "Laundry"),
            ("hall", 420, 403, "Hall"),
            ("garage", 850, 245, "Garage"),
        ):
            width = max(46, len(title) * 6.4 + 15)
            w.rounded(x - width / 2, y - 6, width, 20, (255, 254, 246), radius=5, layer=8).opacity = 220
            self.state_labels[name] = w.label(title, x, y + 1, 8, (48, 65, 63), layer=9, anchor_x="center")
        w.label("Main entrance", 175, 135, 8, (54, 79, 50), layer=9, anchor_x="center")

    def _build_selection(self):
        self.selection_lines = [self.window.line(0, 0, 0, 0, (0, 172, 166), width=2, layer=9) for _ in range(4)]
        for line in self.selection_lines:
            line.opacity = 0

    def hit_test(self, x, y):
        # Sensor pins and door leaves represent different physical objects.
        for cx, cy, selection in self.contact_targets.values():
            if math.hypot(x - cx, y - cy) <= 6:
                return selection
        for name, visual in self.opening_visuals.items():
            if visual.hit_test(x, y):
                return self.opening_selections[name]
        for bx, by, width, height, selection in self.hit_targets:
            if bx <= x <= bx + width and by <= y <= by + height:
                return selection
        return None

    def select(self, selected, point=None):
        changed = self.selection != selected
        self.selection = selected
        if changed:
            self.selection_target = None
        targets = [target for target in self.hit_targets if target[4] == selected]
        if point is not None:
            x, y = point
            targets = [target for target in targets if target[0] <= x <= target[0] + target[2]
                       and target[1] <= y <= target[1] + target[3]]
            self.selection_target = min(targets, key=lambda target: target[2] * target[3]) if targets else None
        elif self.selection_target is None and targets:
            self.selection_target = min(targets, key=lambda target: target[2] * target[3])
        self._refresh_selection()

    def _refresh_selection(self):
        name = self.selection_openings.get(self.selection)
        visual = self.opening_visuals.get(name)
        if visual is not None:
            bounds = visual.bounds
        elif self.selection_target:
            bounds = self.selection_target[:4]
        else:
            bounds = None
        self.selection_bounds = bounds
        if bounds is None:
            if self.selection_outline is not None:
                for line in self.selection_lines:
                    line.opacity = 0
            self.selection_outline = None
            return
        if isinstance(visual, DoorVisual):
            outline = visual.outline
        else:
            x, y, width, height = bounds
            padding = 3
            x, y, width, height = x - padding, y - padding, width + padding * 2, height + padding * 2
            outline = ((x, y), (x + width, y), (x + width, y + height), (x, y + height))
        if outline == self.selection_outline:
            return
        self.selection_outline = outline
        for index, line in enumerate(self.selection_lines):
            (x1, y1), (x2, y2) = outline[index], outline[(index + 1) % 4]
            line.x, line.y, line.x2, line.y2 = x1, y1, x2, y2
            line.opacity = 200

    def refresh(self, house, dt=0):
        for name, visual in self.lights.items():
            visual.update(house.rooms[name].light.is_on, dt)
        for name, visual in self.air_conditioners.items():
            visual.update(house.rooms[name].air_conditioner, dt)
        for key, visual in self.opening_visuals.items():
            opening = house.openings[key]
            visual.update(opening if key == "garage_door" else opening.position)
        self._refresh_selection()
        for key, indicator in self.opening_indicators.items():
            indicator.color = ScenePalette.TEAL if house.openings[key].contact.value else (198, 149, 64)
        self.car.update(house.car_sensor.physical_value)
        self.car_indicator.color = ScenePalette.TEAL if house.car_sensor.value else (149, 161, 155)
        self.motion_indicator.color = ScenePalette.TEAL if house.motion_sensor.value else (134, 151, 150)
        self.breaker_indicator.color = ScenePalette.TEAL if house.breaker.enabled else (188, 104, 83)
        self.pump_indicator.color = ScenePalette.TEAL if house.irrigation.is_on else (160, 184, 174)
        moisture_text = f"{round(house.moisture_sensor.value)}%"
        if self.moisture_label.text != moisture_text:
            self.moisture_label.text = moisture_text
        for bed in self.beds:
            bed.update(house.irrigation.is_on, dt)

    def update(self, house, dt):
        self.refresh(house, dt)
