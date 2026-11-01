"""
video_builder.py - Pixabay API Stok Video İndirici ve MoviePy Montaj Motoru

Bu modülün amacı:
1. Pixabay API (https://pixabay.com/api/docs/) kullanarak senaryodaki her bir sahne
   için yüksek kaliteli, telifsiz stok videolar aramak ve otomatik olarak indirmek.
2. İndirilen yatay (16:9) veya dikey videoları akıllı merkez kırpma (center-crop)
   ve ölçekleme ile YouTube Shorts için ideal dikey 1080x1920 (9:16) boyutuna dönüştürmek.
3. PIXABAY_API_KEY girilmediğinde veya arama sonucu dönmediğinde sistemin aksamaması için
   otomatik olarak şık, sinematik renkli arka plan klibi (fallback visual) oluşturmak.
4. MoviePy motoru ile (MoviePy 1.x ve 2.x ile tam uyumlu) ses sürelerine göre videoları
   kırpmak / döngüye sokmak, sahneleri sırayla birbirine bağlayıp MP4 olarak render almak.
"""

import os
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv

# Ortam değişkenlerini yükle
load_dotenv()

# MoviePy 1.x ve 2.x sürümlerine uyumlu içe aktarma
try:
    from moviepy import VideoFileClip, AudioFileClip, ColorClip, concatenate_videoclips
except ImportError:
    from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip, concatenate_videoclips


# ---------------------------------------------------------------------------
# SÜRÜM UYUMLULUK VE VİDEO DİKEY FORMAT DÖNÜŞTÜRÜCÜ YARDIMCILARI
# ---------------------------------------------------------------------------

def apply_clip_audio(clip, audio_clip):
    """MoviePy sürümüne göre ses atamasını yapar (with_audio veya set_audio)."""
    if hasattr(clip, "with_audio"):
        return clip.with_audio(audio_clip)
    elif hasattr(clip, "set_audio"):
        return clip.set_audio(audio_clip)
    return clip


def clip_subrange(clip, start_time: float, end_time: float):
    """MoviePy sürümüne göre kırpma yapar (subclipped veya subclip)."""
    if hasattr(clip, "subclipped"):
        return clip.subclipped(start_time, end_time)
    elif hasattr(clip, "subclip"):
        return clip.subclip(start_time, end_time)
    return clip


def format_clip_to_vertical_shorts(clip, target_width: int = 1080, target_height: int = 1920):
    """
    Pixabay'den gelen yatay (16:9) veya farklı oranlardaki videoları
    bozulma (esneme) olmadan merkezden kırparak dikey 1080x1920 (9:16) yapar.
    """
    w, h = clip.size

    # Hedef en-boy oranı: 1080 / 1920 = 9 / 16 = 0.5625
    target_ratio = target_width / target_height
    current_ratio = w / h

    try:
        # MoviePy 2.x desteği
        if hasattr(clip, "resized"):
            from moviepy.video.fx import Crop

            if current_ratio > target_ratio:
                # Video hedeften daha geniş (örn: 1920x1080 yatay video)
                # Yüksekliği 1920'ye ölçekle, genişlikten merkez kırp
                scaled = clip.resized(height=target_height)
                new_w, new_h = scaled.size
                cropped = scaled.with_effects([
                    Crop(width=target_width, height=target_height, x_center=new_w / 2, y_center=new_h / 2)
                ])
                return cropped
            else:
                # Video hedeften daha dar
                # Genişliği 1080'e ölçekle, yükseklikten merkez kırp
                scaled = clip.resized(width=target_width)
                new_w, new_h = scaled.size
                cropped = scaled.with_effects([
                    Crop(width=target_width, height=target_height, x_center=new_w / 2, y_center=new_h / 2)
                ])
                return cropped

        # MoviePy 1.x desteği
        elif hasattr(clip, "resize"):
            from moviepy.video.fx.all import crop

            if current_ratio > target_ratio:
                scaled = clip.resize(height=target_height)
                new_w, new_h = scaled.size
                x1 = (new_w - target_width) / 2
                x2 = x1 + target_width
                return crop(scaled, x1=x1, y1=0, x2=x2, y2=target_height)
            else:
                scaled = clip.resize(width=target_width)
                new_w, new_h = scaled.size
                y1 = (new_h - target_height) / 2
                y2 = y1 + target_height
                return crop(scaled, x1=0, y1=y1, x2=target_width, y2=y2)

    except Exception as e:
        print(f"  [UYARI] Boyutlandırma hatası: {e}. Standart ölçekleme deneniyor.")
        try:
            if hasattr(clip, "resized"):
                return clip.resized(height=target_height)
            elif hasattr(clip, "resize"):
                return clip.resize(height=target_height)
        except Exception:
            pass

    return clip


