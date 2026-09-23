# Allow the iPhone/Watch Quick Capture Shortcut to reach the local dev server
# over Tailscale. Run in an ELEVATED PowerShell (Start menu -> PowerShell ->
# right-click -> "Run as administrator").
#
# Security: the allow rule is scoped to the Tailscale CGNAT range
# (100.64.0.0/10), so ONLY devices on your tailnet can reach port 3000.
# Nothing is opened to the public internet or to untrusted Wi-Fi.

Write-Host "=== Inbound BLOCK rules that could affect TCP 3000 ===" -ForegroundColor Cyan
Get-NetFirewallRule -Direction Inbound -Enabled True -Action Block |
  ForEach-Object {
    $pf = $_ | Get-NetFirewallPortFilter
    if ($pf.Protocol -eq 'TCP' -and ($pf.LocalPort -eq '3000' -or $pf.LocalPort -eq 'Any')) {
      [PSCustomObject]@{ Name = $_.DisplayName; Profile = $_.Profile; LocalPort = $pf.LocalPort }
    }
  } | Format-Table -AutoSize

Write-Host "=== Creating scoped allow rule (Tailscale peers only) ===" -ForegroundColor Cyan
$existing = Get-NetFirewallRule -DisplayName "Second Brain capture (Tailscale)" -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Rule already exists - leaving it in place."
} else {
  New-NetFirewallRule `
    -DisplayName "Second Brain capture (Tailscale)" `
    -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow `
    -RemoteAddress 100.64.0.0/10 -Profile Any | Out-Null
  Write-Host "Allow rule created." -ForegroundColor Green
}
