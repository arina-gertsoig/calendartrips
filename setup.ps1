Write-Host ""
Write-Host "=== Налаштування Travel Agent ===" -ForegroundColor Cyan
Write-Host ""

# Step 1: Install dependencies
Write-Host "1. Встановлюю бібліотеки..." -ForegroundColor Yellow
pip install -r requirements.txt
Write-Host ""

# Step 2: Create .env
if (-Not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "2. Створив файл .env" -ForegroundColor Green
} else {
    Write-Host "2. Файл .env вже існує" -ForegroundColor Green
}

# Step 3: Ask for API key
Write-Host ""
$key = Read-Host "3. Встав свій Anthropic API ключ (з console.anthropic.com)"
(Get-Content ".env") -replace "your_anthropic_api_key_here", $key | Set-Content ".env"
Write-Host "   Ключ збережено!" -ForegroundColor Green

# Step 4: Check for credentials.json
Write-Host ""
if (Test-Path "credentials.json") {
    Write-Host "4. credentials.json знайдено!" -ForegroundColor Green
} else {
    Write-Host "4. credentials.json НЕ знайдено!" -ForegroundColor Red
    Write-Host "   Скачай його з Google Cloud Console та поклади в цю папку:" -ForegroundColor Yellow
    Write-Host "   $(Get-Location)" -ForegroundColor White
    Write-Host ""
    Write-Host "   Після того як покладеш файл — запусти:" -ForegroundColor Yellow
    Write-Host "   python agent.py --days 30" -ForegroundColor White
    exit
}

Write-Host ""
Write-Host "=== Все готово! Запускаю агента... ===" -ForegroundColor Cyan
Write-Host ""
python agent.py --days 30
