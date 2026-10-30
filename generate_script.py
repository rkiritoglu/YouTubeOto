"""
generate_script.py - Google Gemini API ile Yapılandırılmış Senaryo Üretici

Bu modülün amacı:
1. Google'ın yeni 'google-genai' SDK'sını kullanarak güncel Gemini modellerine bağlanmak.
2. 'prompts.py' içerisindeki sistem ve kullanıcı prompt şablonlarını modele iletmek.
3. Modelden kesin ve saf JSON çıktısı (Structured Output / JSON Mode) almak ve Python dictionary'ye çevirmek.
4. Versiyon (404 Not Found) veya anlık yoğunluk (503 High Demand) hatalarına karşı
   otomatik basamaklı model yedekleme zinciri (Cascading Model Fallback) çalıştırmak.
"""

import os
import json
import re
from typing import Dict, Any, List
from dotenv import load_dotenv

# prompts.py modülümüzden kuralları ve yardımcı fonksiyonları içe aktarıyoruz
from prompts import (
    SYSTEM_SCRIPT_PROMPT,
    build_script_prompt,
    enrich_image_prompt
)

# .env dosyasındaki ortam değişkenlerini belleğe yükle
load_dotenv()

# En kararlı ve güncel modellerin öncelik sırasına göre listesi
# Eğer biri 503 yoğunluk veya 404 versiyon hatası verirse sıradakine otomatik geçilir
CANDIDATE_GEMINI_MODELS: List[str] = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.8-flash"
]


