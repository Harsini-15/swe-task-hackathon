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
    "claude-3-5-sonnet-20241022", # Newest Sonnet
    "claude-3-5-sonnet-20240620", 
    "claude-3-haiku-20240307",
]
TASK_FILE = "task.yaml"
ARTIFACTS_DIR = "."

def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

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
        # Log action to agent.log
        with open("agent.log", "a") as f:
            f.write(json.dumps({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "type": "tool_use",
                "tool": "run_bash",
                "args": {"command": command},
                "exit_code": result.returncode
            }) + "\n")
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
        with open("agent.log", "a") as f:
            f.write(json.dumps({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "type": "tool_use",
                "tool": "read_file",
                "args": {"path": path}
            }) + "\n")
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
        with open("agent.log", "a") as f:
            f.write(json.dumps({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "type": "tool_use",
                "tool": "write_file",
                "args": {"path": path}
            }) + "\n")
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
            "description": "Write content to a file.",
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
        
    return result

def main():
    log("=== STARTING AGENT WORKFLOW ===")
    
    if not API_KEY:
        log("CRITICAL ERROR: ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    # Load Task
    with open(TASK_FILE, "r") as f:
        task = yaml.safe_load(f)
    
    # Init Logs
    with open("agent.log", "w") as f: 
        f.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "type": "info", "content": "Agent started"}) + "\n")

    # Reproduction
    log("Running pre-verification...")
    pre_result = run_bash(task['tests']['test_command'])
    with open("pre_verification.log", "w") as f:
        f.write(pre_result['output'])
    
    system_prompt = f"""You are an autonomous AI coding agent. Your goal is to solve the following task in the OpenLibrary codebase.
Task ID: {task['task_id']}
Title: {task['title']}
Description: {task['description']}

Requirements:
{task['requirements']}

Interface:
{task['interface']}

The codebase is located in /testbed. You can run tests, read files, and write files.
After you apply your fix, you must verify it by running the tests again.
When you are done and the tests pass, provide a short summary of your changes.
"""

    messages = [{"role": "user", "content": f"Initial test failure:\n{pre_result['output']}"}]
    
    # Agent Loop
    for _ in range(10): # Max 10 turns
        try:
            response = call_anthropic_with_tools(messages, system_prompt, MODELS[0])
            messages.append({"role": "assistant", "content": response['content']})
            
            tool_use = [c for c in response['content'] if c['type'] == 'tool_use']
            if not tool_use:
                log("Agent finished task.")
                break
            
            tool_results = []
            for tool in tool_use:
                name = tool['name']
                args = tool['input']
                t_id = tool['id']
                
                if name == "run_bash":
                    res = run_bash(args['command'])
                    tool_results.append({"type": "tool_result", "tool_use_id": t_id, "content": res['output']})
                elif name == "read_file":
                    res = read_file(args['path'])
                    tool_results.append({"type": "tool_result", "tool_use_id": t_id, "content": res.get('content') or res.get('error')})
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
    run_bash("cd /testbed && git diff > /github/workspace/changes.patch", cwd="/testbed")
    # Also save it locally in case workspace path differs
    run_bash("cd /testbed && git diff > changes.patch", cwd="/testbed")
    
    log("=== AGENT WORKFLOW COMPLETE ===")

if __name__ == "__main__":
    main()
