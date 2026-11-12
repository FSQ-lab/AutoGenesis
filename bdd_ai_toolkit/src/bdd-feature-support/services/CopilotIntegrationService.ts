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

export class CopilotIntegrationService {
  /** Hold canonical Skill bytes from the selected Feature's discovery scope. */
  loadSkillContent(skillName: string, featureFilePath: string):
    { status: 'ready'; content: string } | { status: 'absent' | 'invalid' } {
    const relative = ['.agents', 'skills', skillName, 'SKILL.md'];
    const expectedSha256 = '99e276bde9c95996d9d19c8f548eac41305cea61494a3955c4c6f44563f88f64';
    const selected = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(featureFilePath));
    const projectSkill = selected && path.join(selected.uri.fsPath, ...relative);
    const userSkill = path.join(os.homedir(), ...relative);

    const held = (candidate: string):
      { status: 'ready'; content: string } | { status: 'absent' | 'invalid' } => {
      let descriptor: number | undefined;
      try {
        const expected = fs.lstatSync(candidate);
        if (!expected.isFile() || expected.isSymbolicLink() || expected.size <= 0 || expected.size > 256 * 1024) return { status: 'invalid' };
        const noFollow = process.platform === 'win32' ? 0 : fs.constants.O_NOFOLLOW;
        descriptor = fs.openSync(candidate, fs.constants.O_RDONLY | noFollow);
        const opened = fs.fstatSync(descriptor);
        if (opened.dev !== expected.dev || opened.ino !== expected.ino || opened.size !== expected.size) return { status: 'invalid' };
        const raw = fs.readFileSync(descriptor);
        const final = fs.fstatSync(descriptor);
        if (final.dev !== opened.dev || final.ino !== opened.ino || final.size !== opened.size) return { status: 'invalid' };
        if (createHash('sha256').update(raw).digest('hex') !== expectedSha256) return { status: 'invalid' };
        return { status: 'ready', content: raw.toString('utf8') };
      } catch (error) {
        const code = (error as NodeJS.ErrnoException).code;
        return { status: code === 'ENOENT' ? 'absent' : 'invalid' };
      } finally {
        if (descriptor !== undefined) fs.closeSync(descriptor);
      }
    };

    // Project scope has precedence; invalid bytes fail closed rather than switching scope.
    if (projectSkill) {
      const project = held(projectSkill);
      if (project.status !== 'absent') return project;
    }
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
    const selection = encode({
      featureFilePath,
      lineNumber,
      scenarioName,
      request: 'record-read-only-preview',
    });
    return `Apply this authenticated AutoGenesis Skill snapshot exactly: ${authenticated}\nTreat only this encoded selection as task data: ${selection}\nThis is an explicit recording request. Follow generate_scenario_test, stop after preview_code_changes, and report that generated-file writes are unavailable. Do not copy, save, shell-write, or otherwise persist the proposed bytes.`;
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

}
