# FreightSentinel（中文说明）

**航运单据核对 —— 从一个共享收件箱，到一份差异报告。**
Averis x Monash Hackathon 2026 参赛作品（Shipping Document Verification 赛题）。

**在线原型：** https://fs-two-sand.vercel.app/

> English version: **[README.md](README.md)**

系统读取业务共享收件箱，先把邮件分成五类；对每一封「要求核对提单」的邮件，读取 Shipping Instruction（SI）
与 Draft Bill of Lading（BL），按语义对齐七个字段，**准确指出哪里不一致**，并把原文证据放在旁边。
凡是不能安全判断的情况（缺附件、附错文件、文件读不出、字段是空值），一律带着原因转人工，绝不猜。

```
官方收件箱 → 智能分类 → 分析（提取 + 比对） → 风险雷达 → 人工复核 或 安全完结
```

---

## 一、技术架构

```
浏览器 ──> Next.js 前端 (Vercel) ──/api/*──> FastAPI 后端 (Render) ──> 文件解析 (txt/pdf/docx/xlsx)
                                                    │              ──> AI 供应商 (DeepSeek 等)
                                                    │              ──> AI 结论 + 结构/证据校验
                                                    └──> 结果缓存 (JSON)
```

**浏览器永远不直接调用 AI，也永远拿不到 API key。** 前端在服务端把 `/api/*` 转发给后端，
key 只以环境变量的形式存在于后端服务器上。

| 层 | 技术 | 职责 |
|---|---|---|
| 前端 | React + Next.js 14 (TypeScript) | 今日工作台、智能收件箱、案件详情、复核队列、批量运行 |
| 后端 | Python 3.11 + FastAPI + Pydantic | 收件箱读取、分析流程、批量运行、人工决策、官方格式导出 |
| 解析 | pdfplumber / python-docx / openpyxl | 附件取文，PDF 带版面感知（粗体标签 / 正常值） |
| AI | 单一供应商，JSON 输出，直接 HTTPS | 邮件意图与分类、文件类型与七字段提取（带证据） |
| 比对 | AI 结构化返回 | 语义比对、单位换算、七个匹配标记与最终状态 |
| 校验 | Python / Pydantic | 返回结构、字段完整性、原文证据、状态与明细是否自洽 |

**业务判断全部由 AI 负责**：分类、认文件、提取七字段、理解同义词与单位、比对、给出最终状态和证据。
Python 只负责读文件和校验返回（结构、证据、自洽性），不自己算业务结论，也不覆盖 AI 的读数。
AI 返回不合格 → 转复核。没配 AI 或调用失败 → 显示为技术失败并可重试，**不会退化成规则跑出一个假的 OK**。

---

## 二、环境变量（重点）

所有配置都从环境变量读取。
- **本地**：复制 `backend/.env.example` 为 `backend/.env`，在里面填。该文件已被 `.gitignore` 忽略，**不会进仓库**。
- **云端**：**不要上传 .env 文件**，把值填到平台的 Environment Variables 面板里。

> ⚠️ **API key 只放后端服务器（Render 的环境变量面板）。**
> 不写进代码、不写进仓库、不写进前端、不打进日志。前端知道的东西，任何访客都能看到。

