"""
reference_image_engine.py - İnternetten Gerçek Referans Görsel Bulucu & Vision-to-Flux Telifsiz Klonlama Motoru

Bu modülün amacı:
1. Sahnenin konusuna veya arama terimlerine göre internetten (Wikimedia Commons, Wikipedia,
   Bing Görseller veya kullanıcının verdiği doğrudan resim URL'sinden) GERÇEK bir referans fotoğraf bulup indirmek.
2. İndirilen gerçek fotoğrafı Groq üzerindeki 'qwen/qwen3.8-27b' (Multimodal Vision) modeline göstererek:
   - Fotoğraftaki trenin/yapının gerçek tasarımını, kamera açısını, dönemini, renklerini ve ortamını birebir analiz etmek,
   - Telif oluşturabilecek gerçek kişi yüzlerini, filigranları, logoları ve imzaları temizleyerek
     FLUX.1-schnell için 9:16 dikey formatta ultra detaylı İngilizce yeniden-üretim komutu (reverse-prompt) çıkarmak.
3. Böylece orijinal fotoğrafın hiçbir pikseli kopyalanmadan, internetteki gerçek fotoğrafa
   kompozisyon ve konu olarak çok benzeyen %100 TELİFSİZ (Royalty-Free) yeni bir AI görseli üretilmesini sağlamak.
"""

import os
import re
import io
import html
import base64
import urllib.parse
import requests
from typing import Optional, Dict, Any, List
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 "
        "YouTubeOtoResearchBot/2.0"
    )
}


def _save_valid_rgb_jpeg(raw_bytes: bytes, output_path: str, max_side: int = 1024) -> bool:
    """İndirilen bayt verisini doğrular, RGB JPEG formatına dönüştürür ve kaydeder."""
    try:
        if not raw_bytes or len(raw_bytes) < 4000:
            return False
        img = Image.open(io.BytesIO(raw_bytes)).convert("RGB")
        w, h = img.size
        if w < 180 or h < 180:
            return False
        if max(w, h) > max_side:
            img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        img.save(output_path, "JPEG", quality=90)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 3000
    except Exception:
        return False


def download_image_from_url(image_url: str, output_path: str) -> str:
    """Verilen doğrudan resim URL'sini indirir ve RGB JPEG olarak kaydeder."""
    if not image_url or not image_url.strip().startswith("http"):
        return ""
    try:
        resp = requests.get(image_url.strip(), headers=HTTP_HEADERS, timeout=15)
        if resp.status_code == 200 and _save_valid_rgb_jpeg(resp.content, output_path):
            return output_path
    except Exception as e:
        print(f"  [Uyarı] Referans URL indirilemedi ({image_url[:50]}): {e}")
    return ""


def search_wikimedia_reference_image(query: str, output_path: str) -> str:
    """
    Wikimedia Commons API üzerinden konuyla ilgili gerçek tarihi/teknik fotoğraf arar ve indirir.
    """
    api_url = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6,
        "gsrlimit": 5,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 800,
        "format": "json"
    }
    try:
        resp = requests.get(api_url, params=params, headers=HTTP_HEADERS, timeout=12)
        if resp.status_code == 200:
            pages = (resp.json().get("query") or {}).get("pages") or {}
            for _, page_info in pages.items():
                iinfo = page_info.get("imageinfo") or []
                if iinfo and isinstance(iinfo[0], dict):
                    thumb_url = iinfo[0].get("thumburl") or iinfo[0].get("url")
                    if thumb_url and not thumb_url.lower().endswith((".svg", ".gif", ".tif", ".pdf")):
                        saved = download_image_from_url(thumb_url, output_path)
                        if saved:
                            print(f"  🔍 [Wikimedia Referans] Gerçek fotoğraf bulundu: '{query}'")
                            return saved
    except Exception:
        pass
    return ""


def search_bing_web_reference_image(query: str, output_path: str) -> str:
    """
    Bing Görsel Arama üzerinden internette yayınlanmış gerçek fotoğrafları tarar ve ilk geçerli resmi indirir.
    """
    encoded_q = urllib.parse.quote(query)
    search_url = f"https://www.bing.com/images/async?q={encoded_q}&first=1&count=8&adlt=strict"
    try:
        resp = requests.get(search_url, headers=HTTP_HEADERS, timeout=12)
        if resp.status_code == 200:
            # Bing HTML içindeki murl (orijinal) ve turl (yüksek kaliteli önizleme) bağlantılarını ayıkla
            turls = re.findall(r"turl&quot;:&quot;(https?://[^&]+?)&quot;", resp.text)
            murls = re.findall(r"murl&quot;:&quot;(https?://[^&]+?)&quot;", resp.text)
            candidates = turls[:4] + murls[:4]
            for raw_url in candidates:
                clean_url = html.unescape(raw_url)
                saved = download_image_from_url(clean_url, output_path)
                if saved:
                    print(f"  🌐 [Web Görsel Arama] İnternetten referans resim bulundu: '{query}'")
                    return saved
    except Exception:
        pass
    return ""


