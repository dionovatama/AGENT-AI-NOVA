# Tes end-to-end Phase 5 lewat Agent asli. PowerShell 7+.
#
#   .\lab_e2e.ps1 -Step setup -RouterHost 192.168.7.5 -Fingerprint 2DA0A03F...  (sekali)
#   .\lab_e2e.ps1 -Step call                                                    (berulang)
#   .\lab_e2e.ps1 -Step call -Tool mikrotik.interface_status
#
# Password diminta lewat prompt tersembunyi. State (id saja, tanpa rahasia) disimpan
# di .\e2e_state.json.
param(
    [Parameter(Mandatory)][ValidateSet("setup", "call")][string]$Step,
    [string]$BaseUrl = "http://localhost:8000",
    [string]$Email = "lab@example.com",
    [string]$RouterHost = "192.168.7.5",
    [string]$RouterUser = "nova",
    [string]$Fingerprint,
    [string]$Tool = "mikrotik.system_resource"
)
$ErrorActionPreference = "Stop"
$state = Join-Path $PSScriptRoot "e2e_state.json"

function Read-Plain([string]$prompt) {
    ConvertFrom-SecureString -AsPlainText (Read-Host $prompt -AsSecureString)
}

function Invoke-Api($method, $path, $body = $null, $token = $null) {
    $h = @{}
    if ($token) { $h["Authorization"] = "Bearer $token" }
    $args = @{ Method = $method; Uri = "$BaseUrl$path"; Headers = $h; ContentType = "application/json" }
    if ($body) { $args["Body"] = ($body | ConvertTo-Json -Depth 6) }
    try { Invoke-RestMethod @args }
    catch {
        $detail = $_.ErrorDetails.Message
        throw "API $method $path gagal: $($_.Exception.Message) $detail"
    }
}

function Get-NovaToken {
    $pw = Read-Plain "Password akun NOVA ($Email)"
    try { Invoke-Api POST "/auth/register" @{ email = $Email; password = $pw } | Out-Null } catch { }  # sudah ada: abaikan
    (Invoke-Api POST "/auth/login" @{ email = $Email; password = $pw }).access_token
}

if ($Step -eq "setup") {
    if (-not $Fingerprint) { throw "-Fingerprint wajib (SHA-256 cert nova-api)" }
    $token = Get-NovaToken
    $suffix = Get-Date -Format "HHmmss"

    $agent = Invoke-Api POST "/agents" @{ name = "lab-agent-$suffix" } $token
    $routerPw = Read-Plain "Password RouterOS user $RouterUser"
    $cred = Invoke-Api POST "/credentials" @{ name = "lab-router-$suffix"; type = "password"; secret_reference = $routerPw } $token
    $dev = Invoke-Api POST "/devices" @{
        name = "lab-chr-$suffix"; platform = "mikrotik"; host = $RouterHost; port = 8729
        connection_type = "api-ssl"; credential_id = $cred.id; metadata = @{ username = $RouterUser }
    } $token
    $target = Invoke-Api POST "/agents/$($agent.id)/targets" @{
        name = "lab-chr"; host = $RouterHost; ports = @(8729)
        device_id = $dev.id; tls_fingerprint = $Fingerprint
    } $token

    @{ agent_id = $agent.id; device_id = $dev.id; target_id = $target.id } | ConvertTo-Json | Set-Content $state

    Write-Host "`n=== AGENT (token tampil SEKALI, simpan sekarang) ===" -ForegroundColor Yellow
    Write-Host "agent_id : $($agent.id)"
    Write-Host "token    : $($agent.token)"
    Write-Host "`n=== Tambahkan ke config.json Agent (kunci relay_targets) ===" -ForegroundColor Yellow
    @{ relay_targets = @($target.agent_config) } | ConvertTo-Json -Depth 5
    Write-Host "`nLangkah Agent:"
    Write-Host "  nova-agent init --server-url $BaseUrl --agent-id $($agent.id) --allow-insecure   (token lewat prompt)"
    Write-Host "  edit config.json: tambah relay_targets di atas, lalu  nova-agent run"
    Write-Host "  cek: GET /agents harus 'online', lalu jalankan:  .\lab_e2e.ps1 -Step call"
}
else {
    if (-not (Test-Path $state)) { throw "Jalankan -Step setup dulu." }
    $s = Get-Content $state | ConvertFrom-Json
    $token = Get-NovaToken
    $a = Invoke-Api GET "/agents/$($s.agent_id)" $null $token
    Write-Host "Agent status: $($a.status)"
    if ($a.status -ne "online") { Write-Warning "Agent belum online; relay akan ditolak (AgentOffline)." }
    $r = Invoke-Api POST "/tools/execute" @{ tool_name = $Tool; arguments = @{}; device_id = $s.device_id } $token
    $r | ConvertTo-Json -Depth 8
}
