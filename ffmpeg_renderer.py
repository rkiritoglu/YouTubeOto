"""
ffmpeg_renderer.py - Doğrudan FFmpeg (C/SIMD) Tabanlı Ken Burns (zoompan), Pacing ve .ASS Altyazı Motoru

Mimari Darboğaz 1 & 3 Çözümü:
1. MoviePy'ın her kareyi NumPy dizisine (ndarray) dönüştüren yavaş ve yüksek RAM tüketen
   mimarisini tamamen devre dışı bırakır; doğrudan imageio-ffmpeg (FFmpeg v7.1) binary'sini çağırır.
2. Durağan AI görsellerini (Flux 9:16) FFmpeg'in yerel 'zoompan' filtresiyle işleyerek
   alternatifli Zoom-In, Zoom-Out ve Pan kamera hareketleri üretir.
3. Hareketli AI videolarında (Fal.ai / LTX) video süresi ile ses süresi uyuşmadığında
   FFmpeg 'setpts' ve 'tpad=stop_mode=clone' filtreleriyle milisaniye hassasiyetinde senkron sağlar.
4. Kelime vurgulu .ass altyazı dosyasını tek geçişte (single-pass) videoya gömer.
"""

import os
import math
import shutil
import subprocess
from typing import List, Dict, Any, Callable, Optional
import imageio_ffmpeg

from audio_generator import get_audio_duration_sec
from subtitle_generator import generate_ass_subtitles


FPS = 30
TARGET_W = 1080
TARGET_H = 1920


def get_ffmpeg_bin() -> str:
    """Sistemdeki yerel FFmpeg yürütülebilir dosya yolunu döndürür."""
    return imageio_ffmpeg.get_ffmpeg_exe()


