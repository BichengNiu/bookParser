# MinerU CLI 操作手册

本项目采用纯 CLI 方式操作，不提供 GUI/WebUI。日常文档解析使用 `mineru` 主命令；其他命令用于模型准备、远程服务或多服务部署。

## 1. 命令概览

| 命令 | 用途 |
| --- | --- |
| `mineru` | 解析本地 PDF、图片、DOCX、PPTX、XLSX 文件或目录 |
| `mineru-models-download` | 下载并配置本地模型 |
| `mineru-api` | 启动可被 CLI 或其他客户端调用的 MinerU FastAPI 服务 |
| `mineru-router` | 编排多个 MinerU 服务或多个本地 GPU worker |
| `mineru-openai-server` | 启动 OpenAI 兼容的 VLM 服务，供 `*-http-client` 后端使用 |

普通使用只需要 `mineru`。服务类命令属于进阶部署能力，不需要 GUI，也不会启动 WebUI。

## 2. 安装与首次准备

项目要求 Python `3.10` 至 `3.13`。推荐在虚拟环境中安装：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip uv
uv pip install -U "mineru[all]"
```

如果正在源码目录中开发，使用可编辑安装：

```powershell
uv pip install -e ".[all]"
```

安装后先确认命令可用：

```powershell
mineru --version
mineru --help
```

### 模型下载

首次解析时可能自动下载模型。也可以提前下载并生成用户目录下的 `mineru.json`：

```powershell
mineru-models-download -s modelscope -m all
```

其中 `-s` 可选 `auto`、`huggingface`、`modelscope`，`-m` 可选 `pipeline`、`vlm`、`all`。模型源也可以通过环境变量指定：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
```

Linux/macOS 使用：

```bash
export MINERU_MODEL_SOURCE=modelscope
```

模型源、本地模型目录和缓存位置的完整说明见[模型源配置](docs/zh/usage/model_source.md)。

## 3. 最基本的解析操作

解析单个文件：

```powershell
mineru -p "D:\data\book.pdf" -o "D:\data\output"
```

解析一个目录中的所有支持文件：

```powershell
mineru -p "D:\data\documents" -o "D:\data\output"
```

Linux/macOS 示例：

```bash
mineru -p ./documents -o ./output
```

说明：

- `-p/--path` 是必填的输入文件或目录，路径必须存在。
- `-o/--output` 是必填的输出根目录，不存在时会自动创建。
- Windows 路径建议使用双引号；路径中包含空格时必须加引号。
- 不传 `--api-url` 时，CLI 会在当前进程中自动启动临时本地 `mineru-api` 并完成任务编排。

## 4. 常用参数

| 参数 | 说明 |
| --- | --- |
| `-p, --path PATH` | 输入文件或目录，支持 PDF、图片、DOCX、PPTX、XLSX |
| `-o, --output PATH` | 输出根目录 |
| `--api-url TEXT` | 使用已有 MinerU FastAPI 服务，例如 `http://127.0.0.1:8000` |
| `--devices TEXT` | 本地 `pipeline` 后端的设备选择：`auto`、`cpu`、`gpu`、`npu`，也可组合为 `cpu,gpu`；默认 `auto`。GPU/NPU 设备由 OpenVINO 运行时识别 |
| `-m, --method [auto\|txt\|ocr]` | 解析方法；默认 `auto`，主要用于 `pipeline` 与 `hybrid-*` 后端 |
| `-b, --backend TEXT` | 解析后端；默认 `hybrid-engine` |
| `--effort [medium\|high]` | `hybrid-*` 后端的解析强度；默认 `medium` |
| `--vlm-engine [auto\|transformers\|lmdeploy\|vllm\|vllm-async]` | VLM/Hybrid 的本地推理引擎；默认 `auto`。显式选择后严格执行，缺少依赖直接失败，不会回退到其他后端 |
| `-l, --lang TEXT` | 文档语言，主要用于提升 `pipeline` OCR 准确率；默认 `ch` |
| `-u, --url TEXT` | `vlm-http-client` 或 `hybrid-http-client` 使用的 OpenAI 兼容服务地址 |
| `-s, --start INTEGER` | PDF 起始页，从 `0` 开始；默认 `0` |
| `-e, --end INTEGER` | PDF 结束页，从 `0` 开始且包含该页；默认解析到末页 |
| `-f, --formula BOOLEAN` | 是否解析公式；默认 `true` |
| `-t, --table BOOLEAN` | 是否解析表格；默认 `true` |
| `--image-analysis BOOLEAN` | 是否分析图片/图表；默认 `true` |
| `--client-side-output-generation BOOLEAN` | 在客户端根据服务端返回结果生成 Markdown 和 content list；默认 `false` |

布尔参数显式关闭时传入 `false`，例如：

```powershell
mineru -p input.pdf -o output --formula false --table false
```

查看当前版本的完整参数，以代码实际输出为准：

```powershell
mineru --help
```

## 5. 后端选择

### 5.1 `pipeline`：通用本地解析

适合常规文本、OCR、表格和公式解析。可以显式选择 CPU/GPU/NPU：

```powershell
mineru -p input.pdf -o output -b pipeline --devices cpu
mineru -p input.pdf -o output -b pipeline --devices gpu
mineru -p input.pdf -o output -b pipeline --devices auto
```

`auto` 会根据当前 OpenVINO 运行时可见设备选择 worker；显式指定的 GPU/NPU 必须已经安装对应依赖并且能被 OpenVINO 识别。`--devices` 只对本地 `pipeline` 解析生效，不替代 VLM 后端使用的 CUDA/NPU 设备环境变量。

