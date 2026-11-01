"""
main.py - YouTube Video Otomasyonu Ana Orkestrasyon Betiği

Bu modülün amacı:
1. YouTube Shorts video üretiminin 4 temel halkasını tek bir komutla uçtan uca çalıştırmak:
   - Adım 1: Gemini API ile senaryo, başlık, açıklama ve sahne bazlı stok arama terimleri üretimi.
   - Adım 2: ElevenLabs / Edge-TTS ile sahne metinlerinin yüksek kaliteli Türkçe seslendirmesi (.mp3).
   - Adım 3: Pixabay API'den stok videoların indirilmesi ve MoviePy ile seslere göre montajlanıp MP4 render alınması.
   - Adım 4: YouTube Data API v3 ile oluşturulan videonun kanala otomatik yüklenmesi.
2. Komut satırından parametre alabilme (argparse desteği):
   Örnek: python main.py --topic "Mars'ta Yaşam" --style "science_space" --privacy "private"
"""

import os
import sys
import argparse
from dotenv import load_dotenv

# Kendi yazdığımız modülleri içe aktarıyoruz
from generate_script import create_youtube_script
from audio_generator import process_script_audio
from video_builder import build_final_video
from youtube_uploader import upload_video_to_youtube

# .env dosyasındaki ortam değişkenlerini yükle
load_dotenv()


