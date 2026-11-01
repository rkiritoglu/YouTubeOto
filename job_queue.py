"""
job_queue.py - SQLite (WAL Modu) Tabanlı Asenkron İş Kuyruğu ve Durum Yöneticisi

Mimari Darboğaz 2 Çözümü:
- Streamlit WebSocket kopmalarına, sekme yenilemelerine ve NoSessionContext hatalarına karşı
  tüm video üretim işlerini disk tabanlı SQLite ('jobs.db') veritabanında saklar.
- Streamlit arayüzü yalnızca iş ekler ve @st.fragment(run_every="2s") ile durum okur;
  ağır AI ve FFmpeg işlemleri bağımsız 'worker.py' sürecinde yürütülür.
"""

import os
import json
import uuid
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    """İş kuyruğu tablosunu oluşturur."""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_jobs (
                job_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                style_preset TEXT NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                current_step TEXT NOT NULL DEFAULT '',
                script_json TEXT NOT NULL DEFAULT '{}',
                options_json TEXT NOT NULL DEFAULT '{}',
                output_dir TEXT NOT NULL DEFAULT '',
                video_path TEXT NOT NULL DEFAULT '',
                metadata_path TEXT NOT NULL DEFAULT '',
                youtube_video_id TEXT NOT NULL DEFAULT '',
                error_msg TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def create_job(
    topic: str,
    style_preset: str = "documentary_history",
    script_data: Optional[Dict[str, Any]] = None,
    options: Optional[Dict[str, Any]] = None
) -> str:
    """Yeni bir üretim işi oluşturur ve 'queued' durumunda kaydeder."""
    init_db()
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uid = uuid.uuid4().hex[:6]
    job_id = f"job_{timestamp}_{short_uid}"
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output_dir = os.path.abspath(os.path.join("output", job_id))

    with _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO video_jobs (
                job_id, topic, style_preset, status, progress, current_step,
                script_json, options_json, output_dir, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                topic,
                style_preset,
                "queued",
                2,
                "İş kuyruğa alındı, arka plan işçisi (worker) başlatılıyor...",
                json.dumps(script_data or {}, ensure_ascii=False),
                json.dumps(options or {}, ensure_ascii=False),
                output_dir,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    return job_id


def update_job_progress(
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    current_step: Optional[str] = None,
    script_data: Optional[Dict[str, Any]] = None,
    video_path: Optional[str] = None,
    metadata_path: Optional[str] = None,
    youtube_video_id: Optional[str] = None,
    error_msg: Optional[str] = None
) -> None:
    """Worker tarafından işin anlık durumunu ve ilerleme yüzdesini günceller."""
    init_db()
    fields = []
    values: List[Any] = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if progress is not None:
        fields.append("progress = ?")
        values.append(int(progress))
    if current_step is not None:
        fields.append("current_step = ?")
        values.append(current_step)
    if script_data is not None:
        fields.append("script_json = ?")
        values.append(json.dumps(script_data, ensure_ascii=False))
    if video_path is not None:
        fields.append("video_path = ?")
        values.append(video_path)
    if metadata_path is not None:
        fields.append("metadata_path = ?")
        values.append(metadata_path)
    if youtube_video_id is not None:
        fields.append("youtube_video_id = ?")
        values.append(youtube_video_id)
    if error_msg is not None:
        fields.append("error_msg = ?")
        values.append(error_msg)

    fields.append("updated_at = ?")
    values.append(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    values.append(job_id)

    with _get_conn() as conn:
        conn.execute(
            f"UPDATE video_jobs SET {', '.join(fields)} WHERE job_id = ?",
            tuple(values)
        )
        conn.commit()


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Belirtilen job_id'nin tüm bilgilerini sözlük olarak döndürür."""
    init_db()
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM video_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["script_data"] = json.loads(d.get("script_json") or "{}")
        except Exception:
            d["script_data"] = {}
        try:
            d["options"] = json.loads(d.get("options_json") or "{}")
        except Exception:
            d["options"] = {}
        return d


def list_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    """En son oluşturulan işleri yeniden eskiye sıralı olarak döndürür."""
    init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM video_jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["script_data"] = json.loads(d.get("script_json") or "{}")
            except Exception:
                d["script_data"] = {}
            try:
                d["options"] = json.loads(d.get("options_json") or "{}")
            except Exception:
                d["options"] = {}
            result.append(d)
        return result
