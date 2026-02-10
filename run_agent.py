import os
import sys
import json
import time
import subprocess
import yaml
from anthropic import Anthropic

# Configuration
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
TASK_FILE = "task.yaml"
# Using the most universally available Sonnet 3.5 model
MODELS = ["claude-3-5-sonnet-20240620", "claude-3-5-sonnet-latest", "claude-3-sonnet-20240229"]

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

def call_anthropic(client, messages, system_prompt):
    tools = [
        {"name": "run_bash", "description": "Run bash", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
        {"name": "read_file", "description": "Read file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
        {"name": "write_file", "description": "Write file", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}
    ]
    
    log_jsonl({"timestamp": get_timestamp(), "type": "request", "content": str(messages[-1]['content'])})
    
    # Try models in order until one works (handles 404/NotFoundError)
    for model_name in MODELS:
        try:
            print(f"Attempting to call Anthropic with model: {model_name}")
            response = client.messages.create(
                model=model_name,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
                tools=tools
            )
            log_jsonl({"timestamp": get_timestamp(), "type": "response", "content": str(response.content)})
            return response
        except Exception as e:
            print(f"Error with model {model_name}: {e}")
            if "not_found_error" in str(e).lower() or "not found" in str(e).lower():
                continue
            raise e
    raise Exception("No available models found")

def main():
    if not API_KEY:
        print("API Key not found!")
        sys.exit(1)
        
    client = Anthropic(api_key=API_KEY)
    if os.path.exists("agent.log"): os.remove("agent.log")
    with open(TASK_FILE, "r") as f: task = yaml.safe_load(f)
    test_cmd = task['tests']['test_command']

    print("Pre-verification...")
    out, _ = run_bash(test_cmd)
    with open("pre_verification.log", "w") as f: f.write(out)

    system_prompt = f"Fix OpenLibrary ISBN logic. Edit openlibrary/core/imports.py to use local staged records. Introduce STAGED_SOURCES = ('amazon', 'idb'). Ensure you use tools to apply changes."
    messages = [{"role": "user", "content": f"Tests failing:\n{out}\nPlease fix the logic to use local staged records instead of external API calls."}]
    
    for i in range(5):
        try:
            res = call_anthropic(client, messages, system_prompt)
            messages.append({"role": "assistant", "content": res.content})
            
            tool_calls = [c for c in res.content if c.type == 'tool_use']
            if not tool_calls: break
            
            tool_res = []
            for tc in tool_calls:
                n, a, tid = tc.name, tc.input, tc.id
                print(f"Agent using tool: {n}")
                if n == "run_bash": val, err = run_bash(a['command'])
                elif n == "read_file": val, err = read_file(a['path'])
                elif n == "write_file": val, err = write_file(a['path'], a['content'])
                tool_res.append({"type": "tool_result", "tool_use_id": tid, "content": str(val or err)})
            messages.append({"role": "user", "content": tool_res})
        except Exception as e:
            print(f"Error in agent loop: {e}")
            break

    print("Post-verification...")
    out, _ = run_bash(test_cmd)
    with open("post_verification.log", "w") as f: f.write(out)
    
    diff, _ = run_bash("git diff", cwd="/testbed")
    with open("changes.patch", "w") as f: f.write(diff)
    
    with open("prompts.md", "w") as f:
        f.write("# Engineering History\n\n")
        for m in messages:
            role = m['role'].upper()
            content = m['content']
            if isinstance(content, list):
                # Format tool calls/results for clarity
                str_content = json.dumps([str(c) for c in content], indent=2)
            else:
                str_content = str(content)
            f.write(f"## {role}\n\n{str_content}\n\n")

if __name__ == "__main__": main()
