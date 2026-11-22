"""Download the classifier model and print the hook entry for ~/.claude/settings.json."""
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/"
FILES = {"onnx/model_quantized.onnx": "model_quantized.onnx", "tokenizer.json": "tokenizer.json"}


def download():
    os.makedirs(os.path.join(HERE, "model"), exist_ok=True)
    for remote, local in FILES.items():
        dest = os.path.join(HERE, "model", local)
        if os.path.exists(dest):
            print("already here:", local)
            continue
        print("downloading", remote, "...")
        urllib.request.urlretrieve(REPO + remote, dest + ".part")
        os.replace(dest + ".part", dest)


def hook_entry():
    script = os.path.join(HERE, "reflex.py").replace("\\", "/")
    return {"type": "command", "command": sys.executable.replace("\\", "/"), "args": [script], "timeout": 5}


if __name__ == "__main__":
    download()
    print("\nAdd this to hooks.UserPromptSubmit[].hooks in ~/.claude/settings.json:\n")
    print(json.dumps(hook_entry(), indent=2))
