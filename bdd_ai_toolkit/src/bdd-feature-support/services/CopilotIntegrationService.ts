// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

/**
 * CopilotIntegrationService - Service for integrating with GitHub Copilot
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';
import { createHash } from 'crypto';
import { Scenario, Background } from '../core/gherkin/types';
import { ConfigManager } from '../utils/ConfigManager';

export class CopilotIntegrationService {
  private configManager: ConfigManager;

  constructor() {
    this.configManager = ConfigManager.getInstance();
  }

  /**
   * Generate text for a scenario to send to Copilot
   * @param scenario Scenario object
   * @param featureFilePath Optional feature file path for context
   * @param includeBackground Optional background to include
   * @returns Generated text
   */
  async generateScenarioText(
    scenario: Scenario,
    featureFilePath?: string,
    includeBackground?: Background
  ): Promise<string> {
    let fullText = "";

    // Build scenario header
    fullText += `Scenario: ${scenario.name}\n`;

    // Include background steps if provided (without Background: header)
    if (includeBackground && includeBackground.steps.length > 0) {
      for (const step of includeBackground.steps) {
        fullText += `  ${step.type} ${step.text}\n`;
      }
    }

    // Add all scenario steps
    for (const step of scenario.steps) {
      fullText += `  ${step.type} ${step.text}\n`;
    }

    // Apply custom prompt with placeholders
    return this.applyCustomPrompt(fullText.trim(), featureFilePath);
  }

  /**
   * Generate text for background to send to Copilot
   * @param background Background object
   * @param featureFilePath Optional feature file path for context
   * @returns Generated text
   */
  async generateBackgroundText(
    background: Background,
    featureFilePath?: string
  ): Promise<string> {
    let fullText = "Background:\n";

    // Add all background steps
    for (const step of background.steps) {
      fullText += `  ${step.type} ${step.text}\n`;
    }

    // Apply custom prompt with placeholders
    return this.applyCustomPrompt(fullText.trim(), featureFilePath);
  }

  /**
   * Apply custom prompt with placeholder replacement
   * @param scenarioText Scenario or background text
   * @param featureFilePath Optional feature file path
   * @returns Text with custom prompt applied
   */
  private applyCustomPrompt(scenarioText: string, featureFilePath?: string): string {
    // Get custom prompt from config
    let customPrompt = this.configManager.getCopilotPromptWithPriority(featureFilePath);

    // Check if prompt contains scenario_text placeholder
    if (customPrompt.includes("${scenario_text}")) {
      // Replace scenario_text placeholder
      customPrompt = customPrompt.replace(/\$\{scenario_text\}/g, scenarioText);

      // Replace feature_file_path placeholder if present
      if (featureFilePath && customPrompt.includes("${feature_file_path}")) {
        customPrompt = customPrompt.replace(/\$\{feature_file_path\}/g, featureFilePath);
      }

      // Replace profiles_path placeholder if present
      if (featureFilePath && customPrompt.includes("${profiles_path}")) {
        const profilesPath = this.findProfilesPath(featureFilePath);
        if (profilesPath) {
          customPrompt = customPrompt.replace(/\$\{profiles_path\}/g, profilesPath);
        }
      }

      // Return the customized prompt (scenario text is already included)
      return customPrompt;
    } else {
      // Legacy behavior: append prompt to scenario text
      // Replace feature_file_path placeholder if present
      if (featureFilePath && customPrompt.includes("${feature_file_path}")) {
        customPrompt = customPrompt.replace(/\$\{feature_file_path\}/g, featureFilePath);
      }

      // Replace profiles_path placeholder if present
      if (featureFilePath && customPrompt.includes("${profiles_path}")) {
        const profilesPath = this.findProfilesPath(featureFilePath);
        if (profilesPath) {
          customPrompt = customPrompt.replace(/\$\{profiles_path\}/g, profilesPath);
        }
      }

      return `${scenarioText}\n\n${customPrompt}`;
    }
  }

  /**
   * Find profiles directory path
   * Traverses up two levels from feature file
   * @param featureFilePath Feature file path
   * @returns Profiles path or null
   */
  private findProfilesPath(featureFilePath: string): string | null {
    try {
      let currentDir = path.dirname(featureFilePath);

      // Traverse up two levels
      for (let i = 0; i < 2; i++) {
        const parentDir = path.dirname(currentDir);
        if (parentDir === currentDir) {
          // Reached root directory
          break;
        }
        currentDir = parentDir;
      }

      // Look for profiles directory in the current level
      const profilesPath = path.join(currentDir, "profiles");
      if (fs.existsSync(profilesPath) && fs.statSync(profilesPath).isDirectory()) {
        return profilesPath;
      }

      return null;
    } catch (error) {
      console.error("Error finding profiles path:", error);
      return null;
    }
  }

  /** Resolve only the canonical Skill bytes at the selected Feature's discovery scope. */
  hasSkillAvailable(skillName: string, featureFilePath: string): boolean {
    const relative = ['.agents', 'skills', skillName, 'SKILL.md'];
    const expectedSha256 = '837a83cb03ef5ca3670930510566147490d5cad808ad28b1d4a3f2a0103193a9';
    const selected = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(featureFilePath));
    const projectSkill = selected && path.join(selected.uri.fsPath, ...relative);
    const userSkill = path.join(os.homedir(), ...relative);

    const verified = (candidate: string): boolean => {
      try {
        const info = fs.lstatSync(candidate);
        if (!info.isFile() || info.isSymbolicLink() || info.size <= 0 || info.size > 256 * 1024) {
          return false;
        }
        return createHash('sha256').update(fs.readFileSync(candidate)).digest('hex') === expectedSha256;
      } catch {
        return false;
      }
    };

    // A stale project copy shadows user scope and must fail closed rather than silently switch scope.
    if (projectSkill && fs.existsSync(projectSkill)) {
      return verified(projectSkill);
    }
    return verified(userSkill);
  }

  /** Generate an exact, unambiguous Skill invocation for a selected Scenario. */
  generateSkillCommand(
    skillName: string,
    scenarioName: string,
    featureFilePath: string,
    lineNumber: number
  ): string {
    const selection = JSON.stringify({ featureFilePath, lineNumber, scenarioName });
    return `/${skillName} Execute the exact selected Scenario using this selection data: ${selection}`;
  }

  /**
   * Send text to Copilot chat
   * @param text Text to send
   */
  async sendToCopilot(text: string): Promise<void> {
    try {
      await vscode.commands.executeCommand('workbench.panel.chat.view.copilot.focus');
      await vscode.commands.executeCommand('workbench.action.chat.open', { query: text });
    } catch (error) {
      console.error('Error sending to Copilot:', error);
      vscode.window.showErrorMessage('Failed to send to Copilot');
    }
  }

  /**
   * Get config manager instance
   */
  getConfigManager(): ConfigManager {
    return this.configManager;
  }
}
