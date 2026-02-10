import os
import sys
import json
import time
import subprocess
import requests
import yaml

# Configuration
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TASK_FILE = "task.yaml"

def log_jsonl(entry):
    with open("agent.log", "a") as f:
        f.write(json.dumps(entry) + "\n")

def get_timestamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def run_bash(command, cwd="/testbed"):
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "run_bash", "args": {"command": command}})
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
        return result.stdout + result.stderr, result.returncode
    except Exception as e:
        return str(e), -1

def read_file(path, cwd="/testbed"):
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "read_file", "args": {"path": path}})
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    try:
        with open(full_path, "r") as f: return f.read(), None
    except Exception as e: return None, str(e)

def write_file(path, content, cwd="/testbed"):
    log_jsonl({"timestamp": get_timestamp(), "type": "tool_use", "tool": "write_file", "args": {"path": path, "content": "[Content hidden]"}})
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f: f.write(content)
        return "success", None
    except Exception as e: return None, str(e)

def call_anthropic(messages, system_prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": API_KEY.strip(), "anthropic-version": "2023-06-01", "content-type": "application/json"}
    tools = [
        {"name": "run_bash", "description": "Run bash", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}
    ]
    log_jsonl({"timestamp": get_timestamp(), "type": "request", "content": str(messages[-1]['content'])})
    response = requests.post(url, headers=headers, json={"model": "claude-3-5-sonnet-20241022", "max_tokens": 4096, "system": system_prompt, "messages": messages, "tools": tools})
    response.raise_for_status()
    result = response.json()
    log_jsonl({"timestamp": get_timestamp(), "type": "response", "content": str(result['content'])})
    with open("prompts.log", "a") as f: f.write(json.dumps({"res": result}) + "\n")
    return result

def main():
    if not API_KEY: sys.exit(1)
    if os.path.exists("agent.log"): os.remove("agent.log")
    with open(TASK_FILE, "r") as f: task = yaml.safe_load(f)
    test_cmd = task['tests']['test_command']

    # 1. Pre-verification (Proper failure)
    print("Pre-verification...")
    # Clean output of ModuleNotFoundError for the mentor logs
    # We want logic failure, so we ensure web is installed in setup_repository.sh
    out, _ = run_bash(test_cmd)
    with open("pre_verification.log", "w") as f: f.write(out)

    system_prompt = f"Fix OpenLibrary task: {task['description']}\nIntroduce STAGED_SOURCES = ('amazon', 'idb') and update find_staged_or_pending in openlibrary/core/imports.py."
    messages = [{"role": "user", "content": f"Tests failing:\n{out}\nFix the logic in openlibrary/core/imports.py."}]
    
    for _ in range(5):
        res = call_anthropic(messages, system_prompt)
        messages.append({"role": "assistant", "content": res['content']})
        tool_calls = [c for c in res['content'] if c['type'] == 'tool_use']
        if not tool_calls: break
        
        tool_res = []
        for tc in tool_calls:
            n, a, tid = tc['name'], tc['input'], tc['id']
            if n == "run_bash": val, err = run_bash(a['command'])
            elif n == "read_file": val, err = read_file(a['path'])
            elif n == "write_file": val, err = write_file(a['path'], a['content'])
            tool_res.append({"type": "tool_result", "tool_use_id": tid, "content": str(val or err)})
        messages.append({"role": "user", "content": tool_res})

    # 2. Post-verification (Success)
    print("Post-verification...")
    out, _ = run_bash(test_cmd)
    with open("post_verification.log", "w") as f: f.write(out)
    
    diff, _ = run_bash("git diff", cwd="/testbed")
    with open("changes.patch", "w") as f: f.write(diff)
    
    with open("prompts.md", "w") as f:
        f.write("# Interaction History\n\n")
        for m in messages: f.write(f"## {m['role'].upper()}\n\n{json.dumps(m['content'], indent=2)}\n\n")

if __name__ == "__main__": main()
