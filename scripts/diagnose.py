#!/usr/bin/env python
"""
Checks your setup step by step and prints what is wrong.   Usage:  python scripts/diagnose.py
"""
import os
import sys
import time
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
OK, BAD, WARN = "[ OK ]", "[FAIL]", "[WARN]"
problems = []


def step(name, fn):
    t0 = time.time()
    try:
        ok, msg = fn()
    except Exception as exc:
        ok, msg = False, f"{type(exc).__name__}: {exc}"
    tag = OK if ok is True else WARN if ok is None else BAD
    print(f"{tag} {name} ({time.time() - t0:.1f}s) - {msg}")
    if ok is False:
        problems.append(f"{name}: {msg}")


def packages():
    missing = []
    for mod, pip in [("flask", "flask"), ("flask_login", "flask-login"), ("requests", "requests"), ("dotenv", "python-dotenv"),
                     ("reportlab", "reportlab"), ("bs4", "beautifulsoup4"), ("lxml", "lxml")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip)
    if missing:
        return False, "missing packages: " + ", ".join(missing) + "  ->  run: pip install -r requirements.txt"
    try:
        import ddgs  # noqa: F401
        return True, "all required packages installed"
    except ImportError:
        return None, "all required packages installed; optional 'ddgs' missing (free search will use a fallback)"


def env_file():
    from config import Config
    if not (ROOT / ".env").exists():
        return False, ".env file not found. Run: copy .env.example .env  and add GROQ_API_KEY"
    k = Config.GROQ_API_KEY
    if not k:
        return False, "GROQ_API_KEY is empty in .env"
    from services.groq_service import key_problem
    if key_problem(k):
        return False, "GROQ_API_KEY has invalid characters (quotes, spaces or non-English symbols). Re-copy it from console.groq.com"
    return True, f"GROQ_API_KEY set ({len(k)} chars), model={Config.GROQ_MODEL}" + (f" [{Config.MODEL_NOTE}]" if Config.MODEL_NOTE else "") + \
        f", Tavily key {'set' if Config.TAVILY_API_KEY else 'not set (free search will be used)'}"


def groq():
    from services.groq_service import GroqService
    ok, msg = GroqService().test_connection()
    return ok, msg


def search():
    from services.search_service import SearchService
    s = SearchService()
    res = s.search("food waste management software market size")
    if not res:
        return False, "web search returned nothing: " + str(s.diagnostics[-1].get("error")) + "  -> add a free TAVILY_API_KEY to .env"
    return True, f"{len(res)} results via {res[0]['provider']}; first: {res[0]['url']}"


def website():
    from services.evidence import fetch_page
    p = fetch_page("https://example.com")
    return (True, f"fetched '{p['title']}'") if p["ok"] else (False, f"cannot open websites: {p['error']} (firewall/proxy?)")


def database_and_pages():
    from config import Config
    tmp = tempfile.mkdtemp()
    Config.DATABASE_PATH = os.path.join(tmp, "diag.db")
    from app import create_app
    app = create_app({"TESTING": True})
    c = app.test_client()
    codes = {u: c.get(u).status_code for u in ("/login", "/register")}
    static_ok = all((ROOT / "static" / "css" / f).exists() for f in ("style.css", "dashboard.css"))
    bad = [u for u, code in codes.items() if code != 200]
    if bad or not static_ok:
        return False, f"pages failing: {bad}, css present: {static_ok}"
    return True, "database created, login/register pages render, CSS files present"


print(f"Python {sys.version.split()[0]} | folder: {ROOT}\n")
for name, fn in [("Packages", packages), (".env file", env_file), ("Database + pages", database_and_pages),
                 ("Groq AI call", groq), ("Web search", search), ("Open a website", website)]:
    step(name, fn)

print()
if problems:
    print("PROBLEMS FOUND:")
    for p in problems:
        print("  -", p)
    print("\nFix the first one, run this again, and send me this output if anything is still failing.")
else:
    print("Everything checks out. If the app still misbehaves, send me the last 15 lines of the terminal where 'python run.py' is running.")
