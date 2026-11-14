#!/usr/bin/env python3
"""guard-bash: PreToolUse hook that blocks dangerous shell commands (ecosystem 15.6, OD-74).

Claude Code: register for the Bash tool. The hook reads the event JSON on stdin and exits 2 with a
reason on stderr to block. Codex: same script; argv-list commands (`["bash", "-lc", "<script>"]`)
are unwrapped. Stdlib only, Python 3.9+. A best-effort guard, not a sandbox: it tokenizes the
command, splits it on shell operators, unwraps common wrappers (sudo, env, timeout, nice, nohup,
xargs, eval, `bash|sh|zsh -c`) and recurses into `$(...)` and backticks. Blocks:

  - `pkill -f`, and `pgrep -f` feeding `kill` (kill only by verified PID, OD-74)
  - force pushes (`--force*`, any short-option cluster with `f`, `+refspec`) that target main or
    develop, including `HEAD`/`@` while one of them is checked out, and force with --all/--mirror;
    deleting main or develop on a remote; `git update-ref -d refs/heads/main|develop`
  - reading or copying `.env` files (`*.example`, `*.sample`, `*.template`, `*.dist` allowed;
    `--env-file` loading is allowed because the content does not enter the context)
  - `git reset --hard`, `git clean -f` with `-d` or `-x`, `git push --mirror`, `rm` recursive+force
    outside a temp directory or the working tree (globs that can reach dotfiles included),
    `find -exec` of any blocked command, docker prune / `volume rm` / `compose down -v`,
    destructive SQL (DROP DATABASE/SCHEMA/TABLE, TRUNCATE, dropdb)
Heredoc bodies are analysed by consumer: shells as scripts, interpreters for .env reads, database
clients for destructive SQL; other bodies (commit and PR messages) are data. A shell reading
commands from stdin (`| bash`, `bash -s`) is blocked unless its script is a visible heredoc.
Fails closed: an internal error blocks the command. Hard rules live here, not in prose (15.1).
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import subprocess
import sys

PROTECTED = {"main", "develop"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
OPERATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "!", ";;", "\n"}
KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "for", "case", "esac", "in"}
SAFE_ENV_SUFFIX = re.compile(r"\.(example|sample|template|dist)(\.|$)")
ENV_TOKEN = re.compile(r"(^|[/=<>:@])\.env([.*?][^/]*)?$")
SQL = re.compile(r"\b(DROP\s+(DATABASE|SCHEMA|TABLE)|TRUNCATE)\b", re.I)
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "php", "deno", "bun"}
QUOTED_ENV = re.compile(r"""(['"`]|/)\.env(?!\.(example|sample|template|dist)\b)(\.[\w-]+)?['"`]""")
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)(\w+)\1([^\n]*)\n(.*?)\n[ \t]*\2[ \t]*(?=\n|$)", re.S)
HEREDOC_MARK = "__heredoc_body__"
DB_CLIENTS = {"psql", "mysql", "mariadb", "sqlite3", "mongosh", "clickhouse-client"}
FIND_PREDICATES = {"-name", "-iname", "-path", "-ipath", "-regex", "-iregex", "-type", "-newer", "-mtime", "-mmin",
                   "-size", "-empty", "-user", "-perm"}
GLOB_CHARS = set("*?[")
MESSAGE_FLAGS = {"-m", "--message", "--grep", "-F", "--file", "--title", "--body", "-t", "-b"}
TEMP_PREFIXES = ("/tmp/", "/var/tmp/", "$TMPDIR/", "${TMPDIR}/", "$RUNNER_TEMP/", "${RUNNER_TEMP}/")


def strip_prefix(text: str, prefix: str) -> str:
    return text[len(prefix):] if text.startswith(prefix) else text


FIND_ARG = "__find_arg__"


def tokenize(cmd: str) -> list[str]:
    cmd = re.sub(r"(?<=\s)\{\}(?=\s|$)", FIND_ARG, cmd)  # find -exec placeholder, not a brace group
    lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|(){}<>!\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # bash treats only a word-initial # as a comment; over-blocking is safer
    try:
        return list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a rough split
        return re.findall(r"\n|[;&|(){}<>!]+|[^\s;&|(){}<>!]+", cmd)


def substitutions(cmd: str) -> list[str]:
    inner = re.findall(r"\$\(([^()]*(?:\([^()]*\)[^()]*)*)\)", cmd)
    inner += re.findall(r"`([^`]*)`", cmd)
    return inner


