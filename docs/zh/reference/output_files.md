# MinerU 输出文件

## 默认输出

默认文本解析配置只会在解析目录下输出以下结果：

```text
{name}.md
{name}_content_list_v2.json
images/                  # 只有识别出图片时才创建
```

Markdown 是主要结果文件，JSON 保存结构化内容块。Markdown 中的图片引用
指向 `images/` 目录中的文件。

图片识别和导出默认开启。`images/` 采用延迟创建方式，因此没有可提取图片
的文档不会得到空的图片目录。

## 可选诊断输出

布局 PDF、span PDF、模型输出、middle JSON 和原始 PDF 都属于诊断或归档文件，
默认 CLI 配置不会生成。调试或审计解析过程时，再显式开启对应输出选项。

## 结构化输出

`{name}_content_list_v2.json` 是当前支持的结构化输出。旧的
`{name}_content_list.json` 不再生成，当前代码也不会读取它。

具体数据结构取决于所选后端；二次处理 JSON 前应先按后端校验结构。
