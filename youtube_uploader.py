"""
youtube_uploader.py - YouTube Data API v3 ile Otomatik Video Yükleme Modülü

Bu modülün amacı:
1. Google Cloud Console üzerinden oluşturulan OAuth 2.0 kimlik doğrulama dosyasını
   (client_secret.json) kullanarak YouTube hesabına güvenli erişim sağlamak.
2. İlk oturum açmada tarayıcı üzerinden kullanıcı izni almak ve oluşturulan erişim
   anahtarını (token.pickle / token.json) yerel olarak saklayarak sonraki yüklemelerin
   tamamen otomatik (kullanıcı müdahalesiz) gerçekleşmesini sağlamak.
3. MoviePy ile üretilen dikey Shorts (.mp4) videosunu YouTube Data API v3 üzerinden
   başlık, açıklama, etiketler ve gizlilik durumu ('private', 'unlisted', 'public')
   ile kanala yüklemek.
4. client_secret.json dosyası henüz kurulmamışsa sistemi çökertmeyip kullanıcıya
   açıklayıcı rehber sunmak ve simülasyon çıktısı vermek.
"""

import os
import pickle
from typing import List, Optional
from dotenv import load_dotenv

# Ortam değişkenlerini yükle
load_dotenv()

# YouTube API Yükleme İzni (Scope)
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# Varsayılan OAuth dosya adı
CLIENT_SECRET_FILE = os.environ.get("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_PICKLE_FILE = "token.pickle"


def get_authenticated_youtube_service():
    """
    OAuth 2.0 ile YouTube API servisine bağlanır ve yetkilendirilmiş istemci döndürür.
    Daha önce oturum açılmışsa 'token.pickle' dosyasından otomatik yeniler.
    """
    credentials = None

    # 1. Daha önce kaydedilmiş token var mı kontrol et
    if os.path.exists(TOKEN_PICKLE_FILE):
        try:
            with open(TOKEN_PICKLE_FILE, "rb") as token:
                credentials = pickle.load(token)
        except Exception as e:
            print(f"[UYARI] Kayıtlı oturum dosyası okunamadı: {e}")
            credentials = None

    # 2. Token yoksa veya süresi dolmuşsa yenile / oturum aç
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            from google.auth.transport.requests import Request
            print("[YouTube API] Oturum süresi dolmuş, yenileniyor...")
            credentials.refresh(Request())
        else:
            # client_secret.json dosyasının varlığını kontrol et
            if not os.path.exists(CLIENT_SECRET_FILE):
                print(f"\n[UYARI] '{CLIENT_SECRET_FILE}' dosyası bulunamadı!")
                print("YouTube'a otomatik yükleme yapabilmek için Google Cloud Console'dan")
                print("indirdiğiniz OAuth istemci dosyasını proje dizinine 'client_secret.json' olarak kaydedin.")
                return None

            from google_auth_oauthlib.flow import InstalledAppFlow
            print("\n[YouTube API] Yeni oturum açılıyor. Lütfen açılan tarayıcı penceresinde Google hesabınızı onaylayın...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            credentials = flow.run_local_server(port=0)

        # Token'ı gelecekteki kullanımlar için kaydet
        with open(TOKEN_PICKLE_FILE, "wb") as token:
            pickle.dump(credentials, token)

    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials)


def upload_video_to_youtube(
    video_file: str,
    title: str,
    description: str,
    tags: Optional[List[str]] = None,
    category_id: str = "27",  # 27: Eğitim (Education), 28: Bilim/Teknoloji, 22: Blog
    privacy_status: str = "private"  # 'private', 'unlisted' veya 'public'
) -> str:
    """
    Belirtilen video dosyasını tüm meta verileriyle birlikte YouTube'a yükler.
    
    Parametreler:
        video_file (str): Yüklenecek MP4 video dosyasının yolu.
        title (str): Video başlığı (Maks. 100 karakter).
        description (str): Video açıklaması ve etiketler.
        tags (List[str]): Video anahtar kelimeleri / etiketleri.
        category_id (str): YouTube kategori numarası (Örn: '27' = Eğitim).
        privacy_status (str): 'private' (Gizli), 'unlisted' (Liste Dışı), 'public' (Herkese Açık).
        
    Döndürür:
        str: Başarıyla yüklenen videonun YouTube Video ID'si.
    """
    if not os.path.exists(video_file):
        raise FileNotFoundError(f"Yüklenecek video dosyası bulunamadı: {video_file}")

    print("\n" + "=" * 60)
    print("📤 YOUTUBE VİDEO YÜKLEME AŞAMASI BAŞLADI")
    print("=" * 60)
    print(f"📌 Başlık: {title}")
    print(f"🔒 Gizlilik: {privacy_status}")
    print(f"📁 Video: {video_file}")

    youtube = get_authenticated_youtube_service()

    if youtube is None:
        print("\n[BİLGİ] YouTube API kimlik doğrulaması (client_secret.json) henüz kurulmamış.")
        print("[SİMÜLASYON] Video yerel olarak başarıyla üretildi ve bilgisayarınıza kaydedildi.")
        print(f"[SİMÜLASYON] Üretilen '{video_file}' dosyasını YouTube Studio üzerinden manuel de yükleyebilirsiniz.")
        # Test akışını tamamlayabilmek için simüle edilmiş örnek ID döndürür
        return "SIMULATED_VIDEO_ID_SUCCESS"

    from googleapiclient.http import MediaFileUpload

    # YouTube video gövde bilgileri (Metadata)
    body = {
        "snippet": {
            "title": title[:100],  # YouTube başlık sınırı
            "description": description,
            "tags": tags or ["shorts", "viral", "ai"],
            "categoryId": category_id
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    # Resumable (kesintiye dayanıklı) yükleyici hazırlığı
    media = MediaFileUpload(
        video_file,
        chunksize=5 * 1024 * 1024,  # 5 MB parçalar halinde yükle
        resumable=True,
        mimetype="video/mp4"
    )

    print("\n[Yükleme] Video YouTube sunucularına aktarılıyor...")
    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"  -> Yükleme İlerlemesi: %{progress}")

    video_id = response.get("id", "")
    print(f"\n🎉 TEBRİKLER! Video YouTube'a başarıyla yüklendi!")
    print(f"🔗 Video ID: {video_id}")
    print(f"🔗 YouTube Bağlantısı: https://youtu.be/{video_id}")

    return video_id


# ---------------------------------------------------------------------------
# TEST VE ÇALIŞTIRMA BLOKU
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== youtube_uploader.py Testi Başlatıldı ===")
    
    test_video = "test_shorts_output.mp4"
    if not os.path.exists(test_video):
        print(f"Hata: Test için '{test_video}' bulunamadı.")
    else:
        sample_title = "Piramitlerin Gizli Odaları #shorts"
        sample_desc = "Piramitlerin altındaki sırları keşfedin! #shorts #viral #tarih"
        
        uploaded_id = upload_video_to_youtube(
            video_file=test_video,
            title=sample_title,
            description=sample_desc,
            tags=["shorts", "piramitler", "tarih"],
            privacy_status="private"
        )
        print(f"\nSonuç: {uploaded_id}")
        print("✅ youtube_uploader.py testi tamamlandı!")
