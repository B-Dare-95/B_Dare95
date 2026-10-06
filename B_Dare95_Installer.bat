@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM  B_Dare95 pyRevit Extension - Installer / Repair
REM  Runs as the CURRENT USER. No administrator rights required.
REM  Everything happens inside your own profile.
REM
REM  Run it ONCE. After that the tools keep themselves up to date:
REM  every Revit start / pyRevit Reload, and again when Revit closes.
REM  Re-running it is always safe: it repairs any install - an old
REM  ZIP copy, a copy with local changes, a broken git folder - in
REM  place, without deleting the tools, and updates pyRevit itself.
REM
REM  If git is not installed, MinGit (the minimal Git for Windows
REM  build) is downloaded to %LOCALAPPDATA%\B_Dare95_git.
REM  Per-user, no admin, PATH is not modified.
REM
REM  Switches (optional):
REM    /auto      unattended - no questions, no "press any key"
REM    /noupdate  skip the pyRevit self-update step
REM    /onlyext   same as /noupdate (alias)
REM ============================================================

REM --- Configurable values ---------------------------------------
REM  DEST / BD_GIT_HOME / BD_DATA must match lib\bd_updater.py.
set "REPO_URL=https://github.com/B-Dare-95/B_Dare95.git"
set "BRANCH=main"
set "ZIP_URL=https://github.com/B-Dare-95/B_Dare95/archive/refs/heads/main.zip"
set "PYREVIT_REPO=pyrevitlabs/pyRevit"
set "DEST=%LOCALAPPDATA%\B_Dare95_dist"
set "EXT_FOLDER=B_Dare95.extension"
REM  Deliberately NOT named GIT_DIR - that is a real git variable.
set "BD_GIT_HOME=%LOCALAPPDATA%\B_Dare95_git"
set "BD_DATA=%LOCALAPPDATA%\B_Dare95"
set "BD_LOG=%BD_DATA%\update.log"
REM  Same per-call flags as bd_updater.py; nothing is written to git config.
set "GITFLAGS=-c safe.directory=* -c credential.helper= -c core.longpaths=true -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30"
set "GIT_TERMINAL_PROMPT=0"
set "GCM_INTERACTIVE=never"

REM --- Parse switches ---------------------------------------------
set "AUTO="
set "NOUPDATE="
set "RELAUNCHED="
for %%a in (%*) do (
    if /i "%%~a"=="/auto"       set "AUTO=1"
    if /i "%%~a"=="/noupdate"   set "NOUPDATE=1"
    if /i "%%~a"=="/onlyext"    set "NOUPDATE=1"
    if /i "%%~a"=="/relaunched" set "RELAUNCHED=1"
)

REM --- Run from a throwaway copy -----------------------------------
REM  If this file ever lives inside the install folder, the update
REM  below would rewrite it while cmd.exe is still reading it line by
REM  line. Running a copy from TEMP makes that impossible.
if not defined RELAUNCHED (
    copy /y "%~f0" "%TEMP%\B_Dare95_install_run.bat" >nul 2>nul
    if exist "%TEMP%\B_Dare95_install_run.bat" (
        call "%TEMP%\B_Dare95_install_run.bat" %* /relaunched
        exit /b !errorlevel!
    )
)

echo.
echo ==========================================================
echo   B_Dare95 pyRevit Extension - Installer / Repair
echo ==========================================================
echo   Install location : %DEST%
echo.

if not exist "%BD_DATA%" mkdir "%BD_DATA%" >nul 2>nul

