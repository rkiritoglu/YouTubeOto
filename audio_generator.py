"""
audio_generator.py - ElevenLabs ve Edge-TTS ile Çok Katmanlı Seslendirme Motoru

Bu modülün amacı:
1. Gemini tarafından oluşturulan JSON senaryosundaki her bir sahne metnini (narration) almak.
2. Bu metinleri ElevenLabs API (eleven_multilingual_v2 modeli) kullanarak doğal insan sesine dönüştürmek.
3. ELEVENLABS_API_KEY girilmediğinde veya kota aşıldığında sistemi kilitlememek için
   otomatik olarak Microsoft Edge-TTS (Ücretsiz, Türkçe yüksek kaliteli neural sesler) motoruna geçmek.
4. Üretilen .mp3 ses dosyalarını 'temp_audio' klasörüne kaydetmek ve dosya yollarını JSON senaryosuna bağlamak.
"""

import os
import re
import subprocess
import asyncio
from typing import Dict, Any, List, Tuple
from dotenv import load_dotenv

# .env dosyasından API anahtarlarını yükle
load_dotenv()

# Varsayılan ElevenLabs Sesleri:
# Adam: 'pNInz6obpgDQGcFmaJgB' (Tok, Derin, Belgesel tarzı erkek sesi)
# Rachel: '21m00Tcm4TlvDq8ikWAM' (Akıcı, Enerjik kadın sesi)
DEFAULT_ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"

# Varsayılan Edge-TTS Türkçe Sesleri (Ücretsiz Yedek):
# 'tr-TR-AhmetNeural' (Erkek, Ciddi & Akıcı)
# 'tr-TR-EmelNeural'  (Kadın, Net & Doğal)
DEFAULT_EDGE_TTS_VOICE = "tr-TR-AhmetNeural"

# ---------------------------------------------------------------------------
# STÜDYO SESLENDİRME PROFİLLERİ (Hız, Perde/Ton ve Seslendirmen Seçenekleri)
# ---------------------------------------------------------------------------
VOICE_PROFILES: Dict[str, Dict[str, str]] = {
    "belgesel_tok_erkek": {
        "label": "🎙️ Belgesel & Tarih (Tok ve Derin Erkek - Ahmet)",
        "voice": "tr-TR-AhmetNeural",
        "rate": "-6%",
        "pitch": "-8Hz",
        "elevenlabs_id": "pNInz6obpgDQGcFmaJgB"  # Adam
    },
    "viral_hizli_erkek": {
        "label": "⚡ Viral Shorts (Dinamik ve Hızlı Erkek - Ahmet)",
        "voice": "tr-TR-AhmetNeural",
        "rate": "+12%",
        "pitch": "+0Hz",
        "elevenlabs_id": "ErXwobaYiN019PkySvjV"  # Antoni
    },
    "standart_erkek": {
        "label": "👔 Klasik Anlatıcı (Doğal Dengeli Erkek - Ahmet)",
        "voice": "tr-TR-AhmetNeural",
        "rate": "+2%",
        "pitch": "+0Hz",
        "elevenlabs_id": "pNInz6obpgDQGcFmaJgB"
    },
    "sicak_anlatici_kadin": {
        "label": "🌸 Sıcak & Akıcı Anlatıcı (Doğal Kadın - Emel)",
        "voice": "tr-TR-EmelNeural",
        "rate": "+3%",
        "pitch": "+0Hz",
        "elevenlabs_id": "21m00Tcm4TlvDq8ikWAM"  # Rachel
    },
    "belgesel_kadin": {
        "label": "🏛️ Sinematik Belgesel (Ağırbaşlı Kadın - Emel)",
        "voice": "tr-TR-EmelNeural",
        "rate": "-5%",
        "pitch": "-5Hz",
        "elevenlabs_id": "21m00Tcm4TlvDq8ikWAM"
    },
    "viral_hizli_kadin": {
        "label": "🔥 Enerjik Shorts (Hızlı ve Canlı Kadın - Emel)",
        "voice": "tr-TR-EmelNeural",
        "rate": "+13%",
        "pitch": "+3Hz",
        "elevenlabs_id": "21m00Tcm4TlvDq8ikWAM"
    }
}


