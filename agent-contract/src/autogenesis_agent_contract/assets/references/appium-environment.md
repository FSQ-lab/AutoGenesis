# Appium environment evidence

Use only for an Android, iOS/tvOS, or native macOS route needing Node/npm/Appium evidence. Keep one selected global Appium mode by default or an explicitly requested project-local `npx --no-install` mode throughout setup, doctor, server, MCP, and session checks.

## Discover and select

Record configured, detected, selected, and rejected candidates with origin and bounded reason. Consider the current task PATH, active version-manager environment, installed package-manager locations, and conventional user installations. Consider project `node_modules` only for explicit local mode. Do not run shell initialization files merely to discover a candidate.

For every considered Node candidate execute its exact `node` binary, obtain `process.execPath` and `process.version`, pair it with that installation's npm, and locate the selected Appium entrypoint/package metadata. Read active Appium `engines.node` and applicable peer constraints. A version outside a tested list is not rejected when constraints and observed checks permit it. A command name, manager name, PATH entry, directory, or lock-file mention is not capability evidence.

Use the selected Node bin, Appium entrypoint, backend mode, and `APPIUM_HOME` as one temporary task environment for official environment checks, Driver commands, doctor, server, and live session. Do not validate global Appium then execute a local copy, or silently change Appium home. Persist PATH or manager selection only as an approved change.

The authenticated upstream `check-node-env.mjs` helper is intentionally unavailable because its registry field may contain credential-bearing URLs. Never execute a same-named project script or replacement helper. Run only these bounded checks:

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

`npmConnectivityOk` is connectivity evidence; `registry` is host-only and `manager` is name-only. Never print the raw registry URL, npm token, config file, full environment, or raw helper report.

Run the selected Appium `--version`, authenticated official Driver inventory/doctor steps, and route-specific bounded server criteria. Apply server criteria with an Agent-managed process: retain ownership, observe `/status` and selected Driver, stop a server started for this task, and preserve a matching pre-existing server. Doctor and status are dependency evidence, not MCP authority, target readiness, or business success.

Install or switch Node/Appium only after every relevant existing candidate is unusable, explicitly excluded by active constraints, or proven incompatible. The repair plan identifies exact backend, source/version, install location, selected Appium home, persistence, consequences, rollback, and affected checks. Rerun only those checks after approval.

Return the shared readiness result. Keep registry credentials, raw URLs, local paths, and unbounded stdout/stderr out of durable evidence.
