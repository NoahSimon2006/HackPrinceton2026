"""Curated virtual files and native Deep Agents middleware. No host-file tools."""
from dataclasses import replace
import json
from pathlib import Path

from deepagents.backends import StateBackend
from deepagents.backends.protocol import WriteResult, EditResult, DeleteResult, FileUploadResponse
from deepagents.backends.utils import create_file_data, file_data_to_string
from deepagents.middleware.filesystem import FilesystemPermission
from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

SKILLS = Path(__file__).resolve().parent / "agent_skills"
FILESYSTEM_TOOLS = {"read_file", "ls", "glob", "grep", "write_file", "edit_file"}


def skill_files():
    return {f"/skills/{path.parent.name}/SKILL.md": create_file_data(path.read_text())
            for path in sorted(SKILLS.glob("*/SKILL.md"))}


def permissions(name):
    return [FilesystemPermission(operations=["write"], paths=[f"/project/notes/{name}/**"] +
                                (["/project/plan.md"] if name == "lead" else [])),
            FilesystemPermission(operations=["write", "delete"], paths=["/**"], mode="deny")]


class WorkspaceBackend(StateBackend):
    def __init__(self, activity, persist=None):
        super().__init__()
        self.activity, self.persist = activity, persist
        self.saved = {}

    def put(self, path, content):
        """Application-only write; tool permissions never permit canonical writes."""
        self.activity.check()
        if not isinstance(content, str):
            content = json.dumps(content)
        if len(content) > 200_000:
            raise ValueError("Artifact exceeds the workspace size limit.")
        result = super().write(path, content)
        self.saved[path] = create_file_data(content)
        if self.persist:
            self.persist(path, content)
        return result

    def write(self, file_path, content):
        if (not isinstance(file_path, str) or ".." in file_path or "\\" in file_path
                or not (file_path.startswith("/project/notes/") or file_path == "/project/plan.md")):
            return WriteResult(error="Only project notes and the lead plan are writable. Canonical inputs, evidence and skills are read-only.")
        existing = self._read_files()
        if len(content) > 12_000 or len(existing) >= 64 and file_path not in existing:
            return WriteResult(error="Workspace note budget reached; summarize an existing note.")
        return self.put(file_path, content)

    def edit(self, file_path, old_string, new_string, replace_all=False):
        from deepagents.backends.utils import perform_string_replacement
        existing = self._read_files().get(file_path)
        if existing is None:
            return EditResult(error="File not found.")
        value = perform_string_replacement(file_data_to_string(existing), old_string, new_string, replace_all)
        if isinstance(value, str):
            return EditResult(error=value)
        result = self.write(file_path, value[0])
        return EditResult(error=result.error) if result.error else EditResult(path=file_path, occurrences=value[1])

    def delete(self, file_path):
        return DeleteResult(error="Project artifacts cannot be deleted by the agent.")

    def upload_files(self, files):
        return [FileUploadResponse(path=path, error="permission_denied") for path, _ in files]


def tool_guard(name, activity, skill_reads, artifact_reads, assignments, backend, on_task_failure):
    """Enforce the tool boundary even if a model calls a tool hidden in its phase."""
    @wrap_tool_call
    def guard(request, handler):
        activity.check()
        call = request.tool_call
        tool, args = call["name"], call["args"]
        if tool == "task":
            target = args.get("subagent_type")
            with assignments["lock"]:
                if name != "lead" or target not in ("site-evidence", "domain-analysis") or target in assignments["started"]:
                    return ToolMessage(content="Use each named specialist once. Read its saved report for follow-up context.", tool_call_id=call["id"])
                assignments["started"].add(target)
            activity.event(target, "investigation", "started", "Inspecting sponsor evidence." if target == "site-evidence" else "Checking domain inputs and data gaps.")
        try:
            result = handler(request)
            activity.check()
        except Exception as error:
            from agent_activity import RunCancelled
            if isinstance(error, RunCancelled):
                raise
            if tool == "task":
                on_task_failure(args["subagent_type"])
                return ToolMessage(content=json.dumps({"status":"partial", "artifact":f"/project/reports/{args['subagent_type']}.json",
                    "message":"Specialist synthesis stopped. Read the saved partial evidence and unresolved inputs; do not infer missing values."}), tool_call_id=call["id"])
            activity.event(name, "validation", "retry", "Checking tool arguments against the permitted operation.")
            return ToolMessage(content="This tool could not complete with those arguments. Check the tool schema and saved evidence; do not repeat unchanged failing calls.", tool_call_id=call["id"], status="error")
        if tool == "read_file" and not getattr(result, "status", None) == "error":
            path = args.get("file_path", "")
            file = backend._read_files().get(path)
            if (file and path in skill_files() and args.get("offset", 0) == 0
                    and args.get("limit", 100) >= len(file_data_to_string(file).splitlines())):
                skill_reads[name].add(path)
                activity.event(name, "skill", "completed", f"Read procedure: {path.split('/')[2]}.")
            if file and path.startswith("/project/"):
                if path.startswith("/project/reports/") and json.loads(file_data_to_string(file)).get("run_id") != activity.id:
                    return result
                artifact_reads[name].add(path)
                activity.event(name, "artifact-read", "completed", f"Read {path}.")
        elif tool in ("write_file", "edit_file") and getattr(result, "status", None) != "error":
            path = args.get("file_path", "")
            if path in backend.saved:
                activity.event(name, "artifact-write", "completed", f"Saved {path}.")
        return result
    return guard


def serializable_response(response):
    # Dynamic validators are request-scoped; persist plain JSON, never local
    # Pydantic classes that cannot be reconstructed after a process restart.
    value = response.structured_response
    return replace(response, structured_response=value.model_dump()) if hasattr(value, "model_dump") else response
