from __future__ import annotations

import argparse
import ast
import builtins
import json
import re
import sys
import symtable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TextIO


CATEGORIES = (
    "Bugs & Logic",
    "Security",
    "Performance",
    "Maintainability",
    "Edge Cases",
)


@dataclass(frozen=True)
class Finding:
    category: str
    severity: str
    line: int
    issue: str
    fix: str


class PythonReview:
    def review(self, source: str, *, is_diff: bool = False) -> list[Finding]:
        findings: list[Finding] = []
        if is_diff:
            self._review_added_lines(source, findings)
        else:
            try:
                tree = ast.parse(source)
                compile(tree, "<snippet>", "exec")
            except SyntaxError:
                tree = None
            if tree is not None:
                self._review_ast(tree, findings)
                self._review_undefined_names(source, tree, findings)

        return sorted(
            findings,
            key=lambda finding: (
                CATEGORIES.index(finding.category),
                finding.line,
                finding.issue,
            ),
        )

    def _review_undefined_names(
        self, source: str, tree: ast.Module, findings: list[Finding]
    ) -> None:
        root_table = symtable.symtable(source, "<snippet>", "exec")
        runtime_globals = {
            "__name__",
            "__doc__",
            "__package__",
            "__loader__",
            "__spec__",
            "__file__",
            "__cached__",
            "__builtins__",
        }
        defined_at_module = {
            symbol.get_name()
            for symbol in root_table.get_symbols()
            if symbol.is_assigned() or symbol.is_imported()
        }
        available_globals = defined_at_module | set(dir(builtins)) | runtime_globals
        visitor = _UndefinedNameVisitor(root_table, available_globals)
        visitor.visit(tree)

        for line, name in sorted(visitor.undefined_names):
            findings.append(
                Finding(
                    "Bugs & Logic",
                    "Medium",
                    line,
                    f"`{name}` is not defined in this snippet and may raise `NameError`.",
                    f"Define or import `{name}` before using it, or confirm it is provided by the surrounding application.",
                )
            )

    def _review_ast(self, tree: ast.Module, findings: list[Finding]) -> None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._check_function(node, findings)
            elif isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append(
                    Finding(
                        "Bugs & Logic",
                        "Medium",
                        node.lineno,
                        "Bare `except` catches unexpected exceptions and can hide failures.",
                        "Catch the specific exception types this code can handle.",
                    )
                )
            elif isinstance(node, ast.ExceptHandler) and all(
                isinstance(statement, ast.Pass)
                or (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                )
                for statement in node.body
            ):
                findings.append(
                    Finding(
                        "Edge Cases",
                        "Medium",
                        node.lineno,
                        "This exception handler silently discards the failure.",
                        "Handle the failure explicitly or log it with enough context to diagnose it.",
                    )
                )
            elif isinstance(node, ast.Call):
                self._check_call(node, findings)

        for loop in (
            node for node in ast.walk(tree) if isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        ):
            if any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany"}
                for statement in loop.body
                for node in ast.walk(statement)
            ):
                findings.append(
                    Finding(
                        "Performance",
                        "Medium",
                        loop.lineno,
                        "A database execution call appears inside a loop, which may cause repeated queries.",
                        "Consider batching the operation or fetching the needed data before the loop.",
                    )
                )

    def _check_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, findings: list[Finding]
    ) -> None:
        defaults = node.args.defaults + [
            default for default in node.args.kw_defaults if default is not None
        ]
        for default in defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)) or (
                isinstance(default, ast.Call)
                and isinstance(default.func, ast.Name)
                and default.func.id in {"list", "dict", "set"}
            ):
                findings.append(
                    Finding(
                        "Bugs & Logic",
                        "Medium",
                        default.lineno,
                        "A mutable default argument is shared between calls.",
                        "Use `None` as the default and create a fresh collection inside the function.",
                    )
                )

        end_line = max(
            (
                getattr(child, "end_lineno", None)
                or getattr(child, "lineno", node.lineno)
                for child in ast.walk(node)
            ),
            default=node.lineno,
        )
        if end_line - node.lineno + 1 > 50:
            findings.append(
                Finding(
                    "Maintainability",
                    "Low",
                    node.lineno,
                    f"Function `{node.name}` spans more than 50 lines.",
                    "Split the function into smaller units with focused responsibilities.",
                )
            )

    def _check_call(self, node: ast.Call, findings: list[Finding]) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            findings.append(
                Finding(
                    "Security",
                    "High",
                    node.lineno,
                    f"`{node.func.id}()` executes code supplied at runtime.",
                    "Replace dynamic code execution with explicit parsing or a constrained dispatch.",
                )
            )

        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "execute",
            "executemany",
        } and node.args:
            if isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                findings.append(
                    Finding(
                        "Security",
                        "High",
                        node.lineno,
                        "SQL may be assembled through string interpolation or concatenation.",
                        "Use the database driver's parameterized query API for all values.",
                    )
                )

        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "run",
            "Popen",
            "call",
            "check_call",
            "check_output",
        }:
            shell_enabled = any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if shell_enabled:
                findings.append(
                    Finding(
                        "Security",
                        "High",
                        node.lineno,
                        "Subprocess execution enables a shell, increasing command-injection risk.",
                        "Pass an argument list with `shell=False`; validate any untrusted arguments.",
                    )
                )

        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "get",
            "post",
            "put",
            "delete",
            "request",
        }:
            if any(
                keyword.arg == "verify"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in node.keywords
            ):
                findings.append(
                    Finding(
                        "Security",
                        "High",
                        node.lineno,
                        "TLS certificate verification is disabled for an HTTP request.",
                        "Remove `verify=False` and configure a trusted certificate bundle if needed.",
                    )
                )

    def _review_added_lines(self, diff: str, findings: list[Finding]) -> None:
        current_line: int | None = None
        hunk_header = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
        for line in diff.splitlines():
            match = hunk_header.match(line)
            if match:
                current_line = int(match.group(1))
                continue
            if current_line is None or line.startswith(("+++", "---")):
                continue
            if line.startswith("+"):
                added_line = line[1:]
                if re.search(r"\b(eval|exec)\s*\(", added_line):
                    findings.append(
                        Finding(
                            "Security",
                            "High",
                            current_line,
                            "Added code calls `eval()` or `exec()` and may execute runtime-supplied code.",
                            "Replace dynamic code execution with explicit parsing or a constrained dispatch.",
                        )
                    )
                if re.search(
                    r"\.(?:execute|executemany)\s*\(\s*(?:f['\"]|['\"].*%s)",
                    added_line,
                ):
                    findings.append(
                        Finding(
                            "Security",
                            "High",
                            current_line,
                            "Added SQL appears to use string interpolation instead of bound parameters.",
                            "Use the database driver's parameterized query API for all values.",
                        )
                    )
                if re.search(r"\b(?:shell)\s*=\s*True\b", added_line):
                    findings.append(
                        Finding(
                            "Security",
                            "High",
                            current_line,
                            "Added subprocess configuration enables a shell, increasing command-injection risk.",
                            "Pass an argument list with `shell=False`; validate any untrusted arguments.",
                        )
                    )
                if re.search(r"\bverify\s*=\s*False\b", added_line):
                    findings.append(
                        Finding(
                            "Security",
                            "High",
                            current_line,
                            "Added HTTP request configuration disables TLS certificate verification.",
                            "Remove `verify=False` and configure a trusted certificate bundle if needed.",
                        )
                    )
                current_line += 1
            elif line.startswith(" "):
                current_line += 1
            elif not line.startswith("\\"):
                current_line = None


