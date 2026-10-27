$ErrorActionPreference = "Stop"

$baseUrl = "http://127.0.0.1:8766"
$userId = "dify-verification-user"

$health = Invoke-RestMethod "$baseUrl/health"
if ($health.status -ne "ok") {
    throw "Bridge is not healthy"
}

$resetBody = @{ user_id = $userId } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/reset" -ContentType "application/json" -Body $resetBody | Out-Null

$initialBody = @{ user_id = $userId; move = "START" } | ConvertTo-Json
$initial = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/recall" -ContentType "application/json" -Body $initialBody

$rememberBody = @{
    user_id = $userId
    move = "让一只茶壶宣布竞选市长"
    story = "午夜旅行社的登记台变成竞选舞台，茶壶承诺为每只鸽子提供免费茉莉花茶。"
    turn_id = "manual-verification-turn-1"
} | ConvertTo-Json
$saved = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/remember" -ContentType "application/json" -Body $rememberBody

$recallBody = @{ user_id = $userId; move = "茶壶市长为什么还在追着我" } | ConvertTo-Json
$recalled = Invoke-RestMethod -Method Post -Uri "$baseUrl/v1/recall" -ContentType "application/json" -Body $recallBody

if ($saved.status -ne "saved" -and $saved.status -ne "already_saved") {
    throw "Story memory was not saved"
}
if ($recalled.memory_context -notmatch "茶壶") {
    throw "PowerContext did not recall the tea-pot choice"
}

Write-Output "health=$($health.status)"
Write-Output "initial_turns=$($initial.turn_count)"
Write-Output "save_status=$($saved.status)"
Write-Output "recalled_turns=$($recalled.turn_count)"
Write-Output "memory_context=$($recalled.memory_context)"