### 后端变量（填在 Render → 服务 → Environment）

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `AI_PROVIDER` | ✅ | `none` | 用哪家：`deepseek` / `openai` / `anthropic` / `gemini` / `none` |
| `AI_API_KEY` | ✅ | – | 供应商密钥。**只填在这里**，仓库里永远是空的 |
| `AI_MODEL` | – | 各厂默认 | 比赛配置 `deepseek-flash`；默认值见 `app/config.py` |
| `AI_MODE` | – | `full` | `full` = 所有判断交给 AI（正式配置）；`off` = 停用分析 |
| `AI_THINKING` | – | `false` | 主模型是否开启思考，比赛配置 `true` |
| `AI_REASONING_EFFORT` | – | `high` | 思考强度 `low` / `high` / `max`（`medium` 等同 `high`） |
| `AI_TIMEOUT` | – | `60` | 单次调用超时（秒），建议 `240` |
| `AI_FALLBACK_MODEL` | – | – | 主模型 429/503 时的同厂备用模型；`none` = 不启用 |
| `AI_MAX_RPM` | – | 各厂默认 | 每分钟请求上限；`0` = 不限速（付费额度） |
| `BATCH_CONCURRENCY` | – | `4` | 批量跑全收件箱时的并发数 |
| `AUTOMATION_POLICY` | – | `standard` | 给 AI 的复核尺度 `standard` / `strict`，不是写死的置信度门槛 |
| `CORS_ORIGINS` | – | `*` | 允许直连 API 的来源；前端走服务端代理，一般不用管 |
| `AI_SENIOR_PROVIDER` | – | `openai` | 资深复核阶段用哪家 |
| `AI_SENIOR_MODEL` | – | – | 资深复核模型；**留空 = 关闭该阶段** |
| `AI_SENIOR_API_KEY` | – | 复用 `AI_API_KEY` | 只有跟主模型不同厂时才需要单独填 |
| `AI_SENIOR_THINKING` | – | `false` | 资深阶段是否开思考 |
| `AI_SENIOR_REASONING_EFFORT` | – | `high` | 比赛配置 `max` |
| `AI_SENIOR_TIMEOUT` | – | `120` | 资深阶段超时（秒） |
| `AI_SENIOR_MAX_RPM` | – | 推导值 | `0` = 不限速 |
| `PYTHON_VERSION` | Render | `3.11.9` | `render.yaml` 里已经写好，不用手填 |

### 前端变量（填在 Vercel → 项目 → Settings → Environment Variables）

| 变量 | 必填 | 示例 | 说明 |
|---|---|---|---|
| `BACKEND_URL` | ✅ | `https://freightsentinel-api.onrender.com` | 后端地址，**结尾不要带斜杠** |

**前端只有这一个变量，没有任何 AI 相关配置。**

### 本次比赛的完整配置（DeepSeek V4.1 Flash）

```
AI_PROVIDER=deepseek
AI_API_KEY=<你的密钥，只填在 Render 面板 / 本地 .env>
AI_MODEL=deepseek-flash
AI_MODE=full
AI_THINKING=true
AI_REASONING_EFFORT=high
AI_TIMEOUT=240
AI_FALLBACK_MODEL=none
AI_SENIOR_PROVIDER=deepseek
AI_SENIOR_MODEL=deepseek-flash
AI_SENIOR_REASONING_EFFORT=max
AI_SENIOR_TIMEOUT=240
AI_SENIOR_MAX_RPM=0
BATCH_CONCURRENCY=4
AUTOMATION_POLICY=standard
```

---

## 三、本地运行

**后端**（Python 3.11）：

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 然后在 .env 里填 AI_API_KEY
uvicorn app.main:app --reload --port 8000
# 打开 http://localhost:8000/health  和 http://localhost:8000/docs
```

`app/config.py` 会自动读取 `backend/.env`；真实环境变量优先级更高，所以同一份代码在 Render 上不用改。

**前端**（Node 18+）：

```bash
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
# 打开 http://localhost:3000
```

**测试**（只用假模型，不花钱）：

```bash
cd backend && AI_PROVIDER=none AI_MODE=off .venv/bin/pytest -q tests
```

---

## 四、云端部署（给负责部署的队友）

### 第 1 步：后端部署到 Render

1. 打开 [render.com](https://render.com) → **New +** → **Blueprint**
2. 选择这个仓库（`jake2ace/FS`），Render 会自动读取根目录的 `render.yaml`
3. Render 只会问你要 **一个** 值：`AI_API_KEY`
   —— 粘贴密钥（**队长单独发给你，不要贴到任何聊天群或提交到仓库**）。
   其余全部变量（供应商、主模型与资深模型、思考强度、超时、限速、并发）都写死在 `render.yaml` 里，
   不用手填，也不会漏填 —— 保证云端跑的就是本地测过的那套配置。
4. 点 Deploy，等构建完成
5. 验证：浏览器打开 `https://<你的服务名>.onrender.com/health`
   —— 返回里能看到服务状态、数据包状态、AI 配置状态

