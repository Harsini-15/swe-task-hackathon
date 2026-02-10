import os
import sys
import json
import time
import subprocess
import requests
import yaml
import re

# Configuration
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODELS = [
    "claude-3-5-sonnet-20241022",
    "claude-3-5-sonnet-20240620", 
    "claude-3-haiku-20240307",
]
TASK_FILE = "task.yaml"

def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def log_agent_action(action_type, content, extra=None):
    """Log formatted entries to agent.log as per hackathon requirements."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": action_type,
    }
    if action_type == "request":
        entry["content"] = content
    elif action_type == "response":
        entry["content"] = content
    elif action_type == "tool_use":
        entry["tool"] = extra.get("tool")
        entry["args"] = extra.get("args")
    
    with open("agent.log", "a") as f:
        f.write(json.dumps(entry) + "\n")

def run_bash(command, cwd="/testbed"):
    """Execute bash commands and return output."""
    log(f"Executing: {command}")
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd
        )
        output = result.stdout + result.stderr
        log_agent_action("tool_use", None, {"tool": "run_bash", "args": {"command": command}})
        return {"output": output, "exit_code": result.returncode}
    except Exception as e:
        return {"output": str(e), "exit_code": -1}

def read_file(path, cwd="/testbed"):
    """Read file content."""
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    log(f"Reading: {path}")
    try:
        with open(full_path, "r") as f:
            content = f.read()
        log_agent_action("tool_use", None, {"tool": "read_file", "args": {"path": path}})
        return {"content": content}
    except Exception as e:
        return {"error": str(e)}

def write_file(path, content, cwd="/testbed"):
    """Write or overwrite file content."""
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    log(f"Writing: {path}")
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f:
            f.write(content)
        log_agent_action("tool_use", None, {"tool": "write_file", "args": {"path": path, "content": "[Content hidden]"}})
        return {"status": "success"}
    except Exception as e:
        return {"error": str(e)}

def call_anthropic_with_tools(messages, system_prompt, model):
    """Call Anthropic API with tool definitions."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": API_KEY.strip(),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    tools = [
        {
            "name": "run_bash",
            "description": "Run a bash command in the /testbed environment.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command to run."}
                },
                "required": ["command"]
            }
        },
        {
            "name": "read_file",
            "description": "Read the contents of a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file."}
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file",
            "description": "Write content to a file. Overwrites existing file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "The path to the file."},
                    "content": {"type": "string", "description": "The content to write."}
                },
                "required": ["path", "content"]
            }
        }
    ]

    last_user_msg = ""
    for m in reversed(messages):
        if m['role'] == 'user' and isinstance(m['content'], str):
            last_user_msg = m['content']
            break
    
    log_agent_action("request", last_user_msg)

    data = {
        "model": model,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": messages,
        "tools": tools
    }

    response = requests.post(url, headers=headers, json=data)
    response.raise_for_status()
    result = response.json()
    
    # Log to prompts.log
    with open("prompts.log", "a") as f:
        f.write(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "request",
            "model": model,
            "messages": messages
        }) + "\n")
        f.write(json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "type": "response",
            "model": model,
            "response": result
        }) + "\n")
        
    response_text = ""
    for content in result['content']:
        if content['type'] == 'text':
            response_text += content['text']
    
    log_agent_action("response", response_text or "[Tool Use Only]")
    return result

def main():
    log("=== STARTING AGENT WORKFLOW ===")
    
    if os.path.exists("agent.log"): os.remove("agent.log")
    if os.path.exists("prompts.log"): os.remove("prompts.log")
    
    if not API_KEY:
        log("CRITICAL ERROR: ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    with open(TASK_FILE, "r") as f:
        task = yaml.safe_load(f)

    # Pre-Verification
    log("Running pre-verification...")
    pre_result = run_bash(task['tests']['test_command'])
    with open("pre_verification.log", "w") as f:
        f.write(pre_result['output'])
    
    system_prompt = f"""You are an expert AI software engineer. Solve the task in /testbed.

TASK ID: {task['task_id']}
TITLE: {task['title']}
DESCRIPTION:
{task['description']}

REQUIREMENTS:
{task['requirements']}

INTERFACE SPEC:
{task['interface']}

FILES TO MODIFY (HINTS):
{', '.join(task.get('files_to_modify', []))}

You MUST:
1. Examine the codebase to understand the current implementation.
2. Reproduce the issue using the provided test command.
3. Apply a fix by editing the files.
4. Verify the fix by running the tests again.
5. Once tests pass, you are done.

Use your tools to solve this!
"""

    messages = [{"role": "user", "content": f"The following tests are failing:\n{pre_result['output']}\nPlease fix the implementation."}]
    
    # Agent Loop
    for i in range(15): # Max 15 turns
        try:
            response = call_anthropic_with_tools(messages, system_prompt, MODELS[0])
            messages.append({"role": "assistant", "content": response['content']})
            
            tool_calls = [c for c in response['content'] if c['type'] == 'tool_use']
            if not tool_calls:
                log("Agent stopped without further tool calls.")
                break
            
            tool_results = []
            for tool in tool_calls:
                name = tool['name']
                args = tool['input']
                t_id = tool['id']
                
                if name == "run_bash":
                    res = run_bash(args['command'])
                    tool_results.append({"type": "tool_result", "tool_use_id": t_id, "content": res['output']})
                elif name == "read_file":
                    res = read_file(args['path'])
                    tool_results.append({"type": "tool_result", "tool_use_id": t_id, "content": res.get('content') or res.get('error') or "Empty file"})
                elif name == "write_file":
                    res = write_file(args['path'], args['content'])
                    tool_results.append({"type": "tool_result", "tool_use_id": t_id, "content": res.get('status') or res.get('error')})
            
            messages.append({"role": "user", "content": tool_results})
            
        except Exception as e:
            log(f"Error in agent loop: {e}")
            break

    # Final Verification
    log("Running post-verification...")
    post_result = run_bash(task['tests']['test_command'])
    with open("post_verification.log", "w") as f:
        f.write(post_result['output'])
    
    # Generate patch
    res = run_bash("git diff", cwd="/testbed")
    with open("changes.patch", "w") as f:
        f.write(res['output'])
    
    # Generate prompts.md
    with open("prompts.md", "w") as f:
        f.write("# Agent Prompt History\n\n")
        f.write(f"## System Prompt\n\n```\n{system_prompt}\n```\n\n")
        for m in messages:
            role = m['role'].upper()
            content = m['content']
            f.write(f"## {role}\n\n")
            if isinstance(content, str):
                f.write(content + "\n\n")
            else:
                f.write(json.dumps(content, indent=2) + "\n\n")

    log("=== AGENT WORKFLOW COMPLETE ===")

if __name__ == "__main__":
    main()
