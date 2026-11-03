// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

/** Configure canonical installed AutoGenesis MCP runtimes for this workspace. */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

export interface McpServerConfig {
  name: string;
  projectPath: string;
  browser: "edge" | "chrome";
  serverType: string;
  isRunning: boolean;
}
interface WorkspaceMcpConfig {
  servers: Record<string, any>;
  [key: string]: unknown;
}

interface CanonicalMcpDefinition {
  command: string;
  args: string[];
  env: Record<string, string>;
}

export class McpServerManager {
  private static instance: McpServerManager;
  private servers = new Map<string, McpServerConfig>();
  private _onServerStatusChanged = new vscode.EventEmitter<{
    name: string;
    isRunning: boolean;
  }>();
  public readonly onServerStatusChanged = this._onServerStatusChanged.event;

  private constructor() {}

  public static getInstance(): McpServerManager {
    if (!McpServerManager.instance) {
      McpServerManager.instance = new McpServerManager();
    }
    return McpServerManager.instance;
  }
  private samePath(left: string, right: string): boolean {
    const normalize = (value: string) =>
      process.platform === "win32" ? value.toLowerCase() : value;
    return normalize(path.resolve(left)) === normalize(path.resolve(right));
  }

  private assertRealDirectory(directory: string, label: string): void {
    const stats = fs.lstatSync(directory);
    if (stats.isSymbolicLink() || !stats.isDirectory()) {
      throw new Error(`${label} must be a real directory, not a link or reparse point.`);
    }
    if (!this.samePath(fs.realpathSync.native(directory), directory)) {
      throw new Error(`${label} must not traverse links or reparse points.`);
    }
  }

  private assertRealFile(file: string, directory: string, label: string): void {
    const stats = fs.lstatSync(file);
    if (stats.isSymbolicLink() || !stats.isFile()) {
      throw new Error(`${label} must be a regular file, not a link or reparse point.`);
    }
    const realFile = fs.realpathSync.native(file);
    if (!this.samePath(path.dirname(realFile), directory)) {
      throw new Error(`${label} must remain inside the selected workspace.`);
    }
  }


  /**
   * Configure the installed Runtime directly. Package installation and Skill
   * verification belong to `autogenesis install`, never to the Extension.
   */
  public async setupMcpServer(
    projectPath: string,
    browser: "edge" | "chrome" = "edge",
    serverType: string = "appium-common"
  ): Promise<string> {
    if (!vscode.workspace.isTrusted) {
      throw new Error("Trust this workspace before configuring executable MCP settings.");
    }
    const projectBaseName = path.basename(projectPath);
    const serverTypeSuffix =
      serverType === "windows-browser" ? "windows" : "appium";
    const serverName = `auto-genesis-extension-${projectBaseName}-${serverTypeSuffix}`;
    const serverConfig: McpServerConfig = {
      name: serverName,
      projectPath,
      browser,
      serverType,
      isRunning: false,
    };

    await this.updateVSCodeMcpSettings(serverConfig);
    this.servers.set(serverName, serverConfig);
    return serverName;
  }

  public async startMcpServer(serverName: string): Promise<void> {
    const server = this.servers.get(serverName);
    if (!server) {
      throw new Error(`Server ${serverName} not found`);
    }
    if (server.isRunning) {
      vscode.window.showInformationMessage(
        `MCP Server ${serverName} is already running`
      );
      return;
    }
    server.isRunning = true;
    this._onServerStatusChanged.fire({ name: serverName, isRunning: true });
  }

  public async stopMcpServer(serverName: string): Promise<void> {
    const server = this.servers.get(serverName);
    if (!server) {
      throw new Error(`Server ${serverName} not found`);
    }
    await this.removeMcpServerFromSettings(serverName);
    server.isRunning = false;
    this._onServerStatusChanged.fire({ name: serverName, isRunning: false });
    vscode.window.showInformationMessage(
      `MCP Server ${serverName} stopped successfully`
    );
  }

  public getServers(): McpServerConfig[] {
    return Array.from(this.servers.values());
  }

  public getServer(name: string): McpServerConfig | undefined {
    return this.servers.get(name);
  }

  public async getWorkspaceMcpConfig(
    projectPath: string
  ): Promise<WorkspaceMcpConfig> {
    this.assertRealDirectory(projectPath, "Workspace");
    const vscodeDirectory = path.join(projectPath, ".vscode");
    if (fs.existsSync(vscodeDirectory)) {
      this.assertRealDirectory(vscodeDirectory, "Workspace .vscode directory");
    }
    const mcpConfigPath = path.join(projectPath, ".vscode", "mcp.json");
    if (!fs.existsSync(mcpConfigPath)) {
      return { servers: {} };
    }
    this.assertRealFile(mcpConfigPath, vscodeDirectory, "Workspace MCP configuration");
    try {
      const content = await fs.promises.readFile(mcpConfigPath, "utf8");
      const config = JSON.parse(content) as Partial<WorkspaceMcpConfig>;
      return { ...config, servers: config.servers || {} };
    } catch (error) {
      throw new Error(`Unable to read ${mcpConfigPath}: ${error}`);
    }
  }

