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

  /** Hold canonical Skill bytes from the selected Feature's discovery scope. */
  loadSkillContent(skillName: string, featureFilePath: string): string | null {
    const relative = ['.agents', 'skills', skillName, 'SKILL.md'];
    const expectedSha256 = '54b23e8a55408cf41815a3dd06db107e5747d27a3473e33f98a04d752c943773';
    const selected = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(featureFilePath));
    const projectSkill = selected && path.join(selected.uri.fsPath, ...relative);
    const userSkill = path.join(os.homedir(), ...relative);

    const held = (candidate: string): string | null => {
      let descriptor: number | undefined;
      try {
        if (process.platform === 'win32') return null;
        const expected = fs.lstatSync(candidate);
        if (!expected.isFile() || expected.isSymbolicLink() || expected.size <= 0 || expected.size > 256 * 1024) return null;
        descriptor = fs.openSync(candidate, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
        const opened = fs.fstatSync(descriptor);
        if (opened.dev !== expected.dev || opened.ino !== expected.ino || opened.size !== expected.size) return null;
        const raw = fs.readFileSync(descriptor);
        const final = fs.fstatSync(descriptor);
        if (final.dev !== opened.dev || final.ino !== opened.ino || final.size !== opened.size) return null;
        if (createHash('sha256').update(raw).digest('hex') !== expectedSha256) return null;
        return raw.toString('utf8');
      } catch {
        return null;
      } finally {
        if (descriptor !== undefined) fs.closeSync(descriptor);
      }
    };

    // A project copy shadows user scope; invalid bytes fail closed rather than switching scope.
    if (projectSkill && fs.existsSync(projectSkill)) return held(projectSkill);
    return held(userSkill);
  }

  /** Generate an invocation bound to the exact held canonical Skill bytes. */
  generateSkillCommand(
    skillName: string,
    scenarioName: string,
    featureFilePath: string,
    lineNumber: number,
    skillContent: string
  ): string {
    const encode = (value: unknown) => JSON.stringify(value).replace(/[<>&]/g, character =>
      `\\u${character.charCodeAt(0).toString(16).padStart(4, '0')}`
    );
    const authenticated = encode({
      name: skillName,
      sha256: createHash('sha256').update(skillContent).digest('hex'),
      content: skillContent,
    });
    const selection = encode({ featureFilePath, lineNumber, scenarioName });
    return `Apply this authenticated AutoGenesis Skill snapshot exactly: ${authenticated}\nExecute only the selected Scenario data: ${selection}`;
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
