# Первый пуш в https://github.com/AndryshaDenisov1488/gitstats
# Требуется установленный Git: https://git-scm.com/download/win
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git не найден в PATH. Установите Git for Windows и откройте новый терминал."
}

if (-not (Test-Path ".git")) {
    git init
}

$hasOrigin = git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0) {
    git remote set-url origin "https://github.com/AndryshaDenisov1488/gitstats.git"
} else {
    git remote add origin "https://github.com/AndryshaDenisov1488/gitstats.git"
}

git add -- github_month_stats.py
$staged = git diff --cached --name-only
if ($staged) {
    git commit -m "Add GitHub monthly stats script"
} else {
    Write-Host "Нет изменений для коммита (файл без изменений)."
}

git branch -M main
git push -u origin main
