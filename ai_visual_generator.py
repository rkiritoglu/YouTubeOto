"""
ai_visual_generator.py - Global Stil ve Sabit Seed Korumalı Hibrit AI Video & Görsel Motoru

Mimari Darboğaz 4 Çözümü:
- Her sahneyi birbirinden kopuk promptlarla üretmek yerine:
  f"{global_style}, {scene_prompt}, vertical 9:16 aspect ratio, no text, no watermark"
  şablonunu ve ortak 'visual_seed' (tohum) numarasını kullanır. Böylece sahneler arasında
  görsel tarz kayması (Style Drift) yaşanmaz.

Hibrit Üretim Katmanları:
1. Katman (Hareketli AI Video - Opsiyonel):
   - FAL_KEY tanımlıysa Fal.ai (Wan / LTX-Video) üzerinden 9:16 hareketli AI video üretir.
2. Katman (Ücretsiz 9:16 AI Görsel - Flux):
   - HF_API_KEY tanımlıysa Hugging Face Serverless (FLUX.1-schnell) ile 1080x1920 görsel üretir.
   - Anahtar yoksa veya kota dolduysa Pollinations AI (Flux modeli, nologo=true, seed=visual_seed)
     ile tamamen ücretsiz 1080x1920 dikey AI görseli üretir.
   - Bu görseller ffmpeg_renderer.py içerisinde yerel FFmpeg 'zoompan' filtresiyle
     sinematik kamera hareketine dönüştürülür.
"""

import os
import time
import urllib.parse
import requests
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()


def build_consistent_prompt(scene: Dict[str, Any], global_style: str) -> str:
    """
    Global stil şablonu ile sahneye özel görsel komutu birleştirerek
    tüm sahnelerin aynı görsel evrende kalmasını sağlar.
    """
    base_prompt = (
        scene.get("ai_image_prompt")
        or scene.get("visual_prompt")
        or scene.get("narration", "cinematic railway scene")
    )
    clean_global = global_style.strip().rstrip(",")
    clean_base = base_prompt.strip().rstrip(",")
    return (
        f"{clean_global}, {clean_base}, "
        "vertical 9:16 aspect ratio, photorealistic, masterpiece, sharp focus, no text, no watermark"
    )


def _generate_video_with_fal(prompt: str, seed: int, output_video_path: str) -> bool:
    """
    FAL_KEY mevcutsa Fal.ai üzerinden 9:16 hareketli AI video üretir.
    """
    fal_key = os.environ.get("FAL_KEY", "").strip()
    if not fal_key or fal_key.startswith("BURAYA"):
        return False

    headers = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "seed": int(seed)
    }

    endpoints = [
        "https://fal.run/fal-ai/ltx-video",
        "https://fal.run/fal-ai/fast-svd/text-to-video"
    ]

    for url in endpoints:
        try:
            print(f"  [Fal.ai Video API] Hareketli AI sahne üretiliyor ({url.split('/')[-1]})...")
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
            if resp.status_code in (401, 403):
                # Bakiye yetersiz (TOP_UP) veya geçersiz anahtar ise diğer endpoint'leri denemeden hızla çık
                break
            if resp.status_code == 200:
                data = resp.json()
                video_url = (
                    (data.get("video") or {}).get("url")
                    if isinstance(data.get("video"), dict)
                    else data.get("video_url")
                )
                if video_url:
                    v_stream = requests.get(video_url, timeout=60)
                    if v_stream.status_code == 200 and len(v_stream.content) > 10000:
                        with open(output_video_path, "wb") as f:
                            f.write(v_stream.content)
                        print(f"  -> [Fal.ai] Hareketli AI video kaydedildi: {output_video_path}")
                        return True
        except Exception as e:
            print(f"  [Bilgi] Fal.ai video adımı atlandı: {e}")
            continue

    return False


def _generate_image_with_huggingface(prompt: str, seed: int, output_image_path: str) -> bool:
    """
    HF_API_KEY mevcutsa Hugging Face Inference API üzerinden FLUX.1-schnell ile
    dikey 9:16 AI görseli üretir.
    """
    hf_key = os.environ.get("HF_API_KEY", "").strip()
    if not hf_key or not hf_key.startswith("hf_"):
        return False

    api_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell"
    headers = {"Authorization": f"Bearer {hf_key}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "width": 768,
            "height": 1344,
            "seed": int(seed),
            "num_inference_steps": 4
        }
    }

    try:
        print("  [HuggingFace Flux] 9:16 AI sahne görseli üretiliyor...")
        resp = requests.post(api_url, headers=headers, json=payload, timeout=45)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(output_image_path, "wb") as f:
                f.write(resp.content)
            print(f"  -> [HuggingFace Flux] Görsel kaydedildi: {output_image_path}")
            return True
    except Exception as e:
        print(f"  [Bilgi] HuggingFace görsel adımı atlandı: {e}")

    return False


def _sanitize_ascii_prompt(text: str) -> str:
    """
    Groq (gpt-oss-120b) gibi modellerin ürettiği Unicode tire (\u2011, \u2013, \u2014)
    ve özel tırnak işaretlerini saf ASCII karakterlere dönüştürür.
    (URL tabanlı görsel servislerinin UTF-8 kaçış dizilerinde takılmasını önler).
    """
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u00a0": " ",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("ascii", errors="ignore").decode("ascii")


