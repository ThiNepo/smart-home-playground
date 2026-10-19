"""Narrow runtime compatibility for the pinned Windows font renderer."""
import ctypes
from sys import platform


class WindowsFontCompatibility:
    @classmethod
    def apply(cls):
        """Correct Pyglet 2.1.16's GDI scan buffer declaration before drawing text."""
        if platform != "win32":
            return False
        import pyglet
        if pyglet.version != "2.1.16" or not pyglet.options["win32_gdi_font"]:
            return False
        from pyglet.image.codecs.gdiplus import gdiplus
        return cls._correct_scan_buffer(gdiplus.GdipCreateBitmapFromScan0)

    @staticmethod
    def _correct_scan_buffer(function):
        argument_types = list(function.argtypes or ())
        if len(argument_types) != 6 or argument_types[4] != ctypes.POINTER(ctypes.c_byte):
            return False
        # GDI+ Scan0 is BYTE*: unsigned bytes, as supplied by Pyglet's renderer.
        # Its signed declaration rejects that buffer on Python 3.11 ctypes.
        argument_types[4] = ctypes.POINTER(ctypes.c_ubyte)
        function.argtypes = argument_types
        return True
