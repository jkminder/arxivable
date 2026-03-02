"""Step: Discover, validate, and remove todo commands.

Uses BFS from \\todo through \\newcommand/\\renewcommand/\\def/\\DeclareRobustCommand
to find all transitive todo commands. Also detects color-marker commands.
"""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field


@dataclass
class TodoCommand:
    """A discovered todo command."""

    name: str  # e.g. "fixme" (without backslash)
    n_optional: int = 0  # number of optional args
    n_required: int = 0  # number of required args
    definition_file: str | None = None  # file where it's defined
    definition_line: int | None = None  # line number of definition


@dataclass
class TodoInvocation:
    """A todo command used in body text."""

    command: str
    file: str
    line: int


@dataclass
class TodoInfo:
    """Full results from todo analysis."""

    commands: dict[str, TodoCommand] = field(default_factory=dict)
    todonotes_disabled: bool = False
    todonotes_file: str | None = None  # file containing \usepackage{todonotes}
    todonotes_line: int | None = None
    invocations: list[TodoInvocation] = field(default_factory=list)
    has_active_todos: bool = False
    # Color-marker commands NOT classified as todos (defined outside todo files)
    # Stored as dict: cmd_name -> definition body (for Claude review)
    borderline_color_commands: dict[str, str] = field(default_factory=dict)


# Patterns for command definitions
_NEWCMD_PATTERN = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand)\s*"
    r"\{?\s*\\(\w+)\}?"  # command name
    r"(\s*\[\s*\d+\s*\])?"  # optional arg count
    r"(\s*\[[^\]]*\])?"  # optional default
    r"\s*\{"  # opening brace of body
)

_DECLARE_ROBUST_PATTERN = re.compile(
    r"\\DeclareRobustCommand\s*"
    r"\{?\s*\\(\w+)\}?"
    r"(\s*\[\s*\d+\s*\])?"
    r"\s*\{"
)

_DEF_PATTERN = re.compile(
    r"\\def\s*\\(\w+)"
)

_USEPACKAGE_TODONOTES = re.compile(
    r"\\usepackage\s*(\[[^\]]*\])?\s*\{todonotes\}"
)

_COLOR_MARKER = re.compile(
    r"\\color\s*\{(red|orange|blue|yellow|green|cyan)\}"
)


