from manga_translator.rendering.text_render import split_into_words


def test_cjk_breaks_at_punctuation():
    # The disclaimer used to wrap as 「...或應 / 用程式無關」, splitting 應用程式.
    words = split_into_words('這個故事是虛構的。與任何真實人物或應用程式無關。')
    assert words == ['這個故事是虛構的。', '與任何真實人物或應用程式無關。']


def test_cjk_breaks_after_closing_bracket():
    assert split_into_words('凜子(36) 身高:157cm') == ['凜子(36)', '身高:157cm']


def test_english_still_splits_on_whitespace():
    assert split_into_words('hello there  world') == ['hello', 'there', 'world']


def test_text_without_punctuation_stays_one_word():
    # No break points available: the per-character fallback downstream handles it.
    assert split_into_words('沒有標點的句子') == ['沒有標點的句子']
