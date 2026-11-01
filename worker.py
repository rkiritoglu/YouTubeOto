"""
worker.py - Streamlit'ten Bağımsız Arka Plan Üretim İşçisi (Detached Background Worker)

Mimari Darboğaz 2, 3, 4 ve 5 Çözümü:
- Streamlit sürecinden tamamen ayrı bir işletim sistemi süreci (process) olarak çalışır.
- Tarayıcı sekmesi kapatılsa veya yenilense dahi üretime devam eder.
- Akış Sırası:
  1. Senaryo & Global Stil + Sabit Seed Kontrolü
  2. ÖNCE SES (ElevenLabs / Edge-TTS) ve Milisaniye Süre Ölçümü (Audio-First Pacing)
  3. Hibrit AI Görsel/Video Üretimi (Fal.ai Video -> Flux 9:16 Dikey Görsel)
  4. Yerel FFmpeg (zoompan + setpts + .ass altyazı) Render Motoru
  5. Yerel 'output/<job_id>/' Paketleme (final_shorts.mp4 + metadata.json)
"""

import os
import sys
import json
import argparse
import traceback
import subprocess
from typing import Dict, Any

from dotenv import load_dotenv
load_dotenv()

from job_queue import get_job, update_job_progress
from generate_script import create_youtube_script
from audio_generator import process_script_audio, DEFAULT_EDGE_TTS_VOICE
from ai_visual_generator import generate_visual_for_scene
from ffmpeg_renderer import render_full_project_ffmpeg
from daily_runner import save_completed_topic


def spawn_worker_for_job(job_id: str) -> None:
    """
    Verilen job_id için worker.py betiğini bağımsız bir arka plan sürecinde başlatır.
    Windows üzerinde CREATE_NEW_PROCESS_GROUP kullanarak Streamlit'ten izole eder.
    """
    worker_script = os.path.abspath(__file__)
    work_cwd = os.path.dirname(worker_script)
    cmd = [sys.executable, worker_script, "--job-id", job_id]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

    log_dir = os.path.join(work_cwd, "output", job_id)
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "worker.log")
    log_handle = open(log_file_path, "a", encoding="utf-8")

    subprocess.Popen(
        cmd,
        cwd=work_cwd,
        stdout=log_handle,
        stderr=log_handle,
        creationflags=creationflags,
        close_fds=(os.name != "nt")
    )


