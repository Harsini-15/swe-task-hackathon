
import json
import os
import re
import time

# Model pricing per 1k tokens (as of 2024)
MODEL_PRICING = {
    "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
    "claude-3-5-sonnet-20240620": {"input": 0.003, "output": 0.015},
    "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
    "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
}


LOG_FILES = {
    "pre": "pre_verification.log",
    "post": "post_verification.log",
    "agent": "agent.log",
    "prompts": "prompts.log"
}

OUTPUT_FILE = "result.json"

def parse_pytest_output(content):
    """
    Parse pytest output to find number of passed/failed tests.
    """
    if "no tests ran" in content:
        return {"passed": 0, "failed": 0, "error": True}
        
    # Look for the final summary line: "== 1 failed, 4 passed in 0.12s =="
    match = re.search(r"=+\s+(?:(\d+)\s+failed,?)?\s*(?:(\d+)\s+passed,?)?.*=+", content)
    if match:
        failed = int(match.group(1)) if match.group(1) else 0
        passed = int(match.group(2)) if match.group(2) else 0
        return {"passed": passed, "failed": failed, "error": False}
        
    return {"passed": 0, "failed": 0, "error": False}

def extract_metrics_from_prompts_log():
    """Extract timing, token, and cost metrics from prompts.log"""
    if not os.path.exists(LOG_FILES['prompts']):
        return None
    
    total_input_tokens = 0
    total_output_tokens = 0
    model_used = None
    timestamps = []
    
    with open(LOG_FILES['prompts'], 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                
                # Track timestamps
                if 'timestamp' in entry:
                    timestamps.append(entry['timestamp'])
                
                # Extract model
                if 'model' in entry and not model_used:
                    model_used = entry['model']
                
                # Extract tokens from response
                if entry.get('type') == 'response' and 'response' in entry:
                    response = entry['response']
                    usage = response.get('usage', {})
                    total_input_tokens += usage.get('input_tokens', 0)
                    total_output_tokens += usage.get('output_tokens', 0)
                    
            except json.JSONDecodeError:
                continue
    
    # Calculate duration (simple: count lines as proxy if timestamps not parseable)
    duration = len(timestamps) * 2 if timestamps else 0
    
    # Calculate cost
    cost = 0.0
    if model_used and model_used in MODEL_PRICING:
        pricing = MODEL_PRICING[model_used]
        cost = (total_input_tokens / 1000 * pricing["input"] + 
                total_output_tokens / 1000 * pricing["output"])
    
    return {
        "duration_seconds": duration,
        "total_cost_usd": round(cost, 3),
        "tokens": {
            "input": total_input_tokens,
            "output": total_output_tokens,
            "cache_read": 0,
            "cache_write": 0
        },
        "model_used": model_used
    }

def extract_tool_usage_from_agent_log():
    """Extract tool usage counts from agent.log"""
    tool_usage = {"read": 0, "write": 0, "edit": 0, "bash": 0}
    
    if not os.path.exists(LOG_FILES['agent']):
        return tool_usage
    
    with open(LOG_FILES['agent'], 'r') as f:
        for line in f:
            try:
                entry = json.loads(line)
                if entry.get("type") == "tool_use":
                    tool_name = entry.get("tool", "")
                    if "read" in tool_name.lower():
                        tool_usage["read"] += 1
                    elif "write" in tool_name.lower():
                        tool_usage["write"] += 1
                    elif "edit" in tool_name.lower():
                        tool_usage["edit"] += 1
                    elif "bash" in tool_name.lower() or "command" in tool_name.lower():
                        tool_usage["bash"] += 1
            except json.JSONDecodeError:
                continue
    
    return tool_usage


def main():
    metrics = {
        "agent_actions": 0,
        "pre_verification_status": "unknown",
        "post_verification_status": "unknown", 
        "resolved": False,
        "details": {}
    }

    # 1. Analyze Agent Logs
    if os.path.exists(LOG_FILES['agent']):
        with open(LOG_FILES['agent'], 'r') as f:
            lines = f.readlines()
            metrics['agent_actions'] = len(lines)

    # 2. Analyze Pre-Verification
    if os.path.exists(LOG_FILES['pre']):
        with open(LOG_FILES['pre'], 'r') as f:
            pre_content = f.read()
        pre_stats = parse_pytest_output(pre_content)
        metrics['details']['pre'] = pre_stats
        # Pre-verification is "successful" if it FAILS (demonstrating the bug)
        if pre_stats['failed'] > 0:
            metrics['pre_verification_status'] = "success_failure_reproduced"
        else:
            metrics['pre_verification_status'] = "unexpected_pass"
    else:
        metrics['pre_verification_status'] = "missing_log"

    # 3. Analyze Post-Verification
    if os.path.exists(LOG_FILES['post']):
        with open(LOG_FILES['post'], 'r') as f:
            post_content = f.read()
        post_stats = parse_pytest_output(post_content)
        metrics['details']['post'] = post_stats
        
        # Post-verification is successful if NO tests failed
        if post_stats['failed'] == 0 and post_stats['passed'] > 0:
            metrics['post_verification_status'] = "success_fixed"
        else:
            metrics['post_verification_status'] = "failed_fix"
    else:
        metrics['post_verification_status'] = "missing_log"

    # 4. Determine Resolution
    if (metrics['pre_verification_status'] == "success_failure_reproduced" and 
        metrics['post_verification_status'] == "success_fixed"):
        metrics['resolved'] = True
    else:
        metrics['resolved'] = False

    # 5. Add Enhanced Metrics
    enhanced = extract_metrics_from_prompts_log()
    if enhanced:
        metrics.update(enhanced)
    
    metrics["tool_usage"] = extract_tool_usage_from_agent_log()

    # 6. Write Result
    print(f"Generating {OUTPUT_FILE} with metrics: {metrics}")
    with open(OUTPUT_FILE, "w") as f:
        json.dump(metrics, f, indent=4)

if __name__ == "__main__":
    main()
