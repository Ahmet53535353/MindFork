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

The split between the two is deliberate: a batch boundary must be stable, a human day must not.
`beyin_v3_projections.receipt_day` therefore joins the *daily log*, not the window, and the fourth
test below pins that the two files in `daily/` read the same clock. It is the third leg of this
divergence and it was untested: a change could put the daily index back on UTC and nothing here
would notice.
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
import beyin_v3_projections as projections

# 21:30 UTC is 00:30 the next day at +03:00, inside the window where the two clocks disagree.
EPOCH = dt.datetime(2026, 9, 28, 21, 30, tzinfo=dt.timezone.utc).timestamp()
UTC_DAY = '2026-09-28'
EAST_DAY = '2026-09-29'
STAMP = '2026-09-28T21:30:00+00:00'


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

    def test_the_daily_index_follows_the_machine_with_the_daily_log_not_the_window(self):
        """The two files in daily/ are one human day; the window is a different concept."""
        self.in_zone('Etc/GMT-3')
        self.assertEqual(projections.receipt_day(STAMP), EAST_DAY)
        self.assertEqual(projections.receipt_day(STAMP), sessionlog._day(EPOCH),
                         'günlük dizin ve günlük log aynı günü söylemeli')
        self.assertNotEqual(projections.receipt_day(STAMP), self.window_day(),
                            'günlük dizin pencereye döndü: sözleşme günlük logla aynı saattir')


if __name__ == '__main__':
    unittest.main()
