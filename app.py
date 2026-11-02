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
import importlib
import streamlit as st
from dotenv import load_dotenv, set_key

import audio_generator
import subtitle_generator
import job_queue
if not hasattr(audio_generator, "VOICE_PROFILES"):
    importlib.reload(audio_generator)
if not hasattr(subtitle_generator, "OVERLAY_TEXT_STYLES"):
    importlib.reload(subtitle_generator)
if not hasattr(job_queue, "delete_job_and_files"):
    importlib.reload(job_queue)

from job_queue import init_db, create_job, list_jobs, update_job_progress, delete_job_and_files
from worker import spawn_worker_for_job
from generate_script import create_youtube_script
from daily_runner import load_past_topics, generate_autonomous_railway_topic
from youtube_uploader import upload_video_to_youtube
from prompts import IMAGE_STYLE_PRESETS
from audio_generator import VOICE_PROFILES, generate_audio_for_scene
from subtitle_generator import OVERLAY_TEXT_STYLES
from ai_visual_generator import generate_visual_for_scene
from ffmpeg_renderer import render_full_project_ffmpeg

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
    st.subheader("⚙️ Görsel Üretim Tercihleri")
    use_web_reference = st.toggle(
        "🌐 İnternetten Referans Resim Bul & Telifsiz Benzerini Üret",
        value=True,
        help="Açık olduğunda her sahne için internetten (Wikimedia / Bing) gerçek fotoğraf bulur, Qwen 3.8 Vision ile analiz eder ve FLUX.1-schnell ile ona çok benzeyen %100 telifsiz yeni görsel üretir."
    )
    prefer_ai_video = st.toggle(
        "Hareketli AI Video Önceliği (Fal.ai)",
        value=True,
        help="FAL_KEY varsa sahneleri doğrudan hareketli AI video olarak üretir; yoksa otomatik Flux 9:16 + FFmpeg Ken Burns kullanır."
    )

    st.divider()
    st.subheader("🎙️ Seslendirme (TTS) Alternatifleri")
    voice_keys = list(VOICE_PROFILES.keys())
    edge_voice = st.selectbox(
        "Seslendirmen & Tonlama Profili",
        options=voice_keys,
        format_func=lambda k: VOICE_PROFILES[k]["label"],
        index=0
    )
    if st.button("🔊 Seçili Sesi Dinle (Önizleme)", width="stretch"):
        os.makedirs("temp_audio", exist_ok=True)
        preview_mp3 = os.path.join("temp_audio", f"preview_{edge_voice}.mp3")
        sample_txt = "Bin sekiz yüz seksen üç yılında Doğu Ekspresi üç bin kilometrelik efsanevi yolculuğuna başladı."
        with st.spinner("Örnek ses üretiliyor..."):
            p_path, _, _ = generate_audio_for_scene(sample_txt, preview_mp3, edge_voice=edge_voice)
            if p_path and os.path.exists(p_path):
                st.audio(p_path, format="audio/mp3")

    st.divider()
    st.subheader("🏷️ Video Üst Katman & Yazı Stilleri")
    style_preset_keys = list(OVERLAY_TEXT_STYLES.keys())
    text_style_preset = st.selectbox(
        "🎨 Yazı & Bant Stili",
        options=style_preset_keys,
        format_func=lambda k: OVERLAY_TEXT_STYLES[k]["label"],
        index=0
    )
    show_top_banner = st.toggle(
        "🏷️ Video Üst Katman Başlığı (Üst Bant)",
        value=True,
        help="Açık olduğunda videonun üst kısmına seçilen yazı stilinde konu/başlık bandı yerleştirir."
    )
    top_banner_text = ""
    if show_top_banner:
        top_banner_text = st.text_input(
            "✏️ Özel Üst Başlık (Boşsa Otomatik Başlık)",
            value="",
            placeholder="Örn: DOĞU EKSPRESİ'NİN GİZEMİ"
        )
    burn_subtitles = st.toggle(
        "💬 Alt Konuşma Altyazısı (.ASS)",
        value=False,
        help="Açık olduğunda videonun alt kısmına kelime kelime vurgulanan konuşma altyazısını yakar (Varsayılan: Kapalı)."
    )


