"""
Turn benchmark JSON into a Markdown write-up by asking the selected model to
interpret locally computed summary statistics.

Examples:
    python3 benchmarks/benchmark-interpret.py \
        --input benchmarks/benchmark-bifrost-results.json \
        --provider bifrost \
        --model "netvlies/gemma4-26b"

    python3 benchmarks/benchmark-interpret.py \
        --input benchmarks/benchmark-local-results.json \
        --provider ollama \
        --model llama3.2 \
        --repeat 5
"""

import argparse
import datetime as dt
import json
import os
import re
import statistics
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_GATEWAY_URL = "https://ai.netvlies.nl/v1"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_TASK_IDS = ["email", "debounce", "csv-sum", "countdown", "rate-limit"]
TASK_LABELS = {
    "email": "email",
    "debounce": "debounce",
    "csv-sum": "csv-sum",
    "countdown": "countdown",
    "rate-limit": "rate-limit",
}


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def strip_code_fences(text):
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n([\s\S]*?)\n```", stripped)
    return match.group(1).strip() if match else stripped


def load_results(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise RuntimeError(f"Unexpected results JSON shape in {path}")
    return data


def median(values):
    return statistics.median(values)


def summarize_results(results):
    arms = list(results.keys())
    task_ids = list(results[arms[0]].keys()) if arms else []
    if not task_ids:
        task_ids = DEFAULT_TASK_IDS

    sample_sizes = {
        arm: {task_id: len(results[arm][task_id]) for task_id in task_ids}
        for arm in arms
    }
    n_values = {count for arm_counts in sample_sizes.values() for count in arm_counts.values()}
    if len(n_values) != 1:
        raise RuntimeError(f"Inconsistent sample sizes in results JSON: {sample_sizes}")
    repeat = n_values.pop() if n_values else 0

    med_loc = {}
    med_time = {}
    total_loc_runs = {}
    total_time_runs = {}
    response_examples = {}

    for arm in arms:
        med_loc[arm] = {}
        med_time[arm] = {}
        total_loc_runs[arm] = []
        total_time_runs[arm] = []
        response_examples[arm] = {}
        for task_id in task_ids:
            rows = results[arm][task_id]
            loc_values = [row["loc"] for row in rows]
            time_values = [row["time"] for row in rows]
            med_loc[arm][task_id] = median(loc_values)
            med_time[arm][task_id] = median(time_values)
            response_examples[arm][task_id] = rows[0]["response"][:600] if rows else ""

        for run_index in range(repeat):
            total_loc_runs[arm].append(sum(results[arm][task_id][run_index]["loc"] for task_id in task_ids))
            total_time_runs[arm].append(sum(results[arm][task_id][run_index]["time"] for task_id in task_ids))

    total_loc_median = {arm: sum(med_loc[arm][task_id] for task_id in task_ids) for arm in arms}
    total_time_median = {arm: round(sum(med_time[arm][task_id] for task_id in task_ids), 1) for arm in arms}

    baseline_total = total_loc_median.get("baseline", 0)
    loc_vs_baseline = {}
    time_vs_baseline = {}
    baseline_time_total = total_time_median.get("baseline", 0)
    for arm in arms:
        if arm == "baseline":
            continue
        arm_total = total_loc_median[arm]
        loc_vs_baseline[arm] = round((1 - arm_total / baseline_total) * 100, 1) if baseline_total else 0
        arm_time = total_time_median[arm]
        time_vs_baseline[arm] = round(baseline_time_total / arm_time, 2) if arm_time else None

    variability = {
        arm: {
            "loc_min": min(total_loc_runs[arm]),
            "loc_max": max(total_loc_runs[arm]),
            "time_min": round(min(total_time_runs[arm]), 1),
            "time_max": round(max(total_time_runs[arm]), 1),
        }
        for arm in arms
    }

    return {
        "arms": arms,
        "task_ids": task_ids,
        "repeat": repeat,
        "med_loc": med_loc,
        "med_time": med_time,
        "total_loc_median": total_loc_median,
        "total_time_median": total_time_median,
        "loc_vs_baseline": loc_vs_baseline,
        "time_vs_baseline": time_vs_baseline,
        "variability": variability,
        "sample_sizes": sample_sizes,
        "response_examples": response_examples,
    }


def format_number(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def render_markdown_table(summary, metric_key, totals_key, formatter):
    headers = ["arm", *[TASK_LABELS[task_id] for task_id in summary["task_ids"]], "**TOTAL**"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|---|" + "|".join(["--:"] * (len(headers) - 1)) + "|",
    ]
    for arm in summary["arms"]:
        row = [arm]
        row.extend(formatter(summary[metric_key][arm][task_id]) for task_id in summary["task_ids"])
        row.append(formatter(summary[totals_key][arm]))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_reproduce_command(args):
    command = [
        "python3 benchmarks/benchmark-interpret.py",
        f"--input {args.input}",
        f"--provider {args.provider}",
        f"--model \"{args.model}\"",
    ]
    if args.output:
        command.append(f"--output {args.output}")
    if args.date:
        command.append(f"--date {args.date}")
    if args.provider == "bifrost" and args.gateway_url != DEFAULT_GATEWAY_URL:
        command.append(f"--gateway-url {args.gateway_url}")
    if args.provider == "ollama" and args.ollama_url != DEFAULT_OLLAMA_URL:
        command.append(f"--ollama-url {args.ollama_url}")
    return " \\\n    ".join(command)


def render_markdown(interp, summary, args, output_path):
    date_text = args.date or dt.date.today().isoformat()
    title_kind = "Bifrost benchmark" if args.provider == "bifrost" else "Local model benchmark"
    route = "via AI gateway" if args.provider == "bifrost" else "via Ollama"
    intro_lines = [
        f"# {title_kind}: {args.model} {route} - {date_text}",
        "",
        interp["intro"].strip(),
    ]
    if interp.get("caveat"):
        intro_lines.extend(["", f"> {interp['caveat'].strip()}"])

    code_table = render_markdown_table(summary, "med_loc", "total_loc_median", lambda value: format_number(float(value) if isinstance(value, int) else value))
    time_table = render_markdown_table(summary, "med_time", "total_time_median", lambda value: f"{float(value):.1f}")

    findings = "\n\n".join(f"**{item['heading']}** {item['body'].strip()}" for item in interp["key_findings"])
    reproduce_env = "CXP_API_KEY=... " if args.provider == "bifrost" else ""
    reproduce_command = reproduce_env + build_reproduce_command(args)
    reproduce_note = (
        f"Run from the repo root with a valid `CXP_API_KEY`:\n\n```bash\n{reproduce_command}\n```"
        if args.provider == "bifrost"
        else f"Run from the repo root:\n\n```bash\n{reproduce_command}\n```"
    )

    return "\n".join(intro_lines) + f"""

## Results (n={summary['repeat']}, median)

**Code LOC**

{code_table}

**Time (seconds)**

{time_table}

## Key findings

{findings}

## Reproduce

{reproduce_note}

Raw responses are saved to `{args.input}`. The generated interpretation is written to `{output_path}`.

## Takeaway

{interp['takeaway'].strip()}
"""


def get_api_key():
    api_key = os.environ.get("CXP_API_KEY")
    if not api_key:
        raise RuntimeError("CXP_API_KEY is required for provider=bifrost")
    return api_key


def extract_bifrost_content(data):
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Bifrost response shape: {data}") from exc


def call_bifrost(model, messages, gateway_url):
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "temperature": 0.2,
    }).encode()

    req = urllib.request.Request(
        f"{gateway_url.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {get_api_key()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.7.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bifrost request failed with HTTP {exc.code}: {body}") from exc
    return extract_bifrost_content(data)


def call_ollama(model, messages, ollama_url):
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()

    req = urllib.request.Request(
        f"{ollama_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        data = json.loads(response.read())
    return data["message"]["content"]


def build_messages(summary, args, output_path):
    date_text = args.date or dt.date.today().isoformat()
    system_prompt = (
                "You are interpreting benchmark results for a software repository. "
                "Be precise, skeptical about sample size, and concise. Return JSON only."
    )
    user_prompt = f"""
Write only the interpretive text for a benchmark result note.

Return strict JSON with this shape:
{{
    "intro": "one short paragraph",
    "caveat": "optional short warning, or empty string",
    "key_findings": [
        {{"heading": "short heading", "body": "one short paragraph"}},
        {{"heading": "short heading", "body": "one short paragraph"}},
        {{"heading": "short heading", "body": "one short paragraph"}}
    ],
    "takeaway": "one short paragraph"
}}

Writing rules:
- Mention the selected model `{args.model}` in the intro or takeaway.
- Mention provider `{args.provider}` and, when provider is bifrost, mention `{args.gateway_url}`.
- The benchmark covers the same 5 tasks and 3 arms: baseline / caveman / ponytail.
- Use the summary numbers exactly as provided; do not invent metrics.
- If repeat == 1, set `caveat` to a direct smoke-test warning.
- If repeat > 1, leave `caveat` empty unless a methodology limit matters.
- Keep claims calibrated. Do not claim correctness, cost, or Claude parity unless the data here directly supports it.
- `key_findings` must contain exactly 3 items.
- Each `body` should be 1-3 sentences.
- Do not include Markdown headings, tables, code fences, or reproduce commands in the JSON values.

Benchmark metadata:
{json.dumps({
    "date": date_text,
    "provider": args.provider,
    "selected_model": args.model,
    "repeat": summary["repeat"],
    "input_json": str(args.input),
        "output_markdown": str(output_path),
    "gateway_url": args.gateway_url if args.provider == "bifrost" else None,
    "ollama_url": args.ollama_url if args.provider == "ollama" else None,
}, indent=2)}

Computed summary:
{json.dumps(summary, indent=2)}
""".strip()
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def default_output_path(args):
    date_text = args.date or dt.date.today().isoformat()
    provider_slug = slugify(args.provider)
    model_slug = slugify(args.model)
    return ROOT / "benchmarks" / "results" / f"{date_text}-{model_slug}-{provider_slug}.md"


def parse_args():
    parser = argparse.ArgumentParser(description="Interpret benchmark JSON into Markdown using the selected model")
    parser.add_argument("--input", type=Path, required=True, help="Path to benchmark JSON results")
    parser.add_argument("--provider", choices=("bifrost", "ollama"), required=True, help="LLM backend to use for interpretation")
    parser.add_argument("--model", required=True, help="Model name to use for the interpretation request")
    parser.add_argument("--output", type=Path, help="Where to write the Markdown note")
    parser.add_argument("--date", help="Date to embed in the note title (default: today)")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Bifrost base URL")
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL, help="Ollama base URL")
    return parser.parse_args()


def main():
    args = parse_args()
    results = load_results(args.input)
    summary = summarize_results(results)
    output_path = args.output or default_output_path(args)
    messages = build_messages(summary, args, output_path)

    if args.provider == "bifrost":
        interpretation = call_bifrost(args.model, messages, args.gateway_url)
    else:
        interpretation = call_ollama(args.model, messages, args.ollama_url)

    try:
        interp = json.loads(strip_code_fences(interpretation))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Interpreter model did not return valid JSON: {interpretation}") from exc

    markdown = render_markdown(interp, summary, args, output_path)
    output_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    print(f"Markdown interpretation -> {output_path}")


if __name__ == "__main__":
    main()