class _UndefinedNameVisitor(ast.NodeVisitor):
    def __init__(self, root_table: symtable.SymbolTable, available_globals: set[str]) -> None:
        self.root_table = root_table
        self.available_globals = available_globals
        self.current_table = root_table
        self.undefined_names: set[tuple[int, str]] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if not isinstance(node.ctx, ast.Load):
            return

        symbol = self.current_table.lookup(node.id)
        if symbol.is_global() and node.id not in self.available_globals:
            self.undefined_names.add((node.lineno, node.id))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_definition(node)

    def _visit_function_definition(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        for expression in (
            *node.decorator_list,
            *node.args.defaults,
            *(default for default in node.args.kw_defaults if default is not None),
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
            *([node.args.vararg] if node.args.vararg else []),
            *([node.args.kwarg] if node.args.kwarg else []),
            *([node.returns] if node.returns else []),
        ):
            self.visit(expression)

        child_table = self._find_child_table("function", node.name, node.lineno)
        self._visit_body(node.body, child_table)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)):
            self.visit(expression)

        child_table = self._find_child_table("class", node.name, node.lineno)
        self._visit_body(node.body, child_table)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in (
            *node.args.defaults,
            *(default for default in node.args.kw_defaults if default is not None),
        ):
            self.visit(expression)

        child_table = self._find_child_table("function", "lambda", node.lineno)
        self._visit_in_table(node.body, child_table)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, "listcomp")

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, "setcomp")

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, "dictcomp")

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, "genexpr")

    def _visit_comprehension(
        self,
        node: ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp,
        table_name: str,
    ) -> None:
        first_generator, *other_generators = node.generators
        self.visit(first_generator.iter)
        child_table = self._find_child_table("function", table_name, node.lineno)
        previous_table = self.current_table
        self.current_table = child_table
        try:
            for generator in (first_generator, *other_generators):
                self.visit(generator.target)
                if generator is not first_generator:
                    self.visit(generator.iter)
                for condition in generator.ifs:
                    self.visit(condition)
            if isinstance(node, ast.DictComp):
                self.visit(node.key)
                self.visit(node.value)
            else:
                self.visit(node.elt)
        finally:
            self.current_table = previous_table

    def _find_child_table(
        self, table_type: str, name: str, line: int
    ) -> symtable.SymbolTable:
        for child in self.current_table.get_children():
            if (
                child.get_type() == table_type
                and child.get_name() == name
                and child.get_lineno() == line
            ):
                return child
        return self.current_table

    def _visit_body(
        self, statements: list[ast.stmt], table: symtable.SymbolTable
    ) -> None:
        previous_table = self.current_table
        self.current_table = table
        try:
            for statement in statements:
                self.visit(statement)
        finally:
            self.current_table = previous_table

    def _visit_in_table(
        self, node: ast.AST, table: symtable.SymbolTable
    ) -> None:
        previous_table = self.current_table
        self.current_table = table
        try:
            self.visit(node)
        finally:
            self.current_table = previous_table


