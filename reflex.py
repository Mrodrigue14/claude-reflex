"""claude-reflex: a Claude Code UserPromptSubmit hook that runs simple desktop commands without calling the model.

Pipeline: filter -> regex rules -> local e5 classifier (only if no rule matched) -> allowlisted action.
When in doubt it prints nothing and the prompt goes to Claude unchanged. Windows only.
Inspired by the "reflex" mode of Nūs Companion (potlakai/nus-companion, Apache-2.0).
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
from urllib.parse import quote_plus

HERE = os.path.dirname(os.path.abspath(__file__))
OFF = os.path.join(HERE, "off")
CONFIG = os.path.join(HERE, "config.json")
MODEL = os.path.join(HERE, "model", "model_quantized.onnx")
TOKENIZER = os.path.join(HERE, "model", "tokenizer.json")
EXAMPLES_CACHE = os.path.join(HERE, "model", "examples.npz")
CATALOG = os.path.join(HERE, "catalog.json")
LOG = os.path.join(HERE, "log.jsonl")
DRY = os.environ.get("REFLEX_DRY") == "1"
MAX_LEN = 60
SCORE_MIN, MARGIN_MIN = 0.88, 0.05
PORT, IDLE_EXIT_S = 47321, 3600

SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com", "github": "https://github.com",
    "google": "https://www.google.com", "google maps": "https://maps.google.com", "maps": "https://maps.google.com",
    "netflix": "https://www.netflix.com", "reddit": "https://www.reddit.com", "wikipedia": "https://www.wikipedia.org",
    "linkedin": "https://www.linkedin.com", "facebook": "https://www.facebook.com", "instagram": "https://www.instagram.com",
    "amazon": "https://www.amazon.com", "claude": "https://claude.ai",
}
BROWSER_EXE = {"firefox": "firefox.exe", "chrome": "chrome.exe", "edge": "msedge.exe"}
# Start-menu names are localized, so each alias lists the names to try in order.
ALIASES = {
    "notepad": ["notepad", "bloc-notes"], "bloc notes": ["bloc-notes"],
    "calculator": ["calculator", "calculatrice"], "calc": ["calculator", "calculatrice"],
    "settings": ["settings", "parametres"], "explorer": ["file explorer", "explorateur de fichiers"],
    "explorateur": ["explorateur de fichiers"],
}
JUNK_APP = re.compile(r"uninstall|desinstall|readme|lisez|help|aide|manual|manuel|website|release notes", re.I)
FILLER = re.compile(r"^(yes|no|ok|okay|thanks|thank you|continue|go(?!\s+to\b)|do it|perfect|great|cool|stop|"
                    r"oui|non|d'accord|merci|vas-y|fais-le|parfait|super)\b", re.I)

# Patterns accept English and French phrasing.
POLITE = r"(?:(?:hey|ok|please|can you|could you|stp|svp|peux-tu|tu peux)[\s,]+)*"
OPEN = r"(?:open|launch|start|go to|ouvre|ouvrir|lance|lancer|d[ée]marre|d[ée]marrer|va sur|aller sur)"
ARTICLE = r"(?:(?:the|my|a|an|le|la|les|un|une|mon|ma|mes)\s+|l')?"
KEY_RULES = [
    ("volume_up", r"volume up|louder|turn it up|turn up the (?:volume|sound)|"
                  r"(?:monte|augmente|hausse)\s+(?:le\s+)?(?:volume|son)|plus fort"),
    ("volume_down", r"volume down|quieter|turn it down|turn down the (?:volume|sound)|"
                    r"(?:baisse|diminue)\s+(?:le\s+)?(?:volume|son)|moins fort"),
    ("mute", r"mute|unmute|silence|(?:coupe|d[ée]sactive)\s+(?:le\s+)?son"),
    ("next_track", r"next (?:song|track)|skip|(?:chanson|piste|toune)\s+suivante"),
    ("prev_track", r"previous (?:song|track)|(?:chanson|piste|toune)\s+pr[ée]c[ée]dente"),
    ("play_pause", r"play|pause|resume|pause the music|(?:mets\s+)?pause(?:\s+la\s+musique)?|reprends(?:\s+la\s+musique)?"),
]
SEARCH = re.compile(r"^" + POLITE + r"(?:(?:search|cherche|recherche)\s+(?:on|sur)\s+(?:google|the web|le web|internet)|google)\s+(.+)$", re.I)
OPEN_RX = re.compile(r"^" + POLITE + OPEN + r"\s+" + ARTICLE + r"(.+?)(?:\s+(?:in|with|dans|avec|sur)\s+(firefox|chrome|edge))?$", re.I)
DOMAIN = re.compile(r"^(?:https?://)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)(/\S*)?$", re.I)
VK = {"volume_up": (0xAF, 3), "volume_down": (0xAE, 3), "mute": (0xAD, 1),
      "next_track": (0xB0, 1), "prev_track": (0xB1, 1), "play_pause": (0xB3, 1)}

# Classifier examples (multilingual model, so any language works). "none" holds requests meant for Claude.
EXAMPLES = {
    "volume_up": ["I can't hear anything", "it's too quiet", "the sound is too low", "a bit more volume",
                  "c'est pas assez fort", "j'entends rien", "le son est trop bas", "c'est trop faible"],
    "volume_down": ["it's way too loud", "that's too loud", "less noise please", "lower the sound a bit",
                    "c'est trop fort", "moins de bruit", "le son est trop haut", "réduis le volume"],
    "mute": ["shh", "no sound", "kill the sound", "chut", "plus de son", "enlève le son"],
    "next_track": ["skip this one", "change the song", "I don't like this song",
                   "passe à la suivante", "change de chanson"],
    "play_pause": ["stop the music", "put the music back on", "arrête la musique", "remets la musique"],
    "open_app": ["put on spotify", "I want to listen to spotify", "show me the calculator", "I need notepad",
                 "mets spotify", "affiche la calculatrice", "j'ai besoin du bloc-notes"],
    "open_site": ["show me youtube", "I want to watch netflix", "take me to github",
                  "montre-moi youtube", "je veux voir netflix", "amène-moi sur github"],
    "none": ["explain this code", "fix the error", "make a commit", "summarize the file", "run the tests",
             "find the bug", "add a function", "why does it crash", "write a test", "proofread my text",
             "what's the problem", "redo it", "change the button color", "open the file", "show me the diff",
             "update the readme", "show the logs", "do it again", "try again", "not that", "undo",
             "next step", "looks good", "it doesn't work", "look again",
             "explique ce code", "corrige l'erreur", "fais un commit", "lance les tests", "cherche le bug",
             "pourquoi ça plante", "ouvre le fichier", "montre-moi le diff", "affiche les logs",
             "fais-le encore", "recommence", "passe à l'étape suivante", "ça marche pas"],
}


def load_config():
    """Merge the optional config.json (sites, aliases, extra examples) into the defaults."""
    if not os.path.exists(CONFIG):
        return
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    SITES.update(cfg.get("sites", {}))
    ALIASES.update(cfg.get("aliases", {}))
    for intent, phrases in cfg.get("examples", {}).items():
        EXAMPLES.setdefault(intent, []).extend(phrases)


load_config()


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip(" .!")


def passes_filter(text):
    t = text.strip()
    return 0 < len(t) <= MAX_LEN and "\n" not in t and not t.startswith("/") and not t.endswith("?")


# ---------- app catalog ----------
def load_catalog():
    if not os.path.exists(CATALOG) or time.time() - os.path.getmtime(CATALOG) > 86400:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"],
                             capture_output=True, text=True, encoding="utf-8", timeout=15).stdout
        with open(CATALOG, "w", encoding="utf-8") as f:
            f.write(out)
    with open(CATALOG, encoding="utf-8") as f:
        return [a for a in json.load(f) if not JUNK_APP.search(a["Name"])]


def match_app(slug, catalog):
    hits = []
    for a in catalog:
        name, appid = norm(a["Name"]), a["AppID"].lower()
        if name == slug:
            hits.append((0, a))
        elif len(slug) >= 4 and (name.startswith(slug + " ") or name.endswith(" " + slug) or slug in re.split(r"[._!\\ ]", appid)):
            hits.append((1, a))
        elif len(slug) >= 5 and slug in appid:
            hits.append((2, a))
    return min(hits, key=lambda h: (h[0], len(h[1]["Name"])))[1] if hits else None


def find_app(name):
    slug = norm(name)
    if not slug:
        return None
    catalog = load_catalog()
    for candidate in [slug] + [norm(c) for c in ALIASES.get(slug, [])]:
        app = match_app(candidate, catalog)
        if app:
            return app
    return None


def resolve_target(target, browser):
    t = norm(target)
    if t in SITES:
        return {"intent": "open_site", "arg": SITES[t], "browser": browser}
    m = DOMAIN.match(target.strip())
    if m and " " not in target.strip():
        return {"intent": "open_site", "arg": "https://" + m.group(1) + (m.group(2) or ""), "browser": browser}
    if browser:
        return None
    app = find_app(target)
    return app and {"intent": "open_app", "arg": app["Name"], "browser": None, "appid": app["AppID"]}


# ---------- rules ----------
def rules(text):
    t = text.strip()
    for intent, rx in KEY_RULES:
        if re.fullmatch(POLITE + r"(?:" + rx + r")[\s.!]*", t, re.I):
            return {"intent": intent, "arg": None, "browser": None}
    m = SEARCH.match(t)
    if m:
        return {"intent": "web_search", "arg": m.group(1).strip(), "browser": None}
    m = OPEN_RX.match(t)
    if m:
        return resolve_target(m.group(1), m.group(2) and m.group(2).lower())
    return None


# ---------- classifier ----------
class Encoder:
    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.np = np
        self.tok = Tokenizer.from_file(TOKENIZER)
        self.tok.enable_padding()
        self.sess = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
        self.inputs = {i.name for i in self.sess.get_inputs()}

    def __call__(self, texts):
        np = self.np
        enc = self.tok.encode_batch(["query: " + t for t in texts])
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        hidden = self.sess.run(None, feed)[0]
        vec = (hidden * mask[..., None]).sum(1) / mask.sum(1, keepdims=True)
        return vec / np.linalg.norm(vec, axis=1, keepdims=True)


def example_vectors(enc):
    np = enc.np
    labels = [k for k, v in EXAMPLES.items() for _ in v]
    key = json.dumps(EXAMPLES, ensure_ascii=False)
    if os.path.exists(EXAMPLES_CACHE):
        c = np.load(EXAMPLES_CACHE, allow_pickle=False)
        if str(c["key"]) == key:
            return labels, c["vecs"]
    vecs = enc([t for v in EXAMPLES.values() for t in v])
    np.savez(EXAMPLES_CACHE, key=key, vecs=vecs)
    return labels, vecs


class Classifier:
    def __init__(self):
        self.enc = Encoder()
        self.labels, self.vecs = example_vectors(self.enc)

    def label(self, text):
        best = {}
        for lab, s in zip(self.labels, self.vecs @ self.enc([text])[0]):
            best[lab] = max(best.get(lab, -1.0), float(s))
        intent = max((k for k in best if k != "none"), key=best.get)
        ok = best[intent] >= SCORE_MIN and best[intent] - best["none"] >= MARGIN_MIN
        return intent if ok else None


_local = None


def ask_server(text):
    """Ask the background classifier; start it if it isn't running (this prompt then passes to Claude)."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.05) as s:
            s.settimeout(0.5)
            s.sendall(text.encode("utf-8") + b"\n")
            return s.makefile(encoding="utf-8").readline().strip() or None
    except OSError:
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        subprocess.Popen([pythonw, os.path.abspath(__file__), "serve"], close_fds=True,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        return None


def serve():
    """Keep the model loaded (about 1.4 s to load) and exit after an hour without requests."""
    import socketserver
    clf = Classifier()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            text = self.rfile.readline().decode("utf-8", "replace").strip()
            self.wfile.write(((clf.label(text) or "") + "\n").encode("utf-8"))

    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as srv:
        srv.timeout = IDLE_EXIT_S
        idle = []
        srv.handle_timeout = lambda: idle.append(1)
        while not idle:
            srv.handle_request()


def model_intent(text):
    global _local
    if not os.path.exists(MODEL) or len(text.split()) > 8:
        return None
    if DRY:
        _local = _local or Classifier()
        intent = _local.label(text)
    else:
        intent = ask_server(text)
    if not intent:
        return None
    if intent in VK:
        return {"intent": intent, "arg": None, "browser": None}
    words = norm(text).split()
    grams = [" ".join(words[i:i + n]) for n in (3, 2, 1) for i in range(len(words) - n + 1)]
    for g in grams:
        if intent == "open_site" and g in SITES:
            return {"intent": "open_site", "arg": SITES[g], "browser": None}
        if intent == "open_app" and len(g) >= 4 and (app := find_app(g)):
            return {"intent": "open_app", "arg": app["Name"], "browser": None, "appid": app["AppID"]}
    return None


def decide(text, classify=True):
    text = text or ""
    if not passes_filter(text) or FILLER.match(text.strip()):
        return None
    d = rules(text)
    if d is None and classify:
        try:
            d = model_intent(text)
        except Exception:
            d = None
    return d


# ---------- actions ----------
def browser_path(name):
    import winreg
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, r"Software\Microsoft\Windows\CurrentVersion\App Paths\\" + BROWSER_EXE[name]) as k:
                return winreg.QueryValue(k, None)
        except OSError:
            pass
    return None


