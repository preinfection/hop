# Builds everything into build\: the two apps (PyInstaller), ffmpeg, and the
# installer (Inno Setup 6). Run from anywhere:  powershell -File installer\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$build = Join-Path $root "build"
$dist = Join-Path $build "dist"
New-Item -ItemType Directory -Force $build, $dist | Out-Null

function App($name, $script, $extra) {
    python -m PyInstaller --noconfirm --windowed --name $name --icon "$root\assets\hop.ico" `
        --distpath $dist --workpath "$build\work" --specpath "$build\spec" @extra $script
    if ($LASTEXITCODE) { throw "$name failed to build" }
}

App "HopIsland" "$root\island\host.py" @(
    "--paths", "$root\island",
    "--add-data", "$root\island\ui;ui", "--add-data", "$root\island\bridge.js;.", "--add-data", "$root\assets;assets",
    "--add-data", "$root\VERSION;.",
    "--collect-all", "webview", "--collect-submodules", "winrt", "--collect-binaries", "winrt",
    "--collect-all", "clr_loader", "--hidden-import", "clr", "--hidden-import", "pycaw.pycaw", "--collect-submodules", "comtypes")

App "HopClipper" "$root\clipper\clipper.py" @(
    "--paths", "$root\clipper",
    "--add-data", "$root\clipper\watermark.png;.", "--add-data", "$root\clipper\click.wav;.",
    "--add-data", "$root\clipper\bunny.png;.", "--add-data", "$root\clipper\bunny.ico;.", "--add-data", "$root\VERSION;.",
    "--collect-all", "soundcard", "--hidden-import", "toastui")

# ffmpeg: gyan.dev's full shared build (one set of DLLs for ffmpeg + ffprobe).
$ff = Join-Path $dist "ffmpeg"
if (-not (Test-Path "$ff\ffmpeg.exe")) {
    $zip = Join-Path $build "ffmpeg-shared.7z"
    Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full-shared.7z" -OutFile $zip
    & "$env:ProgramFiles\7-Zip\7z.exe" x -y "-o$build\ffmpeg-src" $zip | Out-Null
    $bin = Get-ChildItem "$build\ffmpeg-src" -Directory | Select-Object -First 1
    New-Item -ItemType Directory -Force $ff | Out-Null
    Copy-Item "$($bin.FullName)\bin\*.dll", "$($bin.FullName)\bin\ffmpeg.exe", "$($bin.FullName)\bin\ffprobe.exe" $ff
    Copy-Item "$($bin.FullName)\LICENSE" "$ff\LICENSE-ffmpeg.txt"
}

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
& $iscc "$PSScriptRoot\hop.iss"
if ($LASTEXITCODE) { throw "the installer failed to build" }
Get-ChildItem "$build\installer\*.exe" | ForEach-Object { "{0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB) }
