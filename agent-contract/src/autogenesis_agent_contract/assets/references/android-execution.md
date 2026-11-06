# Android execution

Confirm the selected device, application package/activity, native or Web context, current surface, and side-effect limits only as needed for the next action. Do not rerun setup or official-source verification for an already verified live context.

For native Android, prefer a stable resource ID or accessibility description, then an appropriate Android UIAutomator selector, then a narrowly scoped XPath. Coordinates are a last resort and require current screen geometry. Native Android has no useful browser title; use current package/activity, context inventory, bounded page source, and relevant element state.

Keep native and Web contexts distinct. Re-evaluate the current context after navigation or a hybrid transition. Do not apply native locators to Web content or Web assumptions to native controls.

After navigation, refresh, scrolling, context changes, or system UI, reacquire affected elements; do not retain stale element handles or row numbers. Distinguish application UI from permissions, keyboard, notifications, and system dialogs. Change only authorized field content, verify submitted/read-back state, and handle back/keyboard actions only when required by the scenario.

Recover from the observed failure: refresh current package/activity/context for navigation drift; inspect bounded UI evidence for locator failure; reconcile device/session state after timeout or transport loss; never create a second session merely because a response is missing. Preserve user-owned ADB, emulator, application, and server state and close only the task-owned session/resources.
