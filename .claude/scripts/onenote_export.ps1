# Export every page of a local OneNote notebook COPY to XML, then close it.
# Runs against .claude/data/onenote/<notebook> (a copy), never the
# archive original - OneNote may rewrite a notebook it opens.
param(
  [Parameter(Mandatory = $true)][string]$Notebook,
  [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force $Out | Out-Null
$on = New-Object -ComObject OneNote.Application
$id = ""
# cftNone = 0: open an existing notebook folder.
$on.OpenHierarchy($Notebook, "", [ref]$id, 0)
try {
  $hier = ""
  # Sections load asynchronously after OpenHierarchy: sync, then wait until
  # the page count stops growing (or ~3 minutes pass).
  try { $on.SyncHierarchy($id) } catch {}
  $last = -1; $stable = 0
  for ($t = 0; $t -lt 90; $t++) {
    Start-Sleep -Seconds 2
    # hsPages = 4
    $on.GetHierarchy($id, 4, [ref]$hier)
    $n = ([regex]::Matches($hier, "<one:Page ")).Count
    if ($n -gt 0 -and $n -eq $last) { $stable++ } else { $stable = 0 }
    if ($stable -ge 3) { break }
    $last = $n
  }
  [IO.File]::WriteAllText((Join-Path $Out "_hierarchy.xml"), $hier, [Text.Encoding]::UTF8)
  $doc = [xml]$hier
  $ns = New-Object Xml.XmlNamespaceManager($doc.NameTable)
  $ns.AddNamespace("one", $doc.DocumentElement.NamespaceURI)
  $pages = $doc.SelectNodes("//one:Page", $ns)
  $i = 0
  foreach ($p in $pages) {
    $i++
    $xml = ""
    try {
      # piBasic = 0 (text, no binary attachments)
      $on.GetPageContent($p.ID, [ref]$xml, 0)
      $name = "{0:D4}.xml" -f $i
      [IO.File]::WriteAllText((Join-Path $Out $name), $xml, [Text.Encoding]::UTF8)
    } catch {
      Write-Output ("failed page {0}: {1}" -f $p.name, $_.Exception.Message)
    }
  }
  Write-Output ("exported {0} pages" -f $i)
} finally {
  $on.CloseNotebook($id)
}