def _has_audio_stream(media_path: str) -> bool:
    """Verilen video dosyasında ses kanalı (Audio stream) olup olmadığını kontrol eder."""
    if not media_path or not os.path.exists(media_path):
        return False
    try:
        proc = subprocess.run(
            [get_ffmpeg_bin(), "-i", media_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8
        )
        return "Audio:" in (proc.stderr or "")
    except Exception:
        return False


def _build_zoompan_filter(scene_id: int, duration_sec: float, fps: int = FPS) -> str:
    """
    Sahne numarasına göre çeşitlendirilmiş sinematik Ken Burns (zoompan) filtresi üretir.
    Titremeyi (jitter) önlemek için önce 2160x3840'a ölçekler, ardından 1080x1920'ye zoompan uygular.
    """
    total_frames = max(int(math.ceil(duration_sec * fps)) + 5, 30)
    mode = (scene_id - 1) % 3

    if mode == 0:
        # Merkezden yumuşak Zoom-In (1.0 -> 1.22)
        z_expr = "min(zoom+0.0014,1.22)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    elif mode == 1:
        # Yumuşak Zoom-Out (1.22 -> 1.0)
        z_expr = "if(eq(on,1),1.22,max(1.001,zoom-0.0014))"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = "ih/2-(ih/zoom/2)"
    else:
        # Hafif Dikey Kamera Kaydırma (Pan Up + Zoom)
        z_expr = "min(zoom+0.0010,1.18)"
        x_expr = "iw/2-(iw/zoom/2)"
        y_expr = f"max(0,(ih-ih/zoom)*(1-on/{total_frames}))"

    return (
        f"scale=2160:3840:force_original_aspect_ratio=increase,"
        f"crop=2160:3840,"
        f"zoompan=z='{z_expr}':d={total_frames}:x='{x_expr}':y='{y_expr}':s={TARGET_W}x{TARGET_H}:fps={fps},"
        f"format=yuv420p"
    )


def render_single_scene_ffmpeg(
    scene: Dict[str, Any],
    work_dir: str,
    fps: int = FPS
) -> str:
    """
    Tek bir sahneyi (AI Görsel veya AI Video) kendi ses dosyasıyla tam senkronlu olarak
    1080x1920 @ 30fps MP4 parçasına dönüştürür.
    """
    ffmpeg_exe = get_ffmpeg_bin()
    scene_id = int(scene.get("scene_id", 1))
    audio_path = os.path.abspath(scene.get("audio_file_path", ""))
    visual_path = os.path.abspath(scene.get("visual_file_path", ""))
    visual_type = scene.get("visual_type", "image")

    if not os.path.exists(audio_path) or not os.path.exists(visual_path):
        raise FileNotFoundError(f"Sahne {scene_id} için ses veya görsel dosyası eksik.")

    duration_sec = float(scene.get("duration_sec") or get_audio_duration_sec(audio_path) or 3.5)
    scene["duration_sec"] = duration_sec

    out_clip_path = os.path.abspath(os.path.join(work_dir, f"rendered_scene_{scene_id}.mp4"))

    if visual_type == "video":
        # Darboğaz 3 + Özel Kullanıcı Videosu Senkronizasyonu
        total_vid_dur = get_audio_duration_sec(visual_path)
        if total_vid_dur <= 0.2:
            total_vid_dur = 4.0

        custom_start_sec = max(0.0, float(scene.get("custom_start_sec") or 0.0))
        if custom_start_sec >= total_vid_dur:
            custom_start_sec = 0.0

        avail_dur = max(0.3, total_vid_dur - custom_start_sec)
        # Eğer video sesten uzunsa normal hızda (1.0x) oynat ve ses süresinde kes; kısaysa yumuşak uzat
        if avail_dur >= duration_sec:
            pts_factor = 1.0
        else:
            pts_factor = max(0.75, min(1.65, duration_sec / avail_dur))

        pad_extra = max(0.5, duration_sec - (avail_dur * pts_factor) + 0.5)
        fit_mode = str(scene.get("custom_fit_mode") or "crop")
        keep_ambient = bool(scene.get("custom_ambient_audio", False)) and _has_audio_stream(visual_path)

        if fit_mode == "blur_pad":
            # Yatay videoların kenarlarını kesmeden bulanık arka plan üzerinde tam genişlikte göster
            v_filter = (
                f"[0:v]setpts={pts_factor:.3f}*PTS,fps={fps},split=2[bg][fg];"
                f"[bg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_W}:{TARGET_H},boxblur=24:4[bgblur];"
                f"[fg]scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease[fgfit];"
                f"[bgblur][fgfit]overlay=(W-w)/2:(H-h)/2,"
                f"tpad=stop_mode=clone:stop_duration={pad_extra:.2f},format=yuv420p[vout]"
            )
        else:
            # Tam ekran dikey kırpma (9:16 Center Crop)
            v_filter = (
                f"[0:v]setpts={pts_factor:.3f}*PTS,"
                f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_W}:{TARGET_H},"
                f"fps={fps},"
                f"tpad=stop_mode=clone:stop_duration={pad_extra:.2f},"
                f"format=yuv420p[vout]"
            )

        input_args = [ffmpeg_exe, "-y"]
        if custom_start_sec > 0:
            input_args.extend(["-ss", f"{custom_start_sec:.2f}"])
        input_args.extend(["-i", visual_path, "-i", audio_path])

        if keep_ambient:
            filter_complex = (
                f"{v_filter};"
                f"[0:a]volume=0.15[amb];"
                f"[1:a]volume=1.0[tts];"
                f"[amb][tts]amix=inputs=2:duration=second:dropout_transition=0[aout]"
            )
            map_args = ["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"]
        else:
            map_args = ["-filter_complex", v_filter, "-map", "[vout]", "-map", "1:a:0"]

        cmd = input_args + map_args + [
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-t", f"{duration_sec:.3f}",
            out_clip_path
        ]
    else:
        # Durağan 9:16 AI Görsel -> FFmpeg C-seviyesi Zoompan (Ken Burns)
        vf_chain = _build_zoompan_filter(scene_id=scene_id, duration_sec=duration_sec, fps=fps)
        cmd = [
            ffmpeg_exe, "-y",
            "-loop", "1",
            "-i", visual_path,
            "-i", audio_path,
            "-vf", vf_chain,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-ac", "2",
            "-t", f"{duration_sec:.3f}",
            out_clip_path
        ]

    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )
    if proc.returncode != 0 or not os.path.exists(out_clip_path):
        raise RuntimeError(f"FFmpeg Sahne {scene_id} render hatası:\n{proc.stderr[-600:]}")

    return out_clip_path


