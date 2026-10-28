"""Real stdio fixture; imports only the installed contract wheel and MCP SDK."""

import argparse

from mcp.server.fastmcp import FastMCP

from autogenesis_agent_contract import RuntimeContractRequirement, load_contract, load_project_appendix, register_mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args()
    contract = load_contract()
    appendix = load_project_appendix(args.project_root)
    server = FastMCP("contract-stdio-fixture", instructions=contract.instructions, log_level="ERROR")
    runtime = RuntimeContractRequirement(contract.identity.contract_version, contract.identity.manifest_sha256)
    register_mcp(server, contract, appendix, runtime)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