def _extract_brace_body(text: str, start: int) -> str | None:
    """Extract content between matched braces starting at text[start] == '{'."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    i = start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
        i += 1
    return None


def _parse_newcommand_args(line: str, cmd_name: str) -> tuple[int, int]:
    """Parse argument signature of a \\newcommand definition.

    Returns (n_optional, n_required).
    """
    # Find the definition after the command name
    pattern = re.compile(
        rf"\\(?:newcommand|renewcommand|providecommand)\s*"
        rf"\{{?\s*\\{re.escape(cmd_name)}\}}?"
        rf"(\s*\[\s*(\d+)\s*\])?"  # total arg count
        rf"(\s*\[[^\]]*\])?"  # default for optional arg
    )
    m = pattern.search(line)
    if not m:
        return 0, 0

    total_args = int(m.group(2)) if m.group(2) else 0
    has_default = m.group(3) is not None
    n_optional = 1 if has_default else 0
    n_required = total_args - n_optional
    return n_optional, max(0, n_required)


def _scan_definitions(workdir: str) -> dict[str, tuple[str, int, int, str]]:
    """Scan all .tex files for command definitions.

    Returns dict: cmd_name -> (body_text, n_optional, n_required, filepath).
    Prefers \\newcommand (original definitions) over \\renewcommand (local overrides).
    """
    definitions: dict[str, tuple[str, int, int, str]] = {}
    # Track which commands were defined via \newcommand (not \renewcommand)
    is_newcommand: set[str] = set()

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Find \newcommand / \renewcommand / \providecommand
            for m in _NEWCMD_PATTERN.finditer(content):
                cmd_name = m.group(1)
                body = _extract_brace_body(content, m.end() - 1)
                if body is not None:
                    is_new = "\\newcommand" in content[m.start() : m.start() + 15]
                    # Don't let a \renewcommand override an existing \newcommand
                    if cmd_name in is_newcommand and not is_new:
                        continue
                    n_opt, n_req = _parse_newcommand_args(
                        content[m.start() : m.end() + len(body) + 1], cmd_name
                    )
                    definitions[cmd_name] = (body, n_opt, n_req, fpath)
                    if is_new:
                        is_newcommand.add(cmd_name)

            # Find \DeclareRobustCommand
            for m in _DECLARE_ROBUST_PATTERN.finditer(content):
                cmd_name = m.group(1)
                body = _extract_brace_body(content, m.end() - 1)
                if body is not None:
                    if cmd_name in is_newcommand:
                        continue
                    total = int(m.group(2).strip("[] \t")) if m.group(2) else 0
                    definitions[cmd_name] = (body, 0, total, fpath)

    return definitions


def discover_todos(workdir: str, verbose: bool = False) -> TodoInfo:
    """Discover all todo-related commands via BFS from \\todo."""
    info = TodoInfo()

    # Step 1: Find \usepackage{todonotes} (skip commented-out lines)
    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, 1):
                    # Skip commented-out lines
                    if line.lstrip().startswith("%"):
                        continue
                    m = _USEPACKAGE_TODONOTES.search(line)
                    if m:
                        info.todonotes_file = fpath
                        info.todonotes_line = lineno
                        opts = m.group(1) or ""
                        info.todonotes_disabled = "disable" in opts
                        break
            if info.todonotes_file:
                break

    if not info.todonotes_file:
        if verbose:
            print("  No \\usepackage{todonotes} found")
        return info

    # Step 2: Scan all command definitions
    definitions = _scan_definitions(workdir)

    # Step 3: BFS from \todo
    seed_commands = {"todo"}
    visited: set[str] = set()
    queue: deque[str] = deque(seed_commands)

    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)

        # Find all commands whose body references \current
        for cmd_name, (body, n_opt, n_req, fpath) in definitions.items():
            if cmd_name in visited:
                continue
            if re.search(rf"\\{re.escape(current)}(?![a-zA-Z])", body):
                queue.append(cmd_name)

    # Step 4: Also detect color-marker commands, but only from files
    # that already contain todo definitions (to avoid misclassifying
    # styling commands like \shared{{\color{orange}\emph{shared}}} as todos)
    todo_def_files: set[str] = set()
    if info.todonotes_file:
        todo_def_files.add(os.path.normpath(info.todonotes_file))
    for cmd_name in visited:
        if cmd_name != "todo" and cmd_name in definitions:
            todo_def_files.add(os.path.normpath(definitions[cmd_name][3]))

    color_marker_cmds: set[str] = set()
    for cmd_name, (body, n_opt, n_req, fpath) in definitions.items():
        if cmd_name in visited:
            continue
        if not _COLOR_MARKER.search(body):
            continue
        if os.path.normpath(fpath) in todo_def_files:
            color_marker_cmds.add(cmd_name)
        else:
            # Track as borderline — defined outside todo files, might be
            # a styling command (like \shared) or a real todo marker (like \yap)
            info.borderline_color_commands[cmd_name] = body

    # Step 5: Build TodoCommand objects for all discovered commands
    all_todo_cmds = visited | color_marker_cmds
    # Remove 'todo' itself from the command list (it's the base, defined by the package)
    all_todo_cmds.discard("todo")

    for cmd_name in all_todo_cmds:
        if cmd_name in definitions:
            body, n_opt, n_req, fpath = definitions[cmd_name]
            # Find the line number
            lineno = _find_definition_line(fpath, cmd_name)
            info.commands[cmd_name] = TodoCommand(
                name=cmd_name,
                n_optional=n_opt,
                n_required=n_req,
                definition_file=fpath,
                definition_line=lineno,
            )

    if verbose:
        print(f"  Found {len(info.commands)} todo commands: "
              f"{', '.join(sorted(info.commands.keys()))}")

    return info


def _find_definition_line(fpath: str, cmd_name: str) -> int | None:
    """Find the line number where a command is defined."""
    with open(fpath, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            if re.search(rf"\\{re.escape(cmd_name)}(?![a-zA-Z])", line) and (
                "\\newcommand" in line
                or "\\renewcommand" in line
                or "\\providecommand" in line
                or "\\DeclareRobustCommand" in line
                or "\\def" in line
            ):
                return lineno
    return None


def _find_reachable_tex_files(workdir: str, main_tex: str) -> set[str]:
    """Find all .tex files transitively \\input-ed from main_tex.

    Returns set of absolute normalized paths (including main_tex itself).
    """
    main_path = os.path.normpath(os.path.join(workdir, main_tex))
    reachable: set[str] = {main_path}
    queue: list[str] = [main_path]

    while queue:
        current = queue.pop()
        try:
            with open(current, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            continue

        for m in re.finditer(r"\\(?:input|include)\s*\{([^}]+)\}", content):
            ref = m.group(1).strip()
            # Resolve relative to file's directory
            base_dir = os.path.dirname(current)
            candidate = os.path.normpath(os.path.join(base_dir, ref))
            if not candidate.endswith(".tex"):
                candidate += ".tex"
            if candidate not in reachable and os.path.isfile(candidate):
                reachable.add(candidate)
                queue.append(candidate)

    return reachable


def find_todo_invocations(
    workdir: str, main_tex: str, info: TodoInfo, verbose: bool = False
) -> list[TodoInvocation]:
    """Find all uses of todo commands in body text.

    Only scans files reachable from the main document (transitively \\input-ed).
    Excludes preamble and definition files.
    """
    if not info.commands:
        return []

    main_path = os.path.join(workdir, main_tex)
    invocations: list[TodoInvocation] = []

    # Build pattern for all todo command names
    cmd_names = sorted(info.commands.keys(), key=len, reverse=True)
    pattern = re.compile(
        r"\\(" + "|".join(re.escape(c) for c in cmd_names) + r")(?![a-zA-Z])"
    )

    # Only scan files reachable from main document
    reachable = _find_reachable_tex_files(workdir, main_tex)

    # Exclude preamble and definition files
    from arxivable.steps.comments import find_preamble_inputs
    preamble_files = find_preamble_inputs(main_path)

    definition_files: set[str] = set()
    if info.todonotes_file:
        definition_files.add(os.path.normpath(info.todonotes_file))
    for cmd in info.commands.values():
        if cmd.definition_file:
            definition_files.add(os.path.normpath(cmd.definition_file))

    skip_files = preamble_files | definition_files
    # Never skip the main file — it has special handling to only scan
    # after \begin{document}, so preamble definitions are already excluded
    skip_files.discard(os.path.normpath(main_path))
    scan_files = reachable - skip_files

    for fpath in sorted(scan_files):
        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # For main file, only scan after \begin{document}
        if os.path.normpath(fpath) == os.path.normpath(main_path):
            m_doc = re.search(r"\\begin\{document\}", content)
            if m_doc:
                body = content[m_doc.end() :]
                offset = content[: m_doc.end()].count("\n")
            else:
                continue
        else:
            body = content
            offset = 0

        for lineno, line in enumerate(body.split("\n"), 1):
            # Skip commented lines
            stripped = line.lstrip()
            if stripped.startswith("%"):
                continue
            for m in pattern.finditer(line):
                invocations.append(
                    TodoInvocation(
                        command=m.group(1),
                        file=os.path.relpath(fpath, workdir),
                        line=lineno + offset,
                    )
                )

    info.invocations = invocations
    if invocations and not info.todonotes_disabled:
        info.has_active_todos = True

    return invocations


def validate_todos(info: TodoInfo, force: bool = False) -> None:
    """Crash if there are active (non-disabled) todos, unless --force."""
    if info.has_active_todos and not force:
        print("\nError: Found active todo invocations (todonotes is NOT disabled):")
        print("  These todos are visible in the compiled PDF — did you forget to resolve them?\n")
        for inv in info.invocations:
            print(f"  {inv.file}:{inv.line}  \\{inv.command}")
        print(f"\n  Use --force to remove them anyway.")
        raise SystemExit(1)


def _match_brace_group(text: str, pos: int) -> int | None:
    """Match a brace group starting at pos. Returns index after closing brace."""
    if pos >= len(text) or text[pos] != "{":
        return None
    depth = 0
    i = pos
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _match_optional_group(text: str, pos: int) -> int | None:
    """Match an optional argument [...] starting at pos. Returns index after ]."""
    if pos >= len(text) or text[pos] != "[":
        return None
    depth = 0
    i = pos
    while i < len(text):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        elif text[i] == "{":
            # Skip nested braces inside optional arg
            end = _match_brace_group(text, i)
            if end:
                i = end
                continue
        i += 1
    return None


def remove_todo_invocation(text: str, cmd_name: str, cmd: TodoCommand) -> str:
    """Remove all invocations of a todo command from text."""
    pattern = re.compile(rf"\\{re.escape(cmd_name)}(?![a-zA-Z])")

    result = []
    i = 0
    while i < len(text):
        m = pattern.search(text, i)
        if not m:
            result.append(text[i:])
            break

        result.append(text[i : m.start()])
        pos = m.end()

        # Skip whitespace
        while pos < len(text) and text[pos] in " \t":
            pos += 1

        # Match optional args
        for _ in range(cmd.n_optional):
            end = _match_optional_group(text, pos)
            if end:
                pos = end
                while pos < len(text) and text[pos] in " \t":
                    pos += 1

        # Match required args
        for _ in range(cmd.n_required):
            end = _match_brace_group(text, pos)
            if end:
                pos = end
                while pos < len(text) and text[pos] in " \t":
                    pos += 1

        i = pos

    return "".join(result)


def remove_todo_infrastructure(
    workdir: str, main_tex: str, info: TodoInfo, verbose: bool = False
) -> dict:
    """Remove todo definitions and invocations.

    Returns summary dict with keys: definitions_removed, invocations_removed,
    files_cleaned, file_removed.
    """
    summary = {
        "definitions_removed": 0,
        "invocations_removed": len(info.invocations),
        "files_cleaned": [],
        "file_removed": None,
    }

    if not info.todonotes_file:
        return summary

    # Step 1: Clean files containing todo definitions
    # First clean the todonotes package file
    _clean_todonotes_file(workdir, info, summary, verbose)

    # Also clean other files that have todo definitions (e.g. preamble.tex)
    definition_files: set[str] = set()
    for cmd in info.commands.values():
        if cmd.definition_file:
            norm = os.path.normpath(cmd.definition_file)
            if norm != os.path.normpath(info.todonotes_file):
                definition_files.add(norm)
    for def_file in definition_files:
        _clean_definition_file(workdir, def_file, info, summary, verbose)

    # Step 2: Remove inline todo invocations from body text
    if info.invocations:
        _remove_body_invocations(workdir, main_tex, info, verbose)

    return summary


def _clean_todonotes_file(
    workdir: str, info: TodoInfo, summary: dict, verbose: bool
) -> None:
    """Parse the todonotes definition file line by line, removing todo-related lines."""
    fpath = info.todonotes_file
    if not fpath or not os.path.exists(fpath):
        return

    with open(fpath, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    todo_cmd_names = set(info.commands.keys())
    keep_lines: list[str] = []
    removed_count = 0

    # Track if we're inside a multi-line \newcommand
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Remove \usepackage{todonotes}
        if _USEPACKAGE_TODONOTES.search(line):
            if verbose:
                print(f"  Removing: {stripped}")
            removed_count += 1
            i += 1
            continue

        # Check if line is a commented-out todonotes usepackage
        if re.match(r"\s*%\s*\\usepackage.*\{todonotes\}", line):
            removed_count += 1
            i += 1
            continue

        # Check if this is a command definition for a todo command
        is_todo_def = False
        for cmd_name in todo_cmd_names:
            # Match \newcommand{\cmdname}... or \newcommand\cmdname...
            if re.search(
                rf"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
                rf"\s*\{{?\s*\\{re.escape(cmd_name)}\b",
                line,
            ):
                is_todo_def = True
                break

        if is_todo_def:
            if verbose:
                print(f"  Removing definition: \\{cmd_name}")
            removed_count += 1
            # Check if definition spans multiple lines (unmatched braces)
            brace_depth = line.count("{") - line.count("}")
            i += 1
            while brace_depth > 0 and i < len(lines):
                brace_depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue

        # Remove \noindentaftertodo if it appears alone
        if stripped == r"\noindentaftertodo":
            i += 1
            continue

        # Keep everything else
        keep_lines.append(line)
        i += 1

    # Remove empty \makeatletter/\makeatother pairs
    keep_lines = _remove_empty_makeatletter(keep_lines)

    # Remove leading/trailing blank lines and collapse multiple blank lines
    keep_lines = _collapse_blank_lines(keep_lines)

    summary["definitions_removed"] = removed_count

    # Check if file is effectively empty
    content = "".join(keep_lines).strip()
    if not content:
        # Remove the file
        os.remove(fpath)
        summary["file_removed"] = os.path.relpath(fpath, workdir)
        if verbose:
            print(f"  Removed empty file: {summary['file_removed']}")

        # Also remove its \input line from any .tex file
        _remove_input_line(workdir, fpath, verbose)
    else:
        with open(fpath, "w", encoding="utf-8") as f:
            f.writelines(keep_lines)
        summary["files_cleaned"].append(os.path.relpath(fpath, workdir))


def _clean_definition_file(
    workdir: str, fpath: str, info: TodoInfo, summary: dict, verbose: bool
) -> None:
    """Remove todo command definitions from a file (not the todonotes package file)."""
    if not os.path.exists(fpath):
        return

    with open(fpath, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    todo_cmd_names = set(info.commands.keys())
    keep_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Check if this is a command definition for a todo command
        is_todo_def = False
        for cmd_name in todo_cmd_names:
            if re.search(
                rf"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
                rf"\s*\{{?\s*\\{re.escape(cmd_name)}\b",
                line,
            ):
                is_todo_def = True
                break

        if is_todo_def:
            if verbose:
                print(f"  Removing definition: \\{cmd_name} (from {os.path.relpath(fpath, workdir)})")
            brace_depth = line.count("{") - line.count("}")
            i += 1
            while brace_depth > 0 and i < len(lines):
                brace_depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue

        if stripped == r"\noindentaftertodo":
            i += 1
            continue

        keep_lines.append(line)
        i += 1

    keep_lines = _remove_empty_makeatletter(keep_lines)
    keep_lines = _collapse_blank_lines(keep_lines)

    content = "".join(keep_lines).strip()
    if not content:
        os.remove(fpath)
        if verbose:
            print(f"  Removed empty file: {os.path.relpath(fpath, workdir)}")
        _remove_input_line(workdir, fpath, verbose)
    else:
        with open(fpath, "w", encoding="utf-8") as f:
            f.writelines(keep_lines)
        summary["files_cleaned"].append(os.path.relpath(fpath, workdir))


def _remove_empty_makeatletter(lines: list[str]) -> list[str]:
    """Remove \\makeatletter/\\makeatother pairs with nothing between them."""
    result = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == r"\makeatletter":
            # Look ahead for \makeatother with only blank lines between
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j].strip() == r"\makeatother":
                i = j + 1
                continue
        result.append(lines[i])
        i += 1
    return result


def _collapse_blank_lines(lines: list[str]) -> list[str]:
    """Collapse consecutive blank lines into one."""
    result: list[str] = []
    prev_blank = False
    for line in lines:
        if line.strip() == "":
            if prev_blank:
                continue
            prev_blank = True
        else:
            prev_blank = False
        result.append(line)
    # Strip trailing blank lines
    while result and result[-1].strip() == "":
        result.pop()
    if result:
        # Ensure file ends with newline
        if not result[-1].endswith("\n"):
            result[-1] += "\n"
    return result


def _remove_input_line(workdir: str, removed_file: str, verbose: bool) -> None:
    """Remove \\input{...} line referencing the removed file from all .tex files."""
    # Compute the relative path as it would appear in \input
    rel = os.path.relpath(removed_file, workdir)
    # Could be referenced with or without .tex extension
    rel_no_ext = rel.removesuffix(".tex")

    for root, _dirs, files in os.walk(workdir):
        for fname in files:
            if not fname.endswith(".tex"):
                continue
            fpath = os.path.join(root, fname)
            file_dir = os.path.relpath(root, workdir)
            with open(fpath, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            new_lines = []
            modified = False
            for line in lines:
                m = re.search(r"\\input\{([^}]+)\}", line)
                if m:
                    input_path = m.group(1)
                    # Resolve relative to the file's directory
                    if file_dir != ".":
                        resolved = os.path.normpath(
                            os.path.join(file_dir, input_path)
                        )
                    else:
                        resolved = os.path.normpath(input_path)
                    resolved_tex = resolved if resolved.endswith(".tex") else resolved + ".tex"

                    if resolved_tex == rel or resolved == rel_no_ext:
                        if verbose:
                            print(f"  Removed \\input{{{input_path}}} from {os.path.relpath(fpath, workdir)}")
                        modified = True
                        continue
                new_lines.append(line)

            if modified:
                with open(fpath, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)


def _is_renewcmd_todo_line(line: str, detect_pattern: re.Pattern) -> bool:
    """Check if a line is a standalone \\renewcommand redefining a todo command.

    Handles lines like:
      \\renewcommand{\\tiago}[1]{}
      {\\renewcommand{\\tiago}[1]{}}  (with outer scope braces)
    """
    stripped = line.strip()
    if not detect_pattern.search(stripped):
        return False
    # Verify braces are balanced (standalone definition, not part of larger construct)
    depth = 0
    for ch in stripped:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth == 0


def _remove_body_invocations(
    workdir: str, main_tex: str, info: TodoInfo, verbose: bool
) -> None:
    """Remove todo command invocations from body .tex files."""
    # Group invocations by file
    files_with_todos: set[str] = {inv.file for inv in info.invocations}

    # Build pattern to detect \renewcommand for todo commands in body
    todo_cmd_names = set(info.commands.keys())
    _renewcmd_detect = re.compile(
        r"\\renewcommand\s*\{?\s*\\("
        + "|".join(re.escape(c) for c in todo_cmd_names)
        + r")\b"
    )

    for rel_path in files_with_todos:
        fpath = os.path.join(workdir, rel_path)
        if not os.path.exists(fpath):
            continue

        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # First remove \renewcommand lines for todo commands
        # (must happen before remove_todo_invocation, which would strip the
        # command name inside \renewcommand and leave broken LaTeX)
        lines = content.split("\n")
        lines = [l for l in lines if not _is_renewcmd_todo_line(l, _renewcmd_detect)]
        content = "\n".join(lines)

        for cmd_name, cmd in info.commands.items():
            content = remove_todo_invocation(content, cmd_name, cmd)

        # Clean up empty lines left behind
        cleaned_lines = content.split("\n")
        result = []
        prev_blank = False
        for line in cleaned_lines:
            if line.strip() == "":
                if prev_blank:
                    continue
                prev_blank = True
            else:
                prev_blank = False
            result.append(line)

        with open(fpath, "w", encoding="utf-8") as f:
            f.write("\n".join(result))

        if verbose:
            print(f"  Removed todo invocations from {rel_path}")


def remove_borderline_command(
    workdir: str, main_tex: str, cmd_name: str, body: str
) -> int:
    """Remove a single borderline color-marker command from the project.

    Removes the definition and all invocations from reachable .tex files.
    Returns the number of invocations removed.
    """
    # Parse argument signature from the definition
    definitions = _scan_definitions(workdir)
    if cmd_name in definitions:
        _, n_opt, n_req, def_fpath = definitions[cmd_name]
    else:
        n_opt, n_req, def_fpath = 0, 0, None

    cmd = TodoCommand(name=cmd_name, n_optional=n_opt, n_required=n_req)

    # Remove definition from its file
    if def_fpath and os.path.exists(def_fpath):
        with open(def_fpath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        keep = []
        i = 0
        while i < len(lines):
            if re.search(
                rf"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand)"
                rf"\s*\{{?\s*\\{re.escape(cmd_name)}\b",
                lines[i],
            ):
                # Skip definition (may span multiple lines)
                brace_depth = lines[i].count("{") - lines[i].count("}")
                i += 1
                while brace_depth > 0 and i < len(lines):
                    brace_depth += lines[i].count("{") - lines[i].count("}")
                    i += 1
                continue
            keep.append(lines[i])
            i += 1
        with open(def_fpath, "w", encoding="utf-8") as f:
            f.writelines(keep)

    # Count and remove invocations from all reachable .tex files
    invocation_count = 0
    reachable = _find_reachable_tex_files(workdir, main_tex)
    main_path = os.path.normpath(os.path.join(workdir, main_tex))
    pattern = re.compile(rf"\\{re.escape(cmd_name)}(?![a-zA-Z])")

    for fpath in sorted(reachable):
        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # For main file, only process after \begin{document}
        if os.path.normpath(fpath) == main_path:
            m_doc = re.search(r"\\begin\{document\}", content)
            if m_doc:
                preamble = content[: m_doc.end()]
                body_content = content[m_doc.end() :]
            else:
                continue
        else:
            preamble = ""
            body_content = content

        count = len(pattern.findall(body_content))
        if count == 0:
            continue
        invocation_count += count

        new_body = remove_todo_invocation(body_content, cmd_name, cmd)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(preamble + new_body)

    return invocation_count


def find_borderline_usages(
    workdir: str, main_tex: str, cmd_name: str
) -> list[str]:
    """Find usage excerpts of a borderline command in the document.

    Returns a list of short context snippets showing how it's used.
    """
    excerpts: list[str] = []
    reachable = _find_reachable_tex_files(workdir, main_tex)
    main_path = os.path.normpath(os.path.join(workdir, main_tex))
    pattern = re.compile(rf"\\{re.escape(cmd_name)}(?![a-zA-Z])")

    for fpath in sorted(reachable):
        with open(fpath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        rel = os.path.relpath(fpath, workdir)

        # For main file, find \begin{document} line
        body_start = 0
        if os.path.normpath(fpath) == main_path:
            for i, line in enumerate(lines):
                if r"\begin{document}" in line:
                    body_start = i + 1
                    break

        for i, line in enumerate(lines):
            if i < body_start:
                continue
            stripped = line.strip()
            if stripped.startswith("%"):
                continue
            if pattern.search(line):
                # Truncate long lines for display
                display = stripped[:120]
                if len(stripped) > 120:
                    display += "..."
                excerpts.append(f"  {rel}:{i + 1}  {display}")
                if len(excerpts) >= 5:
                    return excerpts

    return excerpts
