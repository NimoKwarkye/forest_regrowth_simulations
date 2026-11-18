@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cl /nologo /Zs /EHsc /std:c++14 /DHAVE_NETCDF /D_CRT_SECURE_NO_WARNINGS /I syntax-only /I F:\post_doc\guess_model\european_applications\framework /I F:\post_doc\guess_model\european_applications\modules /I F:\post_doc\guess_model\european_applications\cru\guessio /I F:\post_doc\guess_model\european_applications\libraries\gutil /I F:\post_doc\guess_model\european_applications\libraries\plib /I F:\post_doc\guess_model\european_applications\libraries\guessnc F:\post_doc\guess_model\european_applications\modules\cfxinput.cpp F:\post_doc\guess_model\european_applications\modules\globalco2file.cpp > syntax-check.log 2>&1
exit /b %errorlevel%
