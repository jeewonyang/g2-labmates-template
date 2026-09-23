# Quick Capture from iPhone & Apple Watch

Capture a thought on the go and have it land in your Second Brain **Inbox**,
ready to triage into a Task / Note / Resource from the web app.

This uses **Apple Shortcuts** (no Mac, no Xcode, no App Store) posting to the
existing [`POST /api/capture`](CAPTURE_API.md) endpoint, reached over
**Tailscale** (a private mesh VPN — nothing is exposed to the public internet).

```
iPhone/Watch Shortcut ──HTTPS/POST──▶ Tailscale serve ──▶ localhost:3000 ──▶ /api/capture ──▶ Inbox
```

We reach the local server with **`tailscale serve`**, which proxies the tunnel
straight into `localhost:3000`. This is what makes it work despite Windows
Firewall blocking inbound connections: the Tailscale daemon (already running and
permitted) terminates the connection and forwards it to loopback, so no firewall
rule or `-H 0.0.0.0` binding is needed. It also gives you real HTTPS.

---

## One-time setup

### 1. Server: set a capture token

Add a long random token to `.env` (this file is gitignored — never commit it):

```
CAPTURE_API_TOKEN="<paste the token you generated>"
```

Generate one anytime with PowerShell:

```powershell
$b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); "sb_" + [Convert]::ToBase64String($b).Replace('+','').Replace('/','').Replace('=','')
```

You'll paste this same value into the Shortcut in step 4. Rotate it by changing
both places.

### 2. Server: just run it normally

The regular server on `localhost:3000` is all you need — start it however you
normally do (the desktop shortcut, or `npm run dev`). Because `tailscale serve`
(step 3) forwards to loopback, you do **not** need `dev:remote`, a firewall
rule, or `-H 0.0.0.0`.

```powershell
$env:Path = "$env:LOCALAPPDATA\Programs\nodejs;$env:Path"   # if `node` doesn't resolve
npm run dev
```

### 3. Tailscale: connect the devices and expose the server over the tunnel

1. Install Tailscale on your **PC** (https://tailscale.com/download/windows) and
   sign in.
2. Install the **Tailscale** app on your **iPhone** from the App Store and sign
   in with the **same account**, and make sure the VPN toggle is ON. (The Watch
   piggybacks on the iPhone's connection — no separate Watch install needed.)
3. On the PC, proxy the local server onto your tailnet (one-time; persists across
   reboots):

   ```powershell
   & "C:\Program Files\Tailscale\tailscale.exe" serve --bg 3000
   ```

   The first time, this may ask you to enable **serve / HTTPS certificates** for
   your tailnet — follow the printed link and click enable. Confirm it's running
   with `tailscale serve status`.

Your capture URL is then your machine's tailnet HTTPS name (find it with
`tailscale status --json`), e.g.:

```
https://your-machine.your-tailnet.ts.net/api/capture
```

> **Note:** you can't test this URL from the PC itself — Tailscale doesn't route
> a machine to its own tailnet name ("hairpin"). Test from the iPhone: open the
> base URL (`https://your-machine.your-tailnet.ts.net`) in Safari; it should load the
> dashboard. To disable the proxy later: `tailscale serve --https=443 off`.

### 4. Build the Shortcut (on iPhone)

This happens in Apple's built-in **Shortcuts** app (pre-installed; if missing,
re-download "Shortcuts" by Apple from the App Store). No coding — a Shortcut is
a stack of actions you assemble by searching and tapping.

Open **Shortcuts** → **Shortcuts** tab → **+** (top right). Tap the title at the
top → **Rename** → **"Quick Capture"**. Then add two actions (use the search bar
at the bottom to find each by name):

1. **Ask for Input**
   - Leave type as **Text**.
   - Prompt: `What's on your mind?`
   - (Optional) expand the action and turn on **Allow Multiple Lines**.

2. **Get Contents of URL**
   - URL: `https://your-machine.your-tailnet.ts.net/api/capture`  ← your tailnet name
   - Tap the small arrow / **Show More** to expand:
     - Method: **POST**
     - Headers → **Add new header**:
       - Key `Authorization` → Value `Bearer <YOUR_TOKEN>`
         (the word `Bearer`, a space, then the token — all in the Value field)
     - Request Body: **JSON** → **Add new field**, twice:
       - **Text** field, key `rawText` → for the value, tap the field and pick
         the **Provided Input** magic variable (it appears in the bar above the
         keyboard, or via **Select Variable**). Do NOT type the words.
       - **Text** field, key `source` → value `siri_shortcut` (typed literally).
   - Choosing Body = JSON sets `Content-Type: application/json` automatically
     and escapes quotes/newlines in your note correctly.

3. **(Optional) Show Notification** — Body: `Captured ✓`. On the Watch a haptic
   is enough.

Tap **Done**. Run it once from inside the app: type a test note, **Allow** the
network permission prompt the first time, and check the item shows up on the
web **Inbox** page.

---

## Trigger it from anywhere

Once the Shortcut works, wire up fast entry points (Settings are in the
Shortcuts app / iOS Settings):