### 5.2 `hybrid-engine`：本地混合解析

这是默认后端，适合需要较高解析质量的场景：

```powershell
mineru -p input.pdf -o output -b hybrid-engine --effort medium
mineru -p input.pdf -o output -b hybrid-engine --effort high --image-analysis true
```

`medium` 更快；`high` 通常更慢，但支持更完整的图片/图表分析。`hybrid` 的 `medium` 强度会自动关闭图片/图表分析。

如果当前平台没有自动选择所需的引擎，可以显式指定引擎。例如 Windows 上使用 Transformers：

```powershell
mineru -p input.pdf -o output -b hybrid-engine --effort medium --vlm-engine transformers
```

`--vlm-engine` 是严格选择，不会把失败的 Hybrid 任务改走 `pipeline`、CPU 或其他引擎；对应 VLM 模型必须已经可下载或已配置在本地。

`pipeline --devices gpu` 也严格使用 OpenVINO GPU；GPU 不支持某个模型时直接报错，不会自动把该模型切到 CPU。

### 5.3 `vlm-engine`：本地 VLM 解析

需要安装 VLM 相关依赖和对应模型：

```powershell
mineru -p input.pdf -o output -b vlm-engine
```

### 5.4 HTTP client 后端：连接 OpenAI 兼容服务

先启动 OpenAI 兼容服务，再在另一个终端执行 CLI：

```powershell
mineru-openai-server --port 30000
mineru -p input.pdf -o output -b hybrid-http-client -u http://127.0.0.1:30000
```

可选后端包括：

- `vlm-http-client`：主要依赖远程 VLM 服务，本地侧更轻量。
- `hybrid-http-client`：远程 VLM 加本地 pipeline 能力，客户端仍需要相应本地依赖。

注意：`--api-url` 是 MinerU FastAPI 服务地址；`-u/--url` 是 HTTP client 后端使用的 OpenAI 兼容服务地址，两者不是同一个参数。

## 6. 批量处理与指定页码

目录输入会批量处理其中的支持文件：

```powershell
mineru -p "D:\data\books" -o "D:\data\parsed" -b pipeline
```

只解析 PDF 的第 1 至第 10 页时，使用从 0 开始的页码 `0` 至 `9`：

```powershell
mineru -p book.pdf -o output -s 0 -e 9
```

只解析第 11 页：

```powershell
mineru -p book.pdf -o output -s 10 -e 10
```

## 7. 输出结果

每个输入文档会在输出根目录下生成独立子目录，目录名称通常取输入文件名。不同后端和输入类型的子目录略有差异，例如：

- `office/`：DOCX、PPTX、XLSX 等办公文档的解析结果。
- `auto/`、`txt/` 或 `ocr/` 等解析方法目录：pipeline 后端结果。
- `vlm/`：VLM 后端结果。
- `hybrid_<method>/`：hybrid 后端结果。

常见结果包括 Markdown、content list、middle JSON、模型输出和页面可视化文件。详细文件含义见[输出文件格式说明](docs/zh/reference/output_files.md)。

建议将输出目录与输入目录分开，并为不同批次使用不同输出目录，避免旧结果与新结果混在一起。

## 8. 使用已有服务

如果已经单独启动 MinerU FastAPI 服务，可以让 CLI 直接连接它：

```powershell
mineru-api --host 127.0.0.1 --port 8000
mineru -p input.pdf -o output --api-url http://127.0.0.1:8000
```

多服务或多 GPU 场景可以使用 router：

```powershell
mineru-router --host 127.0.0.1 --port 8002 --local-gpus auto
mineru -p input.pdf -o output --api-url http://127.0.0.1:8002
```

这些服务仍然是 CLI 进程，不会提供 GUI。服务命令的完整参数可分别查看：

```powershell
mineru-api --help
mineru-router --help
mineru-openai-server --help
```

## 9. 常见问题排查

### 命令不存在

确认虚拟环境已激活，并检查安装是否成功：

```powershell
python -m pip show mineru
Get-Command mineru
```

### 依赖不足

根据所选后端安装对应扩展；最省事的完整安装方式是：

```powershell
uv pip install -U "mineru[all]"
```

如果只使用本地 pipeline，可参考[扩展模块安装指南](docs/zh/quick_start/extension_modules.md)选择较小的依赖集合。

### 模型下载失败

切换模型源后重试：

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
mineru-models-download -s modelscope -m all
```

### Windows 没有使用 CUDA

确认安装了与当前 CUDA 环境匹配的 PyTorch 和 torchvision；VLM/hybrid 后端使用各自的推理设备配置。若使用本地 pipeline 的 OpenVINO GPU 路径，再使用 `--devices gpu`，并检查 OpenVINO 是否能识别该设备。

```powershell
python -c "import openvino as ov; print(ov.Core().available_devices)"
```

### 需要定位某一页或关闭某项解析

优先使用页码和布尔参数缩小问题范围：

```powershell
mineru -p book.pdf -o debug-output -s 0 -e 0 --image-analysis false
```

## 10. 常用命令速查

```powershell
# 查看帮助和版本
mineru --help
mineru --version

# 解析单个文件
mineru -p input.pdf -o output

# 批量解析目录
mineru -p documents -o output

# 使用 pipeline，并指定 CPU
mineru -p input.pdf -o output -b pipeline --devices cpu

# 使用 hybrid 高强度解析
mineru -p input.pdf -o output -b hybrid-engine --effort high

# 只解析 PDF 第 1 页
mineru -p input.pdf -o output -s 0 -e 0

# 连接已有 MinerU API
mineru -p input.pdf -o output --api-url http://127.0.0.1:8000
```
