"""Second Brain platform integrations.

Each integration is a module exposing:
- a dataclass for its data model
- an auth function (or shared auth, e.g. Google)
- query functions returning dataclass instances
- a format_context() turning results into LLM-ready text
- registration in registry.py

The LLM never sees API tokens. Python handles auth and passes only data.
"""