def segments(tokens: list[str]) -> list[list[str]]:
    out, cur = [], []
    for tok in tokens:
        if tok in OPERATORS or (not cur and tok in KEYWORDS):
            if cur:
                out.append(cur)
            cur = []
        elif tok and set(tok) <= set(";&|(){}!\n"):  # operator runs such as ";;" or "&&("
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        out.append(cur)
    return out


def unwrap(words: list[str]) -> list[str]:
    """Drop leading assignments and wrapper commands with their options."""
    while words:
        head = words[0].rsplit("/", 1)[-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words = words[1:]
        elif head in ("sudo", "doas"):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-u", "-g", "-C", "-h", "-p") else words[1:]
        elif head == "env":
            words = words[1:]
            while words and (words[0].startswith("-") or "=" in words[0]):
                words = words[2:] if words[0] in ("-u", "-C", "-S") else words[1:]
        elif head == "timeout":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-s", "-k", "--signal", "--kill-after") else words[1:]
            words = words[1:]  # duration
        elif head == "nice":
            words = words[1:]
            if words and words[0] in ("-n", "--adjustment"):
                words = words[2:]
            elif words and re.fullmatch(r"-n?-?\d+|--adjustment=.*", words[0]):
                words = words[1:]
        elif head == "flock":
            words = words[1:]
            while words and words[0].startswith("-"):
                if words[0] in ("-c", "--command") and len(words) > 1:
                    return ["sh", "-c", words[1]]
                words = words[2:] if words[0] in ("-w", "--timeout", "-E", "--conflict-exit-code") else words[1:]
            words = words[1:]  # lock file or descriptor
            if words and words[0] in ("-c", "--command") and len(words) > 1:
                return ["sh", "-c", words[1]]
        elif head == "xargs":
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[2:] if words[0] in ("-I", "-n", "-P", "-L", "-d", "-E", "-s") else words[1:]
        elif head in ("nohup", "command", "exec", "time", "builtin", "stdbuf", "chrt", "ionice", "setsid"):
            words = words[1:]
            while words and words[0].startswith("-"):
                words = words[1:]
        else:
            return words
    return words


def current_branch(git_dir: str | None) -> str:
    try:
        args = ["git"] + (["-C", git_dir] if git_dir else []) + ["symbolic-ref", "--quiet", "--short", "HEAD"]
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def short_flags(args: list[str]) -> set[str]:
    flags: set[str] = set()
    for a in args:
        if a.startswith("--"):
            flags.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            flags.update(f"-{c}" for c in a[1:])
    return flags


def check_git(args: list[str]) -> str | None:
    git_dir, i = None, 0
    while i < len(args) and args[i].startswith("-"):
        if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            if args[i] == "-C" and i + 1 < len(args):
                git_dir = args[i + 1]
            i += 2
        else:
            i += 1
    if i >= len(args):
        return None
    sub, rest = args[i], args[i + 1:]
    flags = short_flags(rest)
    if sub == "push":
        if "--mirror" in flags:
            return "git push --mirror is blocked (it can delete remote branches)"
        force = bool(flags & {"-f", "--force", "--force-with-lease", "--force-if-includes"})
        positional = [a for a in rest if not a.startswith("-")]
        refspecs = positional[1:]
        if any(r.startswith("+") for r in refspecs):
            force = True
        targets = set()
        for spec in refspecs:
            spec = spec.lstrip("+")
            src, _, dst = spec.partition(":")
            dst = dst if ":" in spec else src
            if spec.startswith(":") and strip_prefix(dst, "refs/heads/") in PROTECTED:
                return "deleting a protected branch on a remote is blocked"
            if dst in ("HEAD", "@") or src in ("HEAD", "@") and not dst:
                dst = current_branch(git_dir)
            targets.add(strip_prefix(dst, "refs/heads/"))
        if flags & {"-d", "--delete"} and targets & PROTECTED:
            return "deleting a protected branch on a remote is blocked"
        if force and "--all" in flags:
            return "force push with --all is blocked"
        if force and (targets & PROTECTED or (not refspecs and current_branch(git_dir) in PROTECTED)):
            return "force push to main or develop is blocked"
    elif sub == "reset" and "--hard" in flags:
        return "git reset --hard is blocked (use git stash or a new branch)"
    elif sub == "clean" and (flags & {"-f", "--force"}) and (flags & {"-d", "-x", "-X"}):
        return "git clean with -f and -d/-x is blocked"
    elif sub == "update-ref" and flags & {"-d"} and any(strip_prefix(a, "refs/heads/") in PROTECTED for a in rest):
        return "deleting a protected branch ref is blocked"
    return None


def risky_rm_path(path: str) -> bool:
    if set(path) & GLOB_CHARS:
        # Allow only globs that cannot reach dotfiles or the repository root: "dir/*", "build/*.js".
        head, _, last = path.rpartition("/")
        return (not head or head.startswith((".", "/", "~", "$")) or set(head) & GLOB_CHARS
                or last.startswith((".", "[", "?")) or ".." in path.split("/"))
    if path.startswith(TEMP_PREFIXES):
        norm = posixpath.normpath(path)
        return ".." in path.split("/") or norm in ("/tmp", "/var/tmp")
    if path.startswith(("/", "~", "$")) or path in (".", "..", "*", ".git") or ".." in path.split("/"):
        return True
    return posixpath.normpath(path).split("/")[0] == ".git"


def reason_for_words(words: list[str], depth: int) -> str | None:
    words = unwrap(words)
    if not words:
        return None
    name, args = words[0].rsplit("/", 1)[-1], words[1:]
    if name in SHELLS:
        for j, a in enumerate(args):
            if a == "<<<" and j + 1 < len(args):
                return reason_for(args[j + 1], depth + 1)
            if a.startswith("-") and not a.startswith("--") and "c" in a and j + 1 < len(args):
                return reason_for(args[j + 1], depth + 1)
        if HEREDOC_MARK in args:
            return None  # the heredoc body was analysed as a script
        script = next((a for a in args if not a.startswith("-") and not set(a) <= set("<>")), None)
        if script is None or "-s" in short_flags(args):
            return "a shell reading commands from stdin is blocked (pass a script file or -c)"
        return None
    if name == "eval":
        return reason_for(" ".join(args), depth + 1)
    if name == "find":
        for j, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                roots = [r for r in args[:j] if not r.startswith("-")][:1] or ["."]
                safe_roots = all(not risky_rm_path(r) or r == "." for r in roots)
                inner = [w for w in args[j + 1:] if w not in ("+", ";")]
                inner = [("found-path" if w == FIND_ARG else w) for w in inner if w != FIND_ARG or safe_roots]
                why = reason_for_words(inner, depth + 1)
                if why:
                    return why
        if "-delete" in args and (any(p in ("/", "~", "..", ".git") for p in args)
                                  or not set(args) & FIND_PREDICATES):
            return "find -delete without a narrowing predicate (or on a protected path) is blocked"
    if name == "dropdb":
        return "dropdb is blocked"
    if name in INTERPRETERS and any(QUOTED_ENV.search(a) for a in args if not a.startswith("--env-file")):
        return "reading .env files is blocked (use .env.example; secrets never enter the context)"
    if name == "pkill" and short_flags(args) & {"-f", "--full"}:
        return "pkill -f is blocked: kill only by verified PID (OD-74)"
    if name == "git":
        return check_git(args)
    if name == "rm":
        flags = short_flags(args)
        if flags & {"-r", "-R", "--recursive"} and flags & {"-f", "--force"}:
            paths = [a for a in args if not a.startswith("-")]
            if not paths or any(risky_rm_path(p) for p in paths):
                return "rm -rf outside a temp directory or the working tree is blocked"
    if name in ("docker", "podman"):
        joined = " ".join(args)
        if re.search(r"\b(system|volume|image|builder|container|network)\s+prune\b", joined):
            return "docker prune is blocked"
        if re.search(r"\bvolume\s+rm\b", joined):
            return "docker volume rm is blocked"
        if re.search(r"\bcompose\b", joined) and "down" in args and short_flags(args) & {"-v", "--volumes"}:
            return "docker compose down -v is blocked (it deletes volumes)"
    if name == "docker-compose" and "down" in args and short_flags(args) & {"-v", "--volumes"}:
        return "docker compose down -v is blocked (it deletes volumes)"
    return None


def env_reference(words: list[str]) -> bool:
    """True when a word of one command segment names a .env file (message values of git/gh skipped)."""
    skip = False
    message_cmd = bool(words) and words[0].rsplit("/", 1)[-1] in ("git", "gh")
    if message_cmd and len(words) > 1 and (words[1] in ("check-ignore", "ls-files")
                                           or (words[1] == "rm" and "--cached" in words)):
        return False  # these do not read the file content
    for tok in words:
        if skip:
            skip = False
            continue
        if (message_cmd and tok in MESSAGE_FLAGS) or tok in ("--env-file", "--env-file-if-exists"):
            skip = True
            continue
        if tok.startswith("--env-file") or tok.startswith(("--message=", "--grep=", "--title=", "--body=")):
            continue
        base = tok.rsplit("/", 1)[-1]
        if ENV_TOKEN.search(tok) and not SAFE_ENV_SUFFIX.search(base):
            return True
    return False


def split_heredocs(cmd: str) -> tuple[str, list[tuple[str, bool, str]]]:
    """Replace heredoc bodies with a marker; return them with their consumer command and quoting."""
    bodies: list[tuple[str, bool, str]] = []

    def repl(m: re.Match) -> str:
        line_start = cmd.rfind("\n", 0, m.start()) + 1
        segs = segments(tokenize(cmd[line_start:m.start()]))
        words = unwrap(segs[-1]) if segs else []
        names = [w.split()[0].rsplit("/", 1)[-1] for w in words if w.split()]
        consumer = next((n for n in names if n in SHELLS | INTERPRETERS | DB_CLIENTS), names[0] if names else "")
        bodies.append((consumer, bool(m.group(1)), m.group(4)))
        return f"<< {HEREDOC_MARK}{m.group(3)}"

    return HEREDOC.sub(repl, cmd), bodies


def reason_for_heredoc(consumer: str, quoted: bool, body: str, depth: int) -> str | None:
    if consumer in SHELLS:
        return reason_for(body, depth + 1)
    if consumer in INTERPRETERS and QUOTED_ENV.search(body):
        return "reading .env files is blocked (use .env.example; secrets never enter the context)"
    if consumer in DB_CLIENTS and SQL.search(body):
        return "destructive SQL (DROP DATABASE/SCHEMA/TABLE, TRUNCATE) is blocked"
    if not quoted:  # unquoted delimiters expand $(...) and backticks inside the body
        for inner in substitutions(body):
            why = reason_for(inner, depth + 1)
            if why:
                return why
    return None  # other bodies are data (commit messages, PR bodies, files)


def reason_for(cmd: str, depth: int = 0) -> str | None:
    if depth > 4:
        return None
    cmd, bodies = split_heredocs(cmd)
    for consumer, quoted, body in bodies:
        why = reason_for_heredoc(consumer, quoted, body, depth)
        if why:
            return why
    tokens = tokenize(cmd)
    for words in segments(tokens):
        if env_reference(unwrap(words)):
            return "reading or copying .env files is blocked (use .env.example; secrets never enter the context)"
        if SQL.search(" ".join(words)) and unwrap(words) and unwrap(words)[0].rsplit("/", 1)[-1] not in ("git", "gh"):
            return "destructive SQL (DROP DATABASE/SCHEMA/TABLE, TRUNCATE) is blocked"
        why = reason_for_words(words, depth)
        if why:
            return why
    if re.search(r"\bpgrep\b[^;&|]*?\s-[A-Za-z]*f", cmd) and re.search(r"(^|[\s;&|(`])kill\b", cmd):
        return "killing the output of pgrep -f is blocked: kill only by verified PID (OD-74)"
    for inner in substitutions(cmd):
        why = reason_for(inner, depth + 1)
        if why:
            return why
    return None


def command_of(event: dict) -> str:
    tool_input = event.get("tool_input") if isinstance(event, dict) else None
    cmd = (tool_input or {}).get("command", "") if isinstance(tool_input, dict) else ""
    if isinstance(cmd, list):
        cmd = " ".join(shlex.quote(str(c)) for c in cmd)
    return str(cmd)


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
    except ValueError:
        return 0  # not a tool event; nothing to guard
    try:
        why = reason_for(command_of(event))
    except Exception as exc:  # noqa: BLE001 - fail closed on any internal error
        why = f"guard-bash could not analyse the command ({exc.__class__.__name__}); failing closed"
    if why:
        print(f"BLOCKED by guard-bash: {why}. Do not work around this; ask the owner.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.environ.setdefault("LC_ALL", "C")
    sys.exit(main())
