# Configuracao do projeto no Windows (rodar uma vez, na pasta do projeto).
# Uso: clique com o botao direito no PowerShell > "Executar como usuario" e rode:
#   powershell -ExecutionPolicy Bypass -File .\setup_windows.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Test-Python {
    try { $v = & python --version 2>&1; return ($LASTEXITCODE -eq 0 -and "$v" -match "Python 3") }
    catch { return $false }
}

Write-Host "== 1/5 Verificando Python ==" -ForegroundColor Cyan
if (-not (Test-Python)) {
    Write-Host "Python nao encontrado. Instalando Python 3.12 via winget..."
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    # recarrega o PATH desta janela para enxergar o python recem-instalado
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Test-Python)) {
        Write-Host "Python instalado, mas esta janela ainda nao o enxerga." -ForegroundColor Yellow
        Write-Host "Feche o PowerShell, abra de novo e rode este script outra vez." -ForegroundColor Yellow
        Write-Host "Se persistir: Configuracoes > Aplicativos > Configuracoes avancadas > Aliases de execucao" -ForegroundColor Yellow
        Write-Host "e desligue python.exe / python3.exe (atalho da Microsoft Store)." -ForegroundColor Yellow
        exit 1
    }
}
python --version

Write-Host "== 2/5 Instalando dependencias ==" -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "== 3/5 Instalando navegador do Playwright ==" -ForegroundColor Cyan
python -m playwright install chromium

Write-Host "== 4/5 Criando banco ==" -ForegroundColor Cyan
$env:PYTHONPATH = "src"
python -m ecommerce_analyzer.cli init-db

Write-Host "== 5/5 Conferindo ==" -ForegroundColor Cyan
python -m ecommerce_analyzer.cli status

Write-Host ""
Write-Host "Pronto. Agora rode nesta pasta:  claude remote-control" -ForegroundColor Green
Write-Host "e abra a sessao nova no Chrome (claude.ai/code)." -ForegroundColor Green
