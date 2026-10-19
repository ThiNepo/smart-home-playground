"""Verify the font workaround preserves byte data and avoids unrelated signatures."""
import ctypes
import sys
from types import SimpleNamespace
import pytest
import smarthouse.compatibility as compatibility
from smarthouse.compatibility import WindowsFontCompatibility


class TestWindowsFontCompatibility:
    @staticmethod
    def first_byte(width, height, stride, pixel_format, scan_buffer, bitmap):
        return scan_buffer[0]

    def test_unsigned_pixel_buffer_is_accepted_without_changing_its_value(self):
        signature = ctypes.CFUNCTYPE(
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_void_p),
        )
        function = signature(self.first_byte)
        argument_types = list(function.argtypes)
        argument_types[4] = ctypes.POINTER(ctypes.c_byte)
        function.argtypes = argument_types
        assert WindowsFontCompatibility._correct_scan_buffer(function)
        pixels = (ctypes.c_ubyte * 4)(255, 128, 64, 0)
        bitmap = ctypes.c_void_p()
        assert function(1, 1, 4, 0, pixels, ctypes.byref(bitmap)) == 255
        assert not WindowsFontCompatibility._correct_scan_buffer(function)

    @pytest.mark.parametrize("argument_types", [None, [], [ctypes.c_int] * 6, [ctypes.c_int] * 5])
    def test_unrelated_signatures_remain_unchanged(self, argument_types):
        function = SimpleNamespace(argtypes=argument_types)
        assert not WindowsFontCompatibility._correct_scan_buffer(function)
        assert function.argtypes is argument_types

    def test_non_windows_does_not_load_the_graphics_package(self, monkeypatch):
        monkeypatch.setattr(compatibility, "platform", "linux")
        monkeypatch.setitem(sys.modules, "pyglet", None)
        assert not WindowsFontCompatibility.apply()

    @pytest.mark.parametrize("version,gdi_enabled", [("2.1.19", True), ("2.1.16", False)])
    def test_other_versions_and_renderers_are_not_modified(self, monkeypatch, version, gdi_enabled):
        monkeypatch.setattr(compatibility, "platform", "win32")
        monkeypatch.setitem(sys.modules, "pyglet", SimpleNamespace(version=version, options={"win32_gdi_font": gdi_enabled}))
        assert not WindowsFontCompatibility.apply()
