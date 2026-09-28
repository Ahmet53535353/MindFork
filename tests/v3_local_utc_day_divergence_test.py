"""The daily log and the consolidation window date their files in different clocks.

`beyin_v3_sessionlog._day` builds its file name from `datetime.fromtimestamp(epoch)`, which is
the machine's local day. `beyin_v3_dream._now` converts to UTC before taking the day, so a
consolidation window is always a UTC day. A user east of Greenwich therefore writes a daily log
under tomorrow's date during the first hours of the day, and the two features disagree about
which day "today" is for three hours every day.

Nothing else in the suite can see this: `tests/conftest.py` pins the whole suite to UTC so the
tests do not break, and under UTC the two sides agree by construction. Pinning the divergence
here is what keeps it from becoming invisible -- a future change that makes the two agree must
come here first, and the fix belongs to the product, not to the clock the tests run in.
"""
import datetime as dt
import os
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3_sessionlog as sessionlog
import beyin_v3_dream as dream

# 21:30 UTC is 00:30 the next day at +03:00, inside the window where the two clocks disagree.
EPOCH = dt.datetime(2026, 9, 28, 21, 30, tzinfo=dt.timezone.utc).timestamp()
UTC_DAY = '2026-09-28'
EAST_DAY = '2026-09-29'


class LocalVsUtcDayTest(unittest.TestCase):
    """Both facts, measured: the clocks differ away from UTC and agree only in UTC."""

    def setUp(self):
        self.original = os.environ.get('TZ')
        self.addCleanup(self.restore)

    def restore(self):
        if self.original is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self.original
        time.tzset()

    def in_zone(self, zone):
        os.environ['TZ'] = zone
        time.tzset()

    def window_day(self):
        return dream._now(dt.datetime.fromtimestamp(EPOCH, dt.timezone.utc)).date().isoformat()

    def test_the_consolidation_window_is_a_utc_day_in_every_zone(self):
        for zone in ('UTC', 'UTC-3', 'UTC+11'):
            with self.subTest(zone=zone):
                self.in_zone(zone)
                self.assertEqual(self.window_day(), UTC_DAY)

    def test_the_daily_log_follows_the_machine_and_thereby_differs_from_the_window(self):
        self.in_zone('UTC-3')
        self.assertEqual(sessionlog._day(EPOCH), EAST_DAY, 'yerel gün artık UTC günü değil')
        self.assertNotEqual(sessionlog._day(EPOCH), self.window_day(),
                            'bölünme kayboldu: ya da günlük log da UTC ye döndü, düzeltmeyi gözden geçir')

    def test_the_two_clocks_agree_under_utc_which_is_why_the_suite_pin_hides_them(self):
        self.in_zone('UTC')
        self.assertEqual(sessionlog._day(EPOCH), self.window_day())


if __name__ == '__main__':
    unittest.main()
