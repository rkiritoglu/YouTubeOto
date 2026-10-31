import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from moviepy import ColorClip, TextClip, AudioFileClip, CompositeVideoClip
from gtts import gTTS

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def create_sample_video(output_filename="output.mp4"):
    text_content = "Yapay zeka ile otomatik olusturulan YouTube videosuna hos geldiniz!"
    audio_path = "voice.mp3"

    tts = gTTS(text=text_content, lang="tr", slow=False)
    tts.save(audio_path)
    audio_clip = AudioFileClip(audio_path)
    duration = audio_clip.duration + 1.0

    bg_clip = ColorClip(size=(1920, 1080), color=(25, 25, 35)).with_duration(duration)
    
    txt_clip = (
        TextClip(
            text=text_content,
            font_size=46,
            color="white",
            size=(1600, None),
            method="caption",
        )
        .with_position("center")
        .with_duration(duration)
    )

    video = CompositeVideoClip([bg_clip, txt_clip]).with_audio(audio_clip)
    video.write_videofile(output_filename, fps=24, codec="libx264", audio_codec="aac")

    audio_clip.close()
    if os.path.exists(audio_path):
        os.remove(audio_path)

    print(f"[+] Video basariyla uretildi: {output_filename}")
    return output_filename

def get_authenticated_service():
    creds = None
    token_file = "token.pickle"

    if os.path.exists(token_file):
        with open(token_file, "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret_file = "client_secret.json" if os.path.exists("client_secret.json") else "client_secrets.json"
            flow = InstalledAppFlow.from_client_secrets_file(secret_file, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_file, "wb") as token:
            pickle.dump(creds, token)

    return build("youtube", "v3", credentials=creds)

def upload_video(youtube, file_path, title, description, tags=None):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or ["otomasyon", "python", "moviepy"],
            "categoryId": "28",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(file_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print("[*] Video YouTube'a yukleniyor...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    Yukleme durumu: %{int(status.progress() * 100)}")

    video_id = response.get("id")
    print(f"[+] Yukleme tamamlandi! Video URL: https://www.youtube.com/watch?v={video_id}")
    return video_id

if __name__ == "__main__":
    generated_video = create_sample_video("otomatik_video.mp4")
    
    try:
        youtube_client = get_authenticated_service()
        upload_video(
            youtube=youtube_client,
            file_path=generated_video,
            title="Python ve MoviePy ile Otomatik Video",
            description="Bu video Python MoviePy ve YouTube Data API v3 kullanılarak otomatik olarak yüklenmiştir.",
            tags=["python", "moviepy", "youtube api", "otomasyon"],
        )
    except Exception as e:
        print(f"\n[!] YouTube yukleme adiminda hata olustu: {e}")
        print(f"[+] Ancak videonuz basariyla olusturuldu ve kaydedildi: {generated_video}")
        print("[i] Videoyu YouTube Studio web sitesinden surukle-birak ile de yukleyebilirsiniz.")
