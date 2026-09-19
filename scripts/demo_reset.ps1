# Restart the API against a pristine store, so a capture run exercises real first use.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*uvicorn*dronebench*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
$root = "C:\Users\shash\Downloads\AITX-Hackathon"
Remove-Item -Recurse -Force "$root\artifacts\demo" -ErrorAction SilentlyContinue
$env:PYTHONPATH = "packages/contracts;packages/graph;packages/recommend;packages/workflow;apps/api"
$env:DRONEBENCH_ROOT = "artifacts/demo"
Set-Location $root
Start-Process -WindowStyle Hidden -FilePath "python" `
  -ArgumentList "-m","uvicorn","dronebench_api.main:app","--host","127.0.0.1","--port","8000","--log-level","warning"
Start-Sleep -Seconds 5
(Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8000/api/designs").Content
