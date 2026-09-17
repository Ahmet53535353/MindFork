# Avenox Ikinci Beyin V3: ajan kurulum rehberi

Bu dosya, kullanicinin su istegini yerine getirmek icin kanonik kurulum tarifidir:

> Bu klasore ikinci beynimi kur. Mevcut kurulum varsa notlarimi koruyarak guncelle.

Kullanici ZIP indirmek, arsiv acmak veya kurulum komutu aramak zorunda degildir. Bunlari
ajan yapar. Yalnizca istemcinin gosterdigi normal klasor, workspace veya hook guven
incelemesi kullaniciya aittir.

## Degismez kurallar

1. Kurulum hedefi, kullanicinin bu istegi verdigi mevcut vault/workspace klasorudur.
2. Kullanici notlarini silme, tasima, yeniden adlandirma veya `git reset` ile ezme.
3. Var olan V1, V2 veya V3 kurulumunu once tespit et. Resmi installer yedekleme,
   cakisma ve geri alma kurallarini uygular; bu kontrolleri elle atlama.
4. Yalniz `avenoxai/avenoxbeyin` deposunun en son kararlı GitHub release paketini kullan.
   Source code arsivlerini veya ucuncu taraf paketleri kullanma.
5. Ham notlari, kimlik bilgilerini, ozel yolları veya gizli degerleri terminal ciktisina,
   sohbete ya da dis servislere dokme.
6. Kurulum tamamlanmadan basarili deme. Installer cikis kodunu, surum damgasini ve
   `beyin.py doctor` sonucunu kontrol et.

## 1. Hedefi ve Python'u bul

- Vault yolu mevcut workspace kokudur. Mutlak ve kanonik yolu kullan.
- Python 3.11 veya daha yenisini ara:
  - macOS/Linux: once `python3`, sonra `python`
  - Windows: once `py -3`, sonra `python`
- Bulunan yorumlayicinin surumunu gercekten calistirip kontrol et.
- Uygun Python yoksa, kullanicinin bu kurulum istegini yetki kabul ederek isletim
  sisteminin resmi paket yoneticisiyle kararlı Python 3 surumunu kur. Yonetici izni veya
  isletim sistemi onayi gerekiyorsa yalniz o noktada kisa ve acik bicimde kullanicidan
  onay iste. Rastgele indirme siteleri kullanma.

Obsidian notlari acmak icindir; kurulum sirasinda Obsidian eklentisi gerekmez. Git, pip,
Node, Mem0, API anahtari veya surekli calisan sunucu gerekmez.

## 2. Resmi paketi gecici alana indir ve dogrula

GitHub API adresi:

`https://api.github.com/repos/avenoxai/avenoxbeyin/releases/latest`

Release kararlı bir `vMAJOR.MINOR.PATCH` etiketi tasimalidir. Etiket `v3.0.2` ise gerekli
varliklar sunlardir:

- `beyin-v3-3.0.2.zip`
- `beyin-v3-3.0.2.zip.sha256`

Surumu sabitleme: Isimleri API'deki gercek etiketten uret. Ikisini HTTPS ile isletim
sisteminin gecici klasorune indir. SHA-256 dosyasindaki ilk alani ZIP'in yerel SHA-256
degeriyle karsilastir. Eslesme yoksa dur, arsivi acma ve sorunu bildir.

ZIP'i gecici bir klasore acarken her uyenin hedefinin bu gecici klasorun icinde kaldigini
kontrol et. Mutlak yol, `..` ile kacis veya sembolik bag iceren arsivi reddet. Paket
kokunde `manifest.json` ve `scripts/install_v3.py` bulunmalidir.

## 3. Resmi installer'i calistir

Buldugun ayni Python yorumlayicisiyla:

```text
<python> <gecici-paket>/scripts/install_v3.py --vault <mutlak-vault-yolu>
```

Vault'ta `.beyin-runtime.json` varsa installer onun dis yerel state konumunu korur.
Yeni kurulumda installer state'i macOS, Linux veya Windows icin uygun yerel uygulama
verisi dizinine koyar. State'i iCloud, OneDrive, Dropbox veya vault icine tasima.

Installer cakisma bildirirse kullanici dosyasini ezme. Cakisan dosyayi ve neden otomatik
devam edilemedigini kisa bicimde bildir. Yarim kalan resmi V3 isleminde once mevcut
vault'taki `beyin.py recover` yolunu kullan; basarisiz olmadan yeniden kopyalama yapma.

## 4. Kurulumu dogrula

Vault kokunde su kontrolleri yap:

```text
<python> beyin.py doctor --human
<python> beyin.py preferences --human
```

Ek olarak `.beyin-version`, `.agents/skills/beyin/SKILL.md`,
`.agents/skills/beyin-doktor/SKILL.md` ve `.agents/skills/beyin-guncelle/SKILL.md`
dosyalarinin varligini kontrol et. Kurulumdan sonra gecici ZIP ve acma klasorunu sil;
kullanici notlarina dokunma.

Codex'te `/hooks` incelemesini, Claude Code ve Antigravity'de normal workspace/klasor
guvenini kullaniciya goster. Guven hash'i uydurma veya onayi atlatma. Ardindan yeni bir
istemci oturumu acilmasini iste. Codex Desktop otomatik hook baglami gorunmezse bu bir
kurulum basarisi iddiasi degildir; kurulu `beyin.py context` ve `sync` komutlariyla
dogrudan tazeleme kullanilabilir.

## 5. Kullanici ile tanis ve gercek geri okuma yap

Kurulumdan sonra `.agents/skills/beyin/SKILL.md` dosyasini oku. Kullaniciya en fazla uc
kisa tanisma sorusu sor. Cevaplarini kaynak Markdown notuna kaydet, `beyin.py sync` ile
esitle ve kaynagi belirterek geri oku. Uydurma profil bilgisi yazma.

Son olarak kullanicidan yeni bir oturum acip kaydedilen ornek bilgiyi sormasini iste.
Bu yeni oturum geri okuması yapilmadan "oturumlar arasi hafiza dogrulandi" deme.

Varsayilan tuketim profili Normal'dir. Kullanici isterse beyin skill'i uzerinden
"ekonomik moda gec", "kontrol araligini 30 dakika yap" veya "otomatik kontrolleri
kapat" diyebilir. Yerel kontroller model cagirmaz ve kapali uygulamayi uyandiran bir
zamanlayici kurulmaz.

## Manuel kacis yolu

Ajanin ag veya dosya yetkisi gercekten yetersizse, kullaniciyi su sayfaya yonlendir:

`https://avenox.lol/ikincibeyin`

Sayfadaki V3 ZIP dugmesi ayni resmi, checksum ile yayinlanmis paketi indirir. Bu yol
otomatik kurulumun yerine gecen son care yoludur; ilk tercih degildir.
