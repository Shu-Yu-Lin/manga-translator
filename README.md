# Manga Studio

A manga translation app that runs **fully on your Mac**. Nothing is sent to the cloud.

Create a *reader* (a book) from one PDF or several images, pick a target language, wait for processing, then read the translated pages with Previous / Next.

> Forked from [zyddnys/manga-image-translator](https://github.com/zyddnys/manga-image-translator) (GPL-3.0). The upstream pipeline (detection, OCR, inpainting, rendering) is still the core. This fork trims it down and adds a local reader app. See [Credits](#credits).

## How it works

| Piece | What it uses |
|---|---|
| Source language | Japanese only |
| Target language | Traditional Chinese (`CHT`) or English (`ENG`), chosen per reader |
| OCR | `manga-ocr-base` (`mocr`) |
| Translation | Local Gemma 4 E4B through Ollama (`gemma4:e4b`), via the OpenAI-compatible `custom_openai` translator |
| Text removal | `lama_large` inpainting |
| Reader | PySide6 desktop app |

Pipeline per page: upscale → detection → OCR → textline merge → translation → mask refinement → inpainting → rendering.

## Requirements

- macOS (Apple Silicon recommended; the pipeline runs on MPS). Packaging is Mac-only. The CLI may work elsewhere but is untested.
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com), with the model pulled:
  ```bash
  ollama pull gemma4:e4b
  ```

Python is pinned to 3.12 (`.python-version`). 3.13 is blocked by `pydensecrf`.

## Install and run

```bash
uv sync
uv run python MangaStudioMain.py
```

The app starts `ollama serve` if it isn't running, and stops it on quit. OCR, detection and inpainting models download to `./models` on first use.

### Double-click app (optional)

```bash
./packaging/build_app.sh
```

Builds `~/Applications/Manga Studio.app`, a launcher for this repo's `.venv`. If you move the repo, rerun the script. Log: `~/Library/Logs/MangaStudio.log`.

`./packaging/release.sh` merges the current branch into `main` (via the `~/manga-translator-stable` worktree), rebuilds the app, and pushes. Commit first.

## Using the app

- **Library:** a grid of covers. **+ New manga** takes a title, an optional description, the target language, and one PDF or several JPG/PNG files. Only one book is processed at a time.
- **Reading:** open a finished book. **‹ Previous** / **Next ›**, the ←/→ keys, and Esc (back to the library) all work. A failed page shows the original with a "translation failed" note.
- **⋯ menu:** **Edit** (title, description, cover, a per-book pre-translation dictionary; save, or save and retranslate the whole book), **Retry** failed books, **Delete**.
- **Failures:** a page that fails 3 times is skipped and marked failed. The book shows an "N pages failed" badge. A book left half-processed by an app exit loads as failed, with Retry.

Reader data lives in `~/Library/Application Support/MangaStudio/`, one folder per book (`source/`, `translated/`, `config.json`, `job.log`).

## Command line

The app only talks to the pipeline through the CLI and a JSON config, so you can run it directly:

```bash
uv run python -m manga_translator local -v -i <image_or_folder> --use-gpu   # output: <path>-translated
uv run python -m manga_translator local -i <path> --config-file configs/cht.json
uv run python -m manga_translator config-help                               # dump the config schema
```

Useful flags: `--attempts N`, `--ignore-errors`, `--pre-dict FILE`, `--post-dict FILE`, `--model-dir DIR`.

### Configuration

[configs/cht.json](configs/cht.json) is the template the app copies for each book (`mocr`, `custom_openai`, `lama_large`). The translation prompt lives in [configs/gpt_config.yaml](configs/gpt_config.yaml). Replacement dictionaries are in [configs/dict/](configs/dict/).

The local LLM is set with environment variables (the app sets the model itself):

| Variable | Default |
|---|---|
| `CUSTOM_OPENAI_API_BASE` | `http://localhost:11434/v1` |
| `CUSTOM_OPENAI_MODEL` | `gemma4:e4b` (set by the app) |
| `CUSTOM_OPENAI_API_KEY` | any non-empty value for Ollama |
| `CUSTOM_OPENAI_MODEL_CONF` | optional model config |

Remaining options: translator `custom_openai` / `none` / `original`; OCR `mocr` / `48px`; detector `default` / `ctd` / `none`; inpainter `default` / `lama_large` / `lama_mpe` / `none` / `original`; renderer `default` / `manga2eng` / `none`. Everything is defined in [manga_translator/config.py](manga_translator/config.py).

## Project layout

```
manga_translator/        # pipeline: one stage per subpackage, MangaTranslator in manga_translator.py
MangaStudioMain.py       # app entry point
MangaStudio_Data/app/ui/library_window.py   # the whole GUI (library, dialogs, reader)
configs/                 # per-language configs, GPT prompt, dictionaries
packaging/               # Mac app build and release scripts
test/                    # pytest
```

## Development

```bash
uv run pytest test/
uv run pytest test/test_translation_manual.py --translator custom_openai --target-lang CHT   # needs Ollama
uv run pylint manga_translator
```

## Status

The app is under active development. `ENG` readers need `configs/eng.json`, which doesn't exist yet. See [PLAN.md](PLAN.md) for decisions and the progress checklist.

## Credits

- [zyddnys/manga-image-translator](https://github.com/zyddnys/manga-image-translator): the upstream project this is forked from.
- [manga-ocr](https://github.com/kha-white/manga-ocr): Japanese manga OCR.
- [Ollama](https://ollama.com) and Google's Gemma: local translation model runtime and weights.

## License

GPL-3.0, same as upstream. See [LICENSE](LICENSE).