def find_web_reference_image(
    scene: Dict[str, Any],
    topic: str,
    output_dir: str
) -> str:
    """
    Bir sahne için sırasıyla:
    1. Kullanıcının girdiği özel 'reference_image_url' veya yerel 'reference_image_path' varsa onu alır,
    2. Sahnenin İngilizce arama terimleriyle Wikimedia Commons'ta gerçek fotoğraf arar,
    3. Bulunamazsa Bing Web Görsel Arama ile internetten gerçek fotoğrafı indirir.
    """
    os.makedirs(output_dir, exist_ok=True)
    scene_id = int(scene.get("scene_id", 1))
    ref_out_path = os.path.join(output_dir, f"ref_scene_{scene_id}.jpg")

    # 1. Kullanıcı özel bir referans dosya yolu veya URL belirttiyse
    existing_ref_path = scene.get("reference_image_path", "")
    if existing_ref_path and os.path.exists(existing_ref_path):
        return existing_ref_path

    custom_url = str(scene.get("reference_image_url") or "").strip()
    if custom_url.startswith("http"):
        saved = download_image_from_url(custom_url, ref_out_path)
        if saved:
            scene["reference_image_path"] = saved
            return saved

    # 2. Arama sorgularını oluştur
    search_terms: List[str] = list(scene.get("stock_search_terms") or [])
    if not search_terms:
        search_terms = [topic]
    else:
        # İlk terime tren/demiryolu bağlamını da ekle
        first_term = search_terms[0]
        if "train" not in first_term.lower() and "rail" not in first_term.lower() and "station" not in first_term.lower():
            search_terms.insert(0, f"{first_term} railway train")

    # Önce Wikimedia Commons, sonra Bing Web Görseller
    for q in search_terms[:2]:
        saved = search_wikimedia_reference_image(q, ref_out_path)
        if saved:
            scene["reference_image_path"] = saved
            return saved

        saved = search_bing_web_reference_image(q, ref_out_path)
        if saved:
            scene["reference_image_path"] = saved
            return saved

    return ""


def analyze_reference_image_for_copyright_free_clone(
    ref_image_path: str,
    scene_narration: str,
    fallback_prompt: str,
    global_style: str
) -> str:
    """
    Groq üzerindeki multimodal 'qwen/qwen3.8-27b' Vision modelini kullanarak
    internetten indirilen gerçek referans fotoğrafı inceler ve telif oluşturmayacak
    ancak görsel olarak birebir benzerini çizdirecek İngilizce FLUX komutunu üretir.
    """
    if not ref_image_path or not os.path.exists(ref_image_path):
        return f"{global_style}, {fallback_prompt}"

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not groq_key or not groq_key.startswith("gsk_"):
        return f"{global_style}, {fallback_prompt}"

    try:
        from groq import Groq
        client = Groq(api_key=groq_key)

        with open(ref_image_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")

        vision_instruction = (
            "You are an expert AI visual director for copyright-free image synthesis. "
            "Analyze this reference photograph from the web and write a single, concise, vivid "
            "English image generation prompt (30-45 words MAX) to recreate a 100% original and "
            "royalty-free vertical (9:16) scene inspired by this reference.\n"
            "Rules:\n"
            "1. Extract the exact visual design of the train/locomotive/station from the reference photo (nose shape, livery colors, era, architecture) and place it PROMINENTLY in the center foreground on railway tracks.\n"
            "2. Keep the iconic background/landmark from the reference (e.g., mountain, bridge, canyon, station roof), but DO NOT include distracting empty asphalt roads, fences, or utility poles blocking the train.\n"
            "3. Ensure it aligns with this scene context: '" + scene_narration + "'.\n"
            "4. Output ONLY the raw English prompt sentence (max 45 words), nothing else."
        )

        completion = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": vision_instruction},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                        }
                    ]
                }
            ],
            temperature=0.3,
            max_tokens=120
        )

        vision_prompt = completion.choices[0].message.content.strip()
        if vision_prompt and len(vision_prompt) > 20:
            print(f"  👁️ [Vision AI Klonlama] Referans resim analiz edildi -> '{vision_prompt[:85]}...'")
            return f"{vision_prompt}, {global_style}, vertical 9:16 aspect ratio, photorealistic, no text"

    except Exception as e:
        print(f"  [Bilgi] Vision referans analizi atlandı ({e}), standart prompt kullanılıyor.")

    return f"{global_style}, {fallback_prompt}"
