# PicoCalc Project Instructions

For this repository, prefer the PicoCalc MCP tools for device operations.

Rules:
- Use PicoCalc MCP `exec` for running apps, demos, diagnostics, and on-screen tests.
- Use PicoCalc MCP `push` for copying files to the device.
- Use PicoCalc MCP `list_files`, `read_file`, `status`, and `reset` for inspection and device management.
- Do not use `mpremote` by default for PicoCalc device actions.
- Use `mpremote` only as a fallback if the PicoCalc MCP path is unavailable or failing.

Rationale:
- The PicoCalc MCP path is more reliable in this repo's workflow and avoids transport conflicts from direct `mpremote` exec sessions.
