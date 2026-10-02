from __future__ import annotations

import base64, ipaddress, os, re, shlex, socket, subprocess, tempfile, threading
from pathlib import Path
from urllib.parse import urlparse

_LOCK = threading.Lock()
DEFAULT_ARGS = "--no-sandbox,--disable-dev-shm-usage,--disable-gpu,--disable-extensions,--disable-background-networking,--renderer-process-limit=2,--js-flags=--max-old-space-size=256"
BLOCKED_SUFFIXES = (".localhost",".local",".internal",".lan",".home.arpa",".railway.internal")
BLOCKED_HOSTS = {"localhost","metadata","metadata.google.internal"}
DENIED_COMMANDS = {"install","upgrade","plugin","dashboard","chat","mcp","connect","profiles","upload","stream","inspect"}
DENIED_FLAGS = {"--allow-file-access","--executable-path","--extension","--init-script","--config","--cdp","--auto-connect","--provider","-p","--profile","--headed","--plugin","--fix","--with-deps","--args","--webgpu","--engine"}
URL_COMMANDS = {"open","goto","navigate","read","a11y","vitals","pushstate"}

class CliError(RuntimeError): pass
class PolicyError(CliError): pass

def _int(name, default):
    try: return int(os.environ.get(name, default))
    except ValueError: return default

def output_limit(): return _int("OUTPUT_LIMIT", 30000)
def memory_limit_mb(): return _int("MEMORY_LIMIT_MB", 900)

def child_env():
    env=dict(os.environ)
    extra=env.pop("CHROME_ARGS_EXTRA","").strip()
    env.setdefault("AGENT_BROWSER_ARGS", DEFAULT_ARGS + ("," + extra if extra else ""))
    env.setdefault("AGENT_BROWSER_IDLE_TIMEOUT_MS","600000")
    env.setdefault("AGENT_BROWSER_MAX_OUTPUT",str(output_limit()))
    env.setdefault("AGENT_BROWSER_CONTENT_BOUNDARIES","1")
    env.setdefault("AGENT_BROWSER_SESSION","default")
    env.setdefault("AGENT_BROWSER_DEFAULT_TIMEOUT","25000")
    return env

def _public(ip):
    mapped=getattr(ip,"ipv4_mapped",None)
    return (mapped or ip).is_global

def check_url(url):
    url=url.strip()
    if not url: raise PolicyError("Empty URL.")
    if url.startswith("//"): url="https:"+url
    elif "://" not in url:
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:",url) and not re.match(r"^[^/:]+:\d+(/|$)",url):
            pass
        else: url="https://"+url
    p=urlparse(url)
    if p.scheme not in ("http","https"): raise PolicyError("Only http(s) URLs are allowed.")
    host=(p.hostname or "").lower().rstrip(".")
    if not host: raise PolicyError("URL has no host.")
    if os.environ.get("ALLOW_PRIVATE_NETWORK","0")=="1": return url
    if host in BLOCKED_HOSTS or host.endswith(BLOCKED_SUFFIXES): raise PolicyError(f"Host '{host}' is internal and blocked.")
    try:
        ip=ipaddress.ip_address(host)
        if not _public(ip): raise PolicyError(f"Address {host} is not public and is blocked.")
        return url
    except ValueError:
        pass
    if all(re.fullmatch(r"\d+|0x[0-9a-f]+",x) for x in host.split(".")):
        raise PolicyError("Numeric hosts are blocked.")
    try: infos=socket.getaddrinfo(host,None)
    except OSError: return url
    for info in infos:
        try: ip=ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError: continue
        if not _public(ip): raise PolicyError(f"'{host}' resolves to a non-public address and is blocked.")
    return url

def split_command(command):
    try: args=shlex.split(command)
    except ValueError as e: raise CliError(str(e))
    if args and args[0]=="agent-browser": args=args[1:]
    if not args: raise CliError("Empty command.")
    return args

