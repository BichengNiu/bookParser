# 模型来源

MinerU 支持 `huggingface`、`modelscope` 和 `local` 三种模型来源。

`auto` 只执行一次 Hugging Face 可访问性检查。检查失败时直接以连接错误
终止，不会静默切换到 ModelScope。

可以通过环境变量指定固定来源：

```bash
export MINERU_MODEL_SOURCE=huggingface
mineru -p <input_path> -o <output_path>
```

如果未设置环境变量，可以在 `mineru.json` 中设置 `model-source` 为
`huggingface`、`modelscope` 或 `auto`。非法值会直接报配置错误。使用已下载
的本地模型解析时，在环境变量中设置 `local`。

```json
{
    "model-source": "huggingface"
}
```

`mineru-models-download` 成功下载后，会将本次选定的固定远程来源写入
`mineru.json`。
