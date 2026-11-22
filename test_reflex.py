import os
import unittest

os.environ["REFLEX_DRY"] = "1"
import reflex  # noqa: E402


def intent(text, classify=False):
    d = reflex.decide(text, classify=classify)
    return d and (d["intent"], d.get("arg"), d.get("browser"))


class Rules(unittest.TestCase):
    def test_fires(self):
        cases = {
            "open youtube": ("open_site", "https://www.youtube.com", None),
            "open youtube in firefox": ("open_site", "https://www.youtube.com", "firefox"),
            "go to github.com": ("open_site", "https://github.com", None),
            "search on google pasta recipe": ("web_search", "pasta recipe", None),
            "google weather montreal": ("web_search", "weather montreal", None),
            "volume up": ("volume_up", None, None),
            "turn it down": ("volume_down", None, None),
            "mute": ("mute", None, None),
            "next song": ("next_track", None, None),
            "pause": ("play_pause", None, None),
            "ouvre youtube": ("open_site", "https://www.youtube.com", None),
            "monte le volume": ("volume_up", None, None),
            "chanson suivante": ("next_track", None, None),
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(intent(text), want)

    def test_opens_builtin_apps(self):
        # Start-menu names depend on the Windows language, so only the intent is checked.
        for text in ["open notepad", "launch the calculator", "open settings", "ouvre notepad"]:
            with self.subTest(text=text):
                self.assertEqual((intent(text) or ("none",))[0], "open_app")

    def test_never_fires(self):
        for text in [
            "find the bug in auth.py",
            "run the tests",
            "open the README file",
            "open a PR",
            "yes",
            "continue",
            "do it",
            "thanks",
            "open notepad?",
            "/compact",
            "open notepad\nand type hello",
            "open some app that does not exist zzz",
            "lance les tests",
            "x" * 61,
            "",
        ]:
            with self.subTest(text=text):
                self.assertIsNone(intent(text, classify=True))

    def test_bad_stdin_passes(self):
        self.assertEqual(reflex.handle_raw("not json"), "")
        self.assertEqual(reflex.handle_raw(""), "")

    def test_off_switch(self):
        open(reflex.OFF, "w").close()
        try:
            self.assertEqual(reflex.handle_raw('{"prompt": "volume up"}'), "")
        finally:
            os.remove(reflex.OFF)

    def test_block_json(self):
        out = reflex.handle_raw('{"prompt": "volume up"}')
        self.assertIn('"decision": "block"', out)


@unittest.skipUnless(os.path.exists(reflex.MODEL), "model not downloaded (run install.py)")
class Classifier(unittest.TestCase):
    def test_paraphrases(self):
        # Phrasings that are not in EXAMPLES: this checks generalization, not recall.
        cases = {
            "the sound is way too loud": "volume_down",
            "I can barely hear it": "volume_up",
            "le son est beaucoup trop fort": "volume_down",
            "c'est vraiment trop bas": "volume_up",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(intent(text, classify=True), (want, None, None))

    def test_claude_requests_pass(self):
        for text in ["refactor this module", "add some logging", "check the build", "why is the test failing",
                     "take a break from the code", "make the text smaller", "restart the server",
                     "refactor ce module", "pourquoi le test échoue"]:
            with self.subTest(text=text):
                self.assertIsNone(intent(text, classify=True))


if __name__ == "__main__":
    unittest.main()
