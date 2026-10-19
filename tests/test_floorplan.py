"""Behavioral checks for the native scene; run with pytest -m gui."""
import math
import pytest
from smarthouse.application import SmartHouseApplication


@pytest.mark.gui
class TestFloorPlan:
    @pytest.fixture
    def window(self):
        from smarthouse.view import SmartHouseWindow
        window = SmartHouseWindow(SmartHouseApplication(), visible=False)
        try:
            yield window
        finally:
            window.close()

    @staticmethod
    def click(window, position):
        from pyglet.window import mouse
        window.on_mouse_press(*position, mouse.LEFT, 0)

    @classmethod
    def click_map(cls, window, position):
        cls.click(window, window.plan_to_screen(position))

    @classmethod
    def click_button(cls, window, text):
        control = next(control for control in window.inspector.controls
                       if getattr(getattr(control, "label", None), "text", None) == text)
        x, y, width, height = control.bounds
        cls.click(window, (x + width / 2, y + height / 2))

    @staticmethod
    def advance(window, duration):
        for _ in range(round(duration * 60)):
            window.update(1 / 60)
        window.refresh(0)

    @staticmethod
    def leaf_midpoint(visual):
        return ((visual.hinge[0] + visual.leaf.x2) / 2,
                (visual.hinge[1] + visual.leaf.y2) / 2)

    @staticmethod
    def inside_outline(point, outline):
        signs = []
        for index, (x1, y1) in enumerate(outline):
            x2, y2 = outline[(index + 1) % len(outline)]
            signs.append((x2 - x1) * (point[1] - y1) - (y2 - y1) * (point[0] - x1))
        return all(value >= 0 for value in signs) or all(value <= 0 for value in signs)

    def test_every_room_can_be_selected_and_illuminated_then_loses_power(self, window):
        house = window.application.house
        plan = window.floor_plan
        assert set(plan.lamp_positions) == set(house.rooms)
        for room in house.rooms:
            self.click_map(window, plan.lamp_positions[room])
            assert window.inspector.selection == (room, "light")
            assert not house.rooms[room].light.is_on
            self.click_button(window, "Turn on")
            assert house.rooms[room].light.is_on
            self.advance(window, 0.1)
            assert 0 < plan.lights[room].level < 1
        self.advance(window, 1)
        assert all(visual.level > 0.99 for visual in plan.lights.values())
        window.toggle_breaker()
        self.advance(window, 1)
        assert all(not room.light.is_on for room in house.rooms.values())
        assert all(visual.level < 0.01 for visual in plan.lights.values())

    @pytest.mark.parametrize("name", [
        "front_door", "rear_door", "bedroom_window", "garage_door",
        "bedroom_door", "bathroom_door", "laundry_door",
        "living_hall_door", "kitchen_hall_door", "garage_hall_door",
    ])
    def test_every_opening_can_be_clicked_on_its_closed_and_open_leaf(self, window, name):
        house = window.application.house
        plan = window.floor_plan
        visual = plan.opening_visuals[name]
        device = house.openings[name]
        selection = plan.opening_selections[name]
        previous = {key: opening.position for key, opening in house.openings.items() if key != name}
        position = (850, 185) if name == "garage_door" else self.leaf_midpoint(visual)
        self.click_map(window, position)
        assert window.inspector.selection == selection
        self.click_button(window, "Open")
        assert device.position == 0
        self.advance(window, 0.1)
        assert 0 < visual.position < 1
        moving_outline = plan.selection_outline
        self.advance(window, 2.2)
        assert visual.position == pytest.approx(1)
        if name == "garage_door":
            assert visual.panel.opacity == 0
            assert all(slat.opacity == 0 for slat in visual.slats)
        else:
            assert plan.selection_outline != moving_outline
            assert math.hypot(visual.leaf.x2 - visual.hinge[0], visual.leaf.y2 - visual.hinge[1]) == pytest.approx(visual.width)
        # Selecting another object proves that the open leaf itself remains clickable.
        window.inspector.select(("garden", "moisture"))
        position = (850, 185) if name == "garage_door" else self.leaf_midpoint(visual)
        self.click_map(window, position)
        assert window.inspector.selection == selection
        self.click_button(window, "Close")
        self.advance(window, 0.1)
        assert 0 < visual.position < 1
        self.advance(window, 2.2)
        assert visual.position == pytest.approx(0)
        assert {key: opening.position for key, opening in house.openings.items() if key != name} == previous

    def test_door_leaves_and_contact_pins_select_distinct_physical_objects(self, window):
        plan = window.floor_plan
        house = window.application.house
        for name, (x, y, sensor_selection) in plan.contact_targets.items():
            visual = plan.opening_visuals[name]
            for opened in (False, True):
                house.set_opening(name, opened)
                self.advance(window, 2.2)
                self.click_map(window, (x, y))
                assert window.inspector.selection == sensor_selection
                position = (850, 185) if name == "garage_door" else self.leaf_midpoint(visual)
                self.click_map(window, position)
                assert window.inspector.selection == plan.opening_selections[name]
                assert not self.inside_outline((x, y), plan.selection_outline)

    def test_room_space_away_from_leaf_is_not_an_invisible_door_target(self, window):
        plan = window.floor_plan
        # The former broad front-door rectangle extended through this empty floor.
        assert plan.hit_test(185, 212) == ("living_room", "light")
        assert plan.hit_test(642, 587) == ("laundry", "light")

    def test_wall_switches_and_air_conditioners_have_distinct_click_targets(self, window):
        plan = window.floor_plan
        for room, point in plan.switch_positions.items():
            self.click_map(window, point)
            assert window.inspector.selection == (room, "light")
            bounds = plan.selection_bounds
            assert bounds[0] <= point[0] <= bounds[0] + bounds[2]
            assert bounds[1] <= point[1] <= bounds[1] + bounds[3]
        for x, y, width, height, selection in plan.hit_targets:
            if selection[1] == "air_conditioner":
                self.click_map(window, (x + width / 2, y + height / 2))
                assert window.inspector.selection == selection
                self.click_map(window, plan.switch_positions[selection[0]])
                assert window.inspector.selection == (selection[0], "light")

    def test_both_beds_water_every_plant_and_stop_when_power_is_cut(self, window):
        house = window.application.house
        plan = window.floor_plan
        self.click_map(window, plan.pump_position)
        assert window.inspector.selection == ("garden", "irrigation")
        self.click_button(window, "Turn on")
        self.advance(window, 0.1)
        assert house.irrigation.is_on
        assert len(plan.beds) == 2
        for bed in plan.beds:
            destinations = {target for drop, source, target, offset in bed.drops}
            assert destinations == {(plant.x, plant.y) for plant in bed.plants}
            assert all(drop.opacity > 0 for drop, source, target, offset in bed.drops)
            assert all(plant.wet.opacity > 0 for plant in bed.plants)
        drop = plan.beds[0].drops[0][0]
        previous = (drop.x, drop.y)
        self.advance(window, 0.2)
        assert (drop.x, drop.y) != previous
        window.toggle_breaker()
        self.advance(window, 0.1)
        assert not house.irrigation.is_on
        assert all(drop.opacity == 0 for bed in plan.beds for drop, source, target, offset in bed.drops)

    def test_vehicle_presence_is_independent_from_the_garage_door(self, window):
        house = window.application.house
        plan = window.floor_plan
        window.command("garage", "door", "OPEN")
        self.advance(window, 2.2)
        assert plan.garage_door.position == 1
        assert plan.car.visible
        house.simulation.set_sensor("garage", "car_presence", False)
        self.advance(window, 0.1)
        assert not plan.car.visible
        assert all(part.opacity == 0 for part in plan.car.parts)
        assert plan.garage_door.position == 1
        window.command("garage", "door", "CLOSE")
        self.advance(window, 2.2)
        assert not plan.car.visible
        house.simulation.set_sensor("garage", "car_presence", True)
        self.advance(window, 0.1)
        assert plan.car.visible
        assert plan.garage_door.position == 0

    def test_only_four_air_conditioners_have_airflow_and_it_respects_power(self, window):
        plan = window.floor_plan
        assert set(plan.air_conditioners) == {"living_room", "kitchen", "bedroom", "garage"}
        for name in plan.air_conditioners:
            window.command(name, "air_conditioner", "ON")
        self.advance(window, 0.2)
        assert all(any(line.opacity > 0 for line, x, y, index in unit.flow) for unit in plan.air_conditioners.values())
        window.toggle_breaker()
        self.advance(window, 0.1)
        assert all(line.opacity == 0 for unit in plan.air_conditioners.values() for line, x, y, index in unit.flow)

    def test_sensor_intervals_apply_from_the_contextual_inspector(self, window):
        self.click_map(window, (339, 710))
        assert window.inspector.selection == ("garden", "moisture")
        inspector = window.inspector
        inspector.fields["read_interval"].buffer = "3"
        inspector.fields["read_interval"].commit()
        inspector.fields["publish_interval"].buffer = "7"
        inspector.fields["publish_interval"].commit()
        inspector.apply_settings()
        sensor = window.application.house.moisture_sensor
        assert sensor.config["read_interval"] == 3
        assert sensor.config["publish_interval"] == 7
        assert inspector.message.text == "Settings applied"
