# Arxiv-tracker · arXiv 每日论文追踪器

[![Stars](https://img.shields.io/github/stars/colorfulandcjy0806/Arxiv-tracker?style=flat-square)](https://github.com/colorfulandcjy0806/Arxiv-tracker/stargazers)
[![CI](https://img.shields.io/github/actions/workflow/status/colorfulandcjy0806/Arxiv-tracker/digest.yml?label=Arxiv%20Digest&style=flat-square)](../../actions)
[![Pages](https://img.shields.io/badge/GitHub%20Pages-online-2ea44f?style=flat-square)](https://colorfulandcjy0806.github.io/Arxiv-tracker/)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776ab?style=flat-square&logo=python)
![Last Commit](https://img.shields.io/github/last-commit/colorfulandcjy0806/Arxiv-tracker?style=flat-square)
![Open Issues](https://img.shields.io/github/issues/colorfulandcjy0806/Arxiv-tracker?style=flat-square)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg?style=flat-square)](./LICENSE)

> **如果你喜欢本项目，欢迎点亮一个 ⭐ Star 获取最新进展！**  

**简体中文 | [English](./README_EN.md)**

---

## 😮 项目亮点（Highlights）

- 🔎 **多学科多主题检索**：支持 `cs.CV / cs.LG / cs.AI / cs.CL` 等分类，自由组合关键词；`logic: AND/OR` 控制“分类集合”与“关键词集合”的布尔关系
- 🧠 **LLM 双语总结**：**英文一段 + 中文一段** 或两阶段摘要（TL;DR + Method Card + Discussion）
- 🔗 **自动提取链接**：Abs / PDF / 代码仓库 / 项目页
- 📨 **邮件推送**：QQ SMTP（465/SSL 或 587/STARTTLS），支持多收件人
- 🌐 **网页发布（GitHub Pages）**：自动生成美观 HTML，历史归档与折叠/展开
- ♻️ **去重 + 新鲜度**：仅推送“近 N 天 & 未发送过”的论文；支持**成功后再写入**的幂等防重
- 📦 **OpenAI-Compatible LLM**：**DeepSeek / SiliconFlow 等统一配置**（一个 `base_url` + 一个 `api_key` 即可）
- 🔁 **自动分页抓取**：避免每次只拿同一批前 N 条导致结果“用尽”

**网页效果如下图：**  
<img src="images/html.png" alt="Preview" width="720">

**邮件效果如下图：**  
<img src="images/email.png" alt="Preview" width="720">

---

## 📰 News
- **2025-12-12**：支持通过关键词排除不想要的文献。
- **2025-09-15**：新增代码链接补全，先从 comments/summary/arXiv 页面 抓取 GitHub/Code 链接；若仍缺失，可选扫描 PDF 首页尝试识别链接，缓解 “github code 显示不全” 问题。
- **2025-08-25**
  - 新增 **Freshness + 去重持久化**（且仅在**成功输出**后写入 `seen.json`）。
  - 新增 **OpenAI-Compatible LLM**：除 DeepSeek 外，已验证可直连 **SiliconFlow** 免费/付费模型（示例：`Qwen/Qwen3-8B`）。
  - 修复“**可能重复发邮件**”的问题；补充 Actions **并发防重**与“**手动触发选择是否发信**”。
  - 新增 **自动分页抓取**，避免总是命中同一批条目。
- **2025-08-22**：完成初版（检索 → 摘要/翻译 → 邮件/网页）。
---

## 🧭 仓库结构

```
arxiv_tracker/        # 核心逻辑（客户端、解析、摘要、站点、邮件等）
docs/                 # GitHub Pages 站点输出（自动生成）
outputs/              # 每次运行保存的 JSON/MD（自动生成）
.state/               # 去重状态（seen.json，建议随仓库提交）
.github/workflows/    # digest.yml 定时任务（每日 03:00 北京时间）
config.yaml           # 检索/摘要/邮件/站点/去重 配置
requirements.txt      # 运行依赖
```

---

## 🚀 快速开始（Fork & 部署）

### 1) Fork 本仓库

点击右上角 **Fork**，得到你自己的副本。

### 2) 配置 Secrets & Variables

> Settings → **Secrets and variables** → **Actions**

**Secrets（机密）**

- `OPENAI_COMPAT_API_KEY`：任意 OpenAI 兼容平台的 API Key（如 **DeepSeek**、**SiliconFlow**）  
- `SMTP_PASS`：QQ 邮箱 **SMTP 授权码**（非登录密码）

**Variables（非机密，可用 Secrets 替代）**

- `EMAIL_TO`：收件人（多个用 `,` 或 `;` 分隔，比如 `a@qq.com,b@xx.com`）
- `EMAIL_SENDER`：发件人邮箱（通常与 SMTP 用户一致，比如 `xxx@qq.com`）
- `SMTP_USER`：SMTP 用户名（通常 = 发件人邮箱，比如 `xxx@qq.com`）

### 3) 启用 GitHub Pages

Settings → **Pages**：Source 选 **Deploy from a branch**；Branch 选 `main`，Folder 选 `/docs`。

### 4) 配置并运行工作流（支持手动触发是否发信，仓库已经写好，这步可以省略，直接运行就行）

`.github/workflows/digest.yml` 示例（节选）：

```yaml
name: arxiv-digest

on:
  workflow_dispatch:
    inputs:
      send_email:
        description: "Send email for manual run?"
        required: false
        default: "false"
        type: choice
        options: ["false", "true"]
  schedule:
    - cron: "0 19 * * *"  # 每天 19:00 UTC = 北京时间次日 03:00

concurrency:
  group: arxiv-digest
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: "3.10" }

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Compute Pages URL
        id: site
        run: |
          REPO="${GITHUB_REPOSITORY}"
          OWNER="${REPO%%/*}"
          NAME="${REPO#*/}"
          echo "url=https://${OWNER}.github.io/${NAME}/" >> $GITHUB_OUTPUT

      - name: Run tracker (schedule-only email unless forced)
        env:
          OPENAI_COMPAT_API_KEY: ${{ secrets.OPENAI_COMPAT_API_KEY }}
          EMAIL_TO:     ${{ secrets.EMAIL_TO   || vars.EMAIL_TO }}
          EMAIL_SENDER: ${{ secrets.EMAIL_SENDER || vars.EMAIL_SENDER }}
          SMTP_USER:    ${{ secrets.SMTP_USER  || vars.SMTP_USER }}
          SMTP_PASS:    ${{ secrets.SMTP_PASS }}
        run: |
          set -e
          EXTRA="--no-email"
          if { [ "${{ github.event_name }}" = "schedule" ] && [ "${{ github.run_attempt }}" = "1" ]; } || \
             { [ "${{ github.event_name }}" = "workflow_dispatch" ] && [ "${{ inputs.send_email }}" = "true" ]; }; then
            EXTRA=""
          fi
          python -m arxiv_tracker.cli run \
            --config config.yaml \
            --site-dir docs \
            --site-url "${{ steps.site.outputs.url }}" \
            $EXTRA \
            --verbose

      - name: Commit outputs
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore: update digest & site"
          file_pattern: |
            docs/**
            outputs/**
            .state/**
```

**配置流程如下：**  
<img src="images/guide.png" alt="Preview" width="720">


> **要点**：`file_pattern` 里包含 `.state/**`，这样去重状态会随运行持久化到仓库，防止重复推送。

---

## ⚙️ 配置说明（`config.yaml`）

> 下面示例演示最常用的字段。完整示例请参考仓库中的 `config.yaml`。

```yaml
# === 检索 ===
categories: ["cs.CV", "cs.LG", "cs.AI"]
keywords:
  - "open vocabulary segmentation"
  - "vision-language grounding"
# [新增] 排除包含以下词汇的论文
exclude_keywords:
  - "Large Language Model"
  - "Generative AI"
logic: "AND"                 # 左：分类集合 (OR)；右：关键词集合 (OR)；二者再 AND/OR
max_results: 100             # 每页抓取上限（内部支持自动分页累计）
sort_by: "lastUpdatedDate"   # 或 submittedDate
sort_order: "descending"

# === 输出语言 ===
lang: "both"                 # zh / en / both

# === 摘要生成 ===
summary:
  mode: "llm"                # none / heuristic / llm
  scope: "both"              # tldr / full / both

# === LLM（OpenAI-Compatible，DeepSeek / SiliconFlow 均可） ===
llm:
  base_url: "https://api.deepseek.com"     # 或 "https://api.siliconflow.cn"
  model: "deepseek-chat"                   # 例：SiliconFlow 可用 "Qwen/Qwen3-8B"
  api_key_env: "OPENAI_COMPAT_API_KEY"     # 统一密钥环境变量
  system_prompt_en: |
    You are a senior paper-reading assistant...
  system_prompt_zh: |
    你是资深论文阅读助手...

# === 可选：题目/摘要中文翻译 ===
translate:
  enabled: true
  lang: "zh"
  fields: ["title", "summary"]

# === 邮件发送（QQ 邮箱示例） ===
email:
  enabled: true
  subject: "[arXiv] Daily Digest"
  smtp_server: "smtp.qq.com"
  smtp_port: 465
  tls: "ssl"                 # auto / ssl / starttls
  debug: false
  detail: "full"             # simple / full
  max_items: 10
  attach_md: true
  attach_pdf: false

# === 站点（GitHub Pages） ===
site:
  enabled: true
  dir: "docs"
  title: "arXiv 论文速递"
  keep_runs: 1024
  theme: "light"
  accent: "#2563eb"

# === 新鲜度 & 去重（成功后落盘） ===
freshness:
  since_days: 3               # 近 N 天（若偶尔为空，可暂时改 2~3）
  unique_only: true           # 开启跨天去重
  state_path: ".state/seen.json"
  fallback_when_empty: false  # 当当天无新增时是否回退展示最近 top 若干
```

> **搜索逻辑**：`categories` 内部按 OR 合并；`keywords` 内部按 OR 合并；二者之间由 `logic` 决定 AND/OR。比如 `logic: AND` 表示“**属于这些学科** 且 **匹配这些关键词**”。

---

## 🛠️ 本地运行（macOS/Linux）

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

export OPENAI_COMPAT_API_KEY="你的密钥"
# base_url/模型在 config.yaml 里配置
export EMAIL_TO="your@qq.com"
export EMAIL_SENDER="your@qq.com"
export SMTP_USER="your@qq.com"
export SMTP_PASS="你的QQ SMTP授权码"

python -m arxiv_tracker.cli run --config config.yaml --site-dir docs --verbose
```

### Windows（PowerShell）

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

$Env:OPENAI_COMPAT_API_KEY = "你的密钥"
$Env:EMAIL_TO     = "your@qq.com"
$Env:EMAIL_SENDER = "your@qq.com"
$Env:SMTP_USER    = "your@qq.com"
$Env:SMTP_PASS    = "你的QQ SMTP授权码"

python -m arxiv_tracker.cli run --config config.yaml --site-dir docs --verbose
```

---

## ❓ 常见问题（FAQ）

- **检索结果总是相同/逐渐变少？**  
  已启用**自动分页** + **新鲜度过滤** + **成功后落盘去重**。若当天为空，可将 `since_days` 临时改为 2~3 并观察；或检查关键词是否过窄。
- **401 Unauthorized（SiliconFlow/DeepSeek）**  
  请确保 `OPENAI_COMPAT_API_KEY` 填写的是真实可用的 API Key；SiliconFlow 的 Bearer 直接放 Key 即可。
- **ReadTimeout（arXiv API）**  
  可能是网络波动，可重试；或稍后再试。
- **邮件没收到？**  
  检查 Actions 日志“Show email env (masked)”是否注入完整；QQ 开启 SMTP 并使用**授权码**；必要时切换 465/SSL 与 587/STARTTLS。

---

## 🗺️ 待办清单
- [x] 解决每天检索到的文献都一样的问题
- [x] 每次会发送2封邮件的bug
- [x] 代码链接补全（缺失时抓取 PDF 首页作为兜底）
- [x] 支持更多LLM，下一步考虑硅基流动的API
- [x] 支持排除特定关键词（如过滤 LLM 泛滥的论文）
- [ ] 更多站点主题（暗色、跟随系统） 
- [ ] 自定义卡片字段开关与顺序 

## ✨ Star History

[![Star History](https://api.star-history.com/svg?repos=colorfulandcjy0806/Arxiv-tracker&type=Date)](https://star-history.com/#colorfulandcjy0806/Arxiv-tracker&Date)

---

## 🤝 Community contributors

<a href="https://github.com/colorfulandcjy0806/Arxiv-tracker/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=colorfulandcjy0806/Arxiv-tracker" alt="Contributors" width="720"/>
</a>

## 🔒 License

本项目基于 **MIT 协议** 开源，详见 [LICENSE](./LICENSE)。
