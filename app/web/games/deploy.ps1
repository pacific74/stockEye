# 보드게임 games 폴더를 stockeye 프로젝트의 games 폴더로 복사한 뒤 GitHub에 올립니다.
# Vercel이 GitHub와 연결되어 있으면 push 후 자동으로 배포됩니다.
param([string]$Message = "")

# ===== 설정 (처음 한 번만 확인) =====
$Src  = "D:\gamesPrj\games"                 # 게임 파일이 들어 있는 폴더
$Repo = "D:\gamesPrj\stockEye"              # GitHub 저장소 pacific74/stockEye 를 clone 한 폴더
$Dest = Join-Path $Repo "app\web\games"    # 저장소 안의 게임 위치 (배포되는 주소: /games/)
# ===================================

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Src))  { throw "게임 폴더가 없습니다: $Src" }
if (-not (Test-Path (Join-Path $Repo ".git")))  { throw "저장소가 아닙니다(.git 없음): $Repo  -> git clone https://github.com/pacific74/stockEye.git 로 받으세요" }

if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = "games update " + (Get-Date -Format "yyyy-MM-dd HH:mm")
}

Write-Host "1/4 게임 파일 복사: $Src -> $Dest"
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
robocopy $Src $Dest /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 실패 (코드 $LASTEXITCODE)" }

Write-Host "2/4 변경 확인"
git -C $Repo add -A
$changed = git -C $Repo status --porcelain
if (-not $changed) {
    Write-Host "변경된 내용이 없습니다. 배포하지 않습니다."
    exit 0
}

Write-Host "3/4 커밋: $Message"
git -C $Repo commit -m $Message | Out-Null

Write-Host "4/4 GitHub에 올리는 중..."
git -C $Repo push
if ($LASTEXITCODE -ne 0) { throw "push 실패" }

Write-Host ""
Write-Host "완료. GitHub Actions(app-build)가 돌아 배포되는 데 몇 분 걸립니다. 저장소의 Actions 탭에서 진행을 볼 수 있습니다."
Write-Host "배포 후 아래 주소에서 확인하세요:"
Write-Host "https://stockeye-pacific74.vercel.app/games/"
