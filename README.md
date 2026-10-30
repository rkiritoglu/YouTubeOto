# 🎬 YouTube Shorts AI Automation Pipeline

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Google Gemini API](https://img.shields.io/badge/AI-Gemini%202.5%20Flash-4285F4.svg)](https://aistudio.google.com/)
[![MoviePy](https://img.shields.io/badge/Video-MoviePy%20v2-red.svg)](https://zulko.github.io/moviepy/)

Yapay zeka kullanarak **YouTube Shorts**, **TikTok** ve **Instagram Reels** için dikey formatta (9:16) uçtan uca otomatik video üreten ve YouTube Data API v3 ile doğrudan kanala yükleyen açık kaynaklı bir otomasyon sistemidir.

---

## 🌟 Öne Çıkan Özellikler

- **🧠 Akıllı Senaryo & Kurgu (Google Gemini API):** İlk 3 saniyede izleyiciyi ekrana bağlayan (Hook) viral senaryolar, sahne bazlı stok video arama anahtar kelimeleri ve YouTube SEO meta verileri (başlık, açıklama, etiketler) üretir.
- **🎙️ Çok Katmanlı Ses Motoru (ElevenLabs + Edge-TTS):** ElevenLabs API ile ultra gerçekçi insan seslendirmesi yapar. API anahtarı girilmediğinde veya kota bittiğinde otomatik olarak **ücretsiz Microsoft Edge-TTS Türkçe doğal seslerine** (`tr-TR-AhmetNeural` / `tr-TR-EmelNeural`) geçiş yapar.
- **🎞️ Dikey Stok Video ve Montaj (Pexels + MoviePy):** Pexels API üzerinden sahnelerle eşleşen dikey HD videoları bulur, ses sürelerine göre kırpar ve MoviePy motoru ile otomatik olarak 1080x1920 dikey MP4 videosu render eder.
- **📤 Otomatik YouTube Yükleme (Data API v3 & OAuth 2.0):** Videoları belirlediğiniz gizlilik seviyesinde (`private`, `unlisted`, `public`) doğrudan kanalınıza yükler. İlk yetkilendirmeden sonra `token.pickle` ile oturumu saklayarak müdahalesiz çalışır.
- **🛡️ Hata Toleranslı (Fail-Safe):** İnternet veya API kesintilerinde çökmez; yedek renk/görsel motorlarını ve senaryo simülasyonunu devreye sokar.

---

## 🏗️ Sistem Mimarisi

```
[ Kullanıcı Konu Girişi ] 
          │
          ▼
[ generate_script.py ] ──> Google Gemini API (gemini-2.5-flash)
          │                ├─ Viral Senaryo & Hook
          │                ├─ Sahne Bazlı Pexels Arama Kelimeleri
          │                └─ YouTube Başlık, Açıklama ve Etiketler
          ▼
[ audio_generator.py ] ──> ElevenLabs API / Edge-TTS (Ücretsiz Türkçe Ses)
          │                └─ Her sahne için senkronize .mp3 dosyaları
          ▼
[ video_builder.py ]   ──> Pexels API + MoviePy (libx264 / aac)
          │                ├─ Dikey (9:16) HD Stok Video İndirme
          │                └─ Ses/Görüntü Kurgusu ve MP4 Render
          ▼
[ youtube_uploader.py] ──> YouTube Data API v3 (OAuth 2.0)
          │                └─ Otomatik Başlık, Açıklama, Etiket ve Yükleme
          ▼
[ 🎉 YouTube Shorts Videosu Yayında! ]
```

---

## 📁 Dizin Yapısı

```
YouTubeOto/
│
├── .github/workflows/        # GitHub Actions CI iş akışları
├── .env.example              # API anahtarları için örnek yapılandırma
├── .gitignore                # Hassas verilerin ve geçici medyaların gizlenmesi
├── requirements.txt          # Gerekli Python kütüphaneleri
├── LICENSE                   # MIT Açık Kaynak Lisansı
├── README.md                 # Proje dokümantasyonu
│
├── prompts.py                # Viral Shorts kuralları, promptlar ve görsel stil şablonları
├── generate_script.py        # Gemini API ile JSON formatında senaryo üretici
├── audio_generator.py        # ElevenLabs ve Edge-TTS seslendirme motoru
├── video_builder.py          # Pexels stok video indirici ve MoviePy montajlayıcı
├── youtube_uploader.py       # YouTube Data API v3 ile video yükleyici
└── main.py                   # Tek tıkla tüm iş akışını yöneten ana orkestrasyon dosyası
```

---

## 🚀 Hızlı Başlangıç

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/KULLANICI_ADINIZ/YouTubeOto.git
cd YouTubeOto
```

### 2. Sanal Ortam Oluşturun ve Bağımlılıkları Yükleyin
```bash
# Sanal ortam oluşturma
python -m venv venv

# Sanal ortamı aktifleştirme (Windows)
venv\Scripts\activate

# Sanal ortamı aktifleştirme (macOS/Linux)
source venv/bin/activate

# Paketleri yükleme
pip install -r requirements.txt
```

### 3. Çevre Değişkenlerini Yapılandırın
`.env.example` dosyasını `.env` olarak kopyalayın:
```bash
cp .env.example .env
```
Ardından `.env` dosyasını açıp API anahtarlarınızı girin:
- **`GEMINI_API_KEY`**: [Google AI Studio](https://aistudio.google.com/app/apikey)'dan ücretsiz alınabilir.
- **`PEXELS_API_KEY`**: [Pexels API](https://www.pexels.com/api/)'den ücretsiz alınabilir.
- **`ELEVENLABS_API_KEY`**: (İsteğe bağlı) [ElevenLabs](https://elevenlabs.io/)'dan alınabilir. Boş bırakırsanız sistem **Edge-TTS** ile ücretsiz devam eder.

---

## 🔑 YouTube Data API v3 Kurulumu (`client_secret.json`)

Videonun kanalınıza otomatik yüklenebilmesi için Google Cloud üzerinden bir istemci dosyası oluşturmanız gerekir:

1. [Google Cloud Console](https://console.cloud.google.com/) adresine gidin ve yeni bir proje oluşturun.
2. **APIs & Services > Library** bölümünden **YouTube Data API v3** servisini bulun ve **Enable** (Etkinleştir) butonuna tıklayın.
3. **OAuth Consent Screen** (Onay Ekranı) bölümünde:
   - Tür olarak **External** seçin.
   - Test kullanıcıları (Test users) kısmına videoyu yükleyeceğiniz Google hesabınızı ekleyin.
4. **Credentials > Create Credentials > OAuth client ID** adımlarını izleyin:
   - Uygulama türü: **Desktop app** (Masaüstü Uygulaması) seçin.
5. İndirilen JSON dosyasının adını `client_secret.json` olarak değiştirip doğrudan proje ana dizinine yerleştirin.

> **Not:** İlk çalıştırmada tarayıcınızda bir Google onay penceresi açılır. Onay verdikten sonra `token.pickle` üretilir ve sonraki yüklemeler arka planda tamamen sessizce gerçekleşir.

---

## 💻 Kullanım

### Tek Komutla Otomatik Üretim ve Yükleme:
```bash
python main.py
```

### Özel Konu, Stil ve Gizlilik Seçerek Çalıştırma:
```bash
python main.py --topic "Büyük Piramitlerin Gizli Odaları" --style "documentary_history" --privacy "private"
```

### Desteklenen Parametreler:
| Parametre | Varsayılan | Açıklama | Seçenekler |
|---|---|---|---|
| `--topic` | Piramitler Konusu | Üretilecek videonun ana teması | Herhangi bir metin |
| `--style` | `documentary_history` | Görsel ve kurgu tarzı | `documentary_history`, `cinematic_dark`, `cyberpunk_neon`, `science_space`, `hyper_realistic` |
| `--privacy` | `private` | YouTube yükleme gizlilik durumu | `private` (Gizli), `unlisted` (Liste Dışı), `public` (Herkese Açık) |
| `--output` | `final_youtube_shorts.mp4` | Çıktı video dosya adı | `.mp4` dosya yolu |

---

## 🧩 Modülleri Ayrı Ayrı Test Etme

Sistemin parçalarını bağımsız olarak test edebilirsiniz:

```bash
# Sadece senaryo üretimini test etmek için:
python generate_script.py

# Sadece seslendirme motorunu test etmek için:
python audio_generator.py

# Sadece stok video ve montaj motorunu test etmek için:
python video_builder.py

# Sadece YouTube yükleme modülünü test etmek için:
python youtube_uploader.py
```

---

## 📜 Lisans

Bu proje [MIT Lisansı](LICENSE) kapsamında lisanslanmıştır. Dilediğiniz gibi geliştirebilir, ticari veya kişisel projelerinizde kullanabilirsiniz.
