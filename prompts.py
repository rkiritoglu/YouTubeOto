"""
prompts.py - YouTube Shorts ve Dikey Video Otomasyonu İçin Gelişmiş Prompt Şablonları

Bu modülün amacı:
1. YouTube Shorts, TikTok ve Instagram Reels gibi platformlarda izleyicinin dikkatini
   ilk 2-3 saniyede yakalayan (Hook mantığı) senaryo üretim kurallarını tanımlamak.
2. Pexels/Pixabay gibi stok video platformlarında aranacak doğru İngilizce anahtar
   kelimelerin (örneğin 'dramatic ocean', 'ancient ruins') üretilmesini sağlamak.
3. Midjourney, DALL-E veya Imagen gibi görsel üretim modellerinde kullanılmak üzere
   sinematik stil önayarlarını (Style Presets) yönetmek.
"""

from typing import Dict, Any


# ---------------------------------------------------------------------------
# 1. SİSTEM PROMPTU (SYSTEM INSTRUCTION)
# ---------------------------------------------------------------------------
# Bu talimat, Gemini modeline bir video yönetmeni ve viral metin yazarı kimliği kazandırır.
# Modelin uyması gereken katı kuralları ve beklenen JSON formatını belirtir.
SYSTEM_SCRIPT_PROMPT = """
Sen YouTube Shorts ve TikTok için viral içerikler üreten kıdemli bir metin yazarı ve kurgu yönetmenisin.
Görevin, sana verilen KONU başlığını alıp izleyiciyi ekrana kilitleyecek 30-50 saniyelik dikey video senaryosu oluşturmaktır.

UYULMASI ZORUNLU KURALLAR:
1. İLK 3 SANİYE (HOOK): Girişte Asla "Merhaba", "Bugün sizlere...", "Kanalıma hoş geldiniz" gibi kelimeler kullanma. 
   Doğrudan şaşırtıcı bir iddia, kışkırtıcı bir soru veya merak uyandıran bir gerçekle başla.
2. DİL VE TEMPO: Cümleler maksimum 8-10 kelime olmalı. Anlatım dili dinamik, net, akıcı ve vurucu olmalıdır.
3. SAHNE YAPISI: Senaryoyu 3-5 saniyelik küçük sahne parçalarına (scenes) böl. Her sahne için:
   - 'scene_id': Sahne sıra numarası (1, 2, 3...)
   - 'narration': Seslendirilecek Türkçe metin (doğal, akıcı, abartısız).
   - 'stock_search_terms': Pexels stok video kütüphanesinde dikey video aramak için 2-3 adet İNGİLİZCE anahtar kelime listesi (Örn: ["pyramids egypt", "desert mystery"]).
   - 'ai_image_prompt': Stok video bulunamazsa veya yapay zeka ile görsel üretilmek istenirse kullanılacak yüksek kaliteli İNGİLİZCE görsel tanımı.

ÇIKTI FORMATI:
Sadece ve sadece geçerli bir JSON objesi döndür. Markdown etiketleri (```json vb.) veya ek açıklama metinleri ekleme.
"""


