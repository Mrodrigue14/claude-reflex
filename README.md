# claude-reflex

A Claude Code hook that runs simple desktop commands on Windows without calling the model.

Type `open youtube`, `volume up` or `launch the calculator` in Claude Code and the action happens in about 50 ms, with no tokens spent. Anything else goes to Claude unchanged.

```
> open spotify
⚡ Reflex: opened Spotify (61 ms)
```

## How it works

claude-reflex is a `UserPromptSubmit` hook. Each prompt goes through four steps:

1. A filter drops anything that doesn't look like a short command: more than 60 characters, several lines, a question, a slash command, or a reply like "yes" or "continue".
2. Regex rules catch exact phrasings ("open X", "volume up", "next song", "search on google X").
3. If no rule matched, a small local classifier tries to catch paraphrases like "it's way too loud". It uses [multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small) and compares the prompt to example phrases, including a "none" class full of normal coding requests. It only fires above a similarity threshold and with a clear margin over "none".
4. The action runs from a fixed allowlist, and the hook returns `{"decision": "block"}` so Claude never sees the prompt.

The design rule is that a false positive is much worse than a missed command. If the hook is unsure, it prints nothing and Claude handles the prompt.

The classifier lives in a background process on `127.0.0.1:47321`, so the model (about 1.4 s to load) stays in memory. The first prompt that needs it starts the process and passes to Claude. Later prompts get an answer in a few milliseconds. The process uses about 440 MB of RAM and exits after an hour without requests.

## What it can do

- Open an installed app, found by name in the Start menu (`open notepad`, `launch discord`)
- Open a known site or any domain, optionally in Firefox, Chrome or Edge (`open youtube in firefox`, `go to github.com`)
- Run a Google search (`search on google pasta recipe`, `google weather montreal`)
- Control volume and media with the media keys (volume up/down, mute, play/pause, next/previous track)

It never types into apps, clicks, deletes anything or sends keyboard shortcuts to windows.

Rules and examples accept English and French. The model is multilingual, so you can add examples in other languages through `config.json`.

## Install

You need Windows, Python 3.8 or later and Claude Code.

```
git clone https://github.com/Mrodrigue14/claude-reflex
cd claude-reflex
pip install -r requirements.txt
python install.py
```

`install.py` downloads the quantized ONNX model and tokenizer (about 135 MB) from Hugging Face into `model/`, then prints a hook entry. Add it to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {"type": "command", "command": "C:/path/to/python.exe", "args": ["C:/path/to/claude-reflex/reflex.py"], "timeout": 5}
        ]
      }
    ]
  }
}
```

Without the model, the regex rules still work. Only paraphrase detection is off.

## Configure

Copy `config.example.json` to `config.json` to add your own sites, app aliases and classifier examples. Aliases map a word to the Start-menu names to try, which helps when Windows uses localized names (`"calculator": ["calculator", "calculatrice"]`).

To turn the hook off without editing settings, create an empty file named `off` next to `reflex.py`. Delete it to turn the hook back on.

Every action is appended to `log.jsonl`, which is useful for spotting false positives.

## Tests

```
python test_reflex.py
```

The tests run in dry mode (`REFLEX_DRY=1`), so nothing is opened. The classifier tests are skipped if the model is not downloaded.

## Credits

The idea of a reflex layer in front of the LLM comes from [Nūs Companion](https://github.com/potlakai/nus-companion) (Apache-2.0). The model is multilingual-e5-small by intfloat (MIT), in the ONNX export by [Xenova](https://huggingface.co/Xenova/multilingual-e5-small).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
