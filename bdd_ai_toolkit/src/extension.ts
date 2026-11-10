// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

import * as vscode from "vscode";
import { registerTools } from "./tools/index";
import {
  activateBddFeatureSupport,
  deactivateBddFeatureSupport,
} from "./bdd-feature-support";
import { GlobalState } from "./globalState";
import { McpServerManager, SetupWebViewProvider } from "./setup";

/**
 * WebView provider instance for the setup panel
 */
let setupWebViewProvider: SetupWebViewProvider | undefined = undefined;

/**
 * Extension activation entry point
 * Called when the extension is first activated by VS Code
 */
export async function activate(context: vscode.ExtensionContext) {
  // Initialize global state
  GlobalState.initialize(context);

  // Activate BDD Feature Support
  activateBddFeatureSupport(context);

  // Register Copilot language model tools
  registerTools(context);
  context.subscriptions.push(McpServerManager.getInstance().registerProvider(context));

  // Register setup panel WebView provider
  setupWebViewProvider = new SetupWebViewProvider(
    context.extensionUri,
    context
  );
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      SetupWebViewProvider.viewType,
      setupWebViewProvider
    )
  );
}


/**
 * Extension deactivation cleanup
 * Called when the extension is deactivated by VS Code
 */
export function deactivate() {
  // Clean up BDD Feature Support resources
  if (deactivateBddFeatureSupport) {
    deactivateBddFeatureSupport();
  }
}
