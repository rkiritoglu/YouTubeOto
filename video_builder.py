"""
video_builder.py - Pexels API Stok Video İndirici ve MoviePy Montaj Motoru

Bu modülün amacı:
1. Pexels API kullanarak senaryodaki sahneler için dikey (9:16 portrait) stok videolar aramak ve indirmek.
2. PEXELS_API_KEY bulunmadığında veya arama sonucu dönmediğinde sistemin çökmemesi için
   otomatik olarak şık, sinematik renkli arka plan klibi (fallback visual) oluşturmak.
3. MoviePy kütüphanesini kullanarak (hem MoviePy 1.x hem MoviePy 2.x ile %100 uyumlu)
   ses dosyalarının uzunluğuna göre videoları kırpmak / döngüye sokmak.
4. Ses ve görüntüleri senkronize etmek, tüm sahneleri arka arkaya bağlamak (concatenate)
   ve 1080x1920 (YouTube Shorts) formatında MP4 çıktısı render etmek.
"""

import os
import requests
from typing import List, Dict, Any
from dotenv import load_dotenv

# Ortam değişkenlerini yükle
load_dotenv()

# MoviePy 1.x ve MoviePy 2.x sürümlerine uyumlu içe aktarma
try:
    from moviepy import VideoFileClip, AudioFileClip, ColorClip, concatenate_videoclips
except ImportError:
    from moviepy.editor import VideoFileClip, AudioFileClip, ColorClip, concatenate_videoclips


# ---------------------------------------------------------------------------
# SÜRÜM UYUMLULUK YARDIMCILARI (MoviePy v1 vs v2)
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


