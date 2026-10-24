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
