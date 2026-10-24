import re

from ..config import TranslatorConfig
from .config_gpt import ConfigGPT  # Import the `gpt_config` parsing parent class

try:
    import openai
except ImportError:
    openai = None
import asyncio
import time
from collections import deque
from difflib import SequenceMatcher
from typing import List
from .common import CommonTranslator, VALID_LANGUAGES
from .keys import CUSTOM_OPENAI_API_KEY, CUSTOM_OPENAI_API_BASE, CUSTOM_OPENAI_MODEL, CUSTOM_OPENAI_MODEL_CONF


class CustomOpenAiTranslator(ConfigGPT, CommonTranslator):
    _INVALID_REPEAT_COUNT = 2  # Retries when an "invalid" translation comes back
    _MAX_REQUESTS_PER_MINUTE = 40  # Requests per minute
    _TIMEOUT = 40  # Seconds to wait for a response before retrying
    _RETRY_ATTEMPTS = 3  # Retries for a failed request
    _TIMEOUT_RETRY_ATTEMPTS = 3  # Retries for a timed-out request
    _RATELIMIT_RETRY_ATTEMPTS = 3  # Retries for a rate-limited request

    # Token budget; also caps how much text goes into one prompt
    _MAX_TOKENS = 4096

    title_text = None  # set per page by translators.dispatch

    _CHUNK_SIZE = 8  # regions per request: a 4B model keeps alignment better with short lists
    _CONTEXT_PAIRS = 10  # earlier source => translation pairs shown with each request

    def __init__(self, model=None, api_base=None, api_key=None, check_openai_key=False):
        # If the user has specified a nested key to use for the model, append the key
        #   Otherwise: Use the `ollama` defaults.
        _CONFIG_KEY='ollama'
        if CUSTOM_OPENAI_MODEL_CONF:
            _CONFIG_KEY+=f".{CUSTOM_OPENAI_MODEL_CONF}"

        ConfigGPT.__init__(self, config_key=_CONFIG_KEY)
        self.model = model
        CommonTranslator.__init__(self)
        self.client = openai.AsyncOpenAI(api_key=api_key or CUSTOM_OPENAI_API_KEY or "ollama") # required, but unused for ollama
        self.client.base_url = api_base or CUSTOM_OPENAI_API_BASE
        self.token_count = 0
        self.token_count_last = 0
        self.history = deque(maxlen=self._CONTEXT_PAIRS)  # finished pairs from earlier pages of this run
        self.title_pair = None  # (cover title as OCR read it, its translation)

    def parse_args(self, args: TranslatorConfig):
        self.config = args.chatgpt_config


    def extract_capture_groups(self, text, regex=r"(.*)"):
        """
        Extracts all capture groups from matches and concatenates them into a single string.
        
        :param text: The multi-line text to search.
        :param regex: The regex pattern with capture groups.
        :return: A concatenated string of all matched groups.
        """
        pattern = re.compile(regex, re.DOTALL)  # DOTALL to match across multiple lines
        matches = pattern.findall(text)  # Find all matches
        
        # Ensure matches are concatonated (handles multiple groups per match)
        extracted_text = "\n".join(
            "\n".join(m) if isinstance(m, tuple) else m for m in matches
        )
        
        return extracted_text.strip() if extracted_text else None

    def _title_note(self, to_lang: str) -> str:
        """Page 1 only: the biggest text is the title. OCR often garbles it, so give its real meaning."""
        if not self.title_text:
            return ''
        note = f'This is the cover page. The line "{self.title_text}" is the title of the manga, the biggest text on the page'
        if self.book_title:
            return note + (f', but the text recognition garbled it. The real title is "{self.book_title}": '
                           f'output the {to_lang} translation of that title for this line.')
        return note + f': translate it as a short title, not as dialogue.'

    def _context_note(self, done: List[tuple]) -> str:
        """Earlier lines (previous pages, then earlier chunks of this page) so the model keeps names and tone."""
        pairs = (list(self.history) + done)[-self._CONTEXT_PAIRS:]
        if not pairs:
            return ''
        lines = '\n'.join(f'{src} => {tr}' for src, tr in pairs)
        return f'Earlier lines, for context only. Do not translate or repeat them:\n{lines}\n\nTranslate these lines:'

    def _assemble_prompts(self, from_lang: str, to_lang: str, queries: List[str], done: List[tuple]):
        # A 4B model follows notes next to the lines far better than at the end of the system prompt.
        notes = [n for n in (self.user_notes, self._title_note(to_lang)) if n]
        header = '\n'.join(notes) + '\n' if notes else ''

        def start():  # read `done` at yield time: _translate fills it as chunks finish
            return header + self._context_note(done)

        prompt = start()
        offset = 0
        for i, query in enumerate(queries):
            prompt += f'\n<|{i + 1 - offset}|>{query}'
            if (i + 1 - offset) % self._CHUNK_SIZE == 0 and i + 1 < len(queries):
                yield prompt.lstrip(), i + 1 - offset
                prompt = start()
                offset = i + 1

        yield prompt.lstrip(), len(queries) - offset

    def _format_prompt_log(self, to_lang: str, prompt: str) -> str:
        if to_lang in self.chat_sample:
            return '\n'.join([
                'System:',
                self.chat_system_template.format(to_lang=to_lang),
                'User:',
                self.chat_sample[to_lang][0],
                'Assistant:',
                self.chat_sample[to_lang][1],
                'User:',
                prompt,
            ])
        else:
            return '\n'.join([
                'System:',
                self.chat_system_template.format(to_lang=to_lang),
                'User:',
                prompt,
            ])

    async def _translate(self, from_lang: str, to_lang: str, queries: List[str]) -> List[str]:
        translations = []
        done = []  # (source, translation) pairs of earlier chunks of this page
        self.logger.debug(f'Temperature: {self.temperature}, TopP: {self.top_p}')

        for prompt, query_size in self._assemble_prompts(from_lang, to_lang, queries, done):
            self.logger.debug('-- GPT Prompt --\n' + self._format_prompt_log(to_lang, prompt))

            ratelimit_attempt = 0
            server_error_attempt = 0
            timeout_attempt = 0
            while True:
                request_task = asyncio.create_task(self._request_translation(to_lang, prompt))
                started = time.time()
                while not request_task.done():
                    await asyncio.sleep(0.1)
                    if time.time() - started > self._TIMEOUT + (timeout_attempt * self._TIMEOUT / 2):
                        # Server takes too long to respond
                        if timeout_attempt >= self._TIMEOUT_RETRY_ATTEMPTS:
                            raise Exception('ollama servers did not respond quickly enough.')
                        timeout_attempt += 1
                        self.logger.warning(f'Restarting request due to timeout. Attempt: {timeout_attempt}')
                        request_task.cancel()
                        request_task = asyncio.create_task(self._request_translation(to_lang, prompt))
                        started = time.time()
                try:
                    response = await request_task
                    break
                except openai.RateLimitError:  # Server returned ratelimit response
                    ratelimit_attempt += 1
                    if ratelimit_attempt >= self._RATELIMIT_RETRY_ATTEMPTS:
                        raise
                    self.logger.warning(
                        f'Restarting request due to ratelimiting by Ollama servers. Attempt: {ratelimit_attempt}')
                    await asyncio.sleep(2)
                except openai.APIError:  # Server returned 500 error (probably server load)
                    server_error_attempt += 1
                    if server_error_attempt >= self._RETRY_ATTEMPTS:
                        self.logger.error(
                            'Ollama encountered a server error, possibly due to high server load. Use a different translator or try again later.')
                        raise
                    self.logger.warning(f'Restarting request due to a server error. Attempt: {server_error_attempt}')
                    await asyncio.sleep(1)

            # self.logger.debug('-- GPT Response --\n' + response)
            

            # Use regex to extract response 
            # ponytail: an empty response means no translations, not a crashed page.
            response=self.extract_capture_groups(response, rf"{self.rgx_capture}") or ''


            # Sometimes it will return line like "<|9>demo", and we need to fix it.
            def add_pipe(match):
                number = match.group(1)
                return f"<|{number}|>"
            response = re.sub(r"<\|?(\d+)\|?>", add_pipe, response)
            

            # self.logger.debug('-- GPT Response (filtered) --\n' + response)

            # @NOTE: This should *should* be superflous now, due to `extract_capture_groups`:
            # 
            # Remove any text preceeding the first translation.
            new_translations = re.split(r'<\|\d+\|>', 'pre_1\n' + response)[1:]
            # new_translations = re.split(r'<\|\d+\|>', response)

            # When there is only one query LLMs likes to exclude the <|1|>
            if not new_translations:
                new_translations = [response]

            # Immediately clean leading and trailing whitespace from each translation text
            new_translations = [t.strip() for t in new_translations]

            if len(new_translations) <= 1 and query_size > 1:
                # Try splitting by newlines instead
                new_translations = re.split(r'\n', response)

            if len(new_translations) > query_size:
                new_translations = new_translations[: query_size]
            elif len(new_translations) < query_size:
                new_translations = new_translations + [''] * (query_size - len(new_translations))

            chunk = [t.strip() for t in new_translations]
            done.extend(zip(queries[len(translations):], chunk))
            translations.extend(chunk)

        self.logger.debug(translations)
        if self.token_count_last:
            self.logger.info(f'Used {self.token_count_last} tokens (Total: {self.token_count})')

        return translations

    async def _request_translation(self, to_lang: str, prompt: str) -> str:
        messages = [{'role': 'system', 'content': self.chat_system_template.format(to_lang=to_lang)}]

        # Add chat samples if available
        lang_chat_samples = self.get_chat_sample(to_lang)
        if lang_chat_samples:
            messages.append({'role': 'user', 'content': lang_chat_samples[0]})
            messages.append({'role': 'assistant', 'content': lang_chat_samples[1]})

        messages.append({'role': 'user', 'content': prompt})

        response = await self.client.chat.completions.create(
            model=self.model or CUSTOM_OPENAI_MODEL,
            messages=messages,
            # thinking (on when there are notes) counts toward this, so give it room
            max_tokens=self._MAX_TOKENS if self.user_notes else self._MAX_TOKENS // 2,
            temperature=self.temperature,
            top_p=self.top_p,
            # gemma4 thinks by default and burns the whole token budget before emitting
            # anything, which returns an empty translation on text-dense pages.
            # Without thinking it also ignores user notes, so think briefly when there are some.
            extra_body={'reasoning_effort': 'low' if self.user_notes else 'none'},
        )

        self.logger.debug('\n-- GPT Response (raw) --')
        self.logger.debug(response.choices[0].message.content)
        self.logger.debug('------------------------\n')


        self.token_count += response.usage.total_tokens
        self.token_count_last = response.usage.total_tokens

        return response.choices[0].message.content

    async def translate(self, from_lang: str, to_lang: str, queries: List[str], use_mtpe: bool = False) -> List[str]:
        # The cover title shows up again on later pages, where OCR garbles it a little differently:
        # reuse the cover's translation so the title stays the same everywhere.
        fixed = {}
        if self.title_pair and not self.title_text:
            fixed = {i: self.title_pair[1] for i, q in enumerate(queries)
                     if SequenceMatcher(None, q, self.title_pair[0]).ratio() >= 0.7}
        rest = [q for i, q in enumerate(queries) if i not in fixed]
        got = iter(await super().translate(from_lang, to_lang, rest, use_mtpe) if rest else [])
        result = [fixed[i] if i in fixed else next(got) for i in range(len(queries))]

        if self.title_text:
            for q, t in zip(queries, result):
                if q == self.title_text and t.strip() and t != q:
                    self.title_pair = (q, t)
        # translate() retries internally, so only its final answer goes into the history.
        # The cover (title_text set) and lines left untranslated are mostly OCR garbage: keep them out.
        else:
            self.history.extend((q, t) for q, t in zip(queries, result) if t.strip() and t != q)
        return result
