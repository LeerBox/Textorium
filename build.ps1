<#
.SYNOPSIS
  LeerBox Text Art Studio 3.0 build script (Windows PowerShell 5.1+ / PowerShell 7).
.EXAMPLE
  .\build.ps1            # fonts + standalone .py + .html + tests
  .\build.ps1 exe        # also the Windows EXE (needs: pip install -r requirements-dev.txt)
  .\build.ps1 html       # only the single-file HTML edition
  .\build.ps1 strict     # rebuild with only explicitly licensed fonts
#>
param([ValidateSet('all','exe','html','python','fonts','test','strict')][string]$Target = 'all')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Step($name, [scriptblock]$cmd) { Write-Host "==> $name" -ForegroundColor Cyan; & $cmd; if ($LASTEXITCODE -ne 0) { throw "$name failed ($LASTEXITCODE)" } }
if ($Target -in 'all','fonts','strict') {
  $tier = if ($Target -eq 'strict') { 'clear' } else { 'all' }
  Step 'Font pack' { python tools/build_fonts.py --license-tier $tier }
  Step 'Mono atlas' { python tools/build_atlas.py }
  Step 'Glyph coverage masks' { python tools/build_glyphs.py }
  Step 'License notices' { python tools/build_licenses.py }
}
if ($Target -in 'all','python','exe','strict') { Step 'Standalone Python script' { python tools/build_python.py } }
if ($Target -in 'all','html','exe','strict') { Step 'Single-file HTML' { python tools/build_html.py } }
if ($Target -eq 'exe') { Step 'Windows EXE (PyInstaller)' { python tools/build_exe.py } }
if ($Target -in 'all','test') {
  Step 'Golden fixtures' { python tools/gen_golden.py }
  Step 'Image Studio fixtures' { python tools/gen_image_golden.py --codecs }
  Step 'JS tests' { node tests/js/run_tests.js }
  Step 'Tests' { Push-Location tests; python -m pytest -q; $code = $LASTEXITCODE; Pop-Location; $global:LASTEXITCODE = $code }
}
Write-Host 'Done.' -ForegroundColor Green