def open_url(url, browser):
    exe = browser and browser_path(browser)
    if exe:
        subprocess.Popen([exe, url])
    else:
        os.startfile(url)


def act(d):
    i, arg = d["intent"], d.get("arg")
    if i in VK:
        import ctypes
        vk, n = VK[i]
        for _ in range(n):
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return {"volume_up": "volume up", "volume_down": "volume down", "mute": "mute toggled",
                "next_track": "next track", "prev_track": "previous track", "play_pause": "play/pause"}[i]
    if i == "open_app":
        subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + d["appid"]])
        return "opened " + arg
    if i == "open_site":
        open_url(arg, d.get("browser"))
        return "opened " + arg + (" in " + d["browser"] if d.get("browser") else "")
    if i == "web_search":
        open_url("https://www.google.com/search?q=" + quote_plus(arg), None)
        return 'searched "' + arg + '"'
    raise ValueError(i)


def handle_raw(raw):
    try:
        if os.path.exists(OFF):
            return ""
        t0 = time.perf_counter()
        prompt = json.loads(raw).get("prompt", "")
        d = decide(prompt)
        if not d:
            return ""
        msg = "(dry run) " + d["intent"] if DRY else act(d)
        ms = int((time.perf_counter() - t0) * 1000)
        if not DRY:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.time(), "prompt": prompt, **d, "ms": ms}, ensure_ascii=False) + "\n")
        return json.dumps({"decision": "block", "reason": f"⚡ Reflex: {msg} ({ms} ms)"}, ensure_ascii=False)
    except Exception:
        return ""


def main():
    if sys.argv[1:] == ["serve"]:
        return serve()
    sys.stdout.reconfigure(encoding="utf-8")
    out = handle_raw(sys.stdin.buffer.read().decode("utf-8", "replace"))
    if out:
        print(out)


if __name__ == "__main__":
    main()
