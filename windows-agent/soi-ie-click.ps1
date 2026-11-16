# Tham do: tren man hinh dang mo trong IE, nhung gi nguoi dung bam duoc (the chuyen, muc cay, dong danh sach, lien ket).
# Chay khi IE dang mo dung man hinh can ghi:   powershell -NoProfile -Sta -ExecutionPolicy Bypass -File soi-ie-click.ps1
# Ket qua: Soi-ie-click.txt tren man hinh nen. Chi doc. So (3 chu so tro len) trong chu bi che thanh #.
$out = New-Object System.Collections.Generic.List[string]
function Log($t) { Write-Host $t; $out.Add($t) }
function Clean($t) { $s = ([string]$t) -replace '\s+', ' '; $s = $s.Trim(); $s = [regex]::Replace($s, '\d{3,}', '#'); if ($s.Length -gt 40) { $s = $s.Substring(0, 40) }; return $s }

function Visit($win, $path, $depth) {
    try {
        $doc = $win.document
        $all = $doc.getElementsByTagName('*')
        $n = [int]$all.length
        $counts = @{}; $hits = 0; $shown = 0
        Log "== khung '$path' ($n phan tu, trang '$(Clean $doc.title)')"
        $max = [Math]::Min($n, 4000)
        for ($i = 0; $i -lt $max; $i++) {
            $e = $all.item($i)
            $tag = [string]$e.tagName
            if ($tag -in 'SCRIPT','STYLE','HEAD','META','LINK','TITLE','HTML','BODY','TBODY','THEAD','BR','OPTION') { continue }
            $cursor = ''; try { $cursor = [string]$e.currentStyle.cursor } catch { }
            $hand = $cursor -in 'pointer','hand'
            $click = $false; try { $click = ($null -ne $e.onclick) } catch { }
            if ($tag -eq 'A' -or $hand -or $click) {
                $hits++
                if ($counts.ContainsKey($tag)) { $counts[$tag]++ } else { $counts[$tag] = 1 }
                if ($shown -lt 60) {
                    $shown++
                    $text = Clean $e.innerText
                    Log ("   {0,-6} id='{1}' lop='{2}' tay={3} onclick={4} chu='{5}'" -f $tag, $e.id, $e.className, $hand, $click, $text)
                }
            }
        }
        Log "   tong so phan tu bam duoc: $hits  ($(($counts.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ' '))"
        if ($depth -lt 6) {
            $c = [int]$win.frames.length
            for ($k = 0; $k -lt $c; $k++) { try { $f = $win.frames.item($k); Visit $f "$path/$([string]$f.name)" ($depth + 1) } catch { Log "   (khung $k khong doc duoc: $($_.Exception.Message))" } }
        }
    } catch { Log "   (loi doc khung '$path': $($_.Exception.Message))" }
}

$shell = New-Object -ComObject Shell.Application
$count = 0
foreach ($w in $shell.Windows()) {
    try { if ($w.FullName -notmatch 'iexplore') { continue }; $count++; Log "Cua so IE #$count"; Visit $w.Document.parentWindow 'top' 0 } catch { }
}
if ($count -eq 0) { Log "Khong thay cua so IE nao." }
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Soi-ie-click.txt'
[IO.File]::WriteAllLines($path, $out, (New-Object System.Text.UTF8Encoding($true)))
Write-Host "`nDa ghi vao $path. Gui file nay cho nhom phat trien."
