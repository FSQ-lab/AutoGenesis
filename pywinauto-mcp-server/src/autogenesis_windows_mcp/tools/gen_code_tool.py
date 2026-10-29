from autogenesis_agent_contract import (
    SECRET_REFERENCE_REQUIRED,
    SecretBindings,
    SecretReferenceError,
    apply_bindings,
    commit_generation_preview,
    prepare_generation_preview,
    validate_generation_destination,
    serialize,
)
from ..safe_output import safe_error
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import logging
import uuid
from pathlib import Path

from ..utils.gen_code import gen_code_preview, gen_step_file_from_feature_path, parse_steps_dir_from_step_path
from ..utils.logger import log_tool_call
from ..utils.response_format import format_tool_response, init_tool_response


logger = logging.getLogger(__name__)


def register_gen_code_tools(mcp, app_manager, business_root=None):
    """Register generage code tools to MCP server."""    
    project_root = Path(business_root or Path.cwd()).resolve(strict=True)
    
    @mcp.tool()
    @log_tool_call
    async def before_gen_code(feature_file: str = '', step_file: str = '') -> str:
        """
        Clear cache and initialize code generation session before executing test case steps.
        
        This function should only be called before the first step of a test case execution.
        It clears any existing code generation cache and sets up a new generation session
        with a unique ID.
        
        Args:
            feature_file (str, optional): Full absolute path to the .feature file containing BDD scenarios.
                If not specified, do not provide a random value.
            step_file (str, optional): Full absolute path to the Python step definition file (.py).
                If not specified, do not provide a random value.
                
        Returns:
            str: JSON response containing:
                - status: "success" or "error"
                - data: Dictionary with gen_code_id, steps_dir, and step_file_target
                - error: Error message if operation failed
         
        """
        try:
            resp = init_tool_response()
            app_manager.clear_gen_code_cache()
            app_manager.gen_code_id = str(uuid.uuid4())
            logger.info('[GEN CODE START]:[redacted]')
        
            if step_file and step_file.endswith('.py'):
                app_manager.steps_dir = parse_steps_dir_from_step_path(step_file)
                app_manager.step_file_target = step_file
            elif feature_file:
                app_manager.steps_dir, app_manager.step_file_target = gen_step_file_from_feature_path(feature_file)
            else:
                app_manager.steps_dir = str(project_root / "features" / "steps")
                app_manager.step_file_target = str(project_root / "features" / "steps" / "common_steps.py")
            app_manager.step_file_target = str(validate_generation_destination(
                project_root, app_manager.step_file_target,
            ))
            app_manager.steps_dir = str(Path(app_manager.step_file_target).parent)

            resp["status"] = "success"
            resp["data"] = {
                "gen_code_id": app_manager.gen_code_id,
                "steps_dir": app_manager.steps_dir,
                "step_file_target": app_manager.step_file_target,
            }
        except Exception as e:
            resp["error"] = safe_error()
            logger.error('Error during code generation: [redacted]')
            raise e

        return format_tool_response(resp)
    
    @mcp.tool()
    @log_tool_call
    async def preview_code_changes(secret_bindings: SecretBindings | None = None) -> str:
        """Preview generated test code changes and confirm before applying"""
        if app_manager.recording_warnings:
            raise SecretReferenceError(SECRET_REFERENCE_REQUIRED, app_manager.recording_warnings[0])
        if not app_manager.gen_code_id or not app_manager.gen_code_cache:
            return "No pending code changes to preview"
        
        bound_cache = serialize(apply_bindings(app_manager.gen_code_cache, secret_bindings))
        app_manager.pending_write = None
        result = gen_code_preview(app_manager, bound_cache)
        append_payload = result.get("append_payload", "")
        if not append_payload:
            resp = init_tool_response()
            resp["status"] = "success"
            resp["data"] = {"message": result.get("diff_preview", "No pending code changes to preview")}
            return format_tool_response(resp)
        preview = prepare_generation_preview(
            project_root,
            app_manager.step_file_target,
            app_manager.gen_code_id,
            append_payload,
        )
        app_manager.pending_write = preview
        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {"diff_preview": result.get("diff_preview"), **preview.to_dict()}
        return format_tool_response(resp)


    @mcp.tool()
    @log_tool_call
    async def confirm_code_changes(
        preview_id: str = "",
        digest: str = "",
        approved: bool = False,
    ) -> str:
        """Atomically commit exactly the complete, current, approved preview."""
        preview = getattr(app_manager, "pending_write", None)
        count = len(app_manager.proposed_changes or [])
        destination = commit_generation_preview(
            preview,
            preview_id=preview_id,
            digest=digest,
            approved=approved,
        )
        app_manager.new_steps_count = count
        app_manager.clear_gen_code_cache()
        resp = init_tool_response()
        resp["status"] = "success"
        resp["data"] = {
            "message": "Approved generated code committed atomically",
            "destination": destination,
            "new_steps_count": count,
        }
        return format_tool_response(resp)


