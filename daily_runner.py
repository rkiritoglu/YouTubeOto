"""
daily_runner.py - Tam Otonom Raylı Sistemler YouTube Shorts Üretim ve Yükleme Robotu

Bu modülün amacı:
1. İnsan müdahalesi olmadan, hem tarihi hem de modern raylı sistemler dünyasından
   (efsanevi lokomotifler, hızlı trenler, mühendislik harikaları, gizemli trenler)
   her gün YouTube Shorts için izlenme oranı yüksek yepyeni bir konu seçmek.
2. Gemini API ile canlı konu araştırması yapar; API geçici olarak yanıt vermezse
   zengin yerleşik raylı sistemler arşivinden daha önce hiç işlenmemiş bir konuyu seçer.
3. Daha önce işlenen konuları 'yapilan_konular.txt' dosyasında tutarak ASLA konu tekrarı yapmaz.
4. Seçilen konuyu sırasıyla: Senaryo Yazımı -> Seslendirme -> Pixabay Stok Video -> MoviePy Montaj -> YouTube Otomatik Yükleme
   adımlarıyla kanala yükler.
"""

import os
import sys
import json
import random
import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Ana otomasyon fonksiyonlarını içe aktar
from main import run_full_youtube_pipeline
from generate_script import get_gemini_client, CANDIDATE_GEMINI_MODELS

# .env değişkenlerini yükle
load_dotenv()

HISTORY_FILE = "yapilan_konular.txt"

# ---------------------------------------------------------------------------
# ZENGİN RAYLI SİSTEMLER YEDEK KONU HAVUZU (Tarihi + Güncel)
# ---------------------------------------------------------------------------
RAILWAY_TOPICS_POOL = [
    # --- TARİHİ TRENLER VE DEMİRYOLU EFSANELERİ ---
    {"topic": "Orient Express: Doğu Ekspresi'nin Çözülemeyen Gizemleri", "style": "documentary_history"},
    {"topic": "Dünyanın En Güçlü Buharlı Lokomotifi: Big Boy 4014", "style": "documentary_history"},
    {"topic": "Tarihteki En Hızlı Buharlı Tren: Mallard 4468", "style": "documentary_history"},
    {"topic": "Hicaz Demiryolu: Çölün Ortasındaki İnanılmaz Mühendislik", "style": "documentary_history"},
    {"topic": "Trans-Sibirya: Dünyanın En Uzun Kesintisiz Demiryolu Hattı", "style": "documentary_history"},
    {"topic": "Zanetti Treni Efsanesi: Tünelde Kaybolan 104 Yolcu", "style": "cinematic_dark"},
    {"topic": "İkinci Dünya Savaşında Nazi Zırhlı Trenleri", "style": "documentary_history"},
    {"topic": "Bulutlara Tırmanan Tren: Arjantin Tren a las Nubes", "style": "documentary_history"},
    {"topic": "Churchill'in Gizli Zırhlı Tren Karargahı", "style": "documentary_history"},
    {"topic": "1918 Versay Vagonu: İki Dünya Savaşını Bitiren Tarihi Tren", "style": "documentary_history"},
    {"topic": "Darjeeling Himalaya Demiryolu: Dağları Aşan Oyuncak Tren", "style": "documentary_history"},
    {"topic": "Gümüş Şimşek: 1930'ların Fütüristik Zephyr Treni", "style": "documentary_history"},
    {"topic": "Rocky Dağlarını Aşan Kanadalı Pasifik Demiryolu Destanı", "style": "documentary_history"},

    # --- GÜNCEL VE MODERN YÜKSEK HIZLI RAYLI SİSTEMLER ---
    {"topic": "Dünyanın En Hızlı Treni: Japonya Maglev L0 Serisi 603 km/s", "style": "science_space"},
    {"topic": "Alplerin Altındaki Dev: İsviçre Gotthard Baz Tüneli", "style": "science_space"},
    {"topic": "Şinkansen: Japon Mermi Trenlerinin Sıfır Kaza Sırrı", "style": "science_space"},
    {"topic": "Çin'in Saatte 450 km Hıza Ulaşan Yeni CR450 Hızlı Treni", "style": "science_space"},
    {"topic": "Manş Tüneli: Denizin Altından İngiltere ve Fransa'yı Bağlayan Raylar", "style": "science_space"},
    {"topic": "Fransa TGV: 574 km/s ile Konvansiyonel Raylarda Dünya Rekoru", "style": "science_space"},
    {"topic": "Dünyanın En Tehlikeli Demiryolu: Şeytanın Burnu Ekvador", "style": "cinematic_dark"},
    {"topic": "Norveç Flåm Demiryolu: Dünyanın En Dik Tren Yolculuğu", "style": "documentary_history"},
    {"topic": "The Ghan: Avustralya Çölünü Baştan Başa Aşan Tren", "style": "documentary_history"},
    {"topic": "Tiber Körfezini Aşan Dünyanın En Dik Teleferikli Raylı Sistemi", "style": "science_space"},
    {"topic": "Sürücüsüz Manyetik Trenler: Geleceğin Şehiriçi Raylı Sistemleri", "style": "science_space"}
]


