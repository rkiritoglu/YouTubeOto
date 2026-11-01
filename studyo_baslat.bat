@echo off
chcp 65001 >nul
title YouTubeOto - Yapay Zeka Video Studyosu
cd /d "%~dp0"
echo ======================================================================
echo 🎬 YOUTUBE SHORTS YAPAY ZEKA VIDEO STUDYOSU BASLATILIYOR...
echo ======================================================================
python -m streamlit run app.py
pause
