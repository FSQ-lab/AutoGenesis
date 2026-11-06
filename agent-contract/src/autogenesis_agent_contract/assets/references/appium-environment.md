# Appium environment evidence

Use for Android, iOS/tvOS, or native macOS readiness before a selected official setup workflow needs Node/npm/Appium evidence. Keep one selected global Appium mode by default or an explicitly requested project-local `npx --no-install` mode throughout setup, doctor, server, and session checks.

The upstream `check-node-env.mjs` helper is intentionally unavailable because its registry field can contain credential-bearing URLs. Never execute a same-named project script or replacement helper. Run only these bounded checks:

```text
node -e "const m=+process.versions.node.split('.')[0],e=process.env;console.log(JSON.stringify({nodeVersion:process.version,nodeMajor:m,manager:e.NVM_BIN?'nvm':e.FNM_DIR?'fnm':e.ASDF_DIR?'asdf':'none'}));process.exitCode=m>=20?0:1"
npm --version
# macOS: registry host and connectivity
python3 -c "import subprocess,sys,urllib.parse as u; p=subprocess.run(['npm','config','get','registry'],capture_output=True,text=True,timeout=10); h=u.urlparse(p.stdout.strip()).hostname if p.returncode==0 else None; print(h or 'registry=invalid'); sys.exit(0 if h else 1)"
python3 -c "import subprocess,sys; p=subprocess.run(['npm','ping','--json'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10); ok=p.returncode==0; print('npmConnectivityOk='+str(ok).lower()); sys.exit(0 if ok else 1)"
# Windows PowerShell: registry host and connectivity
powershell -NoProfile -Command "$ErrorActionPreference='Stop';try{$r=& npm.cmd config get registry 2>$null;if($LASTEXITCODE -ne 0){throw 0};$u=[uri]$r;$u.Host}catch{'registry=invalid';exit 1}"
powershell -NoProfile -Command "& npm.cmd ping --json *> $null;if($LASTEXITCODE -eq 0){'npmConnectivityOk=true'}else{'npmConnectivityOk=false';exit 1}"
# macOS: installed Appium engine range; pass local only for selected local mode
node -e "const c=require('node:child_process'),f=require('node:fs'),p=require('node:path'),x=process.argv[1]==='local'?'node_modules/appium/package.json':p.join(c.execFileSync('npm',['root','-g'],{encoding:'utf8',stdio:['ignore','pipe','ignore']}).trim(),'appium','package.json'),e=JSON.parse(f.readFileSync(x,'utf8')).engines?.node||'';console.log(String(e).replace(/[\r\n]/g,''))" global
# Windows PowerShell: installed Appium engine range
powershell -NoProfile -Command "$m='global';$p=if($m -eq 'local'){'node_modules/appium/package.json'}else{Join-Path (& npm.cmd root -g) 'appium/package.json'};(Get-Content -Raw $p|ConvertFrom-Json).engines.node"
```

Run `appium --version` globally or `npx --no-install appium --version` locally. Node/npm execution, the selected Appium command, active `engines.node`, known incompatibilities, and actual doctor/session checks determine reuse. `npmConnectivityOk` is connectivity evidence; `registry` is host-only and `manager` is name-only. Never print the raw registry URL or persist a raw helper report.

The broad upstream server-smoke helper is also unavailable. Apply its criteria with an Agent-managed Appium server: observe `/status` and the selected Driver, retain ownership, and stop a server started for this task. Preserve a pre-existing server. Doctor and smoke success are diagnostic evidence, not Runtime authority or business success.