  private requireBusinessConfig(serverConfig: McpServerConfig): string {
    const configPath = path.join(serverConfig.projectPath, "bdd_ai_conf.json");
    this.assertRealDirectory(serverConfig.projectPath, "Workspace");
    if (!fs.existsSync(configPath)) {
      throw new Error(
        "Create bdd_ai_conf.json with the selected Runtime profile, then run setup again."
      );
    }
    this.assertRealFile(configPath, serverConfig.projectPath, "bdd_ai_conf.json");
    let config: any;
    try {
      config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    } catch {
      throw new Error("bdd_ai_conf.json must be readable UTF-8 JSON.");
    }
    if (serverConfig.serverType === "windows-browser") {
      const profiles = config?.PYWINAUTO_CONFIG?.apps_config;
      if (!profiles || typeof profiles[serverConfig.browser] !== "object") {
        throw new Error(
          `bdd_ai_conf.json must define PYWINAUTO_CONFIG.apps_config.${serverConfig.browser}.`
        );
      }
    } else {
      const platform = process.platform === "darwin" ? "mac" : "android";
      const profile = config?.APPIUM_DRIVER_CONFIGS?.[platform];
      if (!profile || typeof profile !== "object") {
        throw new Error(
          `bdd_ai_conf.json must define APPIUM_DRIVER_CONFIGS.${platform}.`
        );
      }
    }
    return configPath;
  }

  private canonicalDefinition(
    serverConfig: McpServerConfig
  ): CanonicalMcpDefinition {
    const configPath = this.requireBusinessConfig(serverConfig);
    const configArgs = ["--config", configPath];
    const common = [
      "--transport",
      "stdio",
      "--project-root",
      serverConfig.projectPath,
    ];

    if (serverConfig.serverType === "windows-browser") {
      return {
        command: "autogenesis-windows-mcp",
        args: [
          ...common,
          "--app",
          serverConfig.browser,
          ...configArgs,
        ],
        env: this.runtimeEnvironment(),
      };
    }
    if (serverConfig.serverType === "appium-common") {
      return {
        command: "autogenesis-appium-mcp",
        args: [
          ...common,
          "--platform",
          process.platform === "darwin" ? "mac" : "android",
          ...configArgs,
        ],
        env: this.runtimeEnvironment(),
      };
    }
    throw new Error(`Unsupported MCP server type: ${serverConfig.serverType}`);
  }

  private runtimeEnvironment(): Record<string, string> {
    return {
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
      LANG: "en_US.UTF-8",
      LC_ALL: "en_US.UTF-8",
    };
  }

  private async updateVSCodeMcpSettings(
    serverConfig: McpServerConfig
  ): Promise<void> {
    const mcpConfig = await this.getWorkspaceMcpConfig(
      serverConfig.projectPath
    );
    const expected = this.canonicalDefinition(serverConfig);
    const existing = mcpConfig.servers[serverConfig.name];

    if (existing && JSON.stringify(existing) !== JSON.stringify(expected)) {
      const choice = await vscode.window.showWarningMessage(
        `MCP server configuration '${serverConfig.name}' already exists and has been modified. This will overwrite your custom configuration.`,
        {
          modal: true,
          detail:
            "Your custom modifications will be lost. Do you want to reset this server to the canonical installed Runtime?",
        },
        "Reset to Canonical Runtime"
      );
      if (choice !== "Reset to Canonical Runtime") {
        throw new Error(
          "Setup cancelled by user. Existing MCP configuration preserved."
        );
      }
    }

    mcpConfig.servers[serverConfig.name] = expected;
    delete mcpConfig.servers[`${serverConfig.name}-sse`];
    await this.writeWorkspaceMcpConfig(serverConfig.projectPath, mcpConfig);
  }

  private async writeWorkspaceMcpConfig(
    projectPath: string,
    mcpConfig: WorkspaceMcpConfig
  ): Promise<void> {
    this.assertRealDirectory(projectPath, "Workspace");
    const vscodeDirectory = path.join(projectPath, ".vscode");
    const mcpConfigPath = path.join(vscodeDirectory, "mcp.json");
    try {
      await fs.promises.mkdir(vscodeDirectory, { recursive: false });
    } catch (error: any) {
      if (error?.code !== "EEXIST") {
        throw error;
      }
    }
    this.assertRealDirectory(vscodeDirectory, "Workspace .vscode directory");

    const temporary = `${mcpConfigPath}.${process.pid}.${Date.now()}.tmp`;
    try {
      await fs.promises.writeFile(
        temporary,
        `${JSON.stringify(mcpConfig, null, 2)}\n`,
        { encoding: "utf8", flag: "wx" }
      );
      this.assertRealDirectory(vscodeDirectory, "Workspace .vscode directory");
      this.assertRealFile(temporary, vscodeDirectory, "Temporary MCP configuration");
      await fs.promises.rename(temporary, mcpConfigPath);
      this.assertRealDirectory(vscodeDirectory, "Workspace .vscode directory");
      this.assertRealFile(mcpConfigPath, vscodeDirectory, "Workspace MCP configuration");
    } finally {
      try {
        this.assertRealDirectory(vscodeDirectory, "Workspace .vscode directory");
        await fs.promises.rm(temporary, { force: true });
      } catch {
        // Fail closed rather than following a replaced workspace directory.
      }
    }
  }

  private async removeMcpServerFromSettings(
    serverName: string
  ): Promise<void> {
    const server = this.servers.get(serverName);
    if (!server) {
      return;
    }
    const mcpConfig = await this.getWorkspaceMcpConfig(server.projectPath);
    if (mcpConfig.servers[serverName]) {
      delete mcpConfig.servers[serverName];
      delete mcpConfig.servers[`${serverName}-sse`];
      await this.writeWorkspaceMcpConfig(server.projectPath, mcpConfig);
    }
  }
}