def execute_job(job_id: str) -> bool:
    """Kuyruktaki işi uçtan uca çalıştırır ve her adımda SQLite durumunu günceller."""
    job = get_job(job_id)
    if not job:
        print(f"[HATA] İş bulunamadı: {job_id}")
        return False

    topic = job["topic"]
    style_preset = job["style_preset"]
    output_dir = job["output_dir"]
    options: Dict[str, Any] = job.get("options") or {}
    script_data: Dict[str, Any] = job.get("script_data") or {}

    prefer_ai_video = bool(options.get("prefer_ai_video", True))
    burn_subtitles = bool(options.get("burn_subtitles", True))
    edge_voice = str(options.get("edge_voice") or DEFAULT_EDGE_TTS_VOICE)

    os.makedirs(output_dir, exist_ok=True)
    audio_dir = os.path.join(output_dir, "audio")
    visuals_dir = os.path.join(output_dir, "visuals")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(visuals_dir, exist_ok=True)

    try:
        # -------------------------------------------------------------------
        # ADIM 1: Senaryo, Global Stil ve Sabit Seed Hazırlığı
        # -------------------------------------------------------------------
        update_job_progress(
            job_id,
            status="running",
            progress=8,
            current_step="Adım 1/4: Yapay zeka senaryosu ve Global Stil şablonu hazırlanıyor..."
        )

        if not script_data or not script_data.get("scenes"):
            script_data = create_youtube_script(topic=topic, style_preset=style_preset)

        scenes = script_data.get("scenes", [])
        if not scenes:
            raise RuntimeError("Senaryo sahneleri üretilemedi.")

        global_style = script_data.get(
            "global_style",
            "cinematic documentary photography, 35mm lens, dramatic volumetric lighting, 8k, vertical 9:16"
        )
        visual_seed = int(script_data.get("visual_seed") or (abs(hash(topic)) % 900000 + 100000))
        script_data["global_style"] = global_style
        script_data["visual_seed"] = visual_seed

        update_job_progress(
            job_id,
            progress=18,
            current_step=f"Adım 1/4 Tamamlandı: {len(scenes)} sahnelik senaryo hazır (Seed: {visual_seed}).",
            script_data=script_data
        )

        # -------------------------------------------------------------------
        # ADIM 2: ÖNCE SES (Audio-First Pacing) ve Milisaniye Süre Ölçümü
        # -------------------------------------------------------------------
        update_job_progress(
            job_id,
            progress=22,
            current_step="Adım 2/4: [Önce Ses] Sahne seslendirmeleri ve kelime zamanlamaları üretiliyor..."
        )

        scenes = process_script_audio(script_data, output_dir=audio_dir, edge_voice=edge_voice)
        valid_scenes = [
            s for s in scenes
            if s.get("audio_file_path") and os.path.exists(s["audio_file_path"])
        ]
        if not valid_scenes:
            raise RuntimeError("Hiçbir sahne için ses dosyası üretilemedi.")

        script_data["scenes"] = valid_scenes
        total_audio_dur = sum(float(s.get("duration_sec", 0.0)) for s in valid_scenes)

        update_job_progress(
            job_id,
            progress=35,
            current_step=f"Adım 2/4 Tamamlandı: Toplam ses süresi {total_audio_dur:.1f} saniye olarak ölçüldü.",
            script_data=script_data
        )

        # -------------------------------------------------------------------
        # ADIM 3: Hibrit AI Görsel / Video Üretimi (Global Stil + Sabit Seed)
        # -------------------------------------------------------------------
        total_scenes = len(valid_scenes)
        for idx, scene in enumerate(valid_scenes):
            scene_id = scene.get("scene_id", idx + 1)
            pct = 36 + int(((idx) / max(1, total_scenes)) * 22)
            update_job_progress(
                job_id,
                progress=pct,
                current_step=f"Adım 3/4: Sahne {scene_id}/{total_scenes} yapay zeka görseli/videosu üretiliyor (Seed: {visual_seed})..."
            )

            generate_visual_for_scene(
                scene=scene,
                global_style=global_style,
                visual_seed=visual_seed,
                output_dir=visuals_dir,
                prefer_ai_video=prefer_ai_video
            )
            update_job_progress(job_id, script_data=script_data)

        # -------------------------------------------------------------------
        # ADIM 4: Yerel FFmpeg Render (zoompan + setpts + .ASS Altyazı)
        # -------------------------------------------------------------------
        def _ffmpeg_progress(pct_val: int, msg: str):
            update_job_progress(job_id, progress=pct_val, current_step=f"Adım 4/4: {msg}")

        final_video_path = render_full_project_ffmpeg(
            scenes=valid_scenes,
            output_dir=output_dir,
            final_video_name="final_shorts.mp4",
            burn_subtitles=burn_subtitles,
            progress_callback=_ffmpeg_progress
        )

        if not final_video_path or not os.path.exists(final_video_path):
            raise RuntimeError("FFmpeg final MP4 dosyasını oluşturamadı.")

        # -------------------------------------------------------------------
        # ADIM 5: İzole Paketleme (output/<job_id>/metadata.json)
        # -------------------------------------------------------------------
        clean_tag = "".join(ch for ch in topic.lower() if ch.isalnum())[:25]
        metadata = {
            "job_id": job_id,
            "topic": topic,
            "style_preset": style_preset,
            "title": script_data.get("title", f"{topic} #shorts"),
            "description": script_data.get("description", f"{topic} #shorts #viral #ai"),
            "tags": ["shorts", "viral", "ai", "raylisistemler", clean_tag],
            "global_style": global_style,
            "visual_seed": visual_seed,
            "total_duration_sec": round(total_audio_dur, 2),
            "video_path": final_video_path,
            "youtube_video_id": "",
            "scenes": valid_scenes
        }

        metadata_path = os.path.join(output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        # Konuyu geçmiş hafızasına kaydet
        try:
            save_completed_topic(topic, metadata["title"])
        except Exception:
            pass

        update_job_progress(
            job_id,
            status="completed",
            progress=100,
            current_step="Tamamlandı! Video ve meta veriler 'output/' klasörüne paketlendi.",
            script_data=script_data,
            video_path=final_video_path,
            metadata_path=metadata_path
        )
        print(f"\n[BAŞARILI] İş tamamlandı: {final_video_path}")
        return True

    except Exception as e:
        err_trace = traceback.format_exc()
        print(f"\n[HATA] Worker istisnası:\n{err_trace}")
        update_job_progress(
            job_id,
            status="failed",
            current_step=f"Hata oluştu: {str(e)}",
            error_msg=str(e)
        )
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTubeOto AI Video Arka Plan İşçisi")
    parser.add_argument("--job-id", type=str, required=True, help="Çalıştırılacak işin ID'si")
    args = parser.parse_args()
    ok = execute_job(args.job_id)
    sys.exit(0 if ok else 1)