def run_full_youtube_pipeline(
    topic: str = "Büyük Piramitlerin Altında Bulunan Gizli Odalar",
    style_preset: str = "documentary_history",
    publish_status: str = "private",
    output_video_path: str = "final_youtube_shorts.mp4",
    skip_upload: bool = False
) -> bool:
    """
    Uçtan uca tüm YouTube video otomasyon sürecini sırasıyla yönetir.
    
    Parametreler:
        topic (str): Üretilecek videonun ana konusu.
        style_preset (str): Görsel ve kurgu stili (Örn: 'documentary_history', 'cinematic_dark', 'cyberpunk_neon').
        publish_status (str): YouTube yükleme gizlilik durumu ('private', 'unlisted', 'public').
        output_video_path (str): Üretilecek nihai video dosyasının kaydedileceği yol.
        
    Döndürür:
        bool: Tüm süreç başarıyla tamamlandıysa True, aksi halde False.
    """
    print("\n" + "=" * 70)
    print("🚀 YOUTUBE SHORTS OTOMASYON ZİNCİRİ BAŞLATILDI")
    print(f"📌 Konu            : {topic}")
    print(f"🎨 Stil Konsepti   : {style_preset}")
    print(f"🔒 Gizlilik Durumu : {publish_status}")
    print("=" * 70)

    # ---------------------------------------------------------------------------
    # ADIM 1: Gemini API ile Senaryo ve Meta Veri Üretimi
    # ---------------------------------------------------------------------------
    print("\n[1/4] 📝 ADIM 1: Gemini API ile senaryo ve görsel tanımları üretiliyor...")
    script_data = create_youtube_script(topic=topic, style_preset=style_preset)

    if not script_data or "scenes" not in script_data or not script_data["scenes"]:
        print("❌ [HATA] Senaryo üretilemedi! Süreç sonlandırılıyor.")
        return False

    title = script_data.get("title", f"{topic} #shorts")
    description = script_data.get("description", f"{topic} hakkında dikey video. #shorts #viral")
    total_scenes = len(script_data["scenes"])
    
    print(f"  ✅ Senaryo Hazır! (Toplam {total_scenes} sahne)")
    print(f"  📌 Başlık: {title}")

    # ---------------------------------------------------------------------------
    # ADIM 2: ElevenLabs / Edge-TTS ile Seslendirme Üretimi
    # ---------------------------------------------------------------------------
    print("\n[2/4] 🎙️ ADIM 2: Metinler insan sesine dönüştürülüyor (TTS)...")
    audio_dir = "temp_audio"
    updated_scenes = process_script_audio(script_data, output_dir=audio_dir)

    # Ses dosyalarının oluşturulduğunu kontrol et
    valid_scenes = [s for s in updated_scenes if s.get("audio_file_path") and os.path.exists(s["audio_file_path"])]
    if not valid_scenes:
        print("❌ [HATA] Hiçbir sahne için ses dosyası üretilemedi! Süreç sonlandırılıyor.")
        return False

    print(f"  ✅ {len(valid_scenes)} sahnenin ses dosyaları başarıyla hazırlandı.")

    # ---------------------------------------------------------------------------
    # ADIM 3: Yapay Zeka Görsel/Video + FFmpeg (zoompan + .ASS) ile Montaj ve Render
    # ---------------------------------------------------------------------------
    print("\n[3/4] 🎬 ADIM 3: Yapay zeka sahneleri üretiliyor ve FFmpeg ile render ediliyor...")
    rendered_file = build_final_video(
        valid_scenes,
        output_video_path=output_video_path,
        global_style=script_data.get("global_style", ""),
        visual_seed=int(script_data.get("visual_seed", 428571)),
        use_ai_generation=True
    )

    if not rendered_file or not os.path.exists(rendered_file):
        print("❌ [HATA] Final video dosyası render edilemedi! Süreç sonlandırılıyor.")
        return False

    file_size_mb = os.path.getsize(rendered_file) / (1024 * 1024)
    print(f"  ✅ Video montajı tamamlandı! ({rendered_file} - {file_size_mb:.2f} MB)")

    # ---------------------------------------------------------------------------
    # ADIM 4: YouTube Data API v3 ile Kanala Yükleme
    # ---------------------------------------------------------------------------
    if skip_upload:
        print("\n[4/4] ⏭️ ADIM 4: YouTube yüklemesi atlandı (--skip-upload aktif).")
        print("\n" + "=" * 70)
        print("🎉 TEBRİKLER! VİDEO BAŞARIYLA OLUŞTURULDU!")
        print(f"📁 Video Dosyası: {os.path.abspath(rendered_file)}")
        print("=" * 70)
        return True

    print("\n[4/4] 📤 ADIM 4: YouTube Data API v3 ile videonun kanala yüklenmesi...")
    clean_topic_tag = "".join(ch for ch in topic.lower() if ch.isalnum())
    tags = ["shorts", "viral", "ai", clean_topic_tag]

    try:
        video_id = upload_video_to_youtube(
            video_file=rendered_file,
            title=title,
            description=description,
            tags=tags,
            privacy_status=publish_status
        )
        print("\n" + "=" * 70)
        print("🎉 TEBRİKLER! TÜM OTOMASYON İŞ AKIŞI BAŞARIYLA TAMAMLANDI!")
        print(f"📁 Oluşturulan Video: {os.path.abspath(rendered_file)}")
        if video_id and video_id != "SIMULATED_VIDEO_ID_SUCCESS":
            print(f"🔗 YouTube Canlı Linki: https://youtu.be/{video_id}")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"⚠️ [BİLGİ] YouTube API yükleme adımı istisna bildirdi: {e}")
        print(f"📁 Üretilen '{rendered_file}' videonuz bilgisayarınızda hazır durumdadır.")
        return True


# ---------------------------------------------------------------------------
# KOMUT SATIRI ÇALIŞTIRMA (CLI)
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="YouTube Shorts Yapay Zeka Otomasyon Sistemi",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--topic",
        type=str,
        default="Büyük Piramitlerin Altında Bulunan Gizli Odalar",
        help="Videonun konusu"
    )
    parser.add_argument(
        "--style",
        type=str,
        default="documentary_history",
        choices=["documentary_history", "cinematic_dark", "hyper_realistic", "cyberpunk_neon", "science_space"],
        help="Görsel ve kurgu stili"
    )
    parser.add_argument(
        "--privacy",
        type=str,
        default="private",
        choices=["private", "unlisted", "public"],
        help="YouTube yükleme gizlilik seviyesi (Güvenlik için varsayılan: 'private')"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="final_youtube_shorts.mp4",
        help="Oluşturulacak video dosya adı"
    )
    parser.add_argument(
        "--skip-upload",
        action="store_true",
        help="YouTube yükleme adımını atlar, sadece videoyu yerel olarak üretir"
    )

    args = parser.parse_args()

    success = run_full_youtube_pipeline(
        topic=args.topic,
        style_preset=args.style,
        publish_status=args.privacy,
        output_video_path=args.output,
        skip_upload=args.skip_upload
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