def get_gemini_client():
    """
    Ortam değişkenlerinde tanımlı GEMINI_API_KEY ile bir Google GenAI istemcisi oluşturur.
    API anahtarı bulunamazsa None döndürür.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key.startswith("AIzaSy_BURAYA"):
        return None
    
    try:
        from google import genai
        return genai.Client(api_key=api_key)
    except Exception as e:
        print(f"[UYARI] Gemini API istemcisi başlatılamadı: {e}")
        return None


def get_mock_script(topic: str) -> Dict[str, Any]:
    """
    API anahtarı girilmediğinde veya internet/kota kesintisinde
    sistemin kesintiye uğramadan çalışabilmesi için örnek bir dikey video senaryosu döndürür.
    """
    return {
        "title": f"{topic} Hakkında Şoke Eden Gerçekler!",
        "description": f"{topic} hakkında bilmedikleriniz ve gizemler! #shorts #viral #bilgi #tarih",
        "scenes": [
            {
                "scene_id": 1,
                "narration": f"Piramitlerin altında saklanan gizli odaları daha önce hiç duymuş muydunuz?",
                "stock_search_terms": ["pyramids egypt", "desert mystery"],
                "ai_image_prompt": "Cinematic shot of ancient Egyptian pyramids at night with mysterious glowing chambers, 8k, photorealistic, 9:16 aspect ratio"
            },
            {
                "scene_id": 2,
                "narration": "Son yüksek teknoloji radar taramaları, dev blokların ardında devasa boşluklar buldu.",
                "stock_search_terms": ["archeologist radar", "ancient chamber"],
                "ai_image_prompt": "Archeologists with advanced laser scanners inside a dark stone corridor, dust particles in light beam, 9:16 aspect ratio"
            },
            {
                "scene_id": 3,
                "narration": "Bazı uzmanlar bu odalarda kayıp kütüphanelerin saklandığına inanıyor.",
                "stock_search_terms": ["ancient scrolls", "library secrets"],
                "ai_image_prompt": "Ancient hidden underground library with golden artifacts and mysterious papyrus scrolls, dramatic lighting, 9:16 aspect ratio"
            },
            {
                "scene_id": 4,
                "narration": "Gerçekleri öğrenmek için takipte kalın ve videoyu beğenmeyi unutmayın!",
                "stock_search_terms": ["dramatic sky", "sunset desert"],
                "ai_image_prompt": "Epic sunset over the desert horizon, cinematic wind blowing sand, masterpiece, 9:16 aspect ratio"
            }
        ]
    }


def create_youtube_script(topic: str, style_preset: str = "documentary_history") -> Dict[str, Any]:
    """
    Belirtilen konu ve stil şablonuna göre Gemini API üzerinden
    JSON formatında senaryo ve görsel/stok arama verilerini üretir.
    
    Parametreler:
        topic (str): Video konusu (Örn: 'Büyük Piramitlerin Altındaki Gizli Odalar').
        style_preset (str): Görsel ve kurgu stili (Örn: 'documentary_history', 'cinematic_dark').
        
    Döndürür:
        Dict[str, Any]: Başlık, açıklama ve sahne detaylarını içeren Python sözlüğü.
    """
    print(f"\n[Gemini API] '{topic}' konusu için dikey senaryo üretiliyor...")

    client = get_gemini_client()

    # Eğer geçerli bir Gemini API anahtarı yoksa test/mock senaryosunu devreye al
    if client is None:
        print("[BİLGİ] Geçerli bir GEMINI_API_KEY bulunamadı veya henüz ayarlanmadı.")
        print("[BİLGİ] Sistem kesintisiz test için yerleşik zengin şablonu (Simülasyon Senaryosu) kullanıyor.")
        script_data = get_mock_script(topic)
    else:
        from google.genai import types

        # prompts.py dosyasındaki fonksiyonla kullanıcı komutunu hazırla
        user_prompt = build_script_prompt(topic, style_preset=style_preset)
        script_data = None

        # Modelleri sırayla dene (Versiyon 404 veya 503 yoğunluk hatalarına karşı korumalı)
        for model_name in CANDIDATE_GEMINI_MODELS:
            try:
                print(f"  [Model Deneniyor] '{model_name}' ile senaryo oluşturuluyor...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_SCRIPT_PROMPT,
                        response_mime_type="application/json",  # Kesin JSON çıktısı garantiler
                        temperature=0.7,
                    ),
                )

                raw_text = response.text.strip()
                # Olası markdown işaretlerini (```json ... ```) temizle
                clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)

                parsed_json = json.loads(clean_text)
                if parsed_json and "scenes" in parsed_json:
                    script_data = parsed_json
                    print(f"  -> Başarılı! Model: '{model_name}'")
                    break

            except Exception as e:
                err_msg = str(e)
                # Kısa ve temiz hata teşhisi
                if "404" in err_msg or "not found" in err_msg.lower():
                    print(f"  [Versiyon Uyarısı] '{model_name}' bu API sürümünde aktif değil, sıradaki modele geçiliyor...")
                elif "503" in err_msg or "UNAVAILABLE" in err_msg:
                    print(f"  [Yoğunluk Uyarısı] '{model_name}' şu anda aşırı talep alıyor, sıradaki modele geçiliyor...")
                else:
                    print(f"  [Uyarı] '{model_name}' çağrısı başarısız oldu: {err_msg[:60]}... Sıradaki deneniyor.")

        # Eğer tüm modeller başarısız olursa yerel yedek senaryoyu devreye sok
        if script_data is None:
            print("[UYARI] Tüm Gemini modelleri meşguldü veya hata verdi.")
            print("[BİLGİ] Kesintisiz akış için yerleşik senaryo şablonu kullanılıyor.")
            script_data = get_mock_script(topic)

    # Her sahne için görsel promptlarını prompts.py içerisindeki fonksiyonla zenginleştir
    for scene in script_data.get("scenes", []):
        raw_ai_prompt = scene.get("ai_image_prompt", "")
        if raw_ai_prompt:
            scene["ai_image_prompt_enhanced"] = enrich_image_prompt(
                raw_ai_prompt,
                style_key=style_preset
            )

    return script_data


# ---------------------------------------------------------------------------
# TEST VE ÇALIŞTIRMA BLOKU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    TEST_TOPIC = "Büyük Piramitlerin Altında Bulunan Gizli Odalar"
    STYLE = "documentary_history"

    print("=== generate_script.py Testi Başlatıldı ===")
    result = create_youtube_script(topic=TEST_TOPIC, style_preset=STYLE)

    print("\n--- ÜRETİLEN SENARYO DETAYLARI ---")
    print(f"📌 Başlık: {result.get('title')}")
    print(f"📄 Açıklama: {result.get('description')}")
    print(f"🎬 Toplam Sahne Sayısı: {len(result.get('scenes', []))}")
    
    for scene in result.get("scenes", []):
        print(f"\n[Sahne {scene.get('scene_id')}]")
        print(f"  🎙️ Metin: {scene.get('narration')}")
        print(f"  🔍 Stok Arama Terimleri: {scene.get('stock_search_terms')}")
        print(f"  🎨 Görsel Prompt: {scene.get('ai_image_prompt_enhanced')[:60]}...")

    print("\n✅ generate_script.py testi başarıyla tamamlandı!")
