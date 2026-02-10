import json
import os
import re
import time

# Model pricing per 1k tokens
MODEL_PRICING = {
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
    "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
}

LOG_FILES = {
    "pre": "pre_verification.log",
    "post": "post_verification.log",
    "agent": "agent.log",
    "prompts": "prompts.log"
}

OUTPUT_FILE = "result.json"

def parse_pytest_output(content):
    """Parse pytest output for pass/fail counts."""
    if not content:
        return {"passed": 0, "failed": 0, "error": True}
    
    # Check for failure in output
    failed_match = re.search(r"(\d+) failed", content)
    passed_match = re.search(r"(\d+) passed", content)
    
    failed = int(failed_match.group(1)) if failed_match else 0
    passed = int(passed_match.group(1)) if passed_match else 0
    
    # If explicitly "PASSED" or "FAILED" on individual tests, count them if summary is missing
    if failed == 0 and passed == 0:
        failed = len(re.findall(r"FAILED", content))
        passed = len(re.findall(r"PASSED", content))
        
    return {"passed": passed, "failed": failed, "error": False}

def main():
    start_time = time.time()
    
    # 1. Initialize result structure
    result = {
        "resolved": False,
        "duration_seconds": 0,
        "total_cost_usd": 0.0,
        "tokens": {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0
        },
        "tool_usage": {
            "read": 0,
            "write": 0,
            "edit": 0,
            "bash": 0
        }
    }

    # 2. Extract metrics from prompts.log
    if os.path.exists(LOG_FILES['prompts']):
        with open(LOG_FILES['prompts'], 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "response":
                        usage = entry.get("response", {}).get("usage", {})
                        result["tokens"]["input"] += usage.get("input_tokens", 0)
                        result["tokens"]["output"] += usage.get("output_tokens", 0)
                        
                        model = entry.get("model")
                        if model in MODEL_PRICING:
                            pricing = MODEL_PRICING[model]
                            result["total_cost_usd"] += (usage.get("input_tokens", 0) / 1000 * pricing["input"])
                            result["total_cost_usd"] += (usage.get("output_tokens", 0) / 1000 * pricing["output"])
                except:
                    continue

    # 3. Extract tool usage from agent.log
    if os.path.exists(LOG_FILES['agent']):
        with open(LOG_FILES['agent'], 'r') as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("type") == "tool_use":
                        tool = entry.get("tool")
                        if tool == "read_file":
                            result["tool_usage"]["read"] += 1
                        elif tool == "write_file":
                            result["tool_usage"]["write"] += 1
                        elif tool == "run_bash":
                            result["tool_usage"]["bash"] += 1
                        elif "edit" in tool:
                            result["tool_usage"]["edit"] += 1
                except:
                    continue

    # 4. Determine resolution from test logs
    pre_stats = {"failed": 0, "passed": 0}
    post_stats = {"failed": 0, "passed": 0}
    
    if os.path.exists(LOG_FILES['pre']):
        with open(LOG_FILES['pre'], 'r') as f:
            pre_stats = parse_pytest_output(f.read())
            
    if os.path.exists(LOG_FILES['post']):
        with open(LOG_FILES['post'], 'r') as f:
            post_stats = parse_pytest_output(f.read())
            
    # Task is resolved if pre failed but post passed (or at least improved)
    # Standard SWE-bench criteria: fail-to-pass tests must all pass
    if pre_stats['failed'] > 0 and post_stats['failed'] == 0 and post_stats['passed'] > 0:
        result["resolved"] = True
    
    # Fill in duration (rough estimate from file mtime if needed, but we can just use 0 or something)
    # Actually, let's use the actual duration if possible.
    if os.path.exists(LOG_FILES['agent']):
        mtime = os.path.getmtime(LOG_FILES['agent'])
        ctime = os.path.getctime(LOG_FILES['agent'])
        result["duration_seconds"] = int(mtime - ctime)
    
    result["total_cost_usd"] = round(result["total_cost_usd"], 4)

    # 5. Output JSON
    print(f"Final resolution: {result['resolved']}")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(result, f, indent=2)

if __name__ == "__main__":
    main()
