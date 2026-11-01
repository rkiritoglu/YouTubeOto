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
Sen National Geographic ve BBC düzeyinde belgesel hazırlayan kıdemli bir tarih/mühendislik araştırmacısı ve YouTube Shorts yönetmenisin.
Görevin, sana verilen KONU başlığı hakkında %100 GERÇEK BİLGİLERE, somut tarihlere, mühendislik verilerine (yıl, hız, uzunluk, ülke, gerçek olaylar) dayanan 30-45 saniyelik büyüleyici bir dikey belgesel senaryosu yazmaktır.

UYULMASI ZORUNLU KATI KURALLAR:
1. KESİNLİKLE UYDURMA / SOYUT CÜMLE YAZMA:
   - "Gizli harita kayboldu", "Her kabinde cinayet planı vardı", "Gizli odanın kapısı hâlâ kilitli" gibi uydurma, masalsı ve konuyla alakasız cümleler KESİNLİKLE YASAKTIR!
   - İzleyiciye gerçekten yeni ve doğru bir bilgi ver: Hangi yılda yapıldı? Hangi ülkeleri/şehirleri bağladı? Kaç km uzunluğunda veya kaç km/s hızında? Hangi gerçek tarihi olay yaşandı?
2. DOĞAL VE AKICI TÜRKÇE ANLATIM:
   - İlk cümlede (Hook) konunun en çarpıcı gerçek özelliğini söyle.
   - Sahneler birbirinin devamı olan anlamlı bir hikaye/belgesel akışı oluşturmalı (12-18 kelimelik tam, anlamlı ve düzgün Türkçe cümleler kur).
   - Video açıklaması (description) ile videoda anlatılan metin BİREBİR aynı gerçek bilgileri özetlemeli.
3. GÖRSEL VE METİN BİREBİR EŞLEŞMESİ (ÇOK ÖNEMLİ):
   - Her sahnenin 'ai_image_prompt' değeri, o sahnedeki Türkçe 'narration' cümlesinde ne anlatılıyorsa TAM OLARAK ONU göstermelidir!
   - Konu bir tren, demiryolu veya mühendislik yapısıysa HER SAHNENİN GÖRSELİNDE o tren, lokomotif, raylar, köprü veya istasyon açıkça yer almalıdır (asla konuyla alakasız hançer, kağıt, kapı kolu gibi kopuk nesneler çizdirme).
   - 'global_style': Tüm sahnelerin aynı sinematik belgesel atmosferinde görünmesini sağlayan ortak İngilizce stil tanımı.

ÇIKTI FORMATI:
Sadece ve sadece geçerli bir JSON objesi döndür. Markdown etiketleri (```json vb.) veya ek açıklama metinleri ekleme.
"""


# ---------------------------------------------------------------------------
# 2. KULLANICI PROMPT ŞABLONU (USER PROMPT TEMPLATE)
# ---------------------------------------------------------------------------
# Kullanıcının belirlediği konu ve konsepte göre modele gönderilecek dinamik mesaj şablonu.
USER_SCRIPT_PROMPT_TEMPLATE = """
KONU: {topic}
HEDEF KİTLE VE ANLATIM KONSEPTİ: {style_preset}

Lütfen bu konu hakkında uydurma olmayan, %100 gerçek tarihi ve teknik bilgilere dayanan 5 sahnelik bir belgesel senaryosu üret.
Her sahnenin 'ai_image_prompt' açıklaması, o sahnenin Türkçe metniyle birebir örtüşmeli ve ana konuyu (treni/demiryolunu/mekanı) net biçimde betimlemelidir:

{{
  "title": "YouTube Video Başlığı (Konuyu net anlatan, merak uyandırıcı Türkçe başlık, max 60 karakter)",
  "description": "Videoda anlatılan gerçek bilgilerin 2 cümlelik özeti ve etiketler (#shorts #belgesel #tren #tarih)",
  "global_style": "Award-winning historical documentary photography, shot on 35mm ARRI Alexa, natural volumetric lighting, ultra-detailed realistic textures, 8k, vertical 9:16 aspect ratio, clean frame without logos",
  "visual_seed": 428571,
  "scenes": [
    {{
      "scene_id": 1,
      "narration": "Konunun en çarpıcı gerçek tarihi veya mühendislik bilgisini veren güçlü giriş cümlesi.",
      "stock_search_terms": ["specific train keyword", "railway history"],
      "ai_image_prompt": "Wide cinematic vertical shot of the exact train/railway described in narration, realistic historical setting, steam and rails clearly visible"
    }},
    {{
      "scene_id": 2,
      "narration": "Yapım yılı, güzergahı veya teknik rekorunu anlatan somut ikinci cümle.",
      "stock_search_terms": ["locomotive engineering", "railway bridge"],
      "ai_image_prompt": "Detailed vertical shot showing the specific route, station, or locomotive engineering described in scene 2 narration"
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