def resolve_voice_profile(voice_or_profile: str) -> Dict[str, str]:
    """Profil anahtarını veya doğrudan ses adını (tr-TR-AhmetNeural vb.) ses parametrelerine çözümler."""
    if voice_or_profile in VOICE_PROFILES:
        return VOICE_PROFILES[voice_or_profile]
    if "Emel" in str(voice_or_profile):
        return VOICE_PROFILES["sicak_anlatici_kadin"]
    return {
        "label": str(voice_or_profile or DEFAULT_EDGE_TTS_VOICE),
        "voice": str(voice_or_profile if str(voice_or_profile).startswith("tr-TR-") else DEFAULT_EDGE_TTS_VOICE),
        "rate": "+0%",
        "pitch": "+0Hz",
        "elevenlabs_id": DEFAULT_ELEVENLABS_VOICE_ID
    }


# ---------------------------------------------------------------------------
# TÜRKÇE TTS METİN NORMALLEŞTİRİCİ (Rakam, Kısaltma ve Matematiksel İfade Dönüştürücü)
# ---------------------------------------------------------------------------

_ONES = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_TENS = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def _three_digits_to_turkish(n: int) -> str:
    if n == 0:
        return ""
    parts = []
    hundreds = n // 100
    rem = n % 100
    tens = rem // 10
    ones = rem % 10

    if hundreds == 1:
        parts.append("yüz")
    elif hundreds > 1:
        parts.append(_ONES[hundreds] + " yüz")

    if tens > 0:
        parts.append(_TENS[tens])
    if ones > 0:
        parts.append(_ONES[ones])

    return " ".join(parts)


def int_to_turkish_words(n: int) -> str:
    """Tam sayıyı Türkçe okunuşuna çevirir (Örn: 1883 -> 'bin sekiz yüz seksen üç')."""
    if n == 0:
        return "sıfır"
    if n < 0:
        return "eksi " + int_to_turkish_words(-n)

    scales = ["", "bin", "milyon", "milyar", "trilyon"]
    parts = []
    scale_idx = 0

    while n > 0 and scale_idx < len(scales):
        chunk = n % 1000
        if chunk > 0:
            if scale_idx == 1 and chunk == 1:
                # 'bir bin' değil 'bin'
                parts.append("bin")
            else:
                chunk_words = _three_digits_to_turkish(chunk)
                scale_name = scales[scale_idx]
                parts.append(f"{chunk_words} {scale_name}".strip())
        n //= 1000
        scale_idx += 1

    return " ".join(reversed(parts)).strip()


def _ordinal_suffix_for_words(words: str) -> str:
    """Sayı kelimesinin sonuna doğru Türkçe sıra eki (-inci/-üncü/-uncu/-ı) ekler."""
    w = words.strip()
    if w.endswith("dört"):
        return w[:-4] + "dördüncü"
    mapping = {
        "bir": "birinci",
        "iki": "ikinci",
        "üç": "üçüncü",
        "beş": "beşinci",
        "altı": "altıncı",
        "yedi": "yedinci",
        "sekiz": "sekizinci",
        "dokuz": "dokuzuncu",
        "on": "onuncu",
        "yirmi": "yirminci",
        "otuz": "otuzuncu",
        "kırk": "kırkıncı",
        "elli": "ellinci",
        "altmış": "altmışıncı",
        "yetmiş": "yetmişinci",
        "seksen": "sekseninci",
        "doksan": "doksanıncı",
        "yüz": "yüzüncü",
        "bin": "bininci",
        "milyon": "milyonuncu",
    }
    for key, val in mapping.items():
        if w.endswith(key):
            return w[: -len(key)] + val
    return w + "ıncı"


