# Windows execution

Enter with one verified Windows MCP binding. Confirm the selected application instance, top-level window, focus, and current UIA surface only as needed. Do not relaunch or rebind merely to repeat readiness.

Prefer AutomationId, then a unique accessible name combined with control type and the selected window scope. Use a narrowly scoped UIA hierarchy when necessary. Coordinates are a last resort with current window geometry. Multiple matching controls or windows require narrower evidence; never choose the first arbitrary result.

Reacquire controls after navigation, window replacement, dialog creation, list virtualization, or application refresh. Distinguish application dialogs from system dialogs and preserve the selected process/window identity. Verify text entry and requested state through UIA properties or visible state rather than narrated success.

Classify launch/binding errors before recovery. Invalid configuration, elevation mismatch, executable rejection, and window ambiguity are not retried unchanged. After timeout or connection loss, observe whether the selected process/window still exists and whether the binding is valid before relaunching; do not duplicate an action whose outcome is unknown.

Runtime shutdown releases binding only. Preserve user-owned applications unless the user explicitly requested close. `app_close` targets only the selected instance; never close unrelated processes because they share an executable path.
