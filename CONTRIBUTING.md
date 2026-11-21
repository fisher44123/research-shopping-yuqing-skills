# Contributing Guidelines（贡献指南）

感谢你关注并参与改进 **research-shopping-yuqing-skills**！为了保持仓库高信噪比、低依赖与清晰边界，请先阅读以下约定：

## 1. 非常欢迎的贡献方向（Welcome）
- **确定性核验规则优化与误报修复**：改进 `tools/review_check.py` / `tools/review_rules.json` / `tools/citation_audit.py` 的识别精准度（请附带最小复现报告片段）。
- **消费品 SKU 边界用例扩展**：向 `tools/sku_check.py` 与 `tools/sku_rules.json` 补充易错品类解析（如复杂规格折算、新版/老代命名陷阱、色系陷阱词），必须附带对应的 `unittest` 用例。
- **方法论与 Eval 考题补强**：补充高质量的跨领域 `evals/*.eval.json` 触发与输出断言用例，帮助检验 Agent 是否偷懒或编造。
- **合法官方 API / MCP 适配器示例**：展示如何将公开官方 API（如 GitHub REST API、RSS/Atom 等合法数据源）输出整理为符合 [`adapter-schema.json`](skills/quick-research/references/adapter-schema.json) 的格式。

## 2. 明确拒收的内容（Out of Scope — Will Be Closed）
- **任何私有站点爬虫、反爬绕过、验证码破解、Cookie 提取或无头浏览器劫持脚本**；
- 引入第三方重量级运行时依赖（所有 `tools/*.py` 必须保持 Python 3.10+ 纯标准库可直接运行）；
- 包含任何个人绝对路径、真实账号凭据、私钥或用户地域属地采集字段的代码。

## 3. AI-Assisted Pull Request Policy（AI 辅助提交规范）
可以使用 AI Coding Agent 协助编写代码或测试用例，但提交 PR 前必须满足：
1. 你自己**读懂并核查过**每一行改动，且明确说明改动意图；
2. 附带本地离线复现测试，绝不提交仅凭 AI 生成却未实测的代码；
3. 提交前在仓库根目录依次执行以下三条命令且全部通过：

```bash
python -m unittest discover -s tests -v
python demo/run_demo.py
python scripts/privacy_audit.py
```