def loop_video_clip(clip, target_duration: float):
    """
    Video süresi sesten kısaysa, ses bitene kadar videoyu döngüye sokarak uzatır.
    """
    try:
        if hasattr(clip, "loop"):
            return clip.loop(duration=target_duration)
        elif hasattr(clip, "with_effects"):
            from moviepy.video.fx import Loop
            return clip.with_effects([Loop(duration=target_duration)])
    except Exception:
        pass

    # Basit döngü yedeği
    repeats = int(target_duration // clip.duration) + 1
    repeated = concatenate_videoclips([clip] * repeats)
    return clip_subrange(repeated, 0, target_duration)


# ---------------------------------------------------------------------------
# 1. PIXABAY API İLE VİDEO İNDİRME MOTORU
# ---------------------------------------------------------------------------

def download_pixabay_video(query: str, output_path: str) -> str:
    """
    Pixabay Video API üzerinden arama kelimesine en uygun stok videoyu bulur ve indirir.
    
    Parametreler:
        query (str): Aranacak İngilizce anahtar kelime (Örn: 'pyramids egypt').
        output_path (str): İndirilecek dosyanın yolu.
        
    Döndürür:
        str: Başarıyla indirilen video dosyasının yolu, başarısızsa boş string.
    """
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()

    if not api_key or api_key.startswith("BURAYA"):
        return ""

    url = "https://pixabay.com/api/videos/"
    params = {
        "key": api_key,
        "q": query,
        "per_page": 5,
        "safesearch": "true"
    }

    try:
        print(f"  [Pixabay API] '{query}' için video aranıyor...")
        response = requests.get(url, params=params, timeout=15)

        if response.status_code != 200:
            print(f"  [UYARI] Pixabay API yanıt vermedi (Durum: {response.status_code})")
            return ""

        data = response.json()
        hits = data.get("hits", [])

        # Eğer ilk aramada sonuç yoksa daha genel bir arama yap
        if not hits:
            general_query = query.split()[0] if query.split() else "cinematic"
            print(f"  [Pixabay API] Sonuç bulunamadı, genel arama deneniyor: '{general_query}'")
            params["q"] = general_query
            data = requests.get(url, params=params, timeout=15).json()
            hits = data.get("hits", [])

        if not hits:
            return ""

        # En uygun video boyutunu (medium veya large) seç
        hit = hits[0]
        videos_dict = hit.get("videos", {})
        
        # 'medium' (1280x720) veya 'large' (1920x1080) hızlı indirme ve kalite için idealdir
        chosen_video = videos_dict.get("medium") or videos_dict.get("large") or videos_dict.get("small")
        
        if not chosen_video or not chosen_video.get("url"):
            return ""

        video_url = chosen_video["url"]

        print(f"  [İndiriliyor] Pixabay stok videosu indiriliyor...")
        video_stream = requests.get(video_url, timeout=30)
        
        with open(output_path, "wb") as f:
            f.write(video_stream.content)

        print(f"  -> Video başarıyla kaydedildi: {output_path}")
        return output_path

    except Exception as e:
        print(f"  [UYARI] Pixabay indirme hatası: {e}")
        return ""


# ---------------------------------------------------------------------------
# 2. PEXELS API (YEDEK STOK MOTORU)
# ---------------------------------------------------------------------------

def download_pexels_video(query: str, output_path: str) -> str:
    """Eğer kullanıcıda Pexels API anahtarı da varsa ikincil yedek olarak çalışır."""
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key or api_key.startswith("BURAYA"):
        return ""

    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=3&orientation=portrait"

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return ""
        data = response.json()
        videos = data.get("videos", [])
        if not videos:
            return ""
        
        video_files = videos[0].get("video_files", [])
        chosen_url = video_files[0].get("link") if video_files else None
        if not chosen_url:
            return ""

        stream = requests.get(chosen_url, timeout=30)
        with open(output_path, "wb") as f:
            f.write(stream.content)
        return output_path
    except Exception:
        return ""


def get_stock_video_for_scene(query: str, output_path: str) -> str:
    """
    Önce Pixabay'i dener; bulunamazsa veya anahtar yoksa Pexels'i dener.
    """
    # 1. Öncelikli olarak Pixabay denenir
    path = download_pixabay_video(query, output_path)
    if path and os.path.exists(path):
        return path

    # 2. Yedek olarak Pexels denenir
    path = download_pexels_video(query, output_path)
    if path and os.path.exists(path):
        return path

    return ""


def create_fallback_clip(duration: float, scene_id: int):
    """
    API anahtarı olmadığında veya internet yokken
    MoviePy ile şık dikey renkli sinematik arka plan klibi üretir.
    """
    color_palette = [
        (15, 23, 42),   # Gece Mavisi
        (45, 10, 40),   # Bordo
        (10, 35, 30),   # Koyu Zümrüt
        (30, 25, 45),   # Mistik Mor
        (25, 25, 25)    # Antrasit Siyah
    ]
    color = color_palette[(scene_id - 1) % len(color_palette)]
    return ColorClip(size=(1080, 1920), color=color, duration=duration)


# ---------------------------------------------------------------------------
# 3. MOVIEPY İLE MONTAJ VE RENDER
# ---------------------------------------------------------------------------

def build_final_video(
    scenes: List[Dict[str, Any]],
    output_video_path: str = "final_output.mp4",
    global_style: str = "cinematic documentary photography, 35mm lens, dramatic volumetric lighting, 8k, vertical 9:16",
    visual_seed: int = 428571,
    use_ai_generation: bool = True
) -> str:
    """
    Yeni Mimari:
    - use_ai_generation=True (varsayılan) olduğunda Pixabay stok videoları yerine
      ai_visual_generator.py (Flux 9:16 / Fal.ai Video) ve ffmpeg_renderer.py (yerel FFmpeg zoompan + .ass altyazı)
      motorlarını kullanarak düşük RAM ve yüksek hızla %100 yapay zeka videosu üretir.
    """
    if use_ai_generation:
        import shutil
        from ai_visual_generator import generate_visual_for_scene
        from ffmpeg_renderer import render_full_project_ffmpeg

        print("\n" + "=" * 60)
        print("🤖 %100 YAPAY ZEKA GÖRSEL/VİDEO + FFMPEG ZOOMPAN MOTORU BAŞLATILDI")
        print("=" * 60)

        temp_job_dir = os.path.abspath("temp_ai_build")
        visuals_dir = os.path.join(temp_job_dir, "visuals")
        os.makedirs(visuals_dir, exist_ok=True)

        valid_scenes = []
        for idx, scene in enumerate(scenes):
            scene_id = scene.get("scene_id", idx + 1)
            audio_path = scene.get("audio_file_path", "")
            if not audio_path or not os.path.exists(audio_path):
                continue
            print(f"\n[AI Sahne {scene_id}] Görsel/Video üretiliyor (Seed: {visual_seed})...")
            generate_visual_for_scene(
                scene=scene,
                global_style=global_style,
                visual_seed=visual_seed,
                output_dir=visuals_dir,
                prefer_ai_video=True
            )
            valid_scenes.append(scene)

        if not valid_scenes:
            print("[HATA] İşlenecek geçerli sahne bulunamadı!")
            return ""

        rendered_temp = render_full_project_ffmpeg(
            scenes=valid_scenes,
            output_dir=temp_job_dir,
            final_video_name="rendered_out.mp4",
            burn_subtitles=True
        )
        if rendered_temp and os.path.exists(rendered_temp):
            shutil.copy2(rendered_temp, output_video_path)
            size_mb = os.path.getsize(output_video_path) / (1024 * 1024)
            print(f"\n✅ Final AI videosu başarıyla oluşturuldu: {output_video_path} ({size_mb:.2f} MB)")
            return output_video_path

    print("\n" + "=" * 60)
    print("🎬 VİDEO VE SES MONTAJ SÜRECİ BAŞLATILDI (STOK YEDEK)")
    print("=" * 60)

    video_clips = []
    temp_files = []

    for idx, scene in enumerate(scenes):
        scene_id = scene.get("scene_id", idx + 1)
        audio_path = scene.get("audio_file_path", "")
        search_terms = scene.get("stock_search_terms", ["cinematic mystery"])
        query = search_terms[0] if search_terms else "cinematic"

        # 1. Ses dosyasını kontrol et
        if not audio_path or not os.path.exists(audio_path):
            print(f"[UYARI] Sahne {scene_id} için ses dosyası bulunamadı, atlanıyor.")
            continue

        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        print(f"\n[Sahne {scene_id}] Ses Süresi: {audio_duration:.2f} saniye")

        # 2. Pixabay (veya Pexels) üzerinden stok videoyu indir
        temp_stock_file = f"temp_stock_scene_{scene_id}.mp4"
        downloaded = get_stock_video_for_scene(query, temp_stock_file)

        clip = None
        if downloaded and os.path.exists(downloaded):
            try:
                raw_clip = VideoFileClip(downloaded)
                temp_files.append(downloaded)

                # Süre senkronizasyonu: video sesten kısaysa döngüye al, uzunsa kırp
                if raw_clip.duration < audio_duration:
                    clip = loop_video_clip(raw_clip, audio_duration)
                else:
                    clip = clip_subrange(raw_clip, 0, audio_duration)

                # Dikey 1080x1920 Shorts formatına dönüştür (Center Crop)
                clip = format_clip_to_vertical_shorts(clip, target_width=1080, target_height=1920)

            except Exception as e:
                print(f"  [UYARI] İndirilen video işlenirken hata: {e}. Yedek sahneye geçiliyor.")
                clip = None

        # Eğer stok video bulunamadıysa yedek görsel klibi kullan
        if clip is None:
            print(f"  [Yedek Görsel] Sahne {scene_id} için estetik dikey arka plan oluşturuluyor.")
            clip = create_fallback_clip(duration=audio_duration, scene_id=scene_id)

        # Sesi videoya ekle
        clip = apply_clip_audio(clip, audio_clip)
        video_clips.append(clip)

    if not video_clips:
        print("[HATA] Montajlanacak hiçbir geçerli sahne bulunamadı!")
        return ""

    # 4. Tüm sahneleri sırayla bağla
    print(f"\n[Montaj] Toplam {len(video_clips)} sahne tek bir dikey videoda birleştiriliyor...")
    final_clip = concatenate_videoclips(video_clips, method="compose")

    # 5. MP4 dosyası olarak render al
    print(f"[Render] Video dosyaya yazılıyor: '{output_video_path}'...")
    final_clip.write_videofile(
        output_video_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",
        logger=None
    )

    # 6. Geçici indirilen stok videoları temizle
    for temp_f in temp_files:
        if os.path.exists(temp_f):
            try:
                os.remove(temp_f)
            except Exception:
                pass

    if os.path.exists(output_video_path):
        size_mb = os.path.getsize(output_video_path) / (1024 * 1024)
        print(f"\n✅ Final videosu başarıyla oluşturuldu!")
        print(f"📁 Dosya: {output_video_path} ({size_mb:.2f} MB)")
        return output_video_path

    return ""


# ---------------------------------------------------------------------------
# TEST VE ÇALIŞTIRMA BLOKU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== video_builder.py Testi (Pixabay Uyumlu) Başlatıldı ===")
    
    test_scenes = [
        {
            "scene_id": 1,
            "stock_search_terms": ["pyramids egypt"],
            "audio_file_path": "test_audio_output/scene_1.mp3"
        },
        {
            "scene_id": 2,
            "stock_search_terms": ["archeology chamber"],
            "audio_file_path": "test_audio_output/scene_2.mp3"
        }
    ]

    out_file = "test_shorts_output.mp4"
    result_path = build_final_video(test_scenes, output_video_path=out_file)

    if result_path and os.path.exists(result_path):
        print(f"\n✅ video_builder.py testi eksiksiz başarıyla tamamlandı: {result_path}")
    else:
        print("\n❌ video_builder.py testi başarısız oldu!")
