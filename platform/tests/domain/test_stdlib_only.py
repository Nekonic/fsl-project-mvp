import ast
import sys
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "domain"


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_domain_imports_only_the_standard_library_and_itself():
    modules = sorted(DOMAIN.rglob("*.py"))
    assert modules
    foreign = {
        str(path.relative_to(DOMAIN)): sorted(roots)
        for path in modules
        if (roots := imported_roots(path) - set(sys.stdlib_module_names) - {"domain", "__future__"})
    }

    assert foreign == {}
