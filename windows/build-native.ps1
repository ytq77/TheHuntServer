param([string]$Toolchain = 'C:\bbsc-dev\msys64\clang64')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PATH = (Join-Path $Toolchain 'bin') + ';' + $env:PATH
$env:WIN_SERVER_TOOLCHAIN = $Toolchain
$env:PYTHONUTF8 = '1'
$python = Join-Path $Toolchain 'bin\python.exe'
$cmake = Join-Path $Toolchain 'bin\cmake.exe'
& $python -B -m unittest discover -s . -p test_summon_poll.py -v
if ($LASTEXITCODE) { throw 'Seamless-only summon polling checks failed.' }
& $python ./prepare-sources.py
if ($LASTEXITCODE) { throw 'Source preparation failed.' }
& $cmake -S ./src -B ./build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ "-DCMAKE_PREFIX_PATH=$($Toolchain.Replace('\','/'))" -DBUILD_TESTING=ON "-DFETCHCONTENT_SOURCE_DIR_ABSL=$($PSScriptRoot.Replace('\','/'))/src/externals/abseil-cpp" -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DABSL_PROPAGATE_CXX_STD=ON
if ($LASTEXITCODE) { throw 'CMake configure failed.' }
& $cmake --build ./build --target shadnet shadnet-sample shadnet-admin test_bloodborne_summon_broker --parallel 6
if ($LASTEXITCODE) { throw 'Native build failed.' }
& (Join-Path $Toolchain 'bin\ctest.exe') --test-dir ./build --output-on-failure
if ($LASTEXITCODE) { throw 'Upstream tests failed.' }
& ./build-gui.ps1
if ($LASTEXITCODE) { throw 'Desktop manager build failed.' }
& $python ./test_apply_update.py
if ($LASTEXITCODE) { throw 'Automatic update preservation and rollback checks failed.' }
& $python ./package.py
if ($LASTEXITCODE) { throw 'Runtime packaging failed.' }
& $python ./smoke-test.py
if ($LASTEXITCODE) { throw 'Packed runtime smoke test failed.' }
& $python ./check-local-login.py
if ($LASTEXITCODE) { throw 'Same-PC game login check failed.' }
& $python ./test-manager.py
if ($LASTEXITCODE) { throw 'Desktop manager integration checks failed.' }
$packageFolder = & $python -c 'from build_config import OUT; print(OUT)'
if ($LASTEXITCODE) { throw 'Package path lookup failed.' }
Copy-Item -LiteralPath ./smoke-results.json -Destination (Join-Path $packageFolder 'LOCAL-VALIDATION.json')
Copy-Item -LiteralPath ./manager-results.json -Destination (Join-Path $packageFolder 'LOCAL-MANAGER-VALIDATION.json')
& $python ./package.py --zip
if ($LASTEXITCODE) { throw 'ZIP packaging failed.' }