REM --- Elevation check ----------------------------------------------
REM  An elevated run can install into a different user's profile
REM  (whoever's admin account was used), not the person using Revit.
fltmc >nul 2>&1
if not errorlevel 1 (
    echo [WARN] This window is running as ADMINISTRATOR.
    echo        The tools will install into the profile of: %USERNAME%
    echo        If that is not the person who uses Revit, close this
    echo        window and double-click the file normally instead.
    echo.
    if not defined AUTO (
        set /p GOON="Continue anyway? (Y/N): "
        if /i not "!GOON!"=="Y" exit /b 1
        echo.
    )
)

REM --- 0. Make sure pyRevit itself is installed --------------------
set "PYREVIT_FOUND="
where pyrevit >nul 2>nul && set "PYREVIT_FOUND=1"
if exist "%APPDATA%\pyRevit-Master" set "PYREVIT_FOUND=1"
if exist "%APPDATA%\pyRevit\pyRevit_config.ini" set "PYREVIT_FOUND=1"

if not defined PYREVIT_FOUND (
    echo [WARN] pyRevit does not appear to be installed on this machine.
    echo.
    if defined AUTO (
        echo        Unattended mode - cannot install pyRevit without you.
        echo        Run this file by double-clicking it and follow the prompts.
        exit /b 1
    )
    echo        This script can download the official pyRevit installer from
    echo        GitHub ^(%PYREVIT_REPO%^) and install it silently. It uses the
    echo        PER-USER build, so no administrator rights are needed.
    echo.
    set /p GETPR="Download and install pyRevit now? (Y/N): "
    if /i "!GETPR!"=="Y" (
        call :UPDATE_PYREVIT
        echo.
        echo ==========================================================
        echo   After pyRevit finishes installing:
        echo     1. Open Revit. When pyRevit asks, click "Always Load"
        echo        so it loads on every startup.
        echo     2. Let pyRevit finish its first-time setup, then close Revit.
        echo     3. Double-click THIS file again to add the B_Dare95 tools.
        echo ==========================================================
        echo.
        pause
        exit /b 0
    ) else (
        echo.
        echo Please install pyRevit first, then re-run this file. Aborting.
        echo.
        pause
        exit /b 0
    )
)
echo [OK]   pyRevit detected.
echo.

REM --- 1. Locate the pyRevit CLI (bundled with pyRevit) ------------
call :FIND_CLI
if defined PYREVIT (
    echo [OK]   Found pyRevit CLI: !PYREVIT!
) else (
    echo [WARN] pyRevit CLI not found on PATH. Files will still install;
    echo        you may need to add the search path once from the UI.
)
echo.

REM --- 2. Keep pyRevit itself up to date (silent) -------------------
set "REVIT_RUNNING="
tasklist /fi "imagename eq Revit.exe" 2>nul | find /i "Revit.exe" >nul && set "REVIT_RUNNING=1"

if defined NOUPDATE (
    echo [SKIP] pyRevit self-update skipped ^(/noupdate^).
) else if defined REVIT_RUNNING (
    echo [SKIP] Revit is running - pyRevit cannot be updated while it is open.
    echo        Close Revit and re-run this file to update pyRevit itself.
) else (
    call :UPDATE_PYREVIT
    REM CLI may have moved or appeared after an update - look again.
    call :FIND_CLI
)
echo.

REM --- 3. Make sure a WORKING git is available ----------------------
set "OFF_REASON="
call :FIND_GIT
if not defined GIT (
    echo [INFO] git not found - installing MinGit ^(per-user, no admin^)...
    call :INSTALL_GIT
    call :FIND_GIT
)
if defined GIT (
    echo [OK]   Using git: !GIT!
) else (
    set "OFF_REASON=git could not be installed on this PC (download blocked?)"
    echo [WARN] git is still unavailable.
)
echo.

REM --- 4. Get the files ----------------------------------------------
set "SYNC_RC=1"
if defined GIT (
    if exist "%DEST%\.git" (
        echo [INFO] Existing install found - bringing it exactly up to date...
    ) else if exist "%DEST%\%EXT_FOLDER%" (
        echo [INFO] Older copy without git found - switching it to automatic updates...
    ) else (
        echo [INFO] Downloading B_Dare95 with git...
    )
    if not exist "%DEST%" mkdir "%DEST%"
    call :GIT_SYNC
    if not "!SYNC_RC!"=="0" (
        echo [WARN] First attempt failed - rebuilding the git data and retrying...
        if exist "%DEST%\.git" rmdir /s /q "%DEST%\.git"
        call :GIT_SYNC
    )
    if not "!SYNC_RC!"=="0" (
        set "OFF_REASON=git could not download from GitHub (proxy or firewall?)"
        echo [WARN] git could not download from GitHub.
    )
)
if not "!SYNC_RC!"=="0" (
    if exist "%DEST%\%EXT_FOLDER%" (
        echo [INFO] Keeping the copy that is already installed.
    ) else (
        call :ZIP_FALLBACK
    )
)
echo.

REM --- 5. Verify the extension folder actually landed --------------
if not exist "%DEST%\%EXT_FOLDER%" (
    echo [ERROR] Could not find "%EXT_FOLDER%" inside "%DEST%".
    echo         The download did not complete correctly. Aborting.
    >>"%BD_LOG%" echo %DATE% %TIME:~0,8%  [installer] FAILED - no extension folder after download
    echo.
    if not defined AUTO pause
    exit /b 1
)
echo [OK]   Extension present: %DEST%\%EXT_FOLDER%
echo.

REM --- 6. Register the PARENT folder as an extension search path ----
REM     pyRevit scans this path, finds the nested .extension, and
REM     lists it in Settings ^> Extensions.
if defined PYREVIT (
    echo [INFO] Registering search path with pyRevit CLI...
    "!PYREVIT!" extensions paths add "%DEST%"
    if not "!errorlevel!"=="0" (
        echo.
        echo [WARN] The CLI command did not succeed - usually a pyRevit
        echo        version difference. Add this path manually in
        echo        pyRevit Settings ^> Extensions ^> Custom Extension Directories:
        echo.
        echo            %DEST%
        echo.
    ) else (
        echo [OK]   Search path registered.
    )
) else (
    echo [ACTION NEEDED] Add this folder as a custom extension directory in
    echo                 pyRevit Settings ^> Extensions:
    echo.
    echo            %DEST%
    echo.
)

REM --- 7. Verdict -----------------------------------------------------
set "AUTOUPDATE=OFF"
set "HEAD_SHORT=unknown"
if defined GIT if "!SYNC_RC!"=="0" if exist "%DEST%\.git" set "AUTOUPDATE=ON"
if defined GIT if exist "%DEST%\.git" (
    for /f "delims=" %%h in ('call "!GIT!" %GITFLAGS% -C "%DEST%" rev-parse --short HEAD 2^>nul') do set "HEAD_SHORT=%%h"
)
if "!AUTOUPDATE!"=="OFF" if not defined OFF_REASON set "OFF_REASON=unknown - see the messages above"
>>"%BD_LOG%" echo %DATE% %TIME:~0,8%  [installer] AUTO-UPDATE !AUTOUPDATE!  commit=!HEAD_SHORT!  git=!GIT!  reason=!OFF_REASON!

echo.
echo ==========================================================
if "!AUTOUPDATE!"=="ON" (
    echo   AUTO-UPDATE: ON          version !HEAD_SHORT!
    echo.
    echo   The tools now update themselves every time Revit starts
    echo   or pyRevit reloads, and again when Revit closes.
    echo   No need to run this file again.
) else (
    echo   AUTO-UPDATE: OFF
    echo   Reason: !OFF_REASON!
    echo.
    echo   The tools are installed and work, but they will NOT update
    echo   themselves. Revit will remind you once a day. Run this file
    echo   again later, or send this window to the person who gave
    echo   you the tools.
)
echo.
if defined REVIT_RUNNING (
    echo   Revit is open: click Reload on the pyRevit tab to load
    echo   this version.
) else (
    echo   Open Revit to load the B_Dare95 tools.
)
echo   Log: %BD_LOG%
echo ==========================================================
echo.
if not defined AUTO pause
endlocal
exit /b 0


REM ================================================================
REM  :FIND_CLI - locate pyrevit.exe, set PYREVIT (empty if missing)
REM ================================================================
:FIND_CLI
set "PYREVIT="
for /f "delims=" %%i in ('where pyrevit 2^>nul') do set "PYREVIT=%%i"
if not defined PYREVIT if exist "%APPDATA%\pyRevit-Master\bin\pyrevit.exe"                 set "PYREVIT=%APPDATA%\pyRevit-Master\bin\pyrevit.exe"
if not defined PYREVIT if exist "%APPDATA%\pyRevit CLI\bin\pyrevit.exe"                    set "PYREVIT=%APPDATA%\pyRevit CLI\bin\pyrevit.exe"
if not defined PYREVIT if exist "%LOCALAPPDATA%\Programs\pyRevit CLI\bin\pyrevit.exe"      set "PYREVIT=%LOCALAPPDATA%\Programs\pyRevit CLI\bin\pyrevit.exe"
if not defined PYREVIT if exist "%ProgramFiles%\pyRevit CLI\bin\pyrevit.exe"               set "PYREVIT=%ProgramFiles%\pyRevit CLI\bin\pyrevit.exe"
goto :eof


REM ================================================================
REM  :FIND_GIT - same search order as find_git() in bd_updater.py:
REM  our MinGit/PortableGit, PATH, then the standard install folders.
REM  Sets GIT to a git.exe that actually RUNS (empty if none).
REM ================================================================
:FIND_GIT
set "GIT="
if exist "%BD_GIT_HOME%\cmd\git.exe" set "GIT=%BD_GIT_HOME%\cmd\git.exe"
if not defined GIT for /f "delims=" %%i in ('where git.exe 2^>nul') do if not defined GIT set "GIT=%%i"
if not defined GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if defined GIT (
    "!GIT!" --version >nul 2>&1 || set "GIT="
)
goto :eof


REM ================================================================
REM  :INSTALL_GIT - download the latest 64-bit MinGit .zip (no
REM  self-extracting .exe for antivirus to block) into BD_GIT_HOME.
REM  Finds the release through the GitHub API, or - when the API is
REM  rate-limited - through the public "latest release" redirect.
REM  PowerShell exit codes: 0 ok | 2 no release | 3 download | 4 extract
REM ================================================================
:INSTALL_GIT
set "BD_GIT_TARGET=%BD_GIT_HOME%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; $h=@{'User-Agent'='B_Dare95'}; $url=$null; try { $rel=Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers $h -TimeoutSec 30; $a=$rel.assets | Where-Object { $_.name -like 'MinGit-*-64-bit.zip' -and $_.name -notlike '*busybox*' } | Select-Object -First 1; if($a){ $url=$a.browser_download_url } } catch { Write-Host ('       release API unavailable: ' + $_.Exception.Message) }; if(-not $url){ try { $rq=[Net.HttpWebRequest]::Create('https://github.com/git-for-windows/git/releases/latest'); $rq.AllowAutoRedirect=$false; $rq.UserAgent='B_Dare95'; $rs=$rq.GetResponse(); $loc=[string]$rs.Headers['Location']; $rs.Close(); $tag=$loc.Substring($loc.LastIndexOf('/')+1); if($tag -match '^v(\d+\.\d+\.\d+)\.windows\.(\d+)$'){ $v=$matches[1]; if($matches[2] -ne '1'){ $v=$v+'.'+$matches[2] }; $url='https://github.com/git-for-windows/git/releases/download/'+$tag+'/MinGit-'+$v+'-64-bit.zip' } } catch { Write-Host ('       release page unavailable: ' + $_.Exception.Message) } }; if(-not $url){ Write-Host '       could not find the latest MinGit release.'; exit 2 }; $zip=Join-Path $env:TEMP 'B_Dare95_MinGit.zip'; $ok=$false; for($i=1; $i -le 3 -and -not $ok; $i++){ try { Write-Host ('       downloading ' + [IO.Path]::GetFileName($url) + ' (attempt ' + $i + ' of 3) ...'); Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -Headers $h -TimeoutSec 600; $ok=$true } catch { Write-Host ('       ' + $_.Exception.Message); Start-Sleep -Seconds 3 } }; if(-not $ok){ exit 3 }; $dst=$env:BD_GIT_TARGET; $tmp=$dst + '.new'; $rc=0; try { Write-Host '       extracting ...'; if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }; Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($zip, $tmp); if(-not (Test-Path (Join-Path $tmp 'cmd\git.exe'))){ Write-Host '       cmd\git.exe missing from the archive.'; $rc=4 } else { if(Test-Path $dst){ Remove-Item $dst -Recurse -Force }; Move-Item $tmp $dst } } catch { Write-Host ('       ' + $_.Exception.Message); $rc=4 }; Remove-Item $zip -Force -ErrorAction SilentlyContinue; exit $rc"
set "GIT_RC=%errorlevel%"
set "BD_GIT_TARGET="

if "%GIT_RC%"=="0" echo [OK]   MinGit installed to %BD_GIT_HOME%
if "%GIT_RC%"=="2" echo [WARN] Could not find the latest Git for Windows release on GitHub.
if "%GIT_RC%"=="3" echo [WARN] git download failed ^(network, proxy or GitHub issue^).
if "%GIT_RC%"=="4" echo [WARN] git could not be extracted ^(antivirus or a locked folder?^).
goto :eof


REM ================================================================
REM  :GIT_SYNC - make DEST exactly origin/main, IN PLACE.
REM  Works for every starting point: empty folder, old ZIP copy,
REM  clone with local changes, diverged or detached clone. Never
REM  deletes the tools themselves. Same steps as _converge() in
REM  bd_updater.py. Sets SYNC_RC=0 on success.
REM ================================================================
:GIT_SYNC
set "SYNC_RC=1"
if not exist "%DEST%\.git" (
    "%GIT%" %GITFLAGS% -C "%DEST%" init -q || goto :eof
    "%GIT%" %GITFLAGS% -C "%DEST%" symbolic-ref HEAD refs/heads/%BRANCH% || goto :eof
)
"%GIT%" %GITFLAGS% -C "%DEST%" remote set-url origin "%REPO_URL%" >nul 2>&1 || "%GIT%" %GITFLAGS% -C "%DEST%" remote add origin "%REPO_URL%" || goto :eof
"%GIT%" %GITFLAGS% -C "%DEST%" fetch --no-tags origin +refs/heads/%BRANCH%:refs/remotes/origin/%BRANCH% || goto :eof
"%GIT%" %GITFLAGS% -C "%DEST%" checkout -q -f -B %BRANCH% origin/%BRANCH% || goto :eof
REM  Remove leftovers (e.g. buttons an old ZIP copy had that were since
REM  renamed/deleted) - only inside the extension, never .gitignore'd files.
"%GIT%" %GITFLAGS% -C "%DEST%" clean -fdq -- %EXT_FOLDER% || goto :eof
set "SYNC_RC=0"
goto :eof


REM ================================================================
REM  :ZIP_FALLBACK - only when git is unusable AND nothing is
REM  installed yet. Copies over DEST without deleting anything.
REM  A ZIP copy does not update itself; Revit reminds the user daily.
REM ================================================================
:ZIP_FALLBACK
echo [INFO] Downloading a ZIP copy instead ^(this copy will NOT auto-update^)...
if not exist "%DEST%" mkdir "%DEST%"
set "BD_ZIP_URL=%ZIP_URL%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; $zip=Join-Path $env:TEMP 'B_Dare95.zip'; $out=Join-Path $env:TEMP 'B_Dare95_unzip'; $rc=3; for($i=1; $i -le 3 -and $rc -ne 0; $i++){ try { Invoke-WebRequest -Uri $env:BD_ZIP_URL -OutFile $zip -UseBasicParsing -TimeoutSec 600; $rc=0 } catch { Write-Host ('       ' + $_.Exception.Message); Start-Sleep -Seconds 3 } }; if($rc -eq 0){ try { if(Test-Path $out){ Remove-Item $out -Recurse -Force }; Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($zip, $out) } catch { Write-Host ('       ' + $_.Exception.Message); $rc=4 } }; Remove-Item $zip -Force -ErrorAction SilentlyContinue; exit $rc"
set "ZIP_RC=%errorlevel%"
set "BD_ZIP_URL="
REM  GitHub zips extract to a "<repo>-main" subfolder; lift its contents up.
if "%ZIP_RC%"=="0" (
    for /d %%d in ("%TEMP%\B_Dare95_unzip\*") do xcopy /e /i /y /q "%%d\*" "%DEST%\" >nul
    echo [OK]   ZIP copy installed.
) else (
    echo [WARN] The ZIP download failed too ^(exit %ZIP_RC%^).
)
rmdir /s /q "%TEMP%\B_Dare95_unzip" >nul 2>nul
goto :eof


REM ================================================================
REM  :UPDATE_PYREVIT - compare installed vs latest GitHub release and
REM  silently install the newest PER-USER build if we are behind.
REM  PowerShell exit codes: 0 updated | 10 already current
REM                         2/3/4 problem | 11 machine-wide install
REM ================================================================
:UPDATE_PYREVIT
echo [INFO] Checking for a newer pyRevit release...
set "BD_CLI=%PYREVIT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; try { $h=@{'User-Agent'='B_Dare95'}; $rel=Invoke-RestMethod -Uri 'https://api.github.com/repos/%PYREVIT_REPO%/releases/latest' -Headers $h -TimeoutSec 30; $t=($rel.tag_name -replace '[^0-9.]','').Trim('.'); $seg=@($t.Split('.')); while($seg.Count -lt 3){$seg+='0'}; $latest=[version]($seg[0..2] -join '.'); $cur=$null; $cli=$env:BD_CLI; if($cli -and (Test-Path $cli)){ $o=(& $cli --version 2>$null | Out-String); if($o -match '(\d+\.\d+\.\d+)'){ $cur=[version]$matches[1] } }; if(-not $cur){ $u=Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'pyRevit*' } | Select-Object -First 1; if($u -and $u.DisplayVersion -match '(\d+\.\d+\.\d+)'){ $cur=[version]$matches[1] } }; $m=Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like 'pyRevit*' } | Select-Object -First 1; $shown=if($cur){$cur.ToString()}else{'unknown'}; Write-Host ('       installed: ' + $shown + '    latest: ' + $latest); if($m -and -not $cur){ Write-Host '       machine-wide pyRevit install detected.'; exit 11 }; if($cur -and $cur -ge $latest){ exit 10 }; $a=$rel.assets | Where-Object { $_.name -like '*.exe' -and $_.name -notlike '*admin*' -and $_.name -notlike '*CLI*' } | Select-Object -First 1; if(-not $a){ Write-Host '       no per-user installer asset in that release.'; exit 2 }; $dst=Join-Path $env:TEMP $a.name; Write-Host ('       downloading ' + $a.name + ' ...'); $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri $a.browser_download_url -OutFile $dst -UseBasicParsing; Write-Host '       installing silently ...'; $pr=Start-Process -FilePath $dst -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOCANCEL','/SP-' -Wait -PassThru; Remove-Item $dst -Force -ErrorAction SilentlyContinue; if($pr.ExitCode -ne 0){ Write-Host ('       installer exit code ' + $pr.ExitCode); exit 4 }; exit 0 } catch { Write-Host ('       ' + $_.Exception.Message); exit 3 }"
set "UPD_RC=%errorlevel%"
set "BD_CLI="

if "%UPD_RC%"=="0"  echo [OK]   pyRevit updated to the latest release.
if "%UPD_RC%"=="10" echo [OK]   pyRevit is already the latest release.
if "%UPD_RC%"=="11" (
    echo [SKIP] pyRevit was installed for ALL USERS on this machine.
    echo        Updating that copy needs administrator rights, so it was
    echo        left alone. Ask IT to run the admin installer from:
    echo            https://github.com/%PYREVIT_REPO%/releases
)
if "%UPD_RC%"=="2" echo [WARN] Could not find a per-user installer in the latest release.
if "%UPD_RC%"=="3" echo [WARN] pyRevit update check failed ^(network or GitHub issue^). Continuing.
if "%UPD_RC%"=="4" echo [WARN] The pyRevit installer did not report success. Continuing.
goto :eof
