$accessToken = $env:LI_ACCESS_TOKEN   # store it in env or Key Vault, not inline
$accessToken = "AQWybr0H6rOoCpW_U3rkTGf-t9vLXKsW0YsHO3_05BJ0YNgyttCc-7JRLtLcK5K0u_zp30hVy1j-aJAXXMpvN2W7_X7wd08P2HM8RAzlx2c72OBkOygcYSeBI0wXSLxiEiwNRRuW4zsXgPRww-ytyWDba8afCIpobKFjeriZm264SzQ2Sn-xxWOjR5IKzTZR7wCExjqf3dF2-SK4krvEX5arX5T9rLT0EQnkzo-Ry3HDe_EfPlDcl1i6r6G_gU9py4qF5NGtEDU-9kkXGVWyzWNHV-xskrcSZWkRuTy1NZMDcWcrICtJkUJRXzDRdlOTVtQX-mmQTz_dVKUzKyJakmSK7FW9VA"


$orgId = "9462"                   # <-- your org id
$authorUrn = "urn:li:organization:$orgId"
$authorEncoded = [System.Uri]::EscapeDataString($authorUrn)

# IMPORTANT: q=author + X-RestLi-Method:FINDER are required for this finder. :contentReference[oaicite:1]{index=1}
$url = "https://api.linkedin.com/rest/posts?author=$authorEncoded&q=author&count=10&sortBy=LAST_MODIFIED"

$headers = @{
  "Authorization"              = "Bearer $accessToken"
  "X-Restli-Protocol-Version"  = "2.0.0"
  "Linkedin-Version"           = "202601"     # YYYYMM format :contentReference[oaicite:2]{index=2}
  "X-RestLi-Method"            = "FINDER"
}

Write-Host "Calling URL:`n$url`n"

Invoke-RestMethod -Method Get -Uri $url -Headers $headers