# ---------------------------------------------------------------------------
# 2. KULLANICI PROMPT ŞABLONU (USER PROMPT TEMPLATE)
# ---------------------------------------------------------------------------
# Kullanıcının belirlediği konu ve konsepte göre Gemini'ye gönderilecek dinamik mesaj şablonu.
USER_SCRIPT_PROMPT_TEMPLATE = """
KONU: {topic}
HEDEF KİTLE VE ANLATIM KONSEPTİ: {style_preset}

Lütfen sistem talimatlarına tam olarak uyarak, aşağıdaki şemaya uygun bir JSON senaryosu üret:

{{
  "title": "YouTube Video Başlığı (Tıklama oranı yüksek, merak uyandırıcı, max 60 karakter)",
  "description": "YouTube Video Açıklaması ve popüler etiketler (Örn: #shorts #viral #bilgi)",
  "scenes": [
    {{
      "scene_id": 1,
      "narration": "Girişteki ilk vurucu cümle...",
      "stock_search_terms": ["cinematic keyword1", "keyword2"],
      "ai_image_prompt": "Cinematic shot of..., 8k resolution, photorealistic, 9:16 aspect ratio"
    }},
    {{
      "scene_id": 2,
      "narration": "Gelişme cümlesi...",
      "stock_search_terms": ["action keyword1", "keyword2"],
      "ai_image_prompt": "Dramatic close up of..., detailed texture, 9:16"
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# 3. YAPAY ZEKA GÖRSEL STİL ŞABLONLARI (AI IMAGE STYLE PRESETS)
# ---------------------------------------------------------------------------
# Farklı video türlerine göre yapay zeka görsellerinin profesyonel görünmesini sağlayan ışık,
# kamera açısı ve render motoru anahtar kelimeleri.
IMAGE_STYLE_PRESETS: Dict[str, str] = {
    "cinematic_dark": (
        "cinematic lighting, dark moody atmosphere, dramatic shadows, shot on 35mm lens, "
        "photorealistic, 8k resolution, Unreal Engine 5 render, hyper-detailed, 9:16 aspect ratio"
    ),
    "hyper_realistic": (
        "photorealistic portrait, natural daylight, highly detailed skin texture, 8k, "
        "shot on Canon EOS R5, professional photography, studio lighting, 9:16 aspect ratio"
    ),
    "cyberpunk_neon": (
        "cyberpunk style, vibrant neon lights, futuristic city background, night time, "
        "octane render, highly detailed, dramatic reflections, 8k resolution, 9:16 aspect ratio"
    ),
    "documentary_history": (
        "vintage oil painting style, historical accurate atmosphere, dramatic chiaroscuro lighting, "
        "museum quality detail, epic composition, masterpiece, 8k, 9:16 aspect ratio"
    ),
    "science_space": (
        "deep space background, nebula colors, cosmic dust, photorealistic astronomy, "
        "Hubble telescope style, James Webb photography, 8k, highly immersive, 9:16 aspect ratio"
    )
}


# ---------------------------------------------------------------------------
# 4. YARDIMCI FONKSİYONLAR
# ---------------------------------------------------------------------------

def build_script_prompt(topic: str, style_preset: str = "cinematic_dark") -> str:
    """
    Kullanıcının belirlediği konu ve konsepte göre dinamik kullanıcı promptu hazırlar.
    
    Parametreler:
        topic (str): Videonun konusu (örneğin 'Mars'ta Yaşam İhtimalleri').
        style_preset (str): Seçilen görsel/içerik tarzı ('cinematic_dark', 'documentary_history' vb.).
        
    Döndürür:
        str: Gemini API'ye iletilmeye hazır formatlanmış kullanıcı mesajı.
    """
    return USER_SCRIPT_PROMPT_TEMPLATE.format(
        topic=topic,
        style_preset=style_preset
    )


def enrich_image_prompt(base_prompt: str, style_key: str = "cinematic_dark") -> str:
    """
    Temel yapay zeka görsel promptuna stil ve render parametrelerini ekleyerek
    görsel üretim kalitesini ve tutarlılığını artırır.
    
    Parametreler:
        base_prompt (str): Modelin ürettiği temel görsel tasviri.
        style_key (str): Seçilen stil önayarı anahtarı.
        
    Döndürür:
        str: Stille zenginleştirilmiş nihai görsel üretim komutu.
    """
    style_suffix = IMAGE_STYLE_PRESETS.get(style_key, IMAGE_STYLE_PRESETS["cinematic_dark"])
    return f"{base_prompt}, {style_suffix}"


# ---------------------------------------------------------------------------
# TEST BLOKU (Bu dosya doğrudan çalıştırıldığında test çıktısı verir)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== prompts.py Modülü Test Ediliyor ===")
    test_topic = "Büyük Piramitlerin Altındaki Gizli Odalar"
    
    print("\n1. Hazırlanan Kullanıcı Promptu:")
    sample_prompt = build_script_prompt(test_topic, style_preset="documentary_history")
    print(sample_prompt[:300] + "...\n(Kısaltıldı)")
    
    print("\n2. Zenginleştirilmiş Görsel Promptu:")
    raw_prompt = "Ancient chamber with glowing hieroglyphs"
    enhanced = enrich_image_prompt(raw_prompt, style_key="documentary_history")
    print(enhanced)
    print("\n✅ prompts.py testi başarıyla tamamlandı!")