- **Siri:** "Hey Siri, Quick Capture" → dictate → done. Works on the Watch too.
- **Home Screen icon:** Shortcut ⋯ → **Add to Home Screen**.
- **Lock Screen widget:** Lock Screen → Customize → add a **Shortcuts** widget →
  pick Quick Capture. One tap from locked.
- **Back Tap:** Settings → Accessibility → Touch → **Back Tap** → Double/Triple
  Tap → Quick Capture. Tap the back of the phone to capture.
- **Apple Watch:**
  - Shortcuts complication on a watch face (tap the shortcut from the face), or
  - the Shortcuts app on the Watch, or
  - "Hey Siri, Quick Capture" on-wrist.
  The Watch relays through the iPhone's Tailscale connection.

---

## Notes & limits

- **On the go without your PC awake:** a *live* capture needs the PC on and
  connected to Tailscale. The **offline-queue version below** removes that
  dependency — it saves every note on the phone first and syncs whenever the PC
  is next reachable, so nothing is lost while the PC sleeps. Build the simple
  version above first to confirm the URL/token work, then upgrade to this.
- **`source` value** `siri_shortcut` tags these captures so you can tell mobile
  entries apart in the Inbox. `ios_widget` is also valid if you want to
  distinguish the Lock Screen widget.
- **HTTP vs HTTPS:** over Tailscale, `http://` on the private `100.x.y.z`
  address is fine — the traffic is already encrypted by Tailscale. Don't expose
  port 3000 to the public internet with plain HTTP.

## Offline-queue version (never lose a capture)

The single-POST version fails if the PC is asleep. This version **always saves
the note to a file on the phone first**, then *tries* to sync. If the sync
fails, the note stays queued and goes up the next time the PC is reachable —
you can capture from a subway with your phone in airplane mode and it still
lands later.

**How it stays correct:**
- Each capture gets a stable `clientId` (a UUID) written into the queue. The
  sync posts the whole queue to
  [`/api/capture/batch`](CAPTURE_API.md#post-apicapturebatch), and the server
  **deduplicates on `clientId`** — so re-sending the queue never creates
  duplicates, even in the "server saved it but the reply got lost" case (the
  classic iOS `-1005` "network connection was lost" failure on a flaky mobile
  link).
- The sync step runs *after* the save step. If the network fails, the Shortcut
  simply stops there with the note already safe on disk; the "clear the queue"
  step only runs after a successful POST.

Build one Shortcut named **"Quick Capture"** with these actions in order. The
queue lives in a file at **iCloud Drive → `Quick Capture/queue.jsonl`**.

**Part A — capture (runs fully offline):**

1. **Ask for Input** — Text, prompt `What's on your mind?`, Allow Multiple
   Lines ON. → *Provided Input*.
2. Escape the text so it's safe inside JSON (three **Replace Text** actions, in
   this order, each feeding the next):
   - Replace `\` with `\\` in *Provided Input*
   - Replace `"` with `\"`
   - Turn **Regex ON**, replace `\n` with a single space  → *Safe Text*
3. **UUID** → *clientId*.
4. **Text** — one line, exactly (insert the two variables where shown):
   `{"rawText":"[Safe Text]","source":"siri_shortcut","clientId":"[clientId]"}`
5. **Get File** — iCloud Drive, path `Quick Capture/queue.jsonl`,
   **"Error If Not Found" OFF** → then **Get Text from Input** → *Existing*
   (empty on the first ever run).
6. **If** *Existing* **has any value** →
   **Text** = `[Existing]`⏎`[line from step 4]` (a real newline between them);
   **Otherwise** → **Text** = `[line from step 4]`. **End If** → *New Queue*.
7. **Save File** — iCloud Drive, path `Quick Capture/queue.jsonl`,
   **"Ask Where to Save" OFF**, **"Overwrite If File Exists" ON**,
   contents = *New Queue*.

**Part B — sync (best-effort; safe to fail):**

8. **Get File** `Quick Capture/queue.jsonl` (Error If Not Found OFF) →
   **Get Text from Input** → *Queue*.
9. **Split Text** *Queue* by **New Lines**.
10. **Combine Text** (the split result) with separator `,` → *Joined*.
11. **Text** = `{"items":[[Joined]]}` → *Batch Body*.
12. **Get Contents of URL**:
    - URL: `https://your-machine.your-tailnet.ts.net/api/capture/batch`
    - Method: **POST**
    - Headers: `Authorization` = `Bearer <YOUR_TOKEN>`, and
      `Content-Type` = `application/json`
    - Request Body: **File** → pick *Batch Body*. (This sends the JSON text
      verbatim; do NOT use the JSON body builder here since you've already built
      the JSON.)
13. **Save File** — same path, Overwrite ON, contents = an **empty Text**
    action. (Only reached if step 12 succeeded, so a failed sync leaves the
    queue intact.)
14. *(Optional)* **Show Notification** — `Synced ✓`.

That's it. Offline, the Shortcut stops at step 12 with your note safe in the
queue; the next successful run flushes everything at once.

> A couple of action names may read slightly differently on your iOS version
> (e.g. "Get Text from Input" may just be "Text" in the file's context menu) —
> pick the closest match and the flow is the same.
