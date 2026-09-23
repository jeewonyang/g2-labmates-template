# AGENT_PRIMARY.md - Which machine runs scheduled automation

The vault can sync across machines (see docs/SYNC_SETUP.md), but only ONE host
may run the *scheduled* automation, or two machines will produce duplicate work
from the same vault. `agent_day.py` reads the hostname from the first fenced
block below and no-ops on every other machine. Interactive runs (dashboard
buttons, skills, `--force`) are never blocked.

Set this to your machine's hostname (run `hostname` to find it):

```
YOUR-MACHINE-HOSTNAME
```