def load_past_topics() -> List[str]:
    """Daha önce işlenmiş konuları hafıza dosyasından okur."""
    if not os.path.exists(HISTORY_FILE):
        return []
    
    past_topics = []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(" - ", 1)
                    topic = parts[1] if len(parts) > 1 else parts[0]
                    # Parantez içindeki açıklamaları temizle
                    if " (Başlık:" in topic:
                        topic = topic.split(" (Başlık:")[0].strip()
                    past_topics.append(topic.lower())
    except Exception as e:
        print(f"[UYARI] Geçmiş konular okunurken hata: {e}")
        
    return past_topics


def save_completed_topic(topic: str, video_title: str = ""):
    """Tamamlanan ve yüklenen konuyu tarih damgasıyla hafızaya ekler."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"{timestamp} - {topic}"
    if video_title:
        entry += f" (Başlık: {video_title})"
    
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(entry + "\n")
    print(f"\n[Hafıza] Yeni konu başarıyla kaydedildi: {topic}")


def generate_autonomous_railway_topic(past_topics: List[str]) -> Dict[str, str]:
    """
    Öncelikle Gemini API ile canlı araştırma yapar.
    API anahtarı geçersizse veya kota doluysa, zengin yerel arşivden
    daha önce İŞLENMEMİŞ taze bir raylı sistem konusunu seçer.
    """
    print("\n" + "=" * 70)
    print("🚂 [Raylı Sistemler Araştırmacısı] Günün konusu belirleniyor...")
    print("=" * 70)

    client = get_gemini_client()
    past_topics_lower = [p.lower() for p in past_topics]

    # 1. ÖNCELİK: Groq API (Llama 3.3) ile Canlı Konu Araştırması
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and groq_key.startswith("gsk_"):
        try:
            from groq import Groq
            groq_client = Groq(api_key=groq_key)
            past_sample = "\n".join([f"- {t}" for t in past_topics[-25:]]) if past_topics else "Yok"

            system_instruction = """
            Sen tarihi ve modern raylı sistemler konusunda kıdemli bir YouTube içerik stratejistisin.
            Görevin, dikey YouTube Shorts için izleyicide merak, hayranlık veya heyecan uyandıracak
            TEK BİR özgün ve gerçekçi raylı sistemler konusu belirlemektir.
            Kapsam: Gerçek efsanevi tarihi trenler, buharlı dev lokomotifler, raylı sistem savaşları/casuslukları,
            dünyanın en hızlı Maglev/hızlı trenleri, efsanevi dağ/deniz tünelleri (Marmaray, Gotthard, Manş vb.),
            dünyanın en tehlikeli veya en lüks tren hatları.
            ÖNEMLİ KURAL:
            1. Konu başlığı (topic) MUTLAKA AKICI VE ÇARPICI BİR TÜRKÇE OLMALIDIR (asla İngilizce olmasın).
            2. KESİNLİKLE daha önce işlenmiş konuları tekrar etme!
            3. Sadece saf bir JSON objesi döndür: {"topic": "Türkçe Konu Başlığı", "style": "documentary_history veya science_space veya cinematic_dark"}
            """

            candidate_topic = None
            candidate_style = "documentary_history"
            
            groq_models = ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
            for model_name in groq_models:
                try:
                    completion = groq_client.chat.completions.create(
                        model=model_name,
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": f"Daha önce işlenenler:\n{past_sample}\n\nBugün için yepyeni 1 raylı sistem konusu üret."}
                        ],
                        response_format={"type": "json_object"}
                    )
                    data = json.loads(completion.choices[0].message.content.strip())
                    topic_text = data.get("topic", "").strip()
                    if topic_text and topic_text.lower() not in past_topics_lower:
                        candidate_topic = topic_text
                        candidate_style = data.get("style", "documentary_history")
                        print(f"  ✅ [Groq AI ({model_name}) Canlı Araştırma] Seçilen Konu: {candidate_topic}")
                        print(f"  🎨 Önerilen Stil: {candidate_style}")
                        return {"topic": candidate_topic, "style": candidate_style}
                except Exception as model_err:
                    print(f"  [Uyarı] Groq model '{model_name}' hatası: {model_err}")
                    continue
        except Exception as e:
            print(f"  [Bilgi] Groq canlı araması atlandı: {e}")

    # 2. ÖNCELİK: Gemini API ile Canlı Üretim
    if client is not None:
        try:
            from google.genai import types

            past_sample = "\n".join([f"- {t}" for t in past_topics[-25:]]) if past_topics else "Yok"

            system_instruction = """
            Sen tarihi ve modern raylı sistemler konusunda kıdemli bir YouTube içerik stratejistisin.
            Görevin, dikey YouTube Shorts için izleyicide merak, hayranlık veya heyecan uyandıracak
            TEK BİR özgün ve gerçekçi raylı sistemler konusu belirlemektir.
            Kapsam: Gerçek efsanevi tarihi trenler, buharlı dev lokomotifler, raylı sistem savaşları/casuslukları,
            dünyanın en hızlı Maglev/hızlı trenleri, efsanevi dağ/deniz tünelleri (Marmaray, Gotthard, Manş vb.),
            dünyanın en tehlikeli veya en lüks tren hatları.
            ÖNEMLİ KURAL:
            1. Konu başlığı (topic) MUTLAKA AKICI VE ÇARPICI BİR TÜRKÇE OLMALIDIR (asla İngilizce olmasın).
            2. KESİNLİKLE daha önce işlenmiş konuları tekrar etme!
            3. Sadece saf bir JSON objesi döndür: {"topic": "Türkçe Konu Başlığı", "style": "documentary_history veya science_space veya cinematic_dark"}
            """

            user_prompt = f"Daha önce işlenen konular:\n{past_sample}\n\nLütfen bugün için yepyeni, şoke edici veya büyüleyici 1 raylı sistem konusu üret."

            for model_name in CANDIDATE_GEMINI_MODELS:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            temperature=0.85,
                        ),
                    )
                    data = json.loads(response.text.strip())
                    candidate_topic = data.get("topic", "").strip()

                    # Tekrar kontrolü
                    if candidate_topic and candidate_topic.lower() not in past_topics_lower:
                        print(f"  ✅ [Gemini Canlı Araştırma] Seçilen Konu: {candidate_topic}")
                        print(f"  🎨 Önerilen Stil: {data.get('style', 'documentary_history')}")
                        return data
                except Exception:
                    continue

        except Exception as e:
            print(f"  [Bilgi] Gemini API canlı araması atlandı ({e}). Yerel otonom arşive geçiliyor...")

    # 2. Öncelik: Zengin Yerel Raylı Sistemler Arşivinden Daha Önce İşlenmemiş Konu Seç
    unused_pool = [t for t in RAILWAY_TOPICS_POOL if t["topic"].lower() not in past_topics_lower]
    
    if unused_pool:
        chosen = random.choice(unused_pool)
        print(f"  ✅ [Otonom Arşiv] Seçilen Taze Konu: {chosen['topic']}")
        print(f"  🎨 Stil: {chosen.get('style', 'documentary_history')}")
        return chosen
    
    # Tüm liste bittiyse rastgele birini seç
    chosen = random.choice(RAILWAY_TOPICS_POOL)
    print(f"  ✅ [Otonom Arşiv] Seçilen Konu: {chosen['topic']}")
    return chosen


def run_daily_autonomous_job(publish_status: str = "private") -> bool:
    """
    Her gün çalışan tam otonom ana döngü:
    1. Geçmişi kontrol eder.
    2. Yeni raylı sistem konusunu üretir.
    3. Videoyu baştan sona oluşturup YouTube'a yükler.
    4. Konuyu hafızaya kaydeder.
    """
    print("\n" + "=" * 70)
    print("🚂 GÜNLÜK OTONOM RAYLI SİSTEMLER SHORTS ROBOTU BAŞLATILDI")
    print(f"⏰ Çalışma Zamanı : {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🔒 Yayın Durumu   : {publish_status}")
    print("=" * 70)

    # 1. Daha önce işlenen konuları al
    past_topics = load_past_topics()
    print(f"[Hafıza] Geçmişte işlenmiş konu sayısı: {len(past_topics)}")

    # 2. Özgün yeni bir raylı sistem konusu belirle
    topic_info = generate_autonomous_railway_topic(past_topics)
    topic = topic_info.get("topic", "Tarihteki Tren Efsaneleri")
    style = topic_info.get("style", "documentary_history")

    # 3. Tüm üretim ve YouTube yükleme zincirini çalıştır
    success = run_full_youtube_pipeline(
        topic=topic,
        style_preset=style,
        publish_status=publish_status,
        output_video_path="gunluk_rayli_sistem_shorts.mp4"
    )

    # 4. Başarılı ise konuyu hafızaya kaydet
    if success:
        save_completed_topic(topic)
        print("\n" + "=" * 70)
        print(f"🎉 GÜNLÜK VİDEO BAŞARIYLA ÜRETİLDİ VE YOUTUBE'A YÜKLENDİ: {topic}")
        print("=" * 70)
        return True
    else:
        print("\n❌ Günlük görev sırasında bir aksilik oluştu.")
        return False


# ---------------------------------------------------------------------------
# ÇALIŞTIRMA BLOKU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Varsayılan yükleme modu: 'private' (YouTube Studio'da gizli bekler, onayınızla yayınlanır)
    # Eğer doğrudan canlıya almak isterseniz: python daily_runner.py public
    status = "private"
    if len(sys.argv) > 1 and sys.argv[1] in ["public", "private", "unlisted"]:
        status = sys.argv[1]

    run_daily_autonomous_job(publish_status=status)
