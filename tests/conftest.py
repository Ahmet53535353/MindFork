"""Deterministik saat: tüm paketi UTC'ye sabitler.

Ürün konsolidasyon penceresini **UTC** ile tarihlendirir (`beyin_v3_dream.py` `_now()`), ama
`dt.date.today()` yereldir. UTC+3'te yerel gece yarısı ile UTC gece yarısı arasında günler ayrışır
ve duvara saate bakan her test **her gün üç saat** düşer; 2026-09-28'de paket bu yüzden kırmızıydı
(`test_cli_apply_then_restore_round_trip`, `test_q15_...`). Testler ve ürün aynı günü okusun diye
saat burada sabitlenir; `TZ=Etc/GMT+12` ile de doğrulanabilir (`TZ=UTC` iken ayrışma yoktur).
"""
import os
import time

os.environ['TZ'] = 'UTC'
time.tzset()
