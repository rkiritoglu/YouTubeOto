@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================================================
echo  GUNLUK OTONOM RAYLI SISTEMLER YOUTUBE SHORTS URETIMI BASLATILIYOR
echo  Tarih / Saat: %date% %time%
echo ======================================================================

:: Python ile günlük otonom robotu çalıştır ('public' olarak kanala yükler)
:: Not: Önce gizli denemek isterseniz 'public' yerine 'private' yazabilirsiniz.
python daily_runner.py public

echo.
echo ======================================================================
echo  Islem tamamlandi. Pencereyi kapatabilirsiniz.
echo ======================================================================
pause
