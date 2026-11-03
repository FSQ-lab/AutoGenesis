// Copyright (c) Microsoft Corporation.
// Licensed under the MIT license.

/** Provide canonical installed AutoGenesis MCP runtimes without workspace writes. */

import * as vscode from "vscode";
import * as path from "path";
import * as fs from "fs";

type ServerType = "windows-browser" | "appium-common";

export interface McpServerConfig {
  name: string;
  projectPath: string;
  browser: "edge" | "chrome";
  serverType: ServerType;
  isRunning: boolean;
}

interface WorkspaceMcpConfig {
  servers: Record<string, { command: string; args: string[] }>;
}

interface CanonicalMcpDefinition {
  command: string;
  args: string[];
  env: Record<string, string>;
  version: string;
}

const PROVIDER_ID = "bdd-ai-toolkit.autogenesis-runtimes";

export class McpServerManager {
  private static instance: McpServerManager;
  private servers = new Map<string, McpServerConfig>();
  private _onServerStatusChanged = new vscode.EventEmitter<{
    name: string;
    isRunning: boolean;
  }>();
  private _onDefinitionsChanged = new vscode.EventEmitter<void>();
  public readonly onServerStatusChanged = this._onServerStatusChanged.event;

  private constructor() {}

  public static getInstance(): McpServerManager {
    if (!McpServerManager.instance) {
      McpServerManager.instance = new McpServerManager();
    }
    return McpServerManager.instance;
  }

  public registerProvider(): vscode.Disposable {
    return vscode.lm.registerMcpServerDefinitionProvider(PROVIDER_ID, {
      onDidChangeMcpServerDefinitions: this._onDefinitionsChanged.event,
      provideMcpServerDefinitions: () =>
        Array.from(this.servers.values())
          .filter((server) => server.isRunning)
          .map((server) => this.vscodeDefinition(server)),
    });
  }

  /**
   * Validate and configure one installed Runtime. Package installation and Skill
   * verification belong to `autogenesis install`, never to the Extension.
   */
  public async setupMcpServer(
    projectPath: string,
    browser: "edge" | "chrome" = "edge",
    serverType: ServerType = "appium-common"
  ): Promise<string> {
    if (!vscode.workspace.isTrusted) {
      throw new Error("Trust this workspace before configuring executable MCP settings.");
    }
    const suffix = serverType === "windows-browser" ? "windows" : "appium";
    const name = `auto-genesis-extension-${path.basename(projectPath)}-${suffix}`;
    const server: McpServerConfig = {
      name,
      projectPath,
      browser,
      serverType,
      isRunning: false,
    };
    this.canonicalDefinition(server);
    this.servers.set(name, server);
    return name;
  }

  public async startMcpServer(serverName: string): Promise<void> {
    const server = this.requireServer(serverName);
    if (server.isRunning) {
      vscode.window.showInformationMessage(`MCP Server ${serverName} is already running`);
      return;
    }
    this.canonicalDefinition(server);
    server.isRunning = true;
    this._onDefinitionsChanged.fire();
    this._onServerStatusChanged.fire({ name: serverName, isRunning: true });
  }

  public async stopMcpServer(serverName: string): Promise<void> {
    const server = this.requireServer(serverName);
    server.isRunning = false;
    this._onDefinitionsChanged.fire();
    this._onServerStatusChanged.fire({ name: serverName, isRunning: false });
    vscode.window.showInformationMessage(`MCP Server ${serverName} stopped successfully`);
  }

  public getServers(): McpServerConfig[] {
    return Array.from(this.servers.values());
  }

  public getServer(name: string): McpServerConfig | undefined {
    return this.servers.get(name);
  }

  public async getWorkspaceMcpConfig(projectPath: string): Promise<WorkspaceMcpConfig> {
    const servers: WorkspaceMcpConfig["servers"] = {};
    for (const server of this.servers.values()) {
      if (server.projectPath === projectPath && server.isRunning) {
        const definition = this.canonicalDefinition(server);
        servers[server.name] = {
          command: definition.command,
          args: definition.args,
        };
      }
    }
    return { servers };
  }

  private requireServer(serverName: string): McpServerConfig {
    const server = this.servers.get(serverName);
    if (!server) {
      throw new Error(`Server ${serverName} not found`);
    }
    return server;
  }

  private requireBusinessConfig(server: McpServerConfig): string {
    const root = path.resolve(server.projectPath);
    const configPath = path.join(root, "bdd_ai_conf.json");
    const rootStats = fs.lstatSync(root);
    if (rootStats.isSymbolicLink() || !rootStats.isDirectory()) {
      throw new Error("Workspace must be a real directory, not a link or reparse point.");
    }
    if (!fs.existsSync(configPath)) {
      throw new Error(
        "Create bdd_ai_conf.json with the selected Runtime profile, then run setup again."
      );
    }
    const configStats = fs.lstatSync(configPath);
    if (configStats.isSymbolicLink() || !configStats.isFile()) {
      throw new Error("bdd_ai_conf.json must be a regular file inside the workspace.");
    }
    if (path.dirname(fs.realpathSync.native(configPath)) !== fs.realpathSync.native(root)) {
      throw new Error("bdd_ai_conf.json must remain inside the selected workspace.");
    }

    let config: any;
    try {
      config = JSON.parse(fs.readFileSync(configPath, "utf8"));
    } catch {
      throw new Error("bdd_ai_conf.json must be readable UTF-8 JSON.");
    }
    if (server.serverType === "windows-browser") {
      if (typeof config?.PYWINAUTO_CONFIG?.apps_config?.[server.browser] !== "object") {
        throw new Error(
          `bdd_ai_conf.json must define PYWINAUTO_CONFIG.apps_config.${server.browser}.`
        );
      }
    } else {
      const platform = process.platform === "darwin" ? "mac" : "android";
      if (typeof config?.APPIUM_DRIVER_CONFIGS?.[platform] !== "object") {
        throw new Error(`bdd_ai_conf.json must define APPIUM_DRIVER_CONFIGS.${platform}.`);
      }
    }
    return configPath;
  }

  private canonicalDefinition(server: McpServerConfig): CanonicalMcpDefinition {
    const configPath = this.requireBusinessConfig(server);
    const common = [
      "--transport",
      "stdio",
      "--project-root",
      server.projectPath,
    ];
    if (server.serverType === "windows-browser") {
      return {
        command: "autogenesis-windows-mcp",
        args: [...common, "--app", server.browser, "--config", configPath],
        env: this.runtimeEnvironment(),
        version: "0.5.0",
      };
    }
    return {
      command: "autogenesis-appium-mcp",
      args: [
        ...common,
        "--platform",
        process.platform === "darwin" ? "mac" : "android",
        "--config",
        configPath,
      ],
      env: this.runtimeEnvironment(),
      version: "0.5.0",
    };
  }

  private vscodeDefinition(server: McpServerConfig): vscode.McpStdioServerDefinition {
    const canonical = this.canonicalDefinition(server);
    const definition = new vscode.McpStdioServerDefinition(
      server.name,
      canonical.command,
      canonical.args,
      canonical.env,
      canonical.version
    );
    definition.cwd = vscode.Uri.file(server.projectPath);
    return definition;
  }

  private runtimeEnvironment(): Record<string, string> {
    return {
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
      LANG: "en_US.UTF-8",
      LC_ALL: "en_US.UTF-8",
    };
  }
}