# ---------------------------------------------------------------------------
# STÜDYO AÇILIŞINDA OTOMATİK 1 ADET VİDEO ÜRETİMİ (Otonom Başlangıç)
# ---------------------------------------------------------------------------
@st.cache_resource
def _auto_start_initial_video_on_launch():
    """
    Streamlit stüdyosu başlatıldığında (sunucu başına 1 kez) otomatik olarak
    daha önce işlenmemiş yeni bir konu seçer ve 1 adet videoyu arka planda üretime alır.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx() is None:
            return None
    except Exception:
        pass

    active = [j for j in list_jobs(limit=10) if j.get("status") in ("queued", "running")]
    if active:
        return {"job_id": active[0]["job_id"], "topic": active[0]["topic"], "already_running": True}

    past = load_past_topics()
    suggestion = generate_autonomous_railway_topic(past)
    auto_topic = suggestion.get("topic", "Orient Express: Doğu Ekspresi'nin Çözülemeyen Gizemleri")
    auto_style = suggestion.get("style", "documentary_history")

    job_id = create_job(
        topic=auto_topic,
        style_preset=auto_style,
        script_data=None,
        options={
            "prefer_ai_video": True,
            "burn_subtitles": False,
            "show_top_banner": True,
            "top_banner_text": "",
            "text_style_preset": "gold_banner",
            "use_web_reference": True,
            "edge_voice": "belgesel_tok_erkek"
        }
    )
    spawn_worker_for_job(job_id)
    return {"job_id": job_id, "topic": auto_topic, "style": auto_style, "already_running": False}


_auto_launch_info = _auto_start_initial_video_on_launch()
if _auto_launch_info:
    st.info(
        f"🚀 **Otonom Başlangıç Aktif:** Stüdyo başlatıldığı için **\"{_auto_launch_info['topic']}\"** "
        f"konulu 1 adet video arka planda otomatik üretime alındı (`{_auto_launch_info['job_id']}`). "
        f"Durumu **⚡ 2. Canlı İş Kuyruğu** sekmesinden canlı takip edebilirsiniz."
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
                    "show_top_banner": show_top_banner,
                    "top_banner_text": top_banner_text,
                    "text_style_preset": text_style_preset,
                    "use_web_reference": use_web_reference,
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

        st.markdown("#### 🎞️ Sahneler (Metin, Telifsiz AI Görsel Kontrolü ve Kendi Videolarınız)")
        st.caption(
            "💡 **İpucu:** Videoyu birleştirmeden önce **tüm sahnelerin veya tek bir sahnenin telifsiz AI resmini üretip kontrol edebilir**, "
            "beğenmediğiniz resmi yeni varyasyonla değiştirebilir veya yerine kendi videonuzu/fotoğrafınızı koyabilirsiniz."
        )
        draft_preview_dir = os.path.abspath(os.path.join("temp_visuals", "draft_preview"))
        os.makedirs(draft_preview_dir, exist_ok=True)

        if st.button("🖼️ Adım 2 (Önerilen): Tüm Sahnelerin Telifsiz Resimlerini Şimdi Üret & Kontrol Et", width="stretch"):
            scenes_to_gen = draft.get("scenes", [])
            g_style = draft.get("global_style", "")
            v_seed = int(draft.get("visual_seed", 428571))
            prog_bar = st.progress(0, text="Sahnelerin telifsiz AI görselleri üretiliyor...")
            for idx_g, sc_g in enumerate(scenes_to_gen):
                sid_g = sc_g.get("scene_id", idx_g + 1)
                if sc_g.get("custom_media_path") and os.path.exists(str(sc_g.get("custom_media_path"))):
                    continue
                prog_bar.progress(
                    int(((idx_g) / max(1, len(scenes_to_gen))) * 100),
                    text=f"Sahne {sid_g}/{len(scenes_to_gen)}: Referans resim aranıyor ve telifsiz AI görseli üretiliyor..."
                )
                generate_visual_for_scene(
                    scene=sc_g,
                    global_style=g_style,
                    visual_seed=v_seed + int(sc_g.get("variation_offset", 0)),
                    output_dir=draft_preview_dir,
                    prefer_ai_video=False,
                    use_web_reference=use_web_reference,
                    topic=st.session_state["topic_input"]
                )
            prog_bar.progress(100, text="✅ Tüm sahnelerin telifsiz görselleri hazır! Aşağıdan inceleyip değiştirebilirsiniz.")

        custom_media_dir = os.path.abspath("custom_media")
        os.makedirs(custom_media_dir, exist_ok=True)
        ALLOWED_CUSTOM_EXTS = (".mp4", ".mov", ".mkv", ".avi", ".webm", ".jpg", ".jpeg", ".png", ".webp")
        existing_custom_files = sorted([
            f for f in os.listdir(custom_media_dir)
            if f.lower().endswith(ALLOWED_CUSTOM_EXTS)
        ])

        scenes_list = draft.get("scenes", [])
        for idx, sc in enumerate(scenes_list):
            sid = sc.get("scene_id", idx + 1)
            has_custom = bool(sc.get("custom_media_path") and os.path.exists(str(sc.get("custom_media_path"))))
            has_generated = bool(sc.get("visual_file_path") and os.path.exists(str(sc.get("visual_file_path"))))
            if has_custom:
                badge = "📹 [Kendi Videonuz/Görseliniz Seçili]"
            elif has_generated:
                badge = "✅ [Telifsiz AI Görseli Hazır - Onaylandı]"
            else:
                badge = "🤖 [AI Üretecek]"
            with st.expander(f"Sahne {sid} {badge}: {sc.get('narration', '')[:60]}...", expanded=(idx == 0 or has_generated)):
                nar_col1, nar_col2 = st.columns([2.4, 1.0])
                with nar_col1:
                    sc["narration"] = st.text_area(
                        f"🎙️ Sahne {sid} Türkçe Konuşma Metni (İstediğiniz gibi düzeltebilirsiniz)",
                        value=sc.get("narration", ""),
                        height=68,
                        key=f"nar_{sid}_{idx}"
                    )
                with nar_col2:
                    st.write("")
                    if st.button(f"🔊 Sahne {sid} Sesini Dinle", key=f"tts_prev_{sid}_{idx}", width="stretch"):
                        os.makedirs("temp_audio", exist_ok=True)
                        sc_prev_mp3 = os.path.join("temp_audio", f"draft_s{sid}_preview.mp3")
                        with st.spinner("Seslendiriliyor..."):
                            p_mp3, p_dur, _ = generate_audio_for_scene(sc["narration"], sc_prev_mp3, edge_voice=edge_voice)
                            if p_mp3 and os.path.exists(p_mp3):
                                st.audio(p_mp3, format="audio/mp3")
                                st.caption(f"Süre: {p_dur:.1f} sn")

                st.markdown("##### 📹 Bu Sahneye Kendi Videonuzu / Görselinizi Yerleştirin (İsteğe Bağlı)")
                cm_col1, cm_col2 = st.columns([1.3, 1.2])
                with cm_col1:
                    uploaded_file = st.file_uploader(
                        f"Sahne {sid} için Bilgisayardan Dosya Yükle (Sürükle & Bırak)",
                        type=["mp4", "mov", "mkv", "webm", "jpg", "jpeg", "png", "webp"],
                        key=f"upl_{sid}_{idx}"
                    )
                    if uploaded_file is not None:
                        safe_fname = f"scene{sid}_{uploaded_file.name}"
                        saved_custom_path = os.path.join(custom_media_dir, safe_fname)
                        with open(saved_custom_path, "wb") as out_f:
                            out_f.write(uploaded_file.getbuffer())
                        sc["custom_media_path"] = saved_custom_path
                        if safe_fname not in existing_custom_files:
                            existing_custom_files.append(safe_fname)

                with cm_col2:
                    folder_options = ["🤖 Yapay Zeka Üretsin (Özel Dosya Yok)"] + existing_custom_files
                    current_custom = str(sc.get("custom_media_path") or "")
                    current_bname = os.path.basename(current_custom) if current_custom else ""
                    default_idx = folder_options.index(current_bname) if current_bname in folder_options else 0

                    selected_folder_item = st.selectbox(
                        f"📁 Veya 'custom_media/' Klasöründen Seç (Sahne {sid})",
                        options=folder_options,
                        index=default_idx,
                        key=f"sel_cm_{sid}_{idx}"
                    )
                    if uploaded_file is None:
                        if selected_folder_item == folder_options[0]:
                            sc["custom_media_path"] = ""
                        else:
                            sc["custom_media_path"] = os.path.join(custom_media_dir, selected_folder_item)

                if sc.get("custom_media_path") and os.path.exists(str(sc["custom_media_path"])):
                    st.success(f"✅ Bu sahnede kendi dosyanız kullanılacak: `{os.path.basename(sc['custom_media_path'])}`")
                    opt_c1, opt_c2, opt_c3 = st.columns([1.5, 1.2, 0.9])
                    with opt_c1:
                        fit_options = {
                            "crop": "📱 Tam Ekran Dikey Kırpma (9:16 Center Crop)",
                            "blur_pad": "🖼️ Bulanık Arka Planlı Tam Sığdırma (Yatay Videolar Kesilmez)"
                        }
                        cur_fit = sc.get("custom_fit_mode", "crop")
                        sc["custom_fit_mode"] = st.selectbox(
                            "Kadraj / Sığdırma Modu",
                            options=list(fit_options.keys()),
                            format_func=lambda k: fit_options[k],
                            index=0 if cur_fit == "crop" else 1,
                            key=f"fit_{sid}_{idx}"
                        )
                    with opt_c2:
                        sc["custom_ambient_audio"] = st.toggle(
                            "🔉 Videonun Orijinal Sesini %15 Ortam Sesi Olarak Arkada Bırak",
                            value=bool(sc.get("custom_ambient_audio", False)),
                            help="Kapalıysa videonuzun sesi tamamen susturulur, sadece Türkçe anlatıcı duyulur. Açıksa kendi videonuzun sesi %15 kısık ambiyans olarak arkada duyulur.",
                            key=f"amb_{sid}_{idx}"
                        )
                    with opt_c3:
                        sc["custom_start_sec"] = float(
                            st.number_input(
                                "⏱️ Başlangıç (sn)",
                                min_value=0.0,
                                value=float(sc.get("custom_start_sec", 0.0)),
                                step=0.5,
                                help="Videonuzun kaçıncı saniyesinden itibaren kullanılacağını seçin.",
                                key=f"start_{sid}_{idx}"
                            )
                        )
                else:
                    sc["ai_image_prompt"] = st.text_area(
                        f"🖌️ Sahne {sid} Yapay Zeka Görsel/Video Komutu (İngilizce)",
                        value=sc.get("ai_image_prompt", ""),
                        height=68,
                        key=f"prm_{sid}_{idx}"
                    )

                    btn_lbl = (
                        f"🔄 Sahne {sid} Telifsiz Resmini Değiştir / Yeni Resim Üret"
                        if (sc.get("visual_file_path") and os.path.exists(str(sc.get("visual_file_path"))))
                        else f"🎨 Sahne {sid} Telifsiz Resmini Şimdi Üret & Önizle"
                    )
                    if st.button(btn_lbl, key=f"gen_single_{sid}_{idx}", width="stretch"):
                        sc["variation_offset"] = int(sc.get("variation_offset", 0)) + 137
                        terms = list(sc.get("stock_search_terms") or [])
                        if len(terms) > 1:
                            sc["stock_search_terms"] = terms[1:] + terms[:1]
                        with st.spinner(f"Sahne {sid} için telifsiz yeni AI görseli üretiliyor..."):
                            out_sub = os.path.join(draft_preview_dir, f"s{sid}_v{sc['variation_offset']}")
                            os.makedirs(out_sub, exist_ok=True)
                            generate_visual_for_scene(
                                scene=sc,
                                global_style=draft.get("global_style", ""),
                                visual_seed=int(draft.get("visual_seed", 428571)) + int(sc["variation_offset"]),
                                output_dir=out_sub,
                                prefer_ai_video=False,
                                use_web_reference=use_web_reference,
                                topic=st.session_state["topic_input"]
                            )
                            st.rerun()

                    # Sadece üretilen telifsiz görseli göster
                    v_file = str(sc.get("visual_file_path") or "")
                    if v_file and os.path.exists(v_file):
                        st.image(v_file, caption=f"✅ Üretilen Telifsiz AI Görsel (Sahne {sid})", width=260)

        if st.button("🎬 Bu Düzenlenmiş Senaryoyu Arka Planda Üret (Worker Başlat)", type="primary", width="stretch"):
            job_id = create_job(
                topic=st.session_state["topic_input"],
                style_preset=st.session_state["style_input"],
                script_data=draft,
                options={
                    "prefer_ai_video": prefer_ai_video,
                    "burn_subtitles": burn_subtitles,
                    "show_top_banner": show_top_banner,
                    "top_banner_text": top_banner_text,
                    "text_style_preset": text_style_preset,
                    "use_web_reference": use_web_reference,
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
                                st.image(v_path, caption=f"✨ Telifsiz AI Sahne {sc.get('scene_id')} ({sc.get('duration_sec', 0):.1f}sn)", width="stretch")
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
        "Videolar önce yerel `output/<job_id>/` klasörüne kaydedilir. "
        "**YouTube'a yüklendiği anda yerel dosyaları otomatik olarak silinir ve bu galeriden kaldırılır.**"
    )

    if st.session_state.get("last_yt_upload_notice"):
        st.success(st.session_state.pop("last_yt_upload_notice"))

    # Daha önce YouTube'a yüklenmiş olan işlerin yerel dosyalarını ve galeri kaydını otomatik temizle
    for _j in list_jobs(limit=50):
        _yt = str(_j.get("youtube_video_id") or "").strip()
        if _yt and _yt != "SIMULATED_VIDEO_ID_SUCCESS":
            delete_job_and_files(_j["job_id"])

    completed_jobs = [
        j for j in list_jobs(limit=30)
        if j["status"] == "completed" and j.get("video_path") and os.path.exists(j["video_path"])
    ]

    if not completed_jobs:
        st.info("Henüz galeride bekleyen bir video bulunmuyor. 1. Sekmeden yeni bir üretim başlatabilirsiniz.")
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
                                    if uploaded_id and uploaded_id != "SIMULATED_VIDEO_ID_SUCCESS":
                                        delete_job_and_files(jid)
                                        st.session_state["last_yt_upload_notice"] = (
                                            f"🎉 Video başarıyla YouTube'a yüklendi (https://youtu.be/{uploaded_id})! "
                                            f"Yerel dosyaları (`output/{jid}/`) silindi ve galeriden kaldırıldı."
                                        )
                                        st.rerun()
                                    elif uploaded_id == "SIMULATED_VIDEO_ID_SUCCESS":
                                        st.warning("⚠️ `client_secret.json` bulunamadığı için simülasyon çalıştı; gerçek yükleme yapılmadığından yerel dosyalar korundu.")
                                except Exception as e:
                                    st.error(f"YouTube yükleme hatası (Videonuz output/ klasöründe güvende): {e}")
                    with b_col3:
                        if st.button("🗑️ Yerel Dosyaları Sil", width="stretch", key=f"del_btn_{jid}"):
                            delete_job_and_files(jid)
                            st.session_state["last_yt_upload_notice"] = f"🗑️ `{jid}` kodlu videonun tüm yerel dosyaları silindi ve galeriden kaldırıldı."
                            st.rerun()

                # Tamamlanan videonun sahne konuşma metinlerini ve resimlerini kontrol etme, değiştirme ve hızlı yeniden birleştirme
                gallery_scenes = meta.get("scenes") or (job.get("script_data") or {}).get("scenes") or []
                if gallery_scenes:
                    with st.expander(f"✏️ Sahnelerin Konuşma Metinlerini & Telifsiz Resimlerini Düzenle ({len(gallery_scenes)} Sahne)", expanded=False):
                        st.caption(
                            "Herhangi bir sahnenin **Türkçe konuşma metnini düzeltebilir**, **telifsiz resmini değiştirebilir** "
                            "veya **bilgisayarınızdan resim/video yükleyip** videoyu birkaç saniyede güncelleyebilirsiniz."
                        )
                        job_out_dir = job.get("output_dir") or os.path.dirname(v_path)
                        job_vis_dir = os.path.join(job_out_dir, "visuals")
                        job_aud_dir = os.path.join(job_out_dir, "audio")
                        os.makedirs(job_vis_dir, exist_ok=True)
                        os.makedirs(job_aud_dir, exist_ok=True)
                        opts = job.get("options") or {}
                        job_voice = str(opts.get("edge_voice") or edge_voice)

                        for g_idx, g_sc in enumerate(gallery_scenes):
                            g_sid = g_sc.get("scene_id", g_idx + 1)
                            g_vpath = str(g_sc.get("visual_file_path") or "")
                            g_apath = str(g_sc.get("audio_file_path") or "")
                            st.markdown(f"#### 🎞️ Sahne {g_sid}")
                            gc1, gc2 = st.columns([1.2, 2.2])
                            with gc1:
                                if g_vpath and os.path.exists(g_vpath):
                                    if g_sc.get("visual_type") == "video":
                                        st.video(g_vpath)
                                    else:
                                        st.image(g_vpath, caption=f"✅ Telifsiz Görsel {g_sid}", width=210)
                                if g_apath and os.path.exists(g_apath):
                                    st.audio(g_apath, format="audio/mp3")
                            with gc2:
                                old_nar = str(g_sc.get("narration") or "")
                                new_nar = st.text_area(
                                    f"🎙️ Sahne {g_sid} Türkçe Konuşma Metni",
                                    value=old_nar,
                                    height=68,
                                    key=f"gal_nar_{jid}_{g_sid}"
                                )
                                if new_nar.strip() != old_nar.strip():
                                    g_sc["_narration_dirty"] = True
                                g_sc["narration"] = new_nar

                                if st.button(f"🎙️ Sahne {g_sid} Konuşma Metnini Kaydet & Sesi Yenile", key=f"gal_revoice_{jid}_{g_sid}", width="stretch"):
                                    with st.spinner(f"Sahne {g_sid} yeni konuşma metniyle seslendiriliyor..."):
                                        new_mp3_path = os.path.abspath(os.path.join(job_aud_dir, f"scene_{g_sid}.mp3"))
                                        saved_a, dur_a, timings_a = generate_audio_for_scene(
                                            new_nar,
                                            new_mp3_path,
                                            edge_voice=job_voice
                                        )
                                        if saved_a:
                                            g_sc["audio_file_path"] = saved_a
                                            g_sc["duration_sec"] = dur_a
                                            g_sc["word_timings"] = timings_a
                                            g_sc.pop("_narration_dirty", None)
                                            meta["scenes"] = gallery_scenes
                                            meta["total_duration_sec"] = round(sum(float(s.get("duration_sec", 0.0)) for s in gallery_scenes), 2)
                                            if m_path:
                                                with open(m_path, "w", encoding="utf-8") as f:
                                                    json.dump(meta, f, ensure_ascii=False, indent=2)
                                            update_job_progress(jid, script_data={"scenes": gallery_scenes, "title": meta.get("title", "")})
                                            st.rerun()

                                new_prm = st.text_input(
                                    f"🖌️ Sahne {g_sid} AI Görsel Komutu (İngilizce)",
                                    value=g_sc.get("ai_image_prompt", ""),
                                    key=f"gal_prm_{jid}_{g_sid}"
                                )
                                g_sc["ai_image_prompt"] = new_prm

                                if st.button(f"🔄 Sahne {g_sid} Telifsiz Resmini Değiştir / Yeniden Üret", key=f"gal_regen_{jid}_{g_sid}", width="stretch"):
                                    g_sc["variation_offset"] = int(g_sc.get("variation_offset", 0)) + 173
                                    terms = list(g_sc.get("stock_search_terms") or [])
                                    if len(terms) > 1:
                                        g_sc["stock_search_terms"] = terms[1:] + terms[:1]
                                    with st.spinner(f"Sahne {g_sid} için yeni telifsiz AI görseli üretiliyor..."):
                                        sub_vdir = os.path.join(job_vis_dir, f"s{g_sid}_v{g_sc['variation_offset']}")
                                        os.makedirs(sub_vdir, exist_ok=True)
                                        generate_visual_for_scene(
                                            scene=g_sc,
                                            global_style=meta.get("global_style", ""),
                                            visual_seed=int(meta.get("visual_seed", 428571)) + int(g_sc["variation_offset"]),
                                            output_dir=sub_vdir,
                                            prefer_ai_video=False,
                                            use_web_reference=use_web_reference,
                                            topic=job["topic"]
                                        )
                                        meta["scenes"] = gallery_scenes
                                        if m_path:
                                            with open(m_path, "w", encoding="utf-8") as f:
                                                json.dump(meta, f, ensure_ascii=False, indent=2)
                                        update_job_progress(jid, script_data={"scenes": gallery_scenes, "title": meta.get("title", "")})
                                        st.rerun()

                                rep_up = st.file_uploader(
                                    f"📁 Veya Sahne {g_sid} İçin Bilgisayardan Resim/Video Yükle",
                                    type=["jpg", "jpeg", "png", "webp", "mp4", "mov", "webm"],
                                    key=f"gal_up_{jid}_{g_sid}"
                                )
                                if rep_up is not None:
                                    ext_u = os.path.splitext(rep_up.name)[1].lower()
                                    rep_dest = os.path.abspath(os.path.join(job_vis_dir, f"scene_{g_sid}_replaced{ext_u}"))
                                    with open(rep_dest, "wb") as out_u:
                                        out_u.write(rep_up.getbuffer())
                                    g_sc["visual_file_path"] = rep_dest
                                    g_sc["visual_type"] = "video" if ext_u in (".mp4", ".mov", ".webm") else "image"
                                    meta["scenes"] = gallery_scenes
                                    if m_path:
                                        with open(m_path, "w", encoding="utf-8") as f:
                                            json.dump(meta, f, ensure_ascii=False, indent=2)
                                    update_job_progress(jid, script_data={"scenes": gallery_scenes, "title": meta.get("title", "")})
                                    st.success(f"Sahne {g_sid} dosyası güncellendi! Aşağıdaki butonla videoyu yenileyin.")
                            st.divider()

                        if st.button(f"⚡ Güncellenen Metin ve Resimlerle Videoyu Tekrar Birleştir ({jid})", type="primary", width="stretch", key=f"rerender_{jid}"):
                            with st.spinner("Değişen konuşma metinleri seslendiriliyor ve FFmpeg ile video yeniden birleştiriliyor..."):
                                # Eğer konuşma metni değiştirilmiş sahneler varsa önce seslerini otomatik güncelle
                                for s_item in gallery_scenes:
                                    s_id_val = s_item.get("scene_id", 1)
                                    a_file = str(s_item.get("audio_file_path") or "")
                                    if s_item.get("_narration_dirty") or not a_file or not os.path.exists(a_file):
                                        target_mp3 = os.path.abspath(os.path.join(job_aud_dir, f"scene_{s_id_val}.mp3"))
                                        saved_a, dur_a, timings_a = generate_audio_for_scene(
                                            str(s_item.get("narration") or ""),
                                            target_mp3,
                                            edge_voice=job_voice
                                        )
                                        if saved_a:
                                            s_item["audio_file_path"] = saved_a
                                            s_item["duration_sec"] = dur_a
                                            s_item["word_timings"] = timings_a
                                            s_item.pop("_narration_dirty", None)

                                meta["scenes"] = gallery_scenes
                                meta["total_duration_sec"] = round(sum(float(s.get("duration_sec", 0.0)) for s in gallery_scenes), 2)
                                if m_path:
                                    with open(m_path, "w", encoding="utf-8") as f:
                                        json.dump(meta, f, ensure_ascii=False, indent=2)
                                update_job_progress(jid, script_data={"scenes": gallery_scenes, "title": meta.get("title", "")})

                                render_full_project_ffmpeg(
                                    scenes=gallery_scenes,
                                    output_dir=job_out_dir,
                                    final_video_name="final_shorts.mp4",
                                    burn_subtitles=bool(opts.get("burn_subtitles", burn_subtitles)),
                                    show_top_banner=bool(opts.get("show_top_banner", show_top_banner)),
                                    top_banner_text=str(opts.get("top_banner_text") or meta.get("title") or job["topic"]),
                                    text_style_preset=str(opts.get("text_style_preset") or text_style_preset)
                                )
                                st.success("✅ Video yeni konuşma metinleri ve sahne görselleriyle başarıyla güncellendi!")
                                st.rerun()


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
