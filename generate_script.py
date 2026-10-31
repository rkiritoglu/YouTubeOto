"""
generate_script.py - Groq (Llama 3.3) ve Gemini Destekli Yapılandırılmış Senaryo Üretici

Bu modülün amacı:
1. Meta'nın en gelişmiş açık kaynaklı Llama 3.3 modelini Groq Cloud API üzerinden
   ışık hızında (ücretsiz, kısıtlamasız ve Google Cloud karmaşası olmadan) çalıştırmak.
2. 'prompts.py' içerisindeki sistem ve kullanıcı prompt şablonlarını modele iletmek.
3. Modelden kesin ve saf JSON çıktısı (JSON Mode) alarak video başlığı, açıklaması,
   etiketleri ve sahne bazlı Türkçe metin ile Pixabay stok arama terimlerini üretmek.
4. Groq anahtarı girilmediğinde Gemini API'yi veya yerleşik zengin senaryo arşivini
   otomatik yedek olarak çalıştırmak.
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

# Gemini yedek modelleri
CANDIDATE_GEMINI_MODELS: List[str] = [
    "gemini-3.5-flash",
    "gemini-3.6-flash",
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-3.8-flash"
]


def generate_with_groq(topic: str, style_preset: str) -> Dict[str, Any]:
    """
    Groq Cloud API üzerinden Llama 3.3 (veya Llama 3.1) kullanarak
    saniyeler içinde JSON formatında dikey video senaryosu üretir.
    """
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key or not groq_key.startswith("gsk_"):
        return {}

    try:
        from groq import Groq
        client = Groq(api_key=groq_key)

        user_prompt = build_script_prompt(topic, style_preset=style_preset)
        
        # En güçlü Llama 3.3 70B modeli (yüksek zeka ve akıcı Türkçe)
        # veya çok hızlı olan Llama 3.1 8B modeli
        models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]

        for model in models_to_try:
            try:
                print(f"  [Groq AI] '{model}' ile senaryo üretiliyor...")
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_SCRIPT_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7,
                    response_format={"type": "json_object"}
                )
                
                raw_content = completion.choices[0].message.content.strip()
                parsed = json.loads(raw_content)
                if parsed and "scenes" in parsed:
                    print(f"  -> Başarılı! Senaryo Groq ({model}) tarafından üretildi.")
                    return parsed
            except Exception as e:
                print(f"  [Uyarı] Groq model '{model}' hatası: {e}")
                continue

    except Exception as e:
        print(f"  [Uyarı] Groq API çağrısı başarısız oldu: {e}")

    return {}


def generate_with_gemini(topic: str, style_preset: str) -> Dict[str, Any]:
    """Gemini API üzerinden yedek senaryo üretimi."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not gemini_key or gemini_key.startswith("AIzaSy_BURAYA") or not gemini_key.startswith("AIzaSy"):
        return {}

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gemini_key)
        user_prompt = build_script_prompt(topic, style_preset=style_preset)

        for model_name in CANDIDATE_GEMINI_MODELS:
            try:
                print(f"  [Gemini AI] '{model_name}' ile senaryo oluşturuluyor...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_SCRIPT_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.7,
                    ),
                )
                raw_text = response.text.strip()
                clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)
                parsed_json = json.loads(clean_text)
                if parsed_json and "scenes" in parsed_json:
                    return parsed_json
            except Exception:
                continue
    except Exception:
        pass

    return {}


def get_mock_script(topic: str) -> Dict[str, Any]:
    """API anahtarı girilmediğinde sistemin kesintiye uğramadan çalışabilmesi için zengin senaryo döndürür."""
    return {
        "title": f"{topic}: Bilinmeyen Gizemler!",
        "description": f"{topic} hakkında duymadığınız en şaşırtıcı detaylar ve gerçekler! #shorts #viral #raylisistemler #trenler #tarih",
        "scenes": [
            {
                "scene_id": 1,
                "narration": f"{topic} hakkında bilinenler sadece buzdağının görünen kısmı.",
                "stock_search_terms": ["steam train dramatic", "railway tracks sunset"],
                "ai_image_prompt": "Cinematic shot of historic railway tracks at dusk with fog, dramatic lighting, 9:16 aspect ratio"
            },
            {
                "scene_id": 2,
                "narration": "Mühendisler tonlarca çelik ve demiri bir araya getirerek bir mucize yarattı.",
                "stock_search_terms": ["train engine detail", "industrial steel machinery"],
                "ai_image_prompt": "Close-up of powerful locomotive engine wheels turning, steam blowing, cinematic 9:16"
            },
            {
                "scene_id": 3,
                "narration": "Sarp dağları, derin vadileri ve aşılmaz engelleri birbirine bağladı.",
                "stock_search_terms": ["train passing mountains", "scenic bridge railway"],
                "ai_image_prompt": "Scenic mountain viaduct bridge with train passing high above green valley, 8k, 9:16"
            },
            {
                "scene_id": 4,
                "narration": "Bugün bile kullanılan bu teknoloji insanlığın en büyük miraslarından biri.",
                "stock_search_terms": ["modern bullet train", "high speed rail"],
                "ai_image_prompt": "Futuristic high-speed bullet train moving fast through neon lit metropolis, 9:16"
            },
            {
                "scene_id": 5,
                "narration": "Peki siz bu efsanevi hat hakkında ne düşünüyorsunuz? Yorumlarda buluşalım!",
                "stock_search_terms": ["train window view", "sunset horizon travel"],
                "ai_image_prompt": "Cinematic POV from train window looking at epic golden sunset, 9:16 aspect ratio"
            }
        ]
    }


def create_youtube_script(topic: str, style_preset: str = "documentary_history") -> Dict[str, Any]:
    """
    Belirtilen konu için önce Groq (Llama 3), sonra Gemini, en son yerel arşivden senaryo üretir.
    """
    print(f"\n[Senaryo Motoru] '{topic}' konusu için dikey senaryo üretiliyor...")

    script_data = None

    # 1. ÖNCELİK: Groq API (Llama 3.3) - En Hızlı ve Sorunsuz
    script_data = generate_with_groq(topic, style_preset)

    # 2. ÖNCELİK: Gemini API
    if not script_data:
        script_data = generate_with_gemini(topic, style_preset)

    # 3. ÖNCELİK: Yerel Şablon Motoru (Sıfır Hata Garantisi)
    if not script_data:
        print("[BİLGİ] Yapay zeka API anahtarı ayarlanmamış veya yanıt vermedi.")
        print("[BİLGİ] Kesintisiz akış için yerleşik senaryo şablonu kullanılıyor.")
        script_data = get_mock_script(topic)

    # Her sahne için görsel promptlarını zenginleştir
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
    TEST_TOPIC = "Orient Express: Doğu Ekspresinin Gizemleri"
    STYLE = "documentary_history"

    print("=== generate_script.py (Groq & Llama 3 Destekli) Test Ediliyor ===")
    result = create_youtube_script(topic=TEST_TOPIC, style_preset=STYLE)

    print("\n--- ÜRETİLEN SENARYO DETAYLARI ---")
    print(f"📌 Başlık: {result.get('title')}")
    print(f"📄 Açıklama: {result.get('description')}")
    print(f"🎬 Toplam Sahne Sayısı: {len(result.get('scenes', []))}")
    
    for scene in result.get("scenes", []):
        print(f"\n[Sahne {scene.get('scene_id')}]")
        print(f"  🎙️ Metin: {scene.get('narration')}")
        print(f"  🔍 Stok Arama Terimleri: {scene.get('stock_search_terms')}")

    print("\n✅ generate_script.py testi başarıyla tamamlandı!")
