param(
    [switch]$UseSavedKey
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$port = 8000
$url = "http://127.0.0.1:$port/"
$healthUrl = "$url" + "api/health"
$defaultGeminiModel = "gemini-3.6-flash"
$keyDirectory = Join-Path $env:LOCALAPPDATA "PythonCodeReview"
$keyFile = Join-Path $keyDirectory "gemini-api-key.dpapi"
$client = [System.Net.Sockets.TcpClient]::new()
$portInUse = $false
try {
    $client.Connect("127.0.0.1", $port)
    $portInUse = $true
} catch [System.Net.Sockets.SocketException] {
} finally {
    $client.Dispose()
}

if ($portInUse) {
    try {
        $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 3 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Start-Process $url
            Write-Host "Python Code Review is already running. Opened $url"
            exit 0
        }
    } catch {
        throw "Port $port is occupied by another service. Close it before starting Python Code Review."
    }
    throw "Port $port is occupied by another service. Close it before starting Python Code Review."
}

Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($env:GEMINI_MODEL)) {
    $env:GEMINI_MODEL = $defaultGeminiModel
}
$secureKey = $null
if (Test-Path -LiteralPath $keyFile -PathType Leaf) {
    if ($UseSavedKey) {
        $encryptedKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
        $secureKey = ConvertTo-SecureString -String $encryptedKey
    } else {
        $keyChoice = Read-Host "A Gemini key is saved encrypted for this Windows account. Press Enter to use it, R to replace it, or D to delete it"
        if ([string]::IsNullOrWhiteSpace($keyChoice)) {
            $encryptedKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
            $secureKey = ConvertTo-SecureString -String $encryptedKey
        } elseif ($keyChoice -match "^[Rr]$") {
            $secureKey = Read-Host "Replacement Gemini API key (input is hidden)" -AsSecureString
            if ($secureKey.Length -eq 0) {
                $secureKey.Dispose()
                $encryptedKey = (Get-Content -LiteralPath $keyFile -Raw).Trim()
                $secureKey = ConvertTo-SecureString -String $encryptedKey
            } else {
                $encryptedKey = ConvertFrom-SecureString -SecureString $secureKey
                Set-Content -LiteralPath $keyFile -Value $encryptedKey -Encoding ASCII
                Write-Host "Encrypted Gemini key saved for this Windows account."
            }
        } elseif ($keyChoice -match "^[Dd]$") {
            Remove-Item -LiteralPath $keyFile
            Write-Host "Saved Gemini key deleted. AI corrections will be unavailable."
        } else {
            throw "Invalid choice. Enter R to replace the saved key or D to delete it."
        }
    }
} else {
    $secureKey = Read-Host "Gemini API key (input is hidden; leave blank to skip AI corrections)" -AsSecureString
    if ($secureKey.Length -gt 0) {
        $saveKey = Read-Host "Save this key encrypted for this Windows account for future launches? (Y/N)"
        if ($saveKey -match "^[Yy]$") {
            New-Item -ItemType Directory -Path $keyDirectory -Force | Out-Null
            $encryptedKey = ConvertFrom-SecureString -SecureString $secureKey
            Set-Content -LiteralPath $keyFile -Value $encryptedKey -Encoding ASCII
            Write-Host "Encrypted Gemini key saved for this Windows account."
        }
    }
}

if ($secureKey -and $secureKey.Length -gt 0) {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    try {
        $env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
}

$python = Get-Command python -ErrorAction SilentlyContinue
$pythonArguments = @()
if (-not $python) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    $pythonArguments = @("-3")
}
if (-not $python) {
    throw "Python 3 was not found. Install Python 3.10 or newer and try again."
}

$pythonExecutable = & $python.Source @pythonArguments -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0 -or -not $pythonExecutable) {
    throw "Could not locate the Python interpreter. Check your Python installation and try again."
}
$pythonExecutable = ($pythonExecutable | Select-Object -Last 1).Trim()
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "The Python interpreter path does not exist: $pythonExecutable"
}

$serverProcess = $null
try {
    $serverProcess = Start-Process `
        -FilePath $pythonExecutable `
        -ArgumentList "web_app.py" `
        -WorkingDirectory $PSScriptRoot `
        -PassThru `
        -NoNewWindow

    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $ready = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($serverProcess.HasExited) {
            throw "The Python server exited during startup (exit code $($serverProcess.ExitCode)). Check the error above."
        }

        try {
            $response = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 2 -UseBasicParsing
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) {
        throw "The server did not respond at $healthUrl within 45 seconds. Check the Python error above."
    }

    Write-Host "Python Code Review is ready at $url"
    Start-Process $url
    Write-Host "Keep this window open while using the website. Press Ctrl+C here to stop the server."
    Wait-Process -Id $serverProcess.Id
} finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id
    }
    Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
    if ($secureKey) {
        $secureKey.Dispose()
    }
}