def render_full_project_ffmpeg(
    scenes: List[Dict[str, Any]],
    output_dir: str,
    final_video_name: str = "final_shorts.mp4",
    burn_subtitles: bool = False,
    show_top_banner: bool = False,
    top_banner_text: str = "",
    text_style_preset: str = "gold_banner",
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> str:
    """
    Tüm sahneleri FFmpeg ile işler, uç uca birleştirir ve üst başlık bandı (Top Banner)
    ve/veya kelime zamanlamalı .ass altyazısını tek geçişte videoya yakarak output_dir altına kaydeder.
    """
    os.makedirs(output_dir, exist_ok=True)
    work_dir = os.path.join(output_dir, "build_temp")
    os.makedirs(work_dir, exist_ok=True)

    ffmpeg_exe = get_ffmpeg_bin()
    rendered_clips: List[str] = []
    total_scenes = len(scenes)

    # 1. Her sahneyi FFmpeg zoompan / setpts ile kendi ses süresinde render et
    for idx, scene in enumerate(scenes):
        scene_id = scene.get("scene_id", idx + 1)
        if progress_callback:
            pct = 60 + int(((idx) / max(1, total_scenes)) * 25)
            progress_callback(pct, f"FFmpeg Render: Sahne {scene_id}/{total_scenes} (Ken Burns & Ses Senkronu)...")

        clip_path = render_single_scene_ffmpeg(scene, work_dir=work_dir)
        rendered_clips.append(clip_path)

    # 2. Üst Katman Başlığı ve/veya Kelime Zamanlamalı .ass dosyasını üret
    ass_filename = "subtitles.ass"
    ass_Work_path = os.path.join(work_dir, ass_filename)
    generate_ass_subtitles(
        scenes,
        output_ass_path=ass_Work_path,
        text_style_preset=text_style_preset,
        show_top_banner=show_top_banner,
        top_banner_text=top_banner_text,
        show_bottom_subtitles=burn_subtitles
    )
    # Kalıcı bir kopyasını da output_dir içine koy
    shutil.copy2(ass_Work_path, os.path.join(output_dir, ass_filename))

    # 3. FFmpeg concat listesi oluştur
    concat_list_path = os.path.join(work_dir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for c_path in rendered_clips:
            safe_path = os.path.abspath(c_path).replace("\\", "/")
            f.write(f"file '{safe_path}'\n")

    merged_no_subs = os.path.join(work_dir, "merged_raw.mp4")
    cmd_concat = [
        ffmpeg_exe, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat_list.txt",
        "-c", "copy",
        "merged_raw.mp4"
    ]
    subprocess.run(cmd_concat, cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    final_output_path = os.path.abspath(os.path.join(output_dir, final_video_name))

    # 4. .ASS Üst Katman Yazısını ve/veya Altyazıyı Tek Geçişte Videoya Yak (Burn-in)
    if progress_callback:
        progress_callback(90, "FFmpeg: Video üst katman yazıları (.ASS) işleniyor...")

    should_burn_ass = (burn_subtitles or (show_top_banner and bool(top_banner_text.strip())))
    if should_burn_ass and os.path.exists(ass_Work_path):
        cmd_sub = [
            ffmpeg_exe, "-y",
            "-i", "merged_raw.mp4",
            "-vf", f"ass={ass_filename}",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-c:a", "copy",
            final_output_path
        ]
        sub_proc = subprocess.run(
            cmd_sub,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        if sub_proc.returncode != 0 or not os.path.exists(final_output_path):
            # libass filtresi desteklenmezse altyazısız birleştirilmiş videoyu kopyala
            shutil.copy2(merged_no_subs, final_output_path)
    else:
        shutil.copy2(merged_no_subs, final_output_path)

    # Geçici build_temp dosyalarını temizle
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    return final_output_path
