set VERSION=latest
rmdir/Q /S sacad
del sacad_latest_win.7z sacad_latest_win.exe
cd ..
call %SYSTEMDRIVE%\Python33\python freeze.py build_exe -b win\sacad
copy LICENSE win\sacad\
copy win\readme.txt win\sacad\
cd win
call "%ProgramFiles%\7-Zip\7z.exe" a -t7z -mx9 sacad_%VERSION%_win.7z sacad
copy /b "%ProgramFiles%\7-Zip\7z.sfx" + sacad_%VERSION%_win.7z sacad_%VERSION%_win.exe
pause
