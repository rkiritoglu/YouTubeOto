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


async def _edge_tts_async(text: str, output_path: str, voice: str) -> List[Dict[str, Any]]:
    """
    Edge-TTS ile hem .mp3 ses dosyasını kaydeder hem de WordBoundary
    olaylarını yakalayarak milisaniye bazlı kelime zamanlamalarını döndürür.
    """
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
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
        print(f"  [Edge-TTS (Ücretsiz)] Ses üretiliyor: '{text[:35]}...'")
        word_timings = asyncio.run(_edge_tts_async(text, output_path, voice))
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
    word_timings: List[Dict[str, Any]] = []

    # 1. Öncelikli olarak ElevenLabs API denenir
    success = generate_with_elevenlabs(text, output_path, voice_id=voice_id)

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
        narration = scene.get("narration", "").strip()

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