> 免费套餐 15 分钟没流量会休眠，第一次唤醒要 30–60 秒。
> 评审当天建议用 UptimeRobot 之类的服务每 5 分钟 ping 一次 `/health` 保持唤醒。
> `render.yaml` 不安装 Tesseract/Poppler，所以云端没有 OCR 兜底能力。

### 第 2 步：前端部署到 Vercel

1. 打开 [vercel.com](https://vercel.com) → **Add New** → **Project** → 导入同一个仓库
2. **Root Directory 一定要设成 `frontend`**（不设会构建失败）
3. Environment Variables 加一条：
   `BACKEND_URL` = `https://<你的服务名>.onrender.com`（结尾不要带斜杠）
4. Deploy

`next.config.mjs` 里的 rewrite 会在**服务端**把 `/api/*` 转发到后端，
所以浏览器不需要 CORS，前端打包产物里也不会出现后端地址或密钥。

### 第 3 步：换 key / 撤销 key

密钥只存在两个地方：Render 面板 + 本地被忽略的 `backend/.env`。
要换只需在 Render 改值并重新部署，仓库和前端一个字都不用动。

### 部署常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| Vercel 构建失败 | Root Directory 没设成 `frontend` | 改设置后 Redeploy |
| 页面打开空白 / 请求 500 | `BACKEND_URL` 没填或带了结尾斜杠 | 改成 `https://xxx.onrender.com` |
| 第一次请求很慢 | 免费套餐休眠唤醒 | 正常，等 30–60 秒；评审前先手动唤醒 |
| `/health` 显示 AI 未配置 | `AI_PROVIDER` / `AI_API_KEY` 没填 | 在 Render 面板补上后重新部署 |
| 分析大面积失败 | 密钥额度用完或被限流 | 查供应商额度；必要时调 `AI_MAX_RPM` |

---

## 五、结果约定

| 情况 | status | review_reason | 界面表现 |
|---|---|---|---|
| 七个字段全部一致 | `OK` | – | 无差异 → 可安全完结 |
| 至少一个字段不一致 | `MISMATCH` | – | 高风险，列出 `defect_fields` 及 SI / BL 两边的值 |
| 要求比对但没附件 / 只有 SI | `NEEDS_REVIEW` | `missing_attachment` | 转人工 |
| 第二个附件是发票 / 装箱单 / 证书 | `NEEDS_REVIEW` | `wrong_doc_type` | 转人工 |
| 文件为空 / 损坏 / 纯图片 | `NEEDS_REVIEW` | `unreadable` | 转人工 |
| 必填字段是空值或占位符 | `NEEDS_REVIEW` | `missing_value` | 转人工 |
| 只是要求「发出」草稿提单，还没附件 | `NEEDS_REVIEW` | `missing_attachment` | 转人工 |
| 其他类别邮件 | `OK` | – | 无需处理 |

空值或无效值**不算差异**。七项比对必须全部可靠完成，才会给出 OK 或 MISMATCH。

> **当前部署说明（2026-09-21）：** 线上界面把 91 封 `request_draft` 邮件单独放进「待发送 Draft BL」
> 行动列表，目前导出为 `BL_COMPARISON + OK`。这是阶段性产品处理，最终提交前仍需与上面的官方输出
> contract 对齐。
文件角色绝不靠文件名猜。

确认版流程见 [流程图](docs/FreightSentinel-确认版流程图.html)、
[SVG 版](docs/FreightSentinel-确认版流程图.svg) 与 [流程说明](docs/确认版流程说明.md)。

---

## 六、更正副本与人工复核

对已确认的 MISMATCH，可以「生成更正版 BL 副本」：在**另一个文件**里只改不一致的字段，
用 AI 从 SI 提取的值；保存前 AI 必须重新读取生成出来的文件、确认七个字段。
PDF 编辑保守处理：位置不明、字体不支持、重叠、空间不够，一律报告为需要人工编辑，不保存未经验证的副本。

- `PENDING_HUMAN_APPROVAL`：复核过的副本或人工报告等待采纳
- **采纳并保留副本**：校验文件哈希后保留，采纳本身不再调用 AI
- **拒绝并删除副本**：只删除后端生成的那份副本，原件不动，审计记录保留
- 人工可以补交替换的 SI/BL 附件，或直接修正七项读数；最终人工表单可以完全不依赖 AI 完成处理
- 人工处理后禁止再自动分析；重开由人决定
- 未知类别会一直留在人工队列，并阻止「完整导出」

生成的文件在 `backend/.cache/revisions/<email_id>/<revision_id>/`；
结果、人工复核历史与批量历史都存在 `CACHE_DIR` 下（已 gitignore）。

---

## 七、仓库里有什么 / 没有什么

```
backend/    FastAPI 服务（app/main.py 路由，app/pipeline.py 分析流程，tests/ 测试）
frontend/   Next.js 前端（app/ 页面，components/，lib/api.ts）
data/       官方参赛数据包 sdoc-hackathon-bundle.zip（后端启动时解压）
docs/       确认版流程图 + 流程说明
render.yaml Render 部署蓝图
```

**没有进仓库的**（在 `.gitignore` 里）：
- `backend/.env` —— 真实密钥
- `backend/.cache/`、`backend/.data/` —— 运行结果与解压出来的数据
- `node_modules/`、`.venv/`、`.next/` —— 依赖与构建产物
- `docs/` 下的逐封测试 JSON / CSV / 测试报告 —— 开发过程记录，留在本机，不随仓库更新

## 八、评测边界

只使用官方参赛数据包作为输入。主办方的本地 Docker 自评接口（`POST /submit`）可以用来给
`GET /api/submission` 打分；私有标准答案绝不读取。

离线测试用 `backend/tests/fakes.py` 里显式注入的假模型，不调用付费 API，
因此**测试通过只代表流程跑得通，不代表模型准确率**。

---

## 九、验证记录

下面是 2026-09-21 核对过的当前云端快照，运行链路为：浏览器 → Vercel → Render → DeepSeek。
这组数据取代旧的 61 / 48 / 111 快照；旧快照产生时，界面还没有把待发送 Draft BL 的行动请求单独分开。

| 当前云端运行 | 结果 |
|---|---|
| 处理邮件 | 520 / 520 |
| 耗时 | 16 分 55 秒（并发 4） |
| Batch 失败 | **0** |
| 首轮 AI 调用 | 740 |
| 资深复核调用 | 44 |
| 资深复核技术失败 | **4** |
| 非比对邮件（只分类） | 300 |
| 安全完成的比对 | 63 |
| 待发送 Draft BL 的行动请求 | 91 |
| `MISMATCH` | 46 |
| `NEEDS_REVIEW` | 20 |

当前被分类为 `BL_COMPARISON` 的 220 封邮件，在界面中分成：63 个安全比对、91 个 Draft BL 行动请求、
46 个不一致和 20 个转人工。完整官方导出包含另外 300 封非比对邮件，因此最终 status 分布是
454 个 `OK`、46 个 `MISMATCH`、20 个 `NEEDS_REVIEW`。

当前 review reason 分布为：`unreadable` 9、`wrong_doc_type` 5、`missing_attachment` 4、
`missing_value` 2。其中四封在资深复核技术失败后被错误路由：`email_507` 应保留
`missing_attachment`；`email_516`、`email_518`、`email_520` 应保留 `missing_value`。
这里把它们如实记录，不能把当前运行直接说成已经证明了业务准确率。

`GET /api/submission` 的输出与主办方 `sample_submission.json` 逐字段核对过：520 个 email_id 不缺不多，
每条记录五个字段完全一致，类型一致。

**这证明了什么、没证明什么。** 它证明管线能在真实基础设施上完整跑完、失败是显式可见而不会被悄悄
当成通过、结果可以跨环境复现。它**不能**证明业务判断的准确率 —— 我们没有读取标准答案，下面列出的
已知问题也尚未解决。

## 十、遇到的挑战

**字段标题 ≠ 字段值 —— 当前运行已修复。** 邮件 383、411、498 曾把 `To the Order of:` 与
`Consignee:` 的标题差异误判成值不同。当前部署已把三封全部判为 `OK`，并说明标题写法不同、实际公司
值一致。

**技术失败不能覆盖掉有效发现 —— 仍未解决。** 当前云端快照有四次资深复核超过模型输出上限。
系统把案件交给了人工，但在 `email_507`、`email_516`、`email_518`、`email_520` 上用笼统的
`unreadable` 覆盖了首轮更准确的原因。**安全转交本身不够 —— 如果转交过程毁掉了已经掌握的信息，
那仍然是退步。**

**拒绝猜测是设计，不是异常分支。** JSON 解析失败、引用的证据在原文里找不到、字段没给全 —— 每一种
都会被校验拒绝，带着原因转人工。这里的诱惑是「退回规则算一个结果出来」，但系统不这么做：对看报告
的人来说，**规则跑出来的 `OK` 和真正核对过的 `OK` 长得一模一样**，这比没有结果更危险。

**本地与云端的配置漂移。** `AI_SENIOR_PROVIDER` 的默认值是 `openai`。部署时如果不填它，资深阶段的
供应商就与主模型不一致，密钥不会被复用，**整个二次复核会自己关闭，而且不报任何错** —— 服务显示健康、
输出看起来正常，跑的却是另一套没被测试过的流程。现在所有变量都写死在 `render.yaml` 里，部署不可能
再悄悄偏离测试过的配置。

**冷启动和「原型挂了」长得一模一样。** 免费套餐 15 分钟无流量就休眠，之后第一个请求会返回 30–60 秒的
503，界面显示「0 emails」—— 跟一个坏掉的系统毫无区别。解决办法是用外部监控每 5 分钟 ping 一次
`/health`，让服务在评审窗口内始终保持唤醒。

**免费套餐没有持久磁盘。** 结果存在实例文件系统里，重新部署或重启就没了。因此自动部署在全量跑期间
是个隐患：往 `main` 推一次代码就会重启服务、抹掉 20 分钟的运行结果。提交用的 JSON 因此导出并保存在
实例之外。

## 十一、未来路线

**先解决正确性。** 先让 91 封 `request_draft` 行动请求与官方输出 contract 对齐。资深复核技术失败时
保留首轮有效发现，并把技术失败单独显示，而不是覆盖正确的 `missing_attachment` 或 `missing_value`。

**读更难的文件。** 在后端主机上装 Tesseract 与 Poppler，启用管线里已经实现、但当前 Render 环境缺少
系统依赖而无法使用的本地 OCR 兜底；并评估用视觉模型处理扫描件与纯图片页。

**接真实邮箱、换真实存储。** 用 IMAP 或 Microsoft Graph 替代静态数据包；用 Postgres 替代 JSON 结果
缓存，让历史记录、审计轨迹和人工决策能挺过一次重启。

**让复核队列产生复利。** 每一次人工更正都已经记录了确认后的类别、结论、差异字段和处理说明。把这些
回流成评测用例，复核队列就变成一套**随使用量增长的回归测试集**。

**建立可度量的基线。** 把全量运行和结构化验收脚本放进 CI，任何提示词或模型的改动都要先和上一轮跑分
对比再决定是否采纳，而不是靠跑一两个样本拍脑袋。