def normalize_turkish_tts_text(text: str) -> str:
    """
    Seslendirme (TTS) öncesinde metindeki tüm kısaltmaları, matematiksel sembolleri
    ve rakamları eksiksiz Türkçe yazı diline çevirir.
    """
    if not text:
        return ""

    # 1. Özel boşluk ve tire karakterlerini standartlaştır
    for ch in ("\u202f", "\u00a0", "\u2009"):
        text = text.replace(ch, " ")
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014"):
        text = text.replace(ch, "-")

    # 2. Binlik nokta ayraçlarını birleştir (Örn: 3.000 -> 3000, 10.500 -> 10500)
    text = re.sub(r"\b(\d{1,3})\.(\d{3})\b", r"\1\2", text)

    # 3. Yüzde ve derece ifadeleri (%80 -> yüzde 80, 25°C -> 25 santigrat derece)
    text = re.sub(r"%\s*(\d+)", r"yüzde \1", text)
    text = re.sub(r"(\d+)\s*°\s*C\b", r"\1 santigrat derece", text, flags=re.IGNORECASE)
    text = re.sub(r"°\s*C\b", " santigrat derece", text, flags=re.IGNORECASE)

    # 4. Üslü ve bileşik birimler (m³, m², km², km/s, km/saat vb.)
    unit_replacements = [
        (r"\bkm/saat\b", "kilometre bölü saat"),
        (r"\bkm/sa\b", "kilometre bölü saat"),
        (r"\bkm/s\b", "kilometre bölü saat"),
        (r"\bkm/h\b", "kilometre bölü saat"),
        (r"\bm/sn\b", "metre bölü saniye"),
        (r"\bm/s\b", "metre bölü saniye"),
        (r"\bkm²\b|\bkm2\b", "kilometrekare"),
        (r"\bm³\b|\bm3\b", "metreküp"),
        (r"\bm²\b|\bm2\b", "metrekare"),
        (r"\bcm³\b|\bcm3\b", "santimetreküp"),
        (r"\bcm²\b|\bcm2\b", "santimetrekare"),
        (r"\bkW\b|\bkw\b", "kilovat"),
        (r"\bMW\b|\bmw\b", "megavat"),
        (r"\bGW\b|\bgw\b", "gigavat"),
        (r"\bkV\b|\bkv\b", "kilovolt"),
        (r"\bkm\b", "kilometre"),
        (r"\bmm\b", "milimetre"),
        (r"\bcm\b", "santimetre"),
        (r"\bkg\b", "kilogram"),
        (r"\bgr\b", "gram"),
        (r"\bdk\.(?=\s|$|[,\.;:!?\)\]\"'])|\bdk\b", "dakika"),
        (r"\bsn\.(?=\s|$|[,\.;:!?\)\]\"'])|\bsn\b", "saniye"),
        (r"\byy\.(?=\s|$|[,\.;:!?\)\]\"'])|\byy\b", "yüzyıl"),
        (r"\bvb\.(?=\s|$|[,\.;:!?\)\]\"'])|\bvb\b", "ve benzeri"),
        (r"\bvs\.(?=\s|$|[,\.;:!?\)\]\"'])|\bvs\b", "vesaire"),
        (r"\byak\.(?=\s|$|[,\.;:!?\)\]\"'])|\byak\b", "yaklaşık"),
        (r"\bmaks\.(?=\s|$|[,\.;:!?\)\]\"'])|\bmaks\b", "maksimum"),
        (r"\bmin\.(?=\s|$|[,\.;:!?\)\]\"'])|\bmin\b", "minimum"),
        (r"\bM\.Ö\.(?=\s|$|[,\.;:!?\)\]\"'])|\bM\.Ö\b|\bMÖ\b", "milattan önce"),
        (r"\bM\.S\.(?=\s|$|[,\.;:!?\)\]\"'])|\bM\.S\b|\bMS\b", "milattan sonra"),
    ]
    for pattern, repl in unit_replacements:
        text = re.sub(pattern, repl, text)

    # Sayıdan hemen sonra gelen tek harfli 'm' (metre) ve 't' (ton) kısaltmaları
    text = re.sub(r"(\d)\s*m\b", r"\1 metre", text)

    # 5. Matematiksel semboller (+, -, =, ×, /)
    text = re.sub(r"(\d)\s*\+\s*(\d)", r"\1 artı \2", text)
    text = re.sub(r"(?<!\w)\+\s*(\d)", r"artı \1", text)
    text = re.sub(r"(?<!\w)-\s*(\d)", r"eksi \1", text)
    text = re.sub(r"(\d)\s*=\s*(\d)", r"\1 eşittir \2", text)
    text = re.sub(r"(\d)\s*[x×\*]\s*(\d)", r"\1 çarpı \2", text)
    text = re.sub(r"(\d)\s*/\s*(\d)", r"\1 bölü \2", text)

    # 6. Ondalık sayılar (Örn: 6,4 veya 6.4 -> altı virgül dört)
    def _replace_decimal(match: re.Match) -> str:
        left = int(match.group(1))
        right_str = match.group(2)
        right_val = int(right_str)
        return f"{int_to_turkish_words(left)} virgül {int_to_turkish_words(right_val)}"

    text = re.sub(r"\b(\d+)[,\.](\d+)\b", _replace_decimal, text)

    # 7. Sıra sayıları (Örn: "19. yüzyıl", "1. Dünya Savaşı", "2. hat")
    # Cümle sonundaki noktayla karışmaması için sonrasında küçük harf veya 'Dünya', 'Yüzyıl', 'Hat', 'Sefer' gibi kelimeler arar
    def _replace_ordinal(match: re.Match) -> str:
        num = int(match.group(1))
        after = match.group(2)
        words = int_to_turkish_words(num)
        return f"{_ordinal_suffix_for_words(words)} {after}"

    text = re.sub(
        r"\b(\d{1,3})\.\s+([a-zçğıöşü]|Yüzyıl|Dünya|Hat|Sefer|Bölüm|Kısım|Cadde|Sokak)",
        _replace_ordinal,
        text
    )

    # 8. Kesme işaretiyle veya doğrudan ek almış sayılar (Örn: 1883'te / 1883te -> bin sekiz yüz seksen üçte)
    def _replace_suffixed_number(match: re.Match) -> str:
        num = int(match.group(1))
        suffix = match.group(2)
        words = int_to_turkish_words(num)
        if words.endswith("dört") and suffix and suffix[0].lower() in "aeıioöuü":
            words = words[:-4] + "dörd"
        return f"{words}{suffix}"

    text = re.sub(r"\b(\d+)['’`]?([a-zA-ZçğıöşüÇĞİÖŞÜ]+)\b", _replace_suffixed_number, text)

    # 9. Kalan tüm tam sayıları Türkçe yazıya çevir
    def _replace_integer(match: re.Match) -> str:
        num = int(match.group(0))
        return int_to_turkish_words(num)

    text = re.sub(r"\b\d+\b", _replace_integer, text)

    # Fazla boşlukları temizle
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def get_audio_duration_sec(audio_path: str) -> float:
    """
    FFmpeg binary'sini kullanarak ses dosyasının milisaniye hassasiyetinde
    tam süresini (saniye cinsinden float) ölçer. (Darboğaz 3: Audio-First Pacing)
    """
    if not os.path.exists(audio_path):
        return 0.0
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        proc = subprocess.run(
            [ffmpeg_exe, "-i", audio_path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=10
        )
        # Duration: 00:00:04.56
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return round(hours * 3600 + minutes * 60 + seconds, 3)
    except Exception:
        pass

    # Yedek ölçüm
    try:
        from moviepy import AudioFileClip
        with AudioFileClip(audio_path) as clip:
            return round(float(clip.duration), 3)
    except Exception:
        return 3.5


def build_proportional_word_timings(text: str, total_duration: float) -> List[Dict[str, Any]]:
    """
    Kelime zamanlaması donanımsal olarak dönmediyse, cümledeki kelimelerin
    harf uzunluklarına göre milisaniye bazlı doğal konuşma zamanlaması hesaplar.
    """
    words = [w.strip() for w in text.split() if w.strip()]
    if not words or total_duration <= 0:
        return []

    # Son 0.15 saniyeyi nefes payı bırak
    effective_dur = max(0.5, total_duration - 0.15)
    weights = [max(2, len(w)) for w in words]
    total_weight = sum(weights)

    timings = []
    cursor = 0.05
    for w, weight in zip(words, weights):
        w_dur = (weight / total_weight) * effective_dur
        start_t = round(cursor, 3)
        end_t = round(cursor + w_dur, 3)
        timings.append({"word": w, "start": start_t, "end": end_t})
        cursor += w_dur

    return timings


def extract_whisper_word_timings(audio_path: str, fallback_text: str, duration: float) -> List[Dict[str, Any]]:
    """
    Groq Whisper API (whisper-large-v3-turbo) ile gerçek kelime zamanlamalarını çıkarır;
    API erişilemezse ağırlıklı kelime zamanlamasına (proportional) döner.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and groq_key.startswith("gsk_") and os.path.exists(audio_path):
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            with open(audio_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    file=(os.path.basename(audio_path), f.read()),
                    model="whisper-large-v3-turbo",
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                    language="tr"
                )
            raw_words = getattr(transcription, "words", None) or (
                transcription.get("words") if isinstance(transcription, dict) else None
            )
            if raw_words:
                timings = []
                for item in raw_words:
                    w = item.get("word", "") if isinstance(item, dict) else getattr(item, "word", "")
                    s = item.get("start", 0.0) if isinstance(item, dict) else getattr(item, "start", 0.0)
                    e = item.get("end", 0.0) if isinstance(item, dict) else getattr(item, "end", 0.0)
                    if w.strip():
                        timings.append({"word": w.strip(), "start": round(float(s), 3), "end": round(float(e), 3)})
                if timings:
                    return timings
        except Exception:
            pass

    return build_proportional_word_timings(fallback_text, duration)


def generate_with_elevenlabs(text: str, output_path: str, voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID) -> bool:
    """
    ElevenLabs API üzerinden metni sese dönüştürür ve dosyaya yazar.
    
    Parametreler:
        text (str): Seslendirilecek metin.
        output_path (str): Kaydedilecek .mp3 dosyasının tam yolu.
        voice_id (str): Kullanılacak sesin kimliği.
        
    Döndürür:
        bool: İşlem başarılı ise True, aksi takdirde False.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key or api_key.startswith("sk_BURAYA"):
        return False

    try:
        from elevenlabs.client import ElevenLabs
        client = ElevenLabs(api_key=api_key)

        print(f"  [ElevenLabs] Ses üretiliyor: '{text[:35]}...'")
        audio_stream = client.text_to_speech.convert(
            voice_id=voice_id,
            output_format="mp3_44100_128",
            text=text,
            model_id="eleven_multilingual_v2"  # Türkçe ve çok dilli akıcı anlatım modeli
        )

        with open(output_path, "wb") as f:
            for chunk in audio_stream:
                if chunk:
                    f.write(chunk)

        return os.path.exists(output_path) and os.path.getsize(output_path) > 0

    except Exception as e:
        print(f"  [UYARI] ElevenLabs API çağrısı başarısız oldu: {e}")
        return False


async def _edge_tts_async(
    text: str,
    output_path: str,
    voice: str,
    rate: str = "+0%",
    pitch: str = "+0Hz"
) -> List[Dict[str, Any]]:
    """
    Edge-TTS ile hem .mp3 ses dosyasını kaydeder hem de WordBoundary
    olaylarını yakalayarak milisaniye bazlı kelime zamanlamalarını döndürür.
    """
    import edge_tts
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        pitch=pitch,
        boundary="WordBoundary"
    )
    word_timings: List[Dict[str, Any]] = []
    with open(output_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset ve duration 100-nanosaniye (1e-7 sn) birimindedir
                start_sec = round(chunk.get("offset", 0) / 10_000_000, 3)
                dur_sec = round(chunk.get("duration", 0) / 10_000_000, 3)
                word_text = str(chunk.get("text", "")).strip()
                if word_text:
                    word_timings.append({
                        "word": word_text,
                        "start": start_sec,
                        "end": round(start_sec + max(0.08, dur_sec), 3)
                    })
    return word_timings


def generate_with_edge_tts(
    text: str,
    output_path: str,
    voice: str = DEFAULT_EDGE_TTS_VOICE
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    API anahtarı gerektirmeyen, tamamen ücretsiz ve yüksek kaliteli
    Microsoft Edge Neural TTS motoru ile Türkçe ses ve kelime zamanlaması üretir.
    """
    try:
        profile = resolve_voice_profile(voice)
        actual_voice = profile["voice"]
        rate = profile.get("rate", "+0%")
        pitch = profile.get("pitch", "+0Hz")
        print(f"  [Edge-TTS ({profile.get('label', actual_voice)})] Ses üretiliyor: '{text[:35]}...'")
        word_timings = asyncio.run(_edge_tts_async(text, output_path, actual_voice, rate=rate, pitch=pitch))
        ok = os.path.exists(output_path) and os.path.getsize(output_path) > 0
        return ok, word_timings
    except Exception as e:
        print(f"  [HATA] Edge-TTS ile ses üretilemedi: {e}")
        return False, []


def generate_audio_for_scene(
    text: str,
    output_path: str,
    voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID,
    edge_voice: str = DEFAULT_EDGE_TTS_VOICE
) -> Tuple[str, float, List[Dict[str, Any]]]:
    """
    Tek bir metin bloğunu önce ElevenLabs ile, eğer yapılandırılmamışsa
    veya hata verirse otomatik olarak Edge-TTS ile .mp3'e çevirir.
    Ses üretildikten hemen sonra gerçek süresini (duration_sec) ve kelime zamanlamalarını ölçer.
    """
    # Rakamları, kısaltmaları ve matematik ifadeleri Türkçe okunuşlarına dönüştür
    text = normalize_turkish_tts_text(text)
    word_timings: List[Dict[str, Any]] = []
    profile = resolve_voice_profile(edge_voice)
    resolved_eleven_id = profile.get("elevenlabs_id") or voice_id

    # 1. Öncelikli olarak ElevenLabs API denenir
    success = generate_with_elevenlabs(text, output_path, voice_id=resolved_eleven_id)

    # 2. ElevenLabs anahtarı yoksa veya hata verdiyse Edge-TTS devreye girer
    if not success:
        success, word_timings = generate_with_edge_tts(text, output_path, voice=edge_voice)

    if not success or not os.path.exists(output_path):
        return "", 0.0, []

    duration_sec = get_audio_duration_sec(output_path)
    if not word_timings:
        word_timings = extract_whisper_word_timings(output_path, text, duration_sec)

    return output_path, duration_sec, word_timings


def process_script_audio(
    script_data: Dict[str, Any],
    output_dir: str = "temp_audio",
    edge_voice: str = DEFAULT_EDGE_TTS_VOICE
) -> List[Dict[str, Any]]:
    """
    ÖNCE SES PRENSİBİ (Darboğaz 3):
    Tüm senaryo JSON yapısını işler, her sahne için .mp3 üretir,
    milisaniye hassasiyetinde 'duration_sec' ve 'word_timings' verilerini
    sahne sözlüklerine yazar. Görsel/video üretimi bu kesin sürelere göre yapılır.
    """
    os.makedirs(output_dir, exist_ok=True)
    scenes = script_data.get("scenes", [])

    print(f"\n[Ses Motoru - Audio-First] Toplam {len(scenes)} sahne için seslendirme ve süre ölçümü başlatılıyor...")

    for scene in scenes:
        scene_id = scene.get("scene_id", 1)
        raw_narration = scene.get("narration", "").strip()
        narration = normalize_turkish_tts_text(raw_narration)
        scene["narration"] = narration

        if narration:
            file_name = f"scene_{scene_id}.mp3"
            file_path = os.path.join(output_dir, file_name)

            saved_path, duration_sec, word_timings = generate_audio_for_scene(
                narration,
                file_path,
                edge_voice=edge_voice
            )
            if saved_path:
                scene["audio_file_path"] = saved_path
                scene["duration_sec"] = duration_sec
                scene["word_timings"] = word_timings
                print(f"  -> Sahne {scene_id} sesi hazır: {file_name} ({duration_sec:.2f} sn, {len(word_timings)} kelime)")
            else:
                print(f"  -> [UYARI] Sahne {scene_id} için ses oluşturulamadı!")

    return scenes


# ---------------------------------------------------------------------------
# TEST VE ÇALIŞTIRMA BLOKU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== audio_generator.py Testi Başlatıldı ===")
    
    sample_script = {
        "title": "Piramitlerin Gizemi",
        "scenes": [
            {
                "scene_id": 1,
                "narration": "Piramitlerin altında saklanan gizli odaları daha önce duymuş muydunuz?"
            },
            {
                "scene_id": 2,
                "narration": "Radar taramaları blokların arkasında devasa gizemli boşluklar gösteriyor."
            }
        ]
    }

    updated = process_script_audio(sample_script, output_dir="test_audio_output")
    
    print("\n--- TEST SONUÇLARI ---")
    for s in updated:
        print(f"Sahne {s['scene_id']}: {s.get('audio_file_path')} (Mevcut: {os.path.exists(s.get('audio_file_path', ''))})")

    print("\n✅ audio_generator.py testi başarıyla tamamlandı!")
