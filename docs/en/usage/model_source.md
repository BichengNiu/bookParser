# Model source

MinerU supports `huggingface`, `modelscope`, and `local` model sources.

`auto` performs one explicit Hugging Face availability check. If that check
fails, parsing stops with the connection error; MinerU does not silently switch
to ModelScope.

Set a fixed source with the environment variable:

```bash
export MINERU_MODEL_SOURCE=huggingface
mineru -p <input_path> -o <output_path>
```

If the environment variable is unset, `mineru.json` may set `model-source` to
`huggingface`, `modelscope`, or `auto`. Invalid values are configuration
errors. Use `local` in the environment when parsing with downloaded local
models.

```json
{
    "model-source": "huggingface"
}
```

The `mineru-models-download` command writes the selected fixed remote source
to `mineru.json` after a successful download.
