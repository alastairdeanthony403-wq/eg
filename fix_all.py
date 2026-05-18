"""
fix_all.py — Run from your repo root: C:\\Users\\User\\eg
  python fix_all.py

Fixes WITHOUT needing to download any files:
  1. Removes duplicate 'runLearn' from Backtester.jsx
  2. Fixes api.js (removes import.meta, CRA-incompatible)
  3. Adds API_BASE to Dashboard/Journal/Settings fetch calls
  4. Commits and pushes
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))

def fix_file(path, fn):
    full = os.path.join(ROOT, path)
    if not os.path.exists(full):
        print(f"  SKIP — not found: {full}")
        return False
    with open(full, "r", encoding="utf-8") as f:
        original = f.read()
    fixed = fn(original)
    if fixed == original:
        print(f"  OK   — no changes needed: {path}")
        return False
    with open(full, "w", encoding="utf-8") as f:
        f.write(fixed)
    print(f"  FIXED — {path}")
    return True

# ── 1. Backtester.jsx: remove duplicate runLearn ──────────────────────────────
def fix_backtester(content):
    starts = [m.start() for m in re.finditer(r'const runLearn\s*=\s*async', content)]
    print(f"  runLearn declarations found: {len(starts)}")

    if len(starts) < 2:
        # Also fix broken apiFetch pattern (r.ok / undefined d)
        content = content.replace(
            'const r = await apiFetch("/api/backtest-runs", {headers:hdrs});\n      if(r.ok) setHistory(Array.isArray(d)?d:[]);',
            'const data = await apiFetch("/api/backtest-runs");\n      setHistory(Array.isArray(data) ? data : []);'
        )
        content = content.replace(
            'const r = await apiFetch("/api/learn/history", {headers:hdrs});\n      if(r.ok) setLearnHistory(d.history||[]);',
            'const data = await apiFetch("/api/learn/history");\n      setLearnHistory(data.history || []);'
        )
        content = content.replace(
            'const r = await apiFetch("/api/learn", {\n        method:"POST", headers:hdrs,\n        body:JSON.stringify({ auto_apply:true, symbol }),\n      });\n      if(!r.ok) throw new Error(d.error||"Learn failed");\n      setLearnResult(d);',
            'const data = await apiFetch("/api/learn", {\n        method:"POST",\n        body:JSON.stringify({ auto_apply:true, symbol }),\n      });\n      setLearnResult(data);'
        )
        return content

    # Remove the second declaration by counting braces
    i = starts[1]
    depth = 0
    started = False
    end = i
    while i < len(content):
        c = content[i]
        if c == '{':
            depth += 1
            started = True
        elif c == '}':
            depth -= 1
        if started and depth == 0:
            end = i + 1
            # Skip trailing semicolons and whitespace up to next newline
            while end < len(content) and content[end] in ' \t;':
                end += 1
            if end < len(content) and content[end] == '\n':
                end += 1
            break
        i += 1

    print(f"  Removing duplicate runLearn (pos {starts[1]}–{end})")
    content = content[:starts[1]] + content[end:]

    # Also fix broken apiFetch patterns
    content = content.replace(
        'const r = await apiFetch("/api/backtest-runs", {headers:hdrs});\n      if(r.ok) setHistory(Array.isArray(d)?d:[]);',
        'const data = await apiFetch("/api/backtest-runs");\n      setHistory(Array.isArray(data) ? data : []);'
    )
    content = content.replace(
        'const r = await apiFetch("/api/learn/history", {headers:hdrs});\n      if(r.ok) setLearnHistory(d.history||[]);',
        'const data = await apiFetch("/api/learn/history");\n      setLearnHistory(data.history || []);'
    )
    content = content.replace(
        'const r = await apiFetch("/api/learn", {\n        method:"POST", headers:hdrs,\n        body:JSON.stringify({ auto_apply:true, symbol }),\n      });\n      if(!r.ok) throw new Error(d.error||"Learn failed");\n      setLearnResult(d);',
        'const data = await apiFetch("/api/learn", {\n        method:"POST",\n        body:JSON.stringify({ auto_apply:true, symbol }),\n      });\n      setLearnResult(data);'
    )
    return content

# ── 2. api.js: replace with CRA-safe version ──────────────────────────────────
NEW_API_JS = '''\
/**
 * src/utils/api.js
 * CRA / craco compatible. Set REACT_APP_API_URL in Vercel env vars.
 * Example: REACT_APP_API_URL=https://your-flask-backend.onrender.com
 */
export const API_BASE = process.env.REACT_APP_API_URL || "";

export async function apiFetch(path, options = {}) {
  const token = localStorage.getItem("token");
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: "Bearer " + token } : {}),
    ...(options.headers || {}),
  };
  const url = API_BASE + path;
  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch (err) {
    throw new Error("Network error: " + err.message);
  }
  const ct = response.headers.get("content-type") || "";
  let data;
  if (ct.includes("application/json")) {
    data = await response.json();
  } else {
    const text = await response.text();
    if (text.trim().startsWith("<")) {
      throw new Error(
        "API returned HTML. Set REACT_APP_API_URL in Vercel env vars " +
        "to point at your Flask backend. Tried: " + url
      );
    }
    try { data = JSON.parse(text); }
    catch { throw new Error("Unexpected response: " + text.slice(0, 100)); }
  }
  if (!response.ok) {
    throw new Error((data && (data.error || data.message)) || "HTTP " + response.status);
  }
  return data;
}
'''

def fix_api(content):
    if "import.meta" in content:
        return NEW_API_JS
    return content

# ── 3. Dashboard/Journal/Settings: add API_BASE to fetch calls ────────────────
API_BASE_LINE = 'const API_BASE = process.env.REACT_APP_API_URL || "";\n'

def inject_api_base(content):
    if "API_BASE" in content:
        return content  # already fixed
    # Insert after last import line
    lines = content.split('\n')
    last_import = 0
    for i, line in enumerate(lines):
        if line.startswith('import '):
            last_import = i
    lines.insert(last_import + 1, '')
    lines.insert(last_import + 2, API_BASE_LINE.strip())
    return '\n'.join(lines)

def fix_dashboard(content):
    content = inject_api_base(content)
    content = content.replace(
        'await fetch(`/api/signals?strategy=${strategy}`',
        'await fetch(`${API_BASE}/api/signals?strategy=${strategy}`'
    )
    return content

def fix_journal(content):
    content = inject_api_base(content)
    content = content.replace('await fetch("/api/journal"', 'await fetch(API_BASE + "/api/journal"')
    content = content.replace('await fetch(`/api/journal/${id}`', 'await fetch(`${API_BASE}/api/journal/${id}`')
    return content

def fix_settings(content):
    content = inject_api_base(content)
    content = content.replace('await fetch("/api/settings"', 'await fetch(API_BASE + "/api/settings"')
    return content

# ── Run all fixes ─────────────────────────────────────────────────────────────
changed = []
print("\n📁 Fixing frontend files...\n")

tasks = [
    ("frontend/src/pages/Backtester.jsx", fix_backtester),
    ("frontend/src/utils/api.js",         fix_api),
    ("frontend/src/pages/Dashboard.jsx",  fix_dashboard),
    ("frontend/src/pages/Journal.jsx",    fix_journal),
    ("frontend/src/pages/Settings.jsx",   fix_settings),
]

for path, fn in tasks:
    print(f"→ {path}")
    if fix_file(path, fn):
        changed.append(path)

# ── Verify Backtester has no duplicate ───────────────────────────────────────
bt = os.path.join(ROOT, "frontend/src/pages/Backtester.jsx")
if os.path.exists(bt):
    with open(bt, encoding="utf-8") as f:
        bt_content = f.read()
    count = len(re.findall(r'const runLearn\s*=\s*async', bt_content))
    print(f"\n✅ runLearn declarations in Backtester.jsx: {count} (must be ≤1)")
    if count > 1:
        print("❌ Still has duplicate! Please share Backtester.jsx content for manual review.")
        sys.exit(1)

if not changed:
    print("\nNo files needed changes. Checking git status...")

# ── Git commit and push ───────────────────────────────────────────────────────
print("\n📦 Committing and pushing...\n")
for path in changed:
    subprocess.run(["git", "add", path], cwd=ROOT)

if changed:
    subprocess.run(["git", "commit", "-m",
        "fix: remove duplicate runLearn, fix apiFetch usage, add API_BASE, fix import.meta"],
        cwd=ROOT)
    result = subprocess.run(["git", "push"], cwd=ROOT)
    if result.returncode == 0:
        print("\n✅ Done! Check Vercel for the new deployment.")
    else:
        print("\n⚠️  Push failed — try 'git push' manually.")
else:
    print("Nothing to commit.")