def resize_video_clip(clip, target_width: int = 1080, target_height: int = 1920):
    """MoviePy sürümüne göre dikey boyuta ölçekler."""
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
    Eğer video süresi sesten kısaysa, ses süresine ulaşana kadar
    videoyu döngüye sokarak uzatır.
    """
    try:
        if hasattr(clip, "loop"):
            return clip.loop(duration=target_duration)
        elif hasattr(clip, "with_effects"):
            # MoviePy 2.x effect yöntemi
            from moviepy.video.fx import Loop
            return clip.with_effects([Loop(duration=target_duration)])
    except Exception:
        pass
    
    # Basit yedek döngü: klibi birden çok kez birleştirip kırp
    repeats = int(target_duration // clip.duration) + 1
    repeated = concatenate_videoclips([clip] * repeats)
    return clip_subrange(repeated, 0, target_duration)


# ---------------------------------------------------------------------------
# 1. PEXELS API İLE STOK VİDEO İNDİRME
# ---------------------------------------------------------------------------

def download_pexels_video(query: str, output_path: str, orientation: str = "portrait") -> str:
    """
    Pexels API üzerinden arama terimine en uygun dikey videoyu bulur ve indirir.
    
    Parametreler:
        query (str): Aranacak İngilizce terim (Örn: 'pyramids egypt').
        output_path (str): İndirilecek video dosya yolu.
        orientation (str): 'portrait' (dikey) veya 'landscape' (yatay).
        
    Döndürür:
        str: İndirilen video dosyasının yolu (Başarısızsa boş string).
    """
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()

    if not api_key or api_key.startswith("BURAYA"):
        # API anahtarı girilmemişse yedek görsel motoru devreye girer
        return ""

    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=5&orientation={orientation}"

    try:
        print(f"  [Pexels API] '{query}' araması yapılıyor...")
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            print(f"  [UYARI] Pexels API yanıt vermedi (Durum Kodu: {response.status_code})")
            return ""

        data = response.json()
        videos = data.get("videos", [])

        if not videos:
            print(f"  [UYARI] '{query}' için dikey video bulunamadı.")
            return ""

        # En uygun çözünürlükteki video bağlantısını bul
        video_files = videos[0].get("video_files", [])
        chosen_url = None

        # Tercihen dikey oranlı (height > width) HD bağlantıyı seç
        for vf in video_files:
            w = vf.get("width", 0)
            h = vf.get("height", 0)
            if h > w and h >= 720:
                chosen_url = vf.get("link")
                break

        if not chosen_url and video_files:
            chosen_url = video_files[0].get("link")

        if not chosen_url:
            return ""

        # Videoyu indir ve kaydet
        print(f"  [İndiriliyor] Video dosyası indiriliyor...")
        video_stream = requests.get(chosen_url, timeout=30)
        with open(output_path, "wb") as f:
            f.write(video_stream.content)

        print(f"  -> Stok video kaydedildi: {output_path}")
        return output_path

    except Exception as e:
        print(f"  [UYARI] Pexels video indirme hatası: {e}")
        return ""


def create_fallback_clip(duration: float, scene_id: int):
    """
    Pexels anahtarı olmadığında veya internet kesintisinde
    MoviePy ile dikey, sinematik degrade renk klibi üretir.
    """
    # Her sahne için farklı estetik koyu tonlar (Lacivert, Bordo, Zümrüt, Antrasit)
    color_palette = [
        (15, 23, 42),   # Koyu Gece Mavisi
        (45, 10, 40),   # Koyu Bordo
        (10, 35, 30),   # Koyu Zümrüt
        (30, 25, 45),   # Koyu Mor
        (25, 25, 25)    # Antrasit Siyah
    ]
    color = color_palette[(scene_id - 1) % len(color_palette)]
    return ColorClip(size=(1080, 1920), color=color, duration=duration)


# ---------------------------------------------------------------------------
# 2. MOVIEPY İLE VİDEO VE SES BİRLEŞTİRME (RENDER)
# ---------------------------------------------------------------------------

def build_final_video(scenes: List[Dict[str, Any]], output_video_path: str = "final_output.mp4") -> str:
    """
    Tüm sahnelerdeki videoları, üretilen ses sürelerine göre ayarlar,
    seslerle birleştirir ve tek bir dikey MP4 dosyası render eder.
    
    Parametreler:
        scenes (List[Dict]): Sahne ses dosya yollarını ve arama terimlerini içeren liste.
        output_video_path (str): Oluşturulacak MP4 videosunun hedef dosya yolu.
        
    Döndürür:
        str: Başarıyla oluşturulan videonun tam dosya yolu.
    """
    print("\n" + "=" * 60)
    print("🎬 VİDEO VE SES MONTAJ SÜRECİ BAŞLATILDI")
    print("=" * 60)

    video_clips = []
    temp_files = []

    for idx, scene in enumerate(scenes):
        scene_id = scene.get("scene_id", idx + 1)
        audio_path = scene.get("audio_file_path", "")
        search_terms = scene.get("stock_search_terms", ["cinematic mystery"])
        query = search_terms[0] if search_terms else "cinematic"

        # 1. Sahnenin ses dosyasını doğrula
        if not audio_path or not os.path.exists(audio_path):
            print(f"[UYARI] Sahne {scene_id} için ses dosyası bulunamadı, atlanıyor.")
            continue

        audio_clip = AudioFileClip(audio_path)
        audio_duration = audio_clip.duration
        print(f"\n[Sahne {scene_id}] Ses Süresi: {audio_duration:.2f} saniye")

        # 2. Pexels'ten stok videoyu indir
        temp_stock_file = f"temp_stock_scene_{scene_id}.mp4"
        downloaded = download_pexels_video(query, temp_stock_file)
        
        clip = None
        if downloaded and os.path.exists(downloaded):
            try:
                raw_clip = VideoFileClip(downloaded)
                temp_files.append(downloaded)

                # Süre senkronizasyonu: video kısaysa döngüye al, uzunsa kırp
                if raw_clip.duration < audio_duration:
                    clip = loop_video_clip(raw_clip, audio_duration)
                else:
                    clip = clip_subrange(raw_clip, 0, audio_duration)

                # Dikey 1080x1920 formata getir
                clip = resize_video_clip(clip, target_width=1080, target_height=1920)

            except Exception as e:
                print(f"  [UYARI] İndirilen video işlenemedi: {e}. Yedek sahneye geçiliyor.")
                clip = None

        # Eğer stok video indirilemediyse veya hata verdiyse yedek görsel klibi kullan
        if clip is None:
            print(f"  [Yedek Görsel] Sahne {scene_id} için renkli sinematik arka plan oluşturuluyor.")
            clip = create_fallback_clip(duration=audio_duration, scene_id=scene_id)

        # 3. Klibe ilgili sahnenin sesini entegre et
        clip = apply_clip_audio(clip, audio_clip)
        video_clips.append(clip)

    if not video_clips:
        print("[HATA] Montajlanacak hiçbir geçerli sahne bulunamadı!")
        return ""

    # 4. Tüm sahneleri sırayla birbirine bağla
    print(f"\n[Montaj] Toplam {len(video_clips)} sahne tek bir dikey videoda birleştiriliyor...")
    final_clip = concatenate_videoclips(video_clips, method="compose")

    # 5. MP4 dosyası olarak yüksek hız ve kalitede render al
    print(f"[Render] Video dosyaya yazılıyor: '{output_video_path}'...")
    final_clip.write_videofile(
        output_video_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        preset="ultrafast",  # Render süresini minimuma indirir
        logger=None          # Terminali temiz tutar
    )

    # 6. Geçici indirilen stok video dosyalarını temizle
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
    print("=== video_builder.py Testi Başlatıldı ===")
    
    # audio_generator testi tarafından üretilen ses dosyalarını kullanarak test yapalım
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
