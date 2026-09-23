# Literature search with Paperclip

Paperclip is the lab's literature tool: a virtual filesystem over ~3.4M
full-text papers (PMC, bioRxiv, medRxiv, arXiv) plus FDA documents, clinical
trials, proteins and GEO. It is installed at `~/.local/bin/paperclip` and is
already signed in. **Full text with stable line numbers is what makes it
different from a web search** — it is why a protocol generated here can cite
the exact line a condition came from, and why a missing condition can be proven
missing rather than guessed at.

Run `paperclip skill` once per session for the complete, current command guide.
What follows is the part this lab uses.

## The search that matters

```bash
paperclip search -s pmc,biorxiv,medrxiv "mammalian acoustic reporter genes gas vesicle" -n 15
```

`-s` is required. Useful flags:

| Flag | Why |
|---|---|
| `-s pmc,biorxiv,medrxiv` | Published + preprints. This lab's field moves in preprints; do not search PMC alone. |
| `--also "<phrasing>"` | Repeatable. Fan out synonyms (`--also "ARG ultrasound imaging"`) — pools are fused and reranked. |
| `--since 2023` | Recency, when the question is about current practice. |
| `--author "Shapiro"` | The lab's own prior art. Do this for nearly every question. |
| `-n 15` | More candidates before filtering. |

Then read rather than trust the snippet:

```bash
paperclip cat /papers/<id>/content.lines --lines 30-45   # line-numbered full text
paperclip grep "imidazole" /papers/<id>/content.lines    # find a condition in one paper
paperclip scan /papers/<id>/content.lines "dialysis" "OD500"
paperclip ask-image /papers/<id>/figures/<fig> "what pressure was used?"
```

Across many papers at once:

```bash
paperclip search -s pmc,biorxiv "GV collapse pressure" -n 10      # note the [s_xxxx] result id
paperclip map --from s_xxxx "what collapse pressure and probe did they use?"
paperclip reduce --from s_xxxx "table of pressures by GV type" --strategy table
```

`grep` wants a **file**, not a document directory: `grep ... /papers/<id>/`
fails with `Cannot read path`. Always grep `content.lines`.

Corpus-wide exact text, when a name or accession must be found:

```bash
paperclip grep "Ana GvpA" /papers/
```

## Papers the user supplies

If the user hands you a PDF, put it in the clipboard so it gets the same
line-numbered treatment, and cite it the same way:

```bash
paperclip cp ~/Desktop/their_paper.pdf /clipboard/shapiro-refs/
paperclip search "<question>" -s clipboard/shapiro-refs
paperclip grep "buffer" /clipboard/shapiro-refs/<id>/content.lines
```

The clipboard is private to this account. It is still an upload to an external
service — **ask before uploading anything unpublished**, and never upload the
lab's own `Protocols/` folder or raw data. Unpublished work stays in the local
protocol index (`index_protocols.py`), which never leaves the machine.

## When the user supplies no paper

Search. Do not answer from memory. The rule for this advisor is that any
condition, parameter or claim that reaches the user is traceable to a line in a
document — the lab's protocol index, a Paperclip document, or a prior run —
or is explicitly flagged as unknown.

## Citations

Cite inline as `[1]`, `[2]` — never `[1, L45]` or `(L45)`. End with:

```
--------
REFERENCES
[1] Authors. "Title." *Journal* vol, pages (year). doi:XX
    https://paperclip.gxl.ai/citations/papers/<doc_id>#L<n>
```

Line numbers come from the `L<n>` prefixes in `content.lines`; `#L45-L52` for a
range, `#L45,L120` for several. Get authors/title/DOI from
`paperclip cat /papers/<id>/meta.json`. Never put a doc_id in prose.

In a **protocol**, a citation is additionally tagged on the line it justifies
(`[CITE: 1]`), so the linter can check it — see `protocol-format.md`.

## Repos are off by default

Do not run `paperclip repo`/`git init`, add papers to a repo, or commit claims
unless the user explicitly asks for a cited repo or claim verification. If a
command prints a leftover `[repo: <name>]` banner from an earlier task, ignore
it. Cite directly instead.

For a systematic review or a quantitative meta-analysis — and only then —
load the dedicated workflow first:

```bash
paperclip routines show paperclip-meta-analysis
```
