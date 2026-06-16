"""
Ponytail Bifrost benchmark - runs the same 5 tasks against any model exposed
through the Bifrost AI gateway.

Usage:
    CXP_API_KEY=... python benchmarks/benchmark-bifrost.py
    CXP_API_KEY=... python benchmarks/benchmark-bifrost.py --model "netvlies/gemma4-26b" --repeat 3

Prerequisites: a valid CXP_API_KEY environment variable.
"""

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent

TASKS = [
    ("email",      "Write me a Python function that validates email addresses."),
    ("debounce",   "Add debounce to a search input in vanilla JavaScript. It currently fires an API call on every keystroke."),
    ("csv-sum",    "Write Python code that reads sales.csv and sums the 'amount' column."),
    ("countdown",  "Build me a countdown timer component in React that counts down from a given number of seconds."),
    ("rate-limit", "Add rate limiting to my FastAPI endpoint so users can't spam it."),
]


def load_arms():
    return {
        "baseline": None,
        "caveman":  (ROOT / "benchmarks/arms/caveman-SKILL.md").read_text(encoding="utf-8"),
        "ponytail": (ROOT / "skills/ponytail/SKILL.md").read_text(encoding="utf-8"),
    }


def count_loc(text):
    """Non-blank, non-comment lines of code: fenced blocks, or the whole
    response when the model emitted bare code with no fence."""
    blocks = re.findall(r"```[a-zA-Z0-9_+\-]*\n([\s\S]*?)```", text)
    lines = ("\n".join(blocks) if blocks else text).splitlines()
    return sum(
        1 for line in lines
        if line.strip()
        and not line.strip().startswith("//")
        and not line.strip().startswith("#")
        and line.strip() not in ("*/",)
        and not line.strip().startswith("/*")
        and not line.strip().startswith("*")
    )


def get_api_key():
    api_key = os.environ.get("CXP_API_KEY")
    if not api_key:
        raise RuntimeError("CXP_API_KEY is required")
    return api_key


def extract_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Bifrost response shape: {data}") from exc


def call_bifrost(model, system_prompt, user_prompt, gateway_url, api_key):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.7,
    }).encode()

    req = urllib.request.Request(
        f"{gateway_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.7.1",
        },
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bifrost request failed with HTTP {exc.code}: {body}") from exc
    elapsed = time.time() - t0
    return extract_content(data), round(elapsed, 1)


def run(model, repeat, gateway_url):
    api_key = get_api_key()
    arms = load_arms()
    task_ids = [task[0] for task in TASKS]
    results = {arm: {task_id: [] for task_id in task_ids} for arm in arms}
    total = len(arms) * len(TASKS) * repeat

    done = 0
    for run_index in range(repeat):
        for arm, system in arms.items():
            for task_id, task_prompt in TASKS:
                done += 1
                label = f"[{done}/{total}] run{run_index + 1} {arm:10s} / {task_id}"
                print(f"{label} ...", end=" ", flush=True)
                response, elapsed = call_bifrost(model, system, task_prompt, gateway_url, api_key)
                loc = count_loc(response)
                results[arm][task_id].append({"loc": loc, "time": elapsed, "response": response})
                print(f"{loc} LOC  {elapsed}s")

    def median(values):
        sorted_values = sorted(values)
        count = len(sorted_values)
        return (
            sorted_values[count // 2]
            if count % 2
            else (sorted_values[count // 2 - 1] + sorted_values[count // 2]) / 2
        )

    med_loc = {
        arm: {task_id: median([result["loc"] for result in results[arm][task_id]]) for task_id in task_ids}
        for arm in arms
    }
    med_time = {
        arm: {task_id: median([result["time"] for result in results[arm][task_id]]) for task_id in task_ids}
        for arm in arms
    }

    col = 12
    header = f"{'arm':<12}" + "".join(f"{task_id:>{col}}" for task_id in task_ids) + f"{'TOTAL':>{col}}"
    sep = "-" * len(header)

    print(f"\n{'=' * 60}")
    print(f"  RESULTS - {model}  (n={repeat}, median)")
    print(f"{'=' * 60}")

    print("\nCode LOC per task (median)")
    print(header)
    print(sep)
    for arm in arms:
        row = [med_loc[arm][task_id] for task_id in task_ids]
        print(f"{arm:<12}" + "".join(f"{value:>{col}}" for value in row) + f"{sum(row):>{col}}")

    print("\nTime seconds per task (median)")
    print(header)
    print(sep)
    for arm in arms:
        row = [med_time[arm][task_id] for task_id in task_ids]
        print(f"{arm:<12}" + "".join(f"{value:>{col}.1f}" for value in row) + f"{sum(row):>{col}.1f}")

    print(f"\n{'=' * 60}")
    print("  LOC vs baseline (median totals)")
    print(f"{'=' * 60}")
    base_total = sum(med_loc["baseline"][task_id] for task_id in task_ids)
    for arm in ("caveman", "ponytail"):
        arm_total = sum(med_loc[arm][task_id] for task_id in task_ids)
        pct = (1 - arm_total / base_total) * 100 if base_total else 0
        sign = "less" if pct >= 0 else "more"
        print(f"  {arm:10s}: {arm_total} LOC  ({abs(pct):.0f}% {sign} than baseline)")

    out = Path(__file__).parent / "benchmark-bifrost-results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nFull responses -> {out}")


def main():
    parser = argparse.ArgumentParser(description="Ponytail benchmark via Bifrost AI gateway")
    parser.add_argument("--model", default="gpt-4.1", help="Model name exposed by Bifrost (default: gpt-4.1)")
    parser.add_argument("--repeat", type=int, default=1, help="Runs per cell; median reported (default: 1)")
    parser.add_argument("--gateway-url", default="https://ai.netvlies.nl/v1", help="Bifrost base URL")
    args = parser.parse_args()
    run(args.model, args.repeat, args.gateway_url)


if __name__ == "__main__":
    main()