def _generate_image_with_fal_flux(prompt: str, seed: int, output_image_path: str) -> bool:
    """
    FAL_KEY tanımlı ve bakiyesi aktifse Fal.ai FLUX.1-schnell üzerinden
    1 saniyede 9:16 dikey AI görseli üretir.
    """
    fal_key = os.environ.get("FAL_KEY", "").strip()
    if not fal_key or fal_key.startswith("BURAYA"):
        return False

    headers = {
        "Authorization": f"Key {fal_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "prompt": prompt,
        "image_size": "portrait_16_9",
        "seed": int(seed),
        "num_inference_steps": 4
    }

    try:
        resp = requests.post("https://fal.run/fal-ai/flux/schnell", headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            images = data.get("images") or []
            if images and isinstance(images[0], dict) and images[0].get("url"):
                img_stream = requests.get(images[0]["url"], timeout=30)
                if img_stream.status_code == 200 and len(img_stream.content) > 5000:
                    with open(output_image_path, "wb") as f:
                        f.write(img_stream.content)
                    print(f"  -> [Fal.ai Flux] 9:16 AI görsel kaydedildi: {output_image_path}")
                    return True
    except Exception:
        pass

    return False


def _generate_image_with_bfl_flux_space(prompt: str, seed: int, output_image_path: str) -> bool:
    """
    Black Forest Labs resmi FLUX.1-schnell Gradio API'si üzerinden
    9:16 dikey yapay zeka görseli üretip 1080x1920 JPEG olarak kaydeder.
    HF_API_KEY varsa ZeroGPU kotasını artırmak için Bearer token olarak iletir.
    """
    import io
    import json as _json
    from PIL import Image

    clean_prompt = _sanitize_ascii_prompt(prompt)[:350].strip()
    call_url = "https://black-forest-labs-flux-1-schnell.hf.space/gradio_api/call/infer"
    payload = {
        "data": [clean_prompt, int(seed) % 2147483647, False, 768, 1344, 4]
    }
    headers = {}
    hf_key = os.environ.get("HF_API_KEY", "").strip()
    if hf_key and hf_key.startswith("hf_"):
        headers["Authorization"] = f"Bearer {hf_key}"

    try:
        print(f"  [BFL FLUX.1-schnell] Sahne görseli üretiliyor (Seed: {seed})...")
        r_init = requests.post(call_url, json=payload, headers=headers, timeout=15)
        if r_init.status_code != 200:
            return False

        event_id = r_init.json().get("event_id")
        if not event_id:
            return False

        r_stream = requests.get(f"{call_url}/{event_id}", headers=headers, timeout=40)
        if r_stream.status_code != 200:
            return False

        for line in r_stream.text.splitlines():
            if line.startswith("data:"):
                raw_data = line[len("data:"):].strip()
                parsed = _json.loads(raw_data)
                if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                    img_url = parsed[0].get("url")
                    if img_url:
                        img_resp = requests.get(img_url, headers=headers, timeout=25)
                        if img_resp.status_code == 200 and len(img_resp.content) > 5000:
                            img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
                            if img.size != (1080, 1920):
                                img = img.resize((1080, 1920), Image.Resampling.LANCZOS)
                            img.save(output_image_path, "JPEG", quality=94)
                            print(f"  -> [BFL FLUX.1-schnell] 1080x1920 görsel hazır: {output_image_path}")
                            return True
    except Exception as e:
        print(f"  [Bilgi] BFL FLUX Space adımı atlandı: {e}")

    return False


def _generate_image_with_pollinations_flux(prompt: str, seed: int, output_image_path: str) -> bool:
    """
    Tamamen ücretsiz Pollinations.ai Flux motoru ile 1080x1920 (9:16) dikey AI görseli üretir.
    Eğer ücretsiz katmanda HTTP 402 ('Retry after Xs' - 45 sn IP limiti) dönerse,
    boş/alakasız yedek ekrana düşmek yerine belirtilen süreyi bekleyip gerçek Flux AI
    görselini indirir. Böylece her sahne %100 konuyla alakalı gerçek AI çizimi olur.
    """
    import re as _re

    clean_prompt = _sanitize_ascii_prompt(prompt)[:260].strip()
    encoded_prompt = urllib.parse.quote(clean_prompt, safe="")
    pollinations_key = os.environ.get("POLLINATIONS_API_KEY", "").strip()

    url = (
        f"https://image.pollinations.ai/prompt/{encoded_prompt}"
        f"?width=1080&height=1920&seed={int(seed)}&model=flux&nologo=true"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YouTubeOtoStudio/2.0"}
    if pollinations_key:
        headers["Authorization"] = f"Bearer {pollinations_key}"

    for attempt in range(3):
        try:
            print(f"  [Pollinations Flux] Sahne görseli çiziliyor (Seed: {seed}, Deneme: {attempt + 1})...")
            resp = requests.get(url, headers=headers, timeout=35)
            if resp.status_code == 200 and len(resp.content) > 8000:
                with open(output_image_path, "wb") as f:
                    f.write(resp.content)
                print(f"  -> [Pollinations Flux] 1080x1920 gerçek AI görseli hazır: {output_image_path}")
                return True
            elif resp.status_code in (402, 429):
                # {"error":{"message":"Free limit reached: 1 image every 45 seconds per IP. Retry after 41s..."}}
                wait_sec = 42
                m = _re.search(r"Retry after\s*(\d+)s", resp.text)
                if m:
                    wait_sec = int(m.group(1)) + 3
                print(f"  [Ücretsiz AI Kotası] Gerçek görsel için {wait_sec} sn bekleniyor (boş ekrana düşmemek için)...")
                time.sleep(wait_sec)
                continue
        except Exception as e:
            print(f"  [Uyarı] Pollinations hatası: {e}")
            time.sleep(3.0)

    return False


def _create_cinematic_fallback_image(output_image_path: str, scene_id: int, topic_text: str = "") -> str:
    """
    İnternet kesintisi veya tüm görsel servislerinin yanıt vermemesi durumunda
    Pillow ile yüksek çözünürlüklü (1080x1920) sinematik gradyan + ışık dokulu
    bir sahne görseli oluşturur (sistem asla çökmez).
    """
    from PIL import Image, ImageDraw

    width, height = 1080, 1920
    palettes = [
        ((12, 20, 38), (38, 65, 110), (210, 150, 60)),
        ((28, 14, 36), (75, 30, 85), (230, 110, 80)),
        ((10, 30, 32), (25, 80, 85), (120, 210, 190)),
        ((32, 20, 14), (95, 55, 30), (245, 185, 90)),
    ]
    top_c, mid_c, accent_c = palettes[(scene_id - 1) % len(palettes)]

    img = Image.new("RGB", (width, height), top_c)
    draw = ImageDraw.Draw(img)

    for y in range(height):
        ratio = y / float(height)
        r = int(top_c[0] * (1 - ratio) + mid_c[0] * ratio)
        g = int(top_c[1] * (1 - ratio) + mid_c[1] * ratio)
        b = int(top_c[2] * (1 - ratio) + mid_c[2] * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Sinematik perspektif ray / ufuk çizgileri
    horizon_y = int(height * 0.58)
    vanish_x = width // 2
    for offset in range(-800, 801, 160):
        draw.line(
            [(vanish_x, horizon_y), (vanish_x + offset * 3, height)],
            fill=accent_c,
            width=3
        )

    img.save(output_image_path, "JPEG", quality=92)
    return output_image_path


def generate_visual_for_scene(
    scene: Dict[str, Any],
    global_style: str,
    visual_seed: int,
    output_dir: str,
    prefer_ai_video: bool = True
) -> Tuple[str, str]:
    """
    Tek bir sahne için hibrit yapay zeka görseli veya videosu üretir.

    Döndürür:
        Tuple[str, str]: (media_type, file_path)
            media_type: 'video' (hareketli AI MP4) veya 'image' (9:16 AI Görsel - Ken Burns uygulanacak)
    """
    os.makedirs(output_dir, exist_ok=True)
    scene_id = int(scene.get("scene_id", 1))
    # Aynı genel tohumu (seed) korurken her sahneye küçük deterministik ofset ekle
    scene_seed = int(visual_seed) + (scene_id * 7)
    full_prompt = build_consistent_prompt(scene, global_style)
    scene["ai_image_prompt_enhanced"] = full_prompt

    # 1. ÖNCELİK: Hareketli AI Video (FAL_KEY mevcutsa ve prefer_ai_video aktifse)
    if prefer_ai_video:
        video_out = os.path.join(output_dir, f"scene_{scene_id}_ai.mp4")
        if _generate_video_with_fal(full_prompt, scene_seed, video_out):
            scene["visual_type"] = "video"
            scene["visual_file_path"] = video_out
            return "video", video_out

    # 2. ÖNCELİK: 9:16 Dikey AI Görsel (BFL FLUX.1-schnell [HF_API_KEY Yetkili] -> Fal Flux -> Pollinations Flux)
    image_out = os.path.join(output_dir, f"scene_{scene_id}_ai.jpg")
    if _generate_image_with_bfl_flux_space(full_prompt, scene_seed, image_out):
        scene["visual_type"] = "image"
        scene["visual_file_path"] = image_out
        return "image", image_out

    if _generate_image_with_fal_flux(full_prompt, scene_seed, image_out):
        scene["visual_type"] = "image"
        scene["visual_file_path"] = image_out
        return "image", image_out

    if _generate_image_with_pollinations_flux(full_prompt, scene_seed, image_out):
        scene["visual_type"] = "image"
        scene["visual_file_path"] = image_out
        return "image", image_out

    # 3. ÖNCELİK: Kesintisiz Sinematik Yedek Görsel
    print(f"  [Yedek Tuval] Sahne {scene_id} için sinematik tuval oluşturuluyor...")
    _create_cinematic_fallback_image(image_out, scene_id)
    scene["visual_type"] = "image"
    scene["visual_file_path"] = image_out
    return "image", image_out
