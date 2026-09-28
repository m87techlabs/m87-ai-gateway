"""Check local Markdown targets and code fences without network access.

Mermaid blocks are checked for a recognized diagram declaration. Rendering and
full Mermaid syntax validation remain separate review checks.
"""

from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
LINK = re.compile(r"\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
MERMAID = re.compile(
    r"^(flowchart|graph|sequenceDiagram|stateDiagram-v2|classDiagram|erDiagram|"
    r"journey|gantt|pie|mindmap|timeline|gitGraph|quadrantChart|requirementDiagram)\b"
)


def check_document(path: Path) -> list[str]:
    errors = []
    opened: tuple[str, int, int, str] | None = None
    diagram_lines: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = FENCE.match(line)
        if opened:
            character, length, start, language = opened
            if (
                match
                and match[1][0] == character
                and len(match[1]) >= length
                and not match[2].strip()
            ):
                if language == "mermaid":
                    content = [
                        item.strip() for item in diagram_lines
                        if item.strip() and not item.strip().startswith("%%")
                    ]
                    if not content or not MERMAID.match(content[0]):
                        errors.append(f"{path}:{start}: missing Mermaid diagram declaration")
                opened = None
                diagram_lines = []
            else:
                diagram_lines.append(line)
            continue
        if match:
            opened = (match[1][0], len(match[1]), number, match[2].strip())
            continue
        for target in LINK.findall(line):
            reference = urlsplit(target.strip("<>"))
            if reference.scheme or reference.netloc or not reference.path:
                continue
            destination = (path.parent / unquote(reference.path)).resolve()
            if not destination.is_relative_to(ROOT) or not destination.exists():
                errors.append(f"{path}:{number}: missing or non-repository target: {target}")
    if opened:
        errors.append(f"{path}:{opened[2]}: unclosed code fence")
    return errors


def main() -> int:
    listing = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    ).decode()
    documents = sorted({ROOT / name for name in listing.split("\0") if name.endswith(".md")})
    errors = [error for path in documents for error in check_document(path)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Checked links and fences in {len(documents)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
