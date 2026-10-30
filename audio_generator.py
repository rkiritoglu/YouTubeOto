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
import asyncio
from typing import Dict, Any, List
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


async def _edge_tts_async(text: str, output_path: str, voice: str):
    """Edge-TTS kütüphanesi asenkron çalıştığı için yardımcı asenkron fonksiyon."""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def generate_with_edge_tts(text: str, output_path: str, voice: str = DEFAULT_EDGE_TTS_VOICE) -> bool:
    """
    API anahtarı gerektirmeyen, tamamen ücretsiz ve yüksek kaliteli
    Microsoft Edge Neural TTS motoru ile Türkçe ses üretir.
    """
    try:
        print(f"  [Edge-TTS (Ücretsiz)] Ses üretiliyor: '{text[:35]}...'")
        asyncio.run(_edge_tts_async(text, output_path, voice))
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"  [HATA] Edge-TTS ile ses üretilemedi: {e}")
        return False


def generate_audio_for_scene(text: str, output_path: str, voice_id: str = DEFAULT_ELEVENLABS_VOICE_ID) -> str:
    """
    Tek bir metin bloğunu önce ElevenLabs ile, eğer yapılandırılmamışsa
    veya hata verirse otomatik olarak Edge-TTS ile .mp3'e çevirir.
    
    Parametreler:
        text (str): Seslendirilecek metin.
        output_path (str): .mp3 çıktı yolu.
        voice_id (str): ElevenLabs ses ID'si.
        
    Döndürür:
        str: Başarıyla kaydedilen dosya yolu, başarısızsa boş string.
    """
    # 1. Öncelikli olarak ElevenLabs API denenir
    success = generate_with_elevenlabs(text, output_path, voice_id=voice_id)

    # 2. ElevenLabs anahtarı yoksa veya hata verdiyse Edge-TTS devreye girer
    if not success:
        success = generate_with_edge_tts(text, output_path)

    if success:
        return output_path
    return ""


def process_script_audio(script_data: Dict[str, Any], output_dir: str = "temp_audio") -> List[Dict[str, Any]]:
    """
    Gemini'den gelen tüm senaryo JSON yapısını işler, her sahne için .mp3 üretir
    ve dosya yollarını sahne sözlüklerine 'audio_file_path' anahtarıyla ekler.
    
    Parametreler:
        script_data (Dict): Gemini tarafından üretilen senaryo verisi.
        output_dir (str): Ses dosyalarının depolanacağı geçici klasör.
        
    Döndürür:
        List[Dict[str, Any]]: 'audio_file_path' eklenmiş güncel sahneler listesi.
    """
    os.makedirs(output_dir, exist_ok=True)
    scenes = script_data.get("scenes", [])

    print(f"\n[Ses Motoru] Toplam {len(scenes)} sahne için seslendirme başlatılıyor...")

    for scene in scenes:
        scene_id = scene.get("scene_id", 1)
        narration = scene.get("narration", "").strip()

        if narration:
            file_name = f"scene_{scene_id}.mp3"
            file_path = os.path.join(output_dir, file_name)

            saved_path = generate_audio_for_scene(narration, file_path)
            if saved_path:
                scene["audio_file_path"] = saved_path
                print(f"  -> Sahne {scene_id} sesi hazır: {file_name}")
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
