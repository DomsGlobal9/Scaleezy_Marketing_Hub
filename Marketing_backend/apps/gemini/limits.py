"""Request limits the studio and autopilot share.

Constants only, so the autopilot policy serializer can read the studio's cap
without importing a views module. `apps.gemini.views` re-exports them under
the names it always had.
"""

#: The studio's typed brief (`instruction`) and an autopilot policy's campaign
#: brief - the same text by the time the worker reads it - after tidying.
MAX_GENERATION_INSTRUCTION_CHARS = 1000
