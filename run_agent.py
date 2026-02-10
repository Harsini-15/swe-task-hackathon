import os
import sys
import json
import time
import subprocess
import yaml
import re
from datetime import datetime

# Choose your AI agent client
# This script supports Claude (Anthropic) as the primary agent for the hackathon.
try:
    from anthropic import Anthropic
except ImportError:
    pass

# Configuration - APIs should be provided via GitHub Secrets
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TASK_ID = "internetarchive__openlibrary-c4eebe6677acc4629cb541a98d5e91311444f5d4"

def get_timestamp():
    return datetime.utcnow().isoformat() + "Z"

def log_jsonl(entry):
    """Log actions to agent.log in strict JSONL format."""
    with open("agent.log", "a") as f:
        f.write(json.dumps(entry) + "\n")

def run_bash(command, cwd="/testbed"):
    """Execute bash commands and return output."""
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "run_bash", "args": {"command": command}})
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
        output = result.stdout + result.stderr
        return output, result.returncode
    except Exception as e:
        return str(e), -1

def read_file(path, cwd="/testbed"):
    """Read a file's content."""
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "read_file", "args": {"path": path}})
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    try:
        with open(full_path, "r") as f:
            return f.read(), None
    except Exception as e:
        return None, str(e)

def write_file(path, content, cwd="/testbed"):
    """Write content to a file."""
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "write_file", "args": {"path": path}})
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        return "File written successfully", None
    except Exception as e:
        return None, str(e)

def edit_file(path, old_str, new_str, cwd="/testbed"):
    """Replace content in a file."""
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "edit_file", "args": {"path": path, "old_str": old_str, "new_str": new_str}})
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    try:
        with open(full_path, "r") as f:
            content = f.read()
        if old_str not in content:
            return None, f"String '{old_str}' not found in file."
        new_content = content.replace(old_str, new_str)
        with open(full_path, "w") as f:
            f.write(new_content)
        return "File edited successfully", None
    except Exception as e:
        return None, str(e)

def setup_anthropic():
    if not ANTHROPIC_API_KEY:
        print("Error: ANTHROPIC_API_KEY not found in environment.")
        sys.exit(1)
    return Anthropic(api_key=ANTHROPIC_API_KEY)

def handle_ai_loop(client, task_desc):
    """Main loop for AI agent interaction."""
    system_prompt = f"""You are an expert software engineer fixing a bug in OpenLibrary.
Task: {task_desc}
Instructions:
1. Explore the codebase using read_file and run_bash.
2. Reproduce the bug by running the provided test command.
3. Apply a fix by introducing STAGED_SOURCES = ('amazon', 'idb') and implementing find_staged_or_pending as a classmethod.
4. Verify the fix passes the tests.
Available tools: read_file, write_file, edit_file, run_bash.
"""
    
    messages = [{"role": "user", "content": "Start fixing the bug."}]
    prompts_history = [f"SYSTEM: {system_prompt}", "USER: Start fixing the bug."]
    
    for iteration in range(10): # Max 10 turns
        log_jsonl({"timestamp": get_timestamp(), "type": "request", "content": messages[-1]['content']})
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
            tools=[
                {"name": "run_bash", "description": "Execute bash commands", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
                {"name": "read_file", "description": "Read a file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
                {"name": "write_file", "description": "Write a file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
                {"name": "edit_file", "description": "Edit a file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}, "required": ["path", "old_str", "new_str"]}}
            ]
        )
        
        assistant_msg = response.content[0].text if response.content[0].type == 'text' else "[Tool Use]"
        print(f"Agent: {assistant_msg}")
        messages.append({"role": "assistant", "content": response.content})
        prompts_history.append(f"ASSISTANT: {assistant_msg}")
        
        tool_calls = [c for c in response.content if c.type == 'tool_use']
        if not tool_calls:
            break
            
        tool_results = []
        for tool_call in tool_calls:
            name = tool_call.name
            args = tool_call.input
            if name == "run_bash":
                res, _ = run_bash(args['command'])
            elif name == "read_file":
                res, _ = read_file(args['path'])
            elif name == "write_file":
                res, _ = write_file(args['path'], args['content'])
            elif name == "edit_file":
                res, _ = edit_file(args['path'], args['old_str'], args['new_str'])
            
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": str(res)
            })
            prompts_history.append(f"TOOL {name} RESULT: {res}")
            
        messages.append({"role": "user", "content": tool_results})

    with open("prompts.md", "w") as f:
        f.write("# AI Agent Prompts History\n\n" + "\n\n---\n\n".join(prompts_history))

def main():
    if os.path.exists("agent.log"): os.remove("agent.log")
    
    # 1. Pre-verification
    print("Running Pre-verification tests...")
    # Exact test command from tips
    test_cmd = "cd /testbed && python -m pytest openlibrary/tests/core/test_imports.py::TestImportItem::test_find_staged_or_pending -xvs"
    out, _ = run_bash(test_cmd)
    with open("pre_verification.log", "w") as f: f.write(out)
    
    # 2. AI Fix
    print("Initializing AI Agent...")
    client = setup_anthropic()
    task_desc = "Improve ISBN import logic by using local staged records instead of external API calls in openlibrary/core/imports.py. Use STAGED_SOURCES = ('amazon', 'idb')."
    
    handle_ai_loop(client, task_desc)
    
    # 3. Post-verification
    print("Running Post-verification tests...")
    out, _ = run_bash(test_cmd)
    with open("post_verification.log", "w") as f: f.write(out)
    
    # 4. Generate Patch
    diff, _ = run_bash("git diff", cwd="/testbed")
    with open("changes.patch", "w") as f: f.write(diff)
    
    print("AI Agent run completed.")

if __name__ == "__main__":
    main()
