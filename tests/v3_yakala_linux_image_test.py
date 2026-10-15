"""Linux/Wayland clipboard pictures: synthetic producers only, never touch the user's clipboard."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_yakala as yakala  # noqa: E402
from v3_yakala_pano_test import make_png, picture  # noqa: E402


@unittest.skipUnless(sys.platform.startswith('linux'), 'Wayland subprocess fixtures require Linux')
class WaylandImageTest(unittest.TestCase):
    def _fake_reader(self, folder, data, code=0):
        executable = Path(folder) / 'fake-wl-paste'
        executable.write_text('#!' + sys.executable + '\n'
                              'import sys\n'
                              'assert sys.argv[1:] == ["--no-newline", "--type", "image/png"]\n'
                              'sys.stdout.buffer.write(' + repr(data) + ')\n'
                              'sys.exit(' + str(code) + ')\n')
        executable.chmod(0o700)
        return str(executable)

    def test_image_only_is_offered_off_and_temp_copy_is_cleaned(self):
        png = make_png(picture(3, 2))
        with tempfile.TemporaryDirectory(prefix='yakala-fake-') as folder:
            fake = self._fake_reader(folder, png)
            with patch.object(yakala.sys, 'platform', 'linux'), \
                    patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}), \
                    patch.object(yakala, '_which', return_value=fake):
                image = yakala.clipboard_image('', {})
        self.assertIsNotNone(image)
        try:
            self.assertEqual((image['width'], image['height'], image['age'], image['on']), (3, 2, None, False))
            self.assertEqual(Path(image['path']).read_bytes(), png)
        finally:
            yakala._image_done(image)
        self.assertFalse(Path(image['path']).exists())

    def test_wayland_reader_rejects_bad_png_and_oversize_and_missing_helper(self):
        png = make_png(picture(2, 2))

        def check(data, *, code=0, limit=None, available=True, wayland=True):
            with tempfile.TemporaryDirectory(prefix='yakala-fake-') as folder:
                fake = self._fake_reader(folder, data, code)
                with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'} if wayland else {}, clear=True), \
                        patch.object(yakala, '_which', return_value=fake if available else None):
                    return yakala._linux_image_payload(**({'limit': limit} if limit is not None else {}))

        self.assertIsNone(check(png, code=1))
        self.assertIsNone(check(png[:-4]))
        self.assertIsNone(check(png + b'x', limit=len(png)))
        self.assertEqual(check(png, limit=len(png))['png'], png)
        self.assertIsNone(check(png, available=False))
        self.assertIsNone(check(png, wayland=False))

    def test_oversized_stream_is_stopped_before_producer_finishes(self):
        with tempfile.TemporaryDirectory(prefix='yakala-overflow-') as folder:
            marker = Path(folder) / 'finished'
            executable = Path(folder) / 'fake-wl-paste'
            executable.write_text('#!' + sys.executable + '\n'
                                  'import sys\n'
                                  'sys.stdout.buffer.write(b"x" * (8 * 1024 * 1024))\n'
                                  'open(' + repr(str(marker)) + ', "w").close()\n')
            executable.chmod(0o700)
            with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}), \
                    patch.object(yakala, '_which', return_value=str(executable)):
                self.assertIsNone(yakala._linux_image_payload(limit=128))
            self.assertFalse(marker.exists(), 'oversized clipboard producer was allowed to finish')

    def test_stalled_producer_is_killed_on_timeout(self):
        with tempfile.TemporaryDirectory(prefix='yakala-stall-') as folder:
            executable = Path(folder) / 'fake-wl-paste'
            executable.write_text('#!' + sys.executable + '\nimport time\ntime.sleep(10)\n')
            executable.chmod(0o700)
            with patch.dict(os.environ, {'WAYLAND_DISPLAY': 'wayland-0'}), \
                    patch.object(yakala, '_which', return_value=str(executable)), \
                    patch.object(yakala, 'CLIP_TIMEOUT', 0.1):
                self.assertIsNone(yakala._linux_image_payload())

    def test_text_or_an_existing_source_wins_without_opening_image(self):
        with patch.object(yakala, '_clipboard_payload', side_effect=AssertionError('image reader invoked')):
            for clip, context in [('https://example.com', {}), ('not', {}), ('', {'dosyalar': ['file.pdf']}),
                                  ('', {'url': 'https://example.com'})]:
                self.assertIsNone(yakala.clipboard_image(clip, context))


if __name__ == '__main__':
    unittest.main()
