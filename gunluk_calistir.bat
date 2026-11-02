@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================================================
echo  GUNLUK OTONOM RAYLI SISTEMLER YOUTUBE SHORTS URETIMI BASLATILIYOR
echo  Tarih / Saat: %date% %time%
echo ======================================================================

:: Python ile günlük otonom robotu çalıştır ('private' olarak YouTube Studio'ya yükler)
:: Video YouTube Studio'da 'Gizli' olarak bekler; siz izleyip onaylayınca 'Yayınla' dersiniz.
:: Doğrudan herkese açık yayınlansın isterseniz 'private' yerine 'public' yazabilirsiniz.
python daily_runner.py private

echo.
echo ======================================================================
echo  Islem tamamlandi. Pencereyi kapatabilirsiniz.
echo ======================================================================
pause