def _render_text(findings: Iterable[Finding]) -> str:
    by_category = {category: [] for category in CATEGORIES}
    for finding in findings:
        by_category[finding.category].append(finding)

    output = ["Automated Python review (heuristic checks)"]
    for category in CATEGORIES:
        output.append(f"\n{category}")
        if not by_category[category]:
            output.append("No issues found")
            continue
        for finding in by_category[category]:
            output.extend(
                (
                    f"- Severity: {finding.severity}",
                    f"  Location: line {finding.line}",
                    f"  Issue: {finding.issue}",
                    f"  Fix: {finding.fix}",
                )
            )
    return "\n".join(output)


def _read_source(path: str | None, stream: TextIO) -> tuple[str, str]:
    if path is None or path == "-":
        return stream.read(), "<stdin>"
    source_path = Path(path)
    return source_path.read_text(encoding="utf-8"), str(source_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Review Python snippets or unified diffs using local heuristics."
    )
    parser.add_argument("input", nargs="?", help="Python file or diff; defaults to stdin")
    parser.add_argument("--diff", action="store_true", help="Review added lines from a unified diff")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        source, source_name = _read_source(args.input, sys.stdin)
    except OSError as error:
        parser.error(f"cannot read input: {error}")
    findings = PythonReview().review(source, is_diff=args.diff)

    if args.format == "json":
        report = {
            "source": source_name,
            "categories": {
                category: [asdict(item) for item in findings if item.category == category]
                for category in CATEGORIES
            },
        }
        print(json.dumps(report, indent=2))
    else:
        print(_render_text(findings))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
