"""Minecraft ve derleme kuralları yalnız geçerli oldukları projelerde yüklensin.

Ayrıntı dosyaları (Test-Kuralları 16.919 karakter, Minecraft-Kuralları) otomatik
yüklenmez. Bu yüzden kısa bir Tetikleyici.md taşıyıcısı var ve **her oturumda** gelir.

İki kural, iki farklı kapsam:
  - Test-Kuralları madde 21 (`./gradlew --stop` görev sonunda): her Gradle/Maven projesi
  - Minecraft-Kuralları kural 8 (ölçüm öncesi RAM boşalt): yalnız Minecraft modu

Bir Fabric UI kütüphanesinde (ModularUI3-) oyun içi ölçüm geçerli değil.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


companion = load('beyin_v3_mc_companion', 'template/.claude/scripts/beyin_v3_companion.py')

TRIGGER = """---
{"kind": "note", "visibility": "internal"}
---
# Tetikleyici — hangi kural, hangi projede

## Derleme yapıyorsan (her Gradle/Maven projesi)

**Madde 21:** Gradle daemon kendiliğinden kapanmaz.
Görev bitince **`./gradlew --stop`**.

## Oyun içi ölçüm yapacaksan (Minecraft modu)

**Kural 8:** ölçümden önce `free -h` ile doğrula.
Sayfa yazma olursa **ölçüm geçersizdir**; raporun başına yaz.
"""

# Gerçek projelerin ölçülmüş yapısı.
FABRIC_LOOM = ('plugins {\n    id "fabric-loom" version "1.8-SNAPSHOT"\n}\n'
               'dependencies {\n    minecraft "com.mojang:minecraft:${project.minecraft_version}"\n}\n')
# ModularUI3-: 1.12.2 / RetroFuturaGradle. mcVersion var, minecraft_version YOK.
RFG = ('plugins {\n    alias(conventions.plugins.minecraft)\n}\n'
       'annotationProcessor(libs.mixinbooter)\n')
GRADLE_PROPS_MC = 'modName = ModularUI\nmodId = modularui\nmcVersion = 1.12.2\n'
PLAIN_GRADLE = ('plugins {\n    id "java"\n}\n'
                'group = "com.example"\nversion = "1.0"\n')


def project(tmp, files):
    root = Path(tmp)
    for name, body in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
    return str(root)


class MinecraftTespit(unittest.TestCase):
    """minecraft_project: oyun içi ölçüm kurallarının geçerli olduğu yer."""

    def tespit(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            return companion.minecraft_project(project(tmp, files))

    def test_fabric_loom_projesi_minecraft(self):
        self.assertTrue(self.tespit({'build.gradle': FABRIC_LOOM}))

    def test_retrofutura_projesi_minecraft(self):
        """ModularUI3-: mcVersion yazıyor, minecraft_version ve fabricmc yazmıyor.

        Konvansiyon eklentisi kullandığı için ilk tespit bunu 'Minecraft değil' saydı
        ve oyun içi ölçüm kuralı o projeye hiç gelmedi. Bu, ölçülmüş hataydır.
        """
        self.assertTrue(self.tespit({'build.gradle.kts': RFG, 'gradle.properties': GRADLE_PROPS_MC}))

    def test_mixins_json_minecraft(self):
        self.assertTrue(self.tespit({'src/main/resources/modularui.mixins.json': '{"mixins":[]}'}))

    def test_mod_tanimi_minecraft(self):
        self.assertTrue(self.tespit({'src/main/resources/fabric.mod.json': '{"id":"x"}'}))

    def test_duz_java_gradle_minecraft_degil(self):
        self.assertFalse(self.tespit({'build.gradle': PLAIN_GRADLE}))

    def test_diger_ekosisistemler_mixin_adini_taşısa_bile_minecraft_degil(self):
        """`mixins.json` yeterli değil, `*.mixins.json` olmalı: Node paketi de böyle adlandırabilir."""
        self.assertFalse(self.tespit({'mixins.json': '{}', 'settings.gradle': 'rootProject.name="x"\n'}))

    def test_rust_python_node_degil(self):
        for files in ({'Cargo.toml': '[package]\n'}, {'pyproject.toml': '[project]\n'},
                      {'package.json': '{"name":"x"}'}):
            with self.subTest(files=tuple(files)):
                self.assertFalse(self.tespit(files))

    def test_yedek_kopya_minecraft_degil(self):
        """fps-sync-yedek: yalnız gradle.properties kalmis, derleme yapisi yok."""
        self.assertFalse(self.tespit({'gradle.properties': 'org.gradle.jvmargs=-Xmx2G\n'}))

    def test_olmayan_dizin_minecraft_degil(self):
        self.assertFalse(companion.minecraft_project('/tmp/beyin-yok-boyle-bir-dizin-12345'))


class TetikleyiciKatman(unittest.TestCase):
    """İki kural farklı kapsamda: Minecraft olmayanda oyun içi ölçüm bölümü düşer."""

    def katman(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = project(tmp, files)
            return companion.tetikleyici_katman('Tetikleyici.md', TRIGGER, cwd)

    def test_minecraft_projesinde_her_iki_kural_kalir(self):
        out = self.katman({'build.gradle': FABRIC_LOOM})
        self.assertIn('./gradlew --stop', out)
        self.assertIn('ölçüm geçersizdir', out)

    def test_minecraft_olmayanda_derleme_kurali_kalir_olcum_kurali_duser(self):
        out = self.katman({'build.gradle': PLAIN_GRADLE})
        self.assertIn('./gradlew --stop', out, 'Madde 21 her derleme projesinde geçerli')
        self.assertNotIn('ölçüm geçersizdir', out, 'Oyun içi ölçüm bu projede oynanmıyor')

    def test_dusurulen_bolumun_yerine_gerekce_kalir(self):
        """Bölümü sessizce atmak ajanı 'kural yok' sanmaya itiyor; gerekçe kalmalı."""
        out = self.katman({'build.gradle': PLAIN_GRADLE})
        self.assertIn('geçerli değil', out)

    def test_baska_dosyalar_katmandan_gecmez(self):
        self.assertEqual(companion.tetikleyici_katman('Kurallar.md', 'kural metni', None), 'kural metni')

    def test_kurallar_dosyasi_ozgun_kisaltmasini_korur(self):
        metin = '# Threads\n\n## Active Threads\nAçık iş.\n\n## Closed Threads\nKapalı iş.\n'
        self.assertNotIn('Kapalı iş', companion.tetikleyici_katman('Threads.md', metin, None))


class HerOturumdaYuklenir(unittest.TestCase):
    """Ahmet kararı (2026-10-07): Tetikleyici her oturumda gelsin, koşula bağlı değil."""

    def test_tetikleyici_adinda_yuklenir(self):
        self.assertIn('Tetikleyici.md', companion.NAMES)

    def test_tetikleyici_icin_limit_var(self):
        """Sınır yoksa dosya sessizce büyür; bugün ölçülen risk bu."""
        self.assertIn('Tetikleyici.md', companion.LIMITS)

    def test_limit_makul(self):
        limit = companion.LIMITS['Tetikleyici.md']
        self.assertTrue(500 <= limit <= 2000, f'limit {limit} taşıyıcı için makul değil')


if __name__ == '__main__':
    unittest.main(verbosity=2)