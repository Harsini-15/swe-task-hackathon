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
]
TASK_FILE = "task.yaml"

def log(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def log_agent_action(action_type, content=None, tool=None, args=None):
    """Log formatted entries to agent.log as per hackathon requirements."""
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": action_type,
    }
    if action_type == "request" or action_type == "response":
        entry["content"] = content
    elif action_type == "tool_use":
        entry["tool"] = tool
        entry["args"] = args
    
    with open("agent.log", "a") as f:
        f.write(json.dumps(entry) + "\n")

def run_bash(command, cwd="/testbed"):
    log(f"Executing: {command}")
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, cwd=cwd)
        output = result.stdout + result.stderr
        log_agent_action("tool_use", tool="run_bash", args={"command": command})
        return {"output": output, "exit_code": result.returncode}
    except Exception as e:
        return {"output": str(e), "exit_code": -1}

def read_file(path, cwd="/testbed"):
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    log(f"Reading: {path}")
    try:
        if not os.path.exists(full_path): return {"error": f"File {path} not found"}
        with open(full_path, "r") as f: content = f.read()
        log_agent_action("tool_use", tool="read_file", args={"path": path})
        return {"content": content}
    except Exception as e: return {"error": str(e)}

def write_file(path, content, cwd="/testbed"):
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    log(f"Writing: {path}")
    try:
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as f: f.write(content)
        log_agent_action("tool_use", tool="write_file", args={"path": path, "content": "[Content hidden]"})
        return {"status": "success"}
    except Exception as e: return {"error": str(e)}

def edit_file(path, old_str, new_str, cwd="/testbed"):
    full_path = os.path.join(cwd, path) if not path.startswith("/") else path
    log(f"Editing: {path}")
    try:
        with open(full_path, "r") as f: content = f.read()
        if old_str not in content: return {"error": "Target string not found in file"}
        new_content = content.replace(old_str, new_str)
        with open(full_path, "w") as f: f.write(new_content)
        log_agent_action("tool_use", tool="edit_file", args={"path": path, "old_str": old_str, "new_str": new_str})
        return {"status": "success"}
    except Exception as e: return {"error": str(e)}

def call_anthropic(messages, system_prompt):
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": API_KEY.strip(), "anthropic-version": "2023-06-01", "content-type": "application/json"}
    
    tools = [
        {"name": "run_bash", "description": "Run bash command.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
        {"name": "edit_file", "description": "Replace text in file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "old_str": {"type": "string"}, "new_str": {"type": "string"}}, "required": ["path", "old_str", "new_str"]}}
    ]

    last_user_msg = messages[-1]['content'] if isinstance(messages[-1]['content'], str) else "Tool Results"
    log_agent_action("request", content=last_user_msg)

    response = requests.post(url, headers=headers, json={"model": MODELS[0], "max_tokens": 4096, "system": system_prompt, "messages": messages, "tools": tools})
    response.raise_for_status()
    result = response.json()
    
    with open("prompts.log", "a") as f: f.write(json.dumps({"ts": time.time(), "req": messages, "res": result}) + "\n")
    
    resp_text = "".join([c['text'] for c in result['content'] if c['type'] == 'text'])
    log_agent_action("response", content=resp_text or "[Tool Use]")
    return result

def main():
    if not API_KEY: sys.exit(1)
    if os.path.exists("agent.log"): os.remove("agent.log")
    
    with open(TASK_FILE, "r") as f: task = yaml.safe_load(f)
    test_cmd = task['tests']['test_command']

    log("Pre-verification...")
    pre = run_bash(test_cmd)
    with open("pre_verification.log", "w") as f: f.write(pre['output'])
    
    sys_prompt = f"Fix this OpenLibrary task: {task['task_id']}\n{task['description']}\nRequirements:\n{task['requirements']}\nInterface:\n{task['interface']}\nReproduce with: {test_cmd}"
    msgs = [{"role": "user", "content": f"Tests failed:\n{pre['output']}\nFix the logic."}]
    
    for _ in range(15):
        try:
            res = call_anthropic(msgs, sys_prompt)
            msgs.append({"role": "assistant", "content": res['content']})
            tool_calls = [c for c in res['content'] if c['type'] == 'tool_use']
            if not tool_calls: break
            
            tool_res = []
            for t in tool_calls:
                n, a, tid = t['name'], t['input'], t['id']
                if n == "run_bash": r = run_bash(a['command'])
                elif n == "read_file": r = read_file(a['path'])
                elif n == "write_file": r = write_file(a['path'], a['content'])
                elif n == "edit_file": r = edit_file(a['path'], a['old_str'], a['new_str'])
                tool_res.append({"type": "tool_result", "tool_use_id": tid, "content": str(r.get('output') or r.get('content') or r.get('status') or r.get('error'))})
            msgs.append({"role": "user", "content": tool_res})
        except Exception as e: break

    log("Post-verification...")
    post = run_bash(test_cmd)
    with open("post_verification.log", "w") as f: f.write(post['output'])
    
    res = run_bash("git diff", cwd="/testbed")
    with open("changes.patch", "w") as f: f.write(res['output'])
    
    with open("prompts.md", "w") as f:
        f.write("# Prompts\n\n")
        for m in msgs: f.write(f"## {m['role'].upper()}\n\n{json.dumps(m['content'], indent=2)}\n\n")

if __name__ == "__main__": main()
