$accessToken = $env:LI_ACCESS_TOKEN   # store it in env or Key Vault, not inline
$accessToken = "AQXkZenWLjnjcY-w6O6BOvz0fDcAziy8TidvMKV_x8fNxp44FkTS0bupg0O-3jlCpXpFi2BAEaQeKxMw8ewykegk-5TY8wV7O0tB76hR0FoWpxs4vi4-5agn2J9Q9jpgOABhdYRm9FyXVf0ca5gTPO9KQA3IzZ9-xJTwGthORSsfwTw4qtyjiYg0Kn_bhtfoIJW0zSi1knTqDkdgh80nLB8CFC4dMFTnFWOgKMjRAniR6hv1WQTDwGwhg6vQdhSXnDUCjua1efkV7rOQImInLHb6D6jtzlJUabKgYOQbmPM7NxPL7GbrF3pgn1qA9zPvfae4rsTaNH8y127QX-ix8-U4_-uobQ"



$orgId = "9462"                   # <-- your org id
$authorUrn = "urn:li:organization:$orgId"
$authorEncoded = [System.Uri]::EscapeDataString($authorUrn)

# IMPORTANT: q=author + X-RestLi-Method:FINDER are required for this finder. :contentReference[oaicite:1]{index=1}
$url = "https://api.linkedin.com/rest/posts?author=$authorEncoded&q=author&count=10&sortBy=LAST_MODIFIED"

$headers = @{
  "Authorization"              = "Bearer $accessToken"
  "X-Restli-Protocol-Version"  = "2.0.0"
  "Linkedin-Version"           = "202602"     # YYYYMM format :contentReference[oaicite:2]{index=2}
  "X-RestLi-Method"            = "FINDER"
}

Write-Host "Calling URL:`n$url`n"

Invoke-RestMethod -Method Get -Uri $url -Headers $headers


