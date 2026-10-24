from manga_translator.translators.custom_openai import CustomOpenAiTranslator


def test_chunks_and_context():
    t = CustomOpenAiTranslator.__new__(CustomOpenAiTranslator)  # no client or config needed for prompt building
    t.history = __import__("collections").deque([("前の行", "上一行")], maxlen=10)
    t.title_text, t._config_get = None, lambda *a, **k: ""
    done = []
    prompts = t._assemble_prompts("JPN", "CHT", [f"q{i}" for i in range(10)], done)
    first, size = next(prompts)
    assert size == 8 and "前の行 => 上一行" in first and first.endswith("<|8|>q7")
    done.extend([("q0", "a0")])  # _translate fills this as chunks finish
    second, size = next(prompts)
    assert size == 2 and "q0 => a0" in second and second.endswith("<|2|>q9")


def test_cover_title_is_reused_on_later_pages(monkeypatch):
    import asyncio
    from collections import deque
    from manga_translator.translators.common import CommonTranslator

    async def fake(self, from_lang, to_lang, queries, use_mtpe=False):
        return [f"T:{q}" for q in queries]

    monkeypatch.setattr(CommonTranslator, "translate", fake)
    t = CustomOpenAiTranslator.__new__(CustomOpenAiTranslator)
    t.history, t.title_pair, t.title_text = deque(maxlen=10), None, "凛子ちドはお外でしたい"
    t.title_pair = None
    asyncio.run(t.translate("JPN", "CHT", ["凛子ちドはお外でしたい"]))  # cover: not translated by the fake, remember it
    t.title_pair = ("凛子ちドはお外でしたい", "凜子醬想在外面做")
    t.title_text = None  # a later page
    out = asyncio.run(t.translate("JPN", "CHT", ["こんにちは", "凛子ちんはお外でしたい"]))
    assert out == ["T:こんにちは", "凜子醬想在外面做"]
