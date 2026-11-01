"""
app.py - Üretim Seviyesi (Production-Grade) Yapay Zeka Video Stüdyosu (Streamlit)

Mimari Özellikler:
1. Native FFmpeg (zoompan + setpts + .ass altyazı): MoviePy CPU/RAM darboğazı olmadan C hızında render.
2. Bağımsız Worker + SQLite İş Kuyruğu (jobs.db): Tarayıcı sekmesi kapatılsa bile arka planda üretim devam eder.
   Canlı durum takibi @st.fragment(run_every="2s") ile sayfayı kilitlemeden yapılır.
3. Önce Ses, Sonra Görüntü (Audio-First Pacing): Her sahnenin ses süresi milisaniye bazında ölçülür,
   görsel ve video süreleri bu süreye göre sentezlenir.
4. Global Stil + Sabit Seed (Style Drift Koruması): Tüm sahneler aynı lens, ışık ve renk paletinde üretilir.
5. İzole 'output/<job_id>/' Paketleme & Ayrık YouTube Yükleyici: Render sonrası MP4 ve metadata.json
   önce diske kaydedilir; önizleme, indirme ve YouTube yükleme işlemleri bağımsız yürütülür.
"""

import os
import json
import streamlit as st
from dotenv import load_dotenv, set_key

from job_queue import init_db, create_job, list_jobs, update_job_progress
from worker import spawn_worker_for_job
from generate_script import create_youtube_script
from daily_runner import load_past_topics, generate_autonomous_railway_topic
from youtube_uploader import upload_video_to_youtube
from prompts import IMAGE_STYLE_PRESETS

load_dotenv()
init_db()

ENV_FILE_PATH = os.path.abspath(".env")