def check_cli_args(args):
    out=list(args)
    positional=[x for x in out if not x.startswith("-")]
    cmd=positional[0] if positional else ""
    if cmd in DENIED_COMMANDS: raise PolicyError(f"Command '{cmd}' is not available.")
    for x in out:
        if x.startswith("-") and x.split("=",1)[0] in DENIED_FLAGS:
            raise PolicyError(f"Flag '{x.split('=',1)[0]}' is not available.")
    if cmd in URL_COMMANDS or (cmd=="tab" and "new" in out) or (cmd=="diff" and "url" in out):
        for i,x in enumerate(out):
            if x.startswith("-") or x in {cmd,"tab","new","diff","url"}: continue
            if "://" in x or "." in x: out[i]=check_url(x)
    return out

def clip(text, limit=None):
    limit=limit or output_limit()
    return text if len(text)<=limit else text[:limit]+f"\n...[truncated {len(text)-limit} chars]"

def run(args, timeout=60):
    with _LOCK:
        try:
            p=subprocess.run(["agent-browser",*args],capture_output=True,text=True,timeout=timeout,env=child_env())
        except FileNotFoundError as e: raise CliError("agent-browser binary not found.") from e
        except subprocess.TimeoutExpired as e: raise CliError(f"agent-browser timed out after {timeout}s.") from e
    if p.returncode:
        raise CliError(clip((p.stderr or p.stdout or f"exit {p.returncode}").strip(),2000))
    return p

def run_text(args, timeout=60):
    p=run(args,timeout)
    return clip((p.stdout or p.stderr or "ok").strip())

def screenshot(full=False, annotate=False, quality=60):
    quality=max(10,min(95,quality))
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/"shot.jpg"
        args=["screenshot",str(path),"--screenshot-format","jpeg","--screenshot-quality",str(quality)]
        if full: args.append("--full")
        if annotate: args.append("--annotate")
        p=run(args,60)
        if not path.exists(): raise CliError("Screenshot was not produced.")
        data=path.read_bytes()
    extra="\n".join(x for x in (p.stdout or "").splitlines() if x.strip() and "Screenshot saved" not in x)
    return data,extra

def to_base64(data): return base64.b64encode(data).decode()

def process_rss():
    rows=[]
    for e in Path("/proc").iterdir():
        if not e.name.isdigit(): continue
        try: s=(e/"status").read_text()
        except OSError: continue
        name="?"
        rss=0
        for line in s.splitlines():
            if line.startswith("Name:"): name=line.split(None,1)[1]
            elif line.startswith("VmRSS:"): rss=int(line.split()[1])/1024
        rows.append((name,rss))
    return rows

def memory_report():
    root=Path("/sys/fs/cgroup")
    try:
        cur=int((root/"memory.current").read_text())
        inactive=0
        try:
            for line in (root/"memory.stat").read_text().splitlines():
                if line.startswith("inactive_file "): inactive=int(line.split()[1])
        except OSError: pass
        used=max(cur-inactive,0)/1048576
        source="cgroup-v2"
    except OSError:
        used=sum(x[1] for x in process_rss()); source="rss"
    lim=memory_limit_mb()
    groups={}
    for name,rss in process_rss():
        key="chrome" if "chrom" in name.lower() else name
        groups[key]=groups.get(key,0)+rss
    return {"used_mb":round(used),"limit_mb":lim,"percent":round(100*used/lim) if lim else None,"source":source,"top_rss_mb_by_process":dict(sorted(groups.items(),key=lambda x:x[1],reverse=True)[:5])}

def memory_guard():
    rep=memory_report()
    pct=_int("MEM_GUARD_PCT",85)
    if pct>0 and rep["percent"] is not None and rep["percent"]>=pct:
        try: run(["close","--all"],30)
        except CliError: pass
        return f"Memory was {rep['used_mb']} MB of {rep['limit_mb']} MB, so Chrome was restarted."
    return None
