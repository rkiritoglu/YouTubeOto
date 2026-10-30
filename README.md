# 🎬 YouTube Shorts AI Automation Pipeline

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Google Gemini API](https://img.shields.io/badge/AI-Gemini%202.5%20Flash-4285F4.svg)](https://aistudio.google.com/)
[![Pixabay API](https://img.shields.io/badge/Stock%20Video-Pixabay%20API-00ab6b.svg)](https://pixabay.com/api/docs/)
[![MoviePy](https://img.shields.io/badge/Video-MoviePy%20v2-red.svg)](https://zulko.github.io/moviepy/)

Yapay zeka kullanarak **YouTube Shorts**, **TikTok** ve **Instagram Reels** için dikey formatta (9:16) uçtan uca otomatik video üreten ve YouTube Data API v3 ile doğrudan kanala yükleyen açık kaynaklı bir otomasyon sistemidir.

---

## 🌟 Öne Çıkan Özellikler

- **🧠 Akıllı Senaryo & Kurgu (Google Gemini API):** İlk 3 saniyede izleyiciyi ekrana bağlayan (Hook) viral senaryolar, sahne bazlı stok video arama anahtar kelimeleri ve YouTube SEO meta verileri (başlık, açıklama, etiketler) üretir.
- **🎙️ Çok Katmanlı Ses Motoru (ElevenLabs + Edge-TTS):** ElevenLabs API ile ultra gerçekçi insan seslendirmesi yapar. API anahtarı girilmediğinde veya kota bittiğinde otomatik olarak **ücretsiz Microsoft Edge-TTS Türkçe doğal seslerine** (`tr-TR-AhmetNeural` / `tr-TR-EmelNeural`) geçiş yapar.
- **🎞️ Dikey Stok Video ve Montaj (Pixabay + MoviePy):** Pixabay API üzerinden sahnelerle eşleşen telifsiz HD stok videoları bulur, akıllı merkez kırpma (center-crop) ile dikey 1080x1920 (9:16) formatına dönüştürür ve ses sürelerine göre MoviePy motoru ile otomatik MP4 render eder.
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
          │                ├─ Sahne Bazlı Pixabay Arama Kelimeleri
          │                └─ YouTube Başlık, Açıklama ve Etiketler
          ▼
[ audio_generator.py ] ──> ElevenLabs API / Edge-TTS (Ücretsiz Türkçe Ses)
          │                └─ Her sahne için senkronize .mp3 dosyaları
          ▼
[ video_builder.py ]   ──> Pixabay API + MoviePy (Center-Crop 9:16)
          │                ├─ Telifsiz Stok Video İndirme
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
├── .env.example              # API anahtarları için örnek yapılandırma
├── .gitignore                # Hassas verilerin ve geçici medyaların gizlenmesi
├── requirements.txt          # Gerekli Python kütüphaneleri
├── LICENSE                   # MIT Açık Kaynak Lisansı
├── README.md                 # Proje dokümantasyonu
│
├── prompts.py                # Viral Shorts kuralları, promptlar ve görsel stil şablonları
├── generate_script.py        # Gemini API ile JSON formatında senaryo üretici
├── audio_generator.py        # ElevenLabs ve Edge-TTS seslendirme motoru
├── video_builder.py          # Pixabay stok video indirici ve MoviePy montajlayıcı
├── youtube_uploader.py       # YouTube Data API v3 ile video yükleyici
└── main.py                   # Tek tıkla tüm iş akışını yöneten ana orkestrasyon dosyası
```

---

## 🚀 Hızlı Başlangıç

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/rkiritoglu/YouTubeOto.git
cd YouTubeOto
```

### 2. Sanal Ortam Oluşturun ve Bağımlılıkları Yükleyin
```bash
# Sanal ortam oluşturma
python -m venv venv

# Sanal ortamı aktifleştirme (Windows)
venv\Scripts\activate

# Paketleri yükleme
pip install -r requirements.txt
```

### 3. Çevre Değişkenlerini Yapılandırın
`.env.example` dosyasını `.env` olarak kopyalayın:
```bash
cp .env.example .env
```
Ardından `.env` dosyasını açıp API anahtarlarınızı girin:
- **`PIXABAY_API_KEY`**: [Pixabay API Docs](https://pixabay.com/api/docs/) adresinden anında ve ücretsiz alınabilir.
- **`GEMINI_API_KEY`**: [Google AI Studio](https://aistudio.google.com/app/apikey)'dan ücretsiz alınabilir.
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

---

## 📜 Lisans

Bu proje [MIT Lisansı](LICENSE) kapsamında lisanslanmıştır. Dilediğiniz gibi geliştirebilir, ticari veya kişisel projelerinizde kullanabilirsiniz.