st.set_page_config(
    page_title="AI Video Stüdyosu | YouTube Shorts",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Şık koyu tema ve kart stilleri
st.markdown(
    """
    <style>
    .job-card {
        border: 1px solid rgba(128, 128, 128, 0.25);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 12px;
        background: rgba(30, 41, 59, 0.35);
    }
    .status-badge-running {
        color: #fbbf24;
        font-weight: 700;
    }
    .status-badge-completed {
        color: #34d399;
        font-weight: 700;
    }
    .status-badge-failed {
        color: #f87171;
        font-weight: 700;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ---------------------------------------------------------------------------
# YAN PANEL (SIDEBAR): SİSTEM DURUMU VE MİMARİ ÖZET
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🤖 AI Video Stüdyosu")
    st.caption("FFmpeg v7.1 + Hibrit AI + Bağımsız Worker Mimarisi")
    st.divider()

    groq_ok = bool(os.environ.get("GROQ_API_KEY", "").strip().startswith("gsk_"))
    fal_ok = bool(os.environ.get("FAL_KEY", "").strip())
    hf_ok = bool(os.environ.get("HF_API_KEY", "").strip().startswith("hf_"))
    eleven_ok = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip().startswith("sk_"))
    yt_ok = os.path.exists("client_secret.json")

    st.subheader("🔌 Aktif Motor Durumu")
    st.write(f"- **Senaryo Motoru:** {'✅ Groq Llama-3 / GPT-OSS' if groq_ok else '⚠️ Yerel / Gemini'}")
    st.write(f"- **AI Görsel (9:16):** ✅ Flux AI (Aktif)" + (" + HF Flux" if hf_ok else ""))
    st.write(f"- **AI Hareketli Video:** {'✅ Fal.ai Aktif' if fal_ok else '🔄 Flux + FFmpeg Zoompan'}")
    st.write(f"- **Seslendirme (TTS):** {'✅ ElevenLabs + Edge-TTS' if eleven_ok else '✅ Edge-TTS Neural (Ücretsiz)'}")
    st.write(f"- **Render Motoru:** ✅ Native FFmpeg (`zoompan` + `.ass`)")
    st.write(f"- **YouTube OAuth:** {'✅ Hazır' if yt_ok else '⚠️ client_secret.json Bekleniyor'}")

    st.divider()
    st.subheader("⚙️ Üretim Tercihleri")
    prefer_ai_video = st.toggle(
        "Hareketli AI Video Önceliği (Fal.ai)",
        value=True,
        help="FAL_KEY varsa sahneleri doğrudan hareketli AI video olarak üretir; yoksa otomatik Flux 9:16 + FFmpeg Ken Burns kullanır."
    )
    burn_subtitles = st.toggle(
        "Dinamik Kelime Vurgulu .ASS Altyazı",
        value=True,
        help="FFmpeg 'ass' filtresiyle kelime kelime vurgulanan Shorts altyazısını tek geçişte videoya yakar."
    )
    edge_voice = st.selectbox(
        "Türkçe Seslendirmen (Edge-TTS)",
        options=["tr-TR-AhmetNeural", "tr-TR-EmelNeural"],
        index=0
    )


# ---------------------------------------------------------------------------
# ANA SEKMELER
# ---------------------------------------------------------------------------
tab_studio, tab_queue, tab_gallery, tab_settings = st.tabs([
    "🎬 1. Yeni AI Video Üret",
    "⚡ 2. Canlı İş Kuyruğu (Worker)",
    "📁 3. Video Galerisi & YouTube Yükle",
    "🔑 4. API & Geçmiş Konular"
])


# ===========================================================================
# SEKME 1: YENİ AI VİDEO STÜDYOSU
# ===========================================================================
with tab_studio:
    st.subheader("🎬 Sıfırdan Yapay Zeka ile Dikey Video Oluştur")
    st.info(
        "**Nasıl Çalışır?** Stok video kullanılmaz. Önce seslendirme üretilip milisaniye süresi ölçülür, "
        "ardından **Global Stil + Sabit Seed** ile tüm sahnelerin yapay zeka görselleri/videoları çizilir ve "
        "arka plandaki bağımsız `worker.py` tarafından **FFmpeg `zoompan` + `.ass` altyazı** ile birleştirilir."
    )

    if "topic_input" not in st.session_state:
        st.session_state["topic_input"] = "Orient Express: Doğu Ekspresi'nin Çözülemeyen Gizemleri"
    if "style_input" not in st.session_state:
        st.session_state["style_input"] = "documentary_history"
    if "draft_script" not in st.session_state:
        st.session_state["draft_script"] = None

    col_t1, col_t2, col_t3 = st.columns([3, 1.3, 1.2])
    with col_t1:
        topic_val = st.text_input(
            "📌 Video Konusu (İstediğiniz konuyu yazın veya AI ile öneri alın)",
            value=st.session_state["topic_input"]
        )
        st.session_state["topic_input"] = topic_val

    with col_t2:
        style_options = list(IMAGE_STYLE_PRESETS.keys())
        current_style_idx = (
            style_options.index(st.session_state["style_input"])
            if st.session_state["style_input"] in style_options
            else 0
        )
        style_val = st.selectbox(
            "🎨 Görsel Atmosfer Stili",
            options=style_options,
            index=current_style_idx
        )
        st.session_state["style_input"] = style_val

    with col_t3:
        st.write("")
        st.write("")
        if st.button("🎲 AI ile Yeni Konu Bul", width="stretch"):
            with st.spinner("Yapay zeka daha önce işlenmemiş yeni bir konu araştırıyor..."):
                past = load_past_topics()
                suggestion = generate_autonomous_railway_topic(past)
                st.session_state["topic_input"] = suggestion.get("topic", topic_val)
                st.session_state["style_input"] = suggestion.get("style", style_val)
                st.session_state["draft_script"] = None
                st.rerun()

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📝 Adım 1: Senaryoyu & Sahne Promptlarını Hazırla (Önizlemeli)", width="stretch"):
            with st.spinner("Senaryo, Global Stil ve sahne yapay zeka komutları üretiliyor..."):
                st.session_state["draft_script"] = create_youtube_script(
                    topic=st.session_state["topic_input"],
                    style_preset=st.session_state["style_input"]
                )

    with col_btn2:
        if st.button("🚀 Hızlı Üretim: Doğrudan İş Kuyruğuna Gönder ve Başlat", type="primary", width="stretch"):
            job_id = create_job(
                topic=st.session_state["topic_input"],
                style_preset=st.session_state["style_input"],
                script_data=st.session_state.get("draft_script"),
                options={
                    "prefer_ai_video": prefer_ai_video,
                    "burn_subtitles": burn_subtitles,
                    "edge_voice": edge_voice
                }
            )
            spawn_worker_for_job(job_id)
            st.success(
                f"✅ İş kuyruğa eklendi (`{job_id}`) ve arka plan işçisi (`worker.py`) başlatıldı! "
                "**'⚡ 2. Canlı İş Kuyruğu'** sekmesinden anlık ilerlemeyi takip edebilirsiniz."
            )

    # Eğer kullanıcı senaryoyu önizlemek/düzenlemek istediyse
    draft = st.session_state.get("draft_script")
    if draft and isinstance(draft, dict) and draft.get("scenes"):
        st.divider()
        st.markdown("### ✏️ Senaryo, Global Stil ve Sabit Seed Düzenleyici")

        c_meta1, c_meta2 = st.columns([2, 1])
        with c_meta1:
            draft["title"] = st.text_input("YouTube Başlığı", value=draft.get("title", ""))
            draft["description"] = st.text_area("YouTube Açıklaması & Etiketler", value=draft.get("description", ""), height=68)
        with c_meta2:
            draft["visual_seed"] = int(
                st.number_input(
                    "🔒 Sabit Görsel Tohumu (Seed - Tutarlılık İçin)",
                    value=int(draft.get("visual_seed", 428571)),
                    step=1
                )
            )
            draft["global_style"] = st.text_area(
                "🎨 Global Stil Şablonu (Tüm Sahnelere Uygulanır)",
                value=draft.get("global_style", ""),
                height=90
            )

        st.markdown("#### 🎞️ Sahneler (Metin ve AI Çizim Promptları)")
        scenes_list = draft.get("scenes", [])
        for idx, sc in enumerate(scenes_list):
            sid = sc.get("scene_id", idx + 1)
            with st.expander(f"Sahne {sid}: {sc.get('narration', '')[:65]}...", expanded=(idx == 0)):
                sc["narration"] = st.text_input(
                    f"🎙️ Sahne {sid} Türkçe Seslendirme Metni",
                    value=sc.get("narration", ""),
                    key=f"nar_{sid}_{idx}"
                )
                sc["ai_image_prompt"] = st.text_area(
                    f"🖌️ Sahne {sid} Yapay Zeka Görsel/Video Komutu (İngilizce)",
                    value=sc.get("ai_image_prompt", ""),
                    height=68,
                    key=f"prm_{sid}_{idx}"
                )

        if st.button("🎬 Bu Düzenlenmiş Senaryoyu Arka Planda Üret (Worker Başlat)", type="primary", width="stretch"):
            job_id = create_job(
                topic=st.session_state["topic_input"],
                style_preset=st.session_state["style_input"],
                script_data=draft,
                options={
                    "prefer_ai_video": prefer_ai_video,
                    "burn_subtitles": burn_subtitles,
                    "edge_voice": edge_voice
                }
            )
            spawn_worker_for_job(job_id)
            st.success(f"✅ Düzenlenmiş senaryo `{job_id}` koduyla arka planda üretime alındı!")


# ===========================================================================
# SEKME 2: CANLI İŞ KUYRUĞU MONİTÖRÜ (Sadece aktif iş varken otomatik yeniler)
# ===========================================================================
def _has_active_jobs() -> bool:
    return any(j["status"] in ("queued", "running") for j in list_jobs(limit=10))


@st.fragment(run_every="3s" if _has_active_jobs() else None)
def render_live_job_queue():
    jobs = list_jobs(limit=15)
    running_jobs = [j for j in jobs if j["status"] in ("queued", "running")]

    col_hdr1, col_hdr2 = st.columns([4, 1])
    with col_hdr1:
        if running_jobs:
            st.info(f"🔄 Şu anda arka planda çalışan **{len(running_jobs)}** aktif üretim işi var (Her 2 saniyede bir otomatik güncellenir).")
        else:
            st.caption("✅ Şu anda aktif çalışan bir iş yok. Tüm arka plan görevleri tamamlandı.")
    with col_hdr2:
        if st.button("🔄 Şimdi Yenile", width="stretch"):
            st.rerun()

    if not jobs:
        st.write("Henüz kuyruğa eklenmiş bir video üretim işi bulunmuyor.")
        return

    for job in jobs:
        jid = job["job_id"]
        status = job["status"]
        progress = int(job.get("progress") or 0)
        step_msg = job.get("current_step") or ""
        topic = job.get("topic")

        badge = {
            "queued": "⏳ Kuyrukta",
            "running": "⚙️ Üretiliyor",
            "completed": "✅ Tamamlandı",
            "failed": "❌ Hata"
        }.get(status, status)

        with st.container(border=True):
            c1, c2 = st.columns([3.5, 1.2])
            with c1:
                st.markdown(f"**{badge}** | **{topic}** (`{jid}`)")
                st.caption(f"Durum: {step_msg}")
            with c2:
                st.caption(f"Başlangıç: {job.get('created_at')}")
                st.caption(f"Güncelleme: {job.get('updated_at')}")

            st.progress(min(100, max(0, progress)), text=f"İlerleme: %{progress}")

            if status == "failed" and job.get("error_msg"):
                st.error(f"Hata Detayı: {job.get('error_msg')}")
                if st.button(f"🔁 Yeniden Dene ({jid})", key=f"retry_{jid}"):
                    update_job_progress(jid, status="queued", progress=2, current_step="Yeniden başlatılıyor...", error_msg="")
                    spawn_worker_for_job(jid)
                    st.rerun()

            # Üretilen sahne görsellerini canlı önizleme
            s_data = job.get("script_data") or {}
            scenes = s_data.get("scenes") or []
            ready_visuals = [
                s for s in scenes
                if s.get("visual_file_path") and os.path.exists(s.get("visual_file_path", ""))
            ]
            if ready_visuals:
                with st.expander(f"🖼️ Üretilen Yapay Zeka Sahneleri ({len(ready_visuals)}/{len(scenes)} Hazır)", expanded=(status == "running")):
                    cols = st.columns(min(5, len(ready_visuals)))
                    for idx, sc in enumerate(ready_visuals):
                        v_path = sc["visual_file_path"]
                        with cols[idx % len(cols)]:
                            if sc.get("visual_type") == "image":
                                st.image(v_path, caption=f"Sahne {sc.get('scene_id')} ({sc.get('duration_sec', 0):.1f}sn)", width="stretch")
                            else:
                                st.video(v_path)


with tab_queue:
    st.subheader("⚡ Arka Plan İş Kuyruğu ve Canlı Worker Takibi")
    render_live_job_queue()


# ===========================================================================
# SEKME 3: TAMAMLANAN VİDEOLAR GALERİSİ & İZOLE YOUTUBE YÜKLEYİCİ
# ===========================================================================
with tab_gallery:
    st.subheader("📁 Tamamlanan Videolar Galerisi (`output/` Klasörü)")
    st.caption(
        "Mimari Darboğaz 5 Çözümü: Videolar önce yerel `output/<job_id>/` klasörüne `.mp4` ve `metadata.json` "
        "olarak kaydedilir. Önizledikten sonra bilgisayarınıza indirebilir veya istediğiniz an YouTube'a yükleyebilirsiniz."
    )

    completed_jobs = [
        j for j in list_jobs(limit=30)
        if j["status"] == "completed" and j.get("video_path") and os.path.exists(j["video_path"])
    ]

    if not completed_jobs:
        st.info("Henüz tamamlanmış bir video bulunmuyor. 1. Sekmeden yeni bir üretim başlatabilirsiniz.")
    else:
        for job in completed_jobs:
            jid = job["job_id"]
            v_path = job["video_path"]
            m_path = job.get("metadata_path", "")
            meta: dict = {}
            if m_path and os.path.exists(m_path):
                try:
                    with open(m_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                except Exception:
                    meta = {}

            with st.container(border=True):
                col_vid, col_info = st.columns([1.2, 2.5])
                with col_vid:
                    st.video(v_path)

                with col_info:
                    st.markdown(f"### 🎬 {meta.get('title') or job['topic']}")
                    st.caption(
                        f"**İş Kodu:** `{jid}` | **Süre:** `{meta.get('total_duration_sec', '?')} sn` | "
                        f"**Seed:** `{meta.get('visual_seed', '?')}` | **Konum:** `{v_path}`"
                    )

                    up_title = st.text_input(
                        "YouTube Başlığı",
                        value=meta.get("title", f"{job['topic']} #shorts"),
                        key=f"yt_title_{jid}"
                    )
                    up_desc = st.text_area(
                        "YouTube Açıklaması",
                        value=meta.get("description", ""),
                        height=75,
                        key=f"yt_desc_{jid}"
                    )
                    up_privacy = st.selectbox(
                        "Yayın Gizlilik Durumu",
                        options=["private", "unlisted", "public"],
                        index=0,
                        key=f"yt_priv_{jid}"
                    )

                    b_col1, b_col2, b_col3 = st.columns(3)
                    with b_col1:
                        with open(v_path, "rb") as vf:
                            st.download_button(
                                label="💾 MP4 Videoyu İndir",
                                data=vf,
                                file_name=f"{jid}_shorts.mp4",
                                mime="video/mp4",
                                width="stretch",
                                key=f"dl_mp4_{jid}"
                            )
                    with b_col2:
                        if m_path and os.path.exists(m_path):
                            with open(m_path, "rb") as mf:
                                st.download_button(
                                    label="📄 metadata.json İndir",
                                    data=mf,
                                    file_name=f"{jid}_metadata.json",
                                    mime="application/json",
                                    width="stretch",
                                    key=f"dl_meta_{jid}"
                                )
                    with b_col3:
                        yt_id = job.get("youtube_video_id") or meta.get("youtube_video_id")
                        if yt_id and yt_id != "SIMULATED_VIDEO_ID_SUCCESS":
                            st.success(f"🔗 [YouTube'da İzle](https://youtu.be/{yt_id})")
                        else:
                            if st.button("📤 YouTube Kanalına Yükle", type="primary", width="stretch", key=f"up_btn_{jid}"):
                                with st.spinner("İzole YouTube yükleyici (youtube_uploader.py) çalıştırılıyor..."):
                                    try:
                                        uploaded_id = upload_video_to_youtube(
                                            video_file=v_path,
                                            title=up_title,
                                            description=up_desc,
                                            tags=meta.get("tags", ["shorts", "viral", "ai"]),
                                            privacy_status=up_privacy
                                        )
                                        if uploaded_id:
                                            update_job_progress(jid, youtube_video_id=uploaded_id)
                                            meta["youtube_video_id"] = uploaded_id
                                            if m_path:
                                                with open(m_path, "w", encoding="utf-8") as f:
                                                    json.dump(meta, f, ensure_ascii=False, indent=2)
                                            st.success(f"🎉 Başarıyla yüklendi! Video ID: {uploaded_id}")
                                            st.rerun()
                                    except Exception as e:
                                        st.error(f"YouTube yükleme hatası (Videonuz output/ klasöründe güvende): {e}")


# ===========================================================================
# SEKME 4: API ANAHTARLARI VE GEÇMİŞ KONULAR YÖNETİMİ
# ===========================================================================
with tab_settings:
    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.subheader("🔑 API Anahtarlarını Yapılandır (.env)")
        st.caption("Anahtarlarınız yerel `.env` dosyanıza kaydedilir.")

        new_groq = st.text_input("GROQ_API_KEY (Ücretsiz Senaryo & Whisper)", value=os.environ.get("GROQ_API_KEY", ""), type="password")
        new_fal = st.text_input("FAL_KEY (İsteğe Bağlı - Hareketli AI Video Wan/LTX)", value=os.environ.get("FAL_KEY", ""), type="password")
        new_hf = st.text_input("HF_API_KEY (İsteğe Bağlı - HuggingFace Flux Schnell)", value=os.environ.get("HF_API_KEY", ""), type="password")
        new_eleven = st.text_input("ELEVENLABS_API_KEY (İsteğe Bağlı - Seslendirme)", value=os.environ.get("ELEVENLABS_API_KEY", ""), type="password")

        if st.button("💾 API Anahtarlarını .env Dosyasına Kaydet", type="primary"):
            if not os.path.exists(ENV_FILE_PATH):
                open(ENV_FILE_PATH, "w", encoding="utf-8").close()
            set_key(ENV_FILE_PATH, "GROQ_API_KEY", new_groq.strip())
            set_key(ENV_FILE_PATH, "FAL_KEY", new_fal.strip())
            set_key(ENV_FILE_PATH, "HF_API_KEY", new_hf.strip())
            set_key(ENV_FILE_PATH, "ELEVENLABS_API_KEY", new_eleven.strip())
            os.environ["GROQ_API_KEY"] = new_groq.strip()
            os.environ["FAL_KEY"] = new_fal.strip()
            os.environ["HF_API_KEY"] = new_hf.strip()
            os.environ["ELEVENLABS_API_KEY"] = new_eleven.strip()
            st.success("✅ API anahtarları başarıyla güncellendi!")

    with col_s2:
        st.subheader("📜 İşlenen Konular Hafızası (`yapilan_konular.txt`)")
        if os.path.exists("yapilan_konular.txt"):
            with open("yapilan_konular.txt", "r", encoding="utf-8") as f:
                history_content = f.read()
        else:
            history_content = ""

        edited_history = st.text_area(
            "Tamamlanan konular (Yapay zeka buradaki konuları tekrar etmez)",
            value=history_content,
            height=260
        )
        if st.button("💾 Konu Hafızasını Güncelle"):
            with open("yapilan_konular.txt", "w", encoding="utf-8") as f:
                f.write(edited_history)
            st.success("✅ Konu hafızası kaydedildi.")
