from typing import Optional, List

import py3langid as langid

from .common import *
from .none import NoneTranslator
from .original import OriginalTranslator
from .custom_openai import CustomOpenAiTranslator
from ..config import Translator, TranslatorConfig, TranslatorChain
from ..utils import Context

TRANSLATORS = {
    Translator.none: NoneTranslator,
    Translator.original: OriginalTranslator,
    Translator.custom_openai: CustomOpenAiTranslator,
}
translator_cache = {}

def get_translator(key: Translator, *args, **kwargs) -> CommonTranslator:
    if key not in TRANSLATORS:
        raise ValueError(f'Could not find translator for: "{key}". Choose from the following: %s' % ','.join(TRANSLATORS))
    if not translator_cache.get(key):
        translator = TRANSLATORS[key]
        translator_cache[key] = translator(*args, **kwargs)
    return translator_cache[key]

async def prepare(chain: TranslatorChain):
    for key, tgt_lang in chain.chain:
        translator = get_translator(key)
        translator.supports_languages('auto', tgt_lang, fatal=True)
        if isinstance(translator, OfflineTranslator):
            await translator.download()

# TODO: Optionally take in strings instead of TranslatorChain for simplicity
async def dispatch(chain: TranslatorChain, queries: List[str], translator_config: Optional[TranslatorConfig] = None, use_mtpe: bool = False, args:Optional[Context] = None, device: str = 'cpu') -> List[str]:
    if not queries:
        return queries

    if chain.target_lang is not None:
        text_lang = ISO_639_1_TO_VALID_LANGUAGES.get(langid.classify('\n'.join(queries))[0])
        translator = None
        flag=0
        for key, lang in chain.chain:           
            #if text_lang == lang:
                #translator = get_translator(key)
            #if translator is None:
            translator = get_translator(chain.translators[flag])
            if isinstance(translator, OfflineTranslator):
                await translator.load('auto', chain.langs[flag], device)
                pass
            if translator_config:
                translator.parse_args(translator_config)
            queries = await translator.translate('auto', chain.langs[flag], queries, use_mtpe)
            await translator.unload(device)
            flag+=1
        return queries
    if args is not None:
        args['translations'] = {}
    for key, tgt_lang in chain.chain:
        translator = get_translator(key)
        if isinstance(translator, OfflineTranslator):
            await translator.load('auto', tgt_lang, device)
        if translator_config:
            translator.parse_args(translator_config)
        queries = await translator.translate('auto', tgt_lang, queries, use_mtpe)
        if args is not None:
            args['translations'][tgt_lang] = queries
    return queries


async def unload(key: Translator):
    translator_cache.pop(key, None)
