# Python Code Review

A dependency-free Python reviewer with a local web interface and command-line
tool. Check pasted Python snippets and unified diffs for common signals across
bugs and logic, security, performance, maintainability, and edge cases.

The supplied code attachment was empty, so this project reviews code you pass
to it rather than reporting findings about an absent snippet.

## Requirements

- Python 3.10 or newer

## Usage

### Open the website on Windows

1. Open this project folder in VS Code or File Explorer.
2. Optional: create a Gemini API key at [Google AI Studio](https://aistudio.google.com/app/apikey) to enable AI corrections.
3. Double-click `start_app.bat` or the **Python Code Review** shortcut on your desktop to start the site using your saved encrypted key. If no key is saved yet, the launcher prompts for one with hidden input and asks whether to encrypt it for future launches. Leave the key blank to use other features without AI corrections. The saved encrypted key is stored under your Windows user profile, outside this project. The launcher passes the key to the local server process for Gemini requests; it is not embedded in the website, source code, or project files.

When a key is already saved, the launcher lets you press **Enter** to use it, type **R** to replace it, or **D** to delete it. The encrypted key can be decrypted only by your Windows account on this computer. The launcher opens **[Python Code Review](http://127.0.0.1:8000/)** when the server is ready. You can also paste `http://127.0.0.1:8000/` into your browser after startup. Keep the server window open while using the website; press **Ctrl+C** there to stop the server. This link works on the same computer only. The server window displays startup errors and remains open if startup fails.

The checker runs on your computer; saved prompts stay in the browser's local
storage. The prompt library lets you save, reload, copy, and delete prompts.
Use **Download DOCX** for a Word document or **Print / Save PDF** and choose
“Save as PDF” in the browser's print dialog. Exports include all saved prompts.
Prompts are not submitted to the deterministic checker; DOCX generation is
performed by the local server.

The website reports Python syntax/compiler errors, likely undefined names, and
other heuristic findings. It supports Python snippets and unified diffs; diff
mode checks added lines only. **Review code** performs local static checks and
sends the Python snippet to Google Gemini to generate a corrected version in
the **Corrected code** panel. Do not submit confidential code. The Gemini API
key stays in the server environment and is never sent to the browser. The
default model is `gemini-3.6-flash`; set `GEMINI_MODEL` before starting the
server to override it.

Gemini is instructed to preserve intended behavior, fix confirmed issues, and
return the complete corrected source. Its structured findings are added to the
Review report and labeled **Gemini**; duplicate static findings are suppressed.
The app rejects responses explicitly marked as truncated and checks returned
code for Python syntax errors. No static or AI review can guarantee finding
every issue or verify runtime behavior; review suggestions and run tests before
using generated code.

Use the separate **Run code** button to execute a Python snippet and display
stdout, errors, and its exit code. Execution is not sandboxed and may access
this computer, so only run code you trust. Runs are limited to 5 seconds and
256 KB of captured output.

The **Corrected code** panel is automatically populated by Gemini after a
Python snippet review, and remains editable. Copy the text, download it as a
DOCX, or use **Print / Save PDF** and choose “Save as PDF” in the browser's
print dialog. Review generated code before using it; AI suggestions can be
incorrect. Unified diffs receive local review only.

The command-line interface remains available:

```powershell
python reviewer.py path\to\snippet.py
python reviewer.py --diff path\to\changes.diff
Get-Content path\to\snippet.py | python reviewer.py
python reviewer.py --format json path\to\snippet.py
```

By default, the tool reads a file path; with no path, it reads standard input.
Use `--diff` for a unified diff. Diff mode checks added lines only. Snippet mode
uses Python's AST when the input parses successfully.

## Scope and limitations

This is a deterministic, heuristic checker, not an LLM or a complete
program-analysis engine. The website reports Python syntax errors separately
from heuristic findings. The checker does not understand application intent,
framework configuration, data flow across modules, authorization policy, or
whether a value is attacker-controlled. Findings need human validation, and no
findings do not establish that code is safe or correct. It analyzes Python only.

The checks cover common signals such as likely undefined names, dynamic
`eval`/`exec`, interpolated SQL, shell execution, mutable defaults, bare or
silently ignored exceptions, database calls inside loops, and very long
functions. In diff mode, only patterns visible on added lines are checked;
incomplete diff context limits analysis.

## Output

Text output lists all five review dimensions, and says `No issues found` for
categories with no detected signals. JSON output contains the same categories
and findings. The process exits with status `0` after a successful review,
whether or not findings were detected. Invalid Python snippets are still
reviewed with line-based checks; parsing errors are not treated as findings.

## Tests

```powershell
python -m unittest discover -s tests -v
```
