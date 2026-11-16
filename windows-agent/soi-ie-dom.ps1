# Tham do: agent co doc duoc trang trong Internet Explorer (ban cu) qua COM khong. Chi DOC, khong ghi gia tri o nhap.
# Chay: mo IE vao trang can ghi, roi:   powershell -NoProfile -ExecutionPolicy Bypass -File soi-ie-dom.ps1
# Ket qua ghi vao Soi-ie-dom.txt tren man hinh nen.
$out = New-Object System.Collections.Generic.List[string]
function Log($t) { Write-Host $t; $out.Add($t) }

function Describe-Doc($doc, $indent) {
    try {
        $url = $doc.location.href; $title = $doc.title
        Log "$indent- trang: '$title'  url(chi may chu): $(([uri]$url).Host)  che_do_tai_lieu: $($doc.documentMode)"
        $kinds = @{}
        foreach ($e in $doc.getElementsByTagName('*')) { $k = $e.tagName; if ($kinds.ContainsKey($k)) { $kinds[$k]++ } else { $kinds[$k] = 1 } }
        Log "$indent  so_the: $(($kinds.GetEnumerator() | Where-Object { $_.Key -in 'INPUT','BUTTON','SELECT','TEXTAREA','A','FORM','TABLE','IFRAME','FRAME','OBJECT','APPLET','EMBED' } | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' ')"
        $n = 0
        foreach ($e in $doc.getElementsByTagName('input')) {
            if ($n -ge 25) { break }; $n++
            $type = $e.type
            Log "$indent  o nhap: type=$type id='$($e.id)' name='$($e.name)'"   # khong in value
        }
        foreach ($e in $doc.getElementsByTagName('button')) { Log "$indent  nut: id='$($e.id)' chu='$($e.innerText)'" }
        foreach ($e in $doc.getElementsByTagName('object')) { Log "$indent  OBJECT: classid='$($e.classid)' type='$($e.type)'" }
        foreach ($e in $doc.getElementsByTagName('applet')) { Log "$indent  APPLET: code='$($e.code)'" }
        $frames = $doc.getElementsByTagName('iframe'); $count = @($frames).Count
        foreach ($f in $frames) {
            try { Describe-Doc $f.contentWindow.document "$indent    " } catch { Log "$indent    (khong doc duoc iframe: $($_.Exception.Message))" }
        }
    } catch { Log "$indent  (loi doc trang: $($_.Exception.Message))" }
}

Log "Thoi gian: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  PowerShell $($PSVersionTable.PSVersion)  $(if ([Environment]::Is64BitProcess) {'64-bit'} else {'32-bit'})"
try { $shell = New-Object -ComObject Shell.Application } catch { Log "Khong tao duoc Shell.Application: $($_.Exception.Message)"; $shell = $null }
$count = 0
if ($shell) {
    foreach ($w in $shell.Windows()) {
        $name = ''; try { $name = $w.FullName } catch {}
        if ($name -notmatch 'iexplore') { continue }
        $count++
        Log "Cua so IE #$count : '$($w.LocationName)'"
        Describe-Doc $w.Document '  '
    }
}
Log "Tong so cua so IE doc duoc: $count"
if ($count -eq 0) { Log "KHONG doc duoc cua so IE nao. Co the do chinh sach may, hoac trang mo bang Edge che do IE (khong phai iexplore.exe)." }
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Soi-ie-dom.txt'
[IO.File]::WriteAllLines($path, $out, (New-Object System.Text.UTF8Encoding($true)))
Write-Host "`nDa ghi vao $path. Gui file nay cho nhom phat trien."
