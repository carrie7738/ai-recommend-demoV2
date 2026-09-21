# AI 采购推荐 Demo

基于 Streamlit 的采购决策演示：将自然语言请求转成结构化意图，由模型提供定性推荐，再由本地规则计算采购数量、费用并校验约束。

V2 为主流程；V2 失败时可能进入带有明确标识的 V1 规则降级。降级结果不等同于通过 V2 校验的计划。本项目用于演示与评估，不直接生成真实采购订单。

页面固定标记为 **DEMO MODE**。页头的 **Business Data Date** 是本次采购计算实际使用的业务日期，可能来自场景日期、活动窗口或供应快照；旁边的 `Run ... local` 仅表示本地页面运行时间。两者不应混用，也不代表真实订单日期。

## 项目入口

本机 Git 仓库在 `D:\carrie\recommend-demo\ai-recommend-demo`。父目录 `D:\carrie\recommend-demo` 另有同名代码，启动、测试和修改均应在本仓库执行。其他机器使用实际克隆目录。

| 文档 | 用途 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 开发协作、业务边界和完成标准 |
| [V2 架构合同](docs/V2_ARCHITECTURE_CONTRACT.md) | 当前运行流程与数据合同 |
| [V2 评估参数](docs/V2_EVALUATION_PARAMETERS.md) | 参数及确认状态 |
| [Debug / Trace 使用说明](docs/V2_DEBUG_TRACE.md) | 本地调试、证据查看与导出 |
| [V2 历史验收报告](docs/V2_ACCEPTANCE_REPORT.md) | 2026-09-04 指定版本的验收证据，不代表当前版本 |
| [正确性修复收尾记录](docs/CORRECTNESS_CLOSEOUT_2026-09-20.md) | 本轮修复分组、离线验证与后续边界 |
| [2026-09-20 端到端验收记录](docs/E2E_ACCEPTANCE_2026-09-20.md) | 当前基线的真实模型、六场景与浏览器验收证据 |
| [V3 PRD](docs/AI_Smart_Procurement_Assistant_PRD_V3.docx) | 产品需求背景；实现边界以当前架构合同核对 |
| [V1 规范](docs/Recommendation_Engine_Specification_V1.docx)、[旧客户指南](CUSTOMER_DEMO_GUIDE.md) | 历史参考，不作为 V2 操作指南 |

## 本地启动

Python 基线固定为 **3.12.14**（[.python-version](.python-version)）。[requirements.txt](requirements.txt) 安装 [requirements-lock.txt](requirements-lock.txt) 中的精确版本；直接依赖范围保留在 [requirements.in](requirements.in)。锁定文件来自已通过回归的 Windows x64 环境，Linux 兼容性由 CI 单独验证；版本固定不等于跨平台验收已通过。

### Windows PowerShell

```powershell
Set-Location D:\carrie\recommend-demo\ai-recommend-demo
# 首次安装时执行；已有可用 .venv 时跳过创建和安装
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# 仅在不存在 .env 时复制，不覆盖已有配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

在本地编辑 `.env`：填写所选 provider 的密钥，或设 `AI_ENABLED=false` 查看无模型时的降级行为。不要保留占位密钥并将其当作有效配置。

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

浏览器打开 [本地页面](http://127.0.0.1:8501)。在启动终端按 `Ctrl+C` 停止。

### macOS / Linux

在实际仓库根目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
# 编辑 .env 后启动
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

## 配置

[config/settings.py](config/settings.py) 从仓库根目录加载 `.env`，**已注入的进程环境变量优先**。修改配置后重启应用；相对 `EXCEL_FILE` 路径依赖启动工作目录。

| 配置 | 说明 |
| --- | --- |
| `AI_ENABLED` | `true` 启用模型；`false` 禁用模型，不代表完成 V2 模型验收 |
| `AI_PROVIDER` | 当前代码有 `deepseek`、`glm`、`gemini` 适配器 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | DeepSeek 凭证、端点与模型 |
| `GLM_API_KEY` / `GLM_BASE_URL` / `GLM_MODEL` | GLM 对应配置 |
| `GEMINI_API_KEY` / `GEMINI_BASE_URL` / `GEMINI_MODEL` | Gemini 对应配置 |
| `AI_TEMPERATURE` | 代码默认 `0.3` |
| `AI_MAX_TOKENS` / `AI_STRUCTURED_MAX_TOKENS` | 代码默认分别为 `1024` / `16384` |
| `AI_THINKING_ENABLED` | 代码默认 `false`；实际能力取决于适配器和供应商 |
| `EXCEL_FILE` | 默认数据包 `data/AI_Demo_Data_Pack_V2_Large.xlsx` |
| `APP_TITLE` / `LOG_LEVEL` / `DEFAULT_CUSTOMER_NAME` | 页面标题、日志级别与默认客户名称 |
| `PROCUREMENT_DEBUG` | 设为 `true` 开启会话内 Trace；共享客户部署保持关闭 |

`.env.example` 的 DeepSeek 模型为历史验收使用的 `deepseek-v4-flash`，代码及现有 systemd 模板默认仍为 `deepseek-chat`。务必显式核对实际模型；这里描述的是仓库配置，不保证供应商当前可用性，也不代表其他适配器已通过真实验收。

密钥只保存在本地 `.env` 或受控的服务环境文件中，不要写入源码、日志或提交记录。

## 验证

### 离线回归

```powershell
$env:AI_ENABLED = 'false'
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Linux / macOS 对应命令：

```bash
AI_ENABLED=false .venv/bin/python -m unittest discover -s tests
```

PowerShell 中该环境变量会持续影响当前终端；切回真实模型运行前设置 `$env:AI_ENABLED = 'true'`。离线测试覆盖本地规则、模拟模型响应和程序化 UI，不证明真实 API 或人工浏览器交互通过。

2026-09-20 使用独立 Windows x64 / Python 3.12.14 虚拟环境，从固定依赖重新安装后，**228 项通过，38.874 秒**；52 个依赖版本与锁定文件一致，`pip check` 通过。这是包含未提交改动的验证快照，不是发布版本承诺。

### 自动回归与依赖更新

[GitHub Actions 工作流](.github/workflows/offline-tests.yml) 在 push、pull request 或手动触发时，对 Windows 2025 和 Ubuntu 24.04 执行固定 Python/依赖安装、`pip check` 和完整 unittest。测试阶段设置 `AI_ENABLED=false` 并清空 provider 密钥；安装阶段需要访问包仓库。工作流不会部署或调用真实模型。

本地对应命令：

```powershell
.\.venv\Scripts\python.exe -m pip check
$env:AI_ENABLED = 'false'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

更新依赖时在新的虚拟环境中安装 `requirements.in`，审查解析后的全部依赖，再用 `python -m pip freeze` 更新 `requirements-lock.txt`。必须重新执行 `pip check`、全量离线回归和受影响的真实模型验收；不要直接从混有无关工具的日常环境覆盖锁定文件。锁定文件固定版本但不包含分发包哈希，不是跨平台通用求解器输出。

CI 首次远端运行和分支保护需要在代码提交/推送后确认；仅添加工作流不会自动成为禁止合并的必需检查。

本轮工作流已通过 actionlint 1.7.12 静态检查（未启用 shellcheck）。Ubuntu 和远端 Actions 尚未运行。本地证据位于被 Git 忽略的 `outputs/ci-install.log`、`outputs/ci-clean-tests.log`；独立验证环境为 `outputs/ci-environment`，不作为项目运行环境或版本提交内容。

### 真实模型验证

以下命令会向指定供应商发送脚本中的测试请求及上下文，并可能产生费用。核对出站范围、有效密钥和模型后运行：

```powershell
$env:AI_ENABLED = 'true'
.\.venv\Scripts\python.exe scripts/model_smoke_test.py --provider deepseek --model deepseek-v4-flash
.\.venv\Scripts\python.exe scripts/v2_scenario_regression.py --provider deepseek --model deepseek-v4-flash --summary
```

Smoke 检查结构化调用；场景脚本检查绑定的演示场景，读取仓库内默认工作簿及场景映射，不使用 `EXCEL_FILE` 替换路径。需分别核对意图来源、业务效果、校验结果及失败/降级状态，不能只看 API 返回成功。

报告应记录代码版本及未提交改动、实际 provider/model、数据与 Prompt 版本、参数、时间、耗时及 token 指标。上述内容变化后按影响范围重新验收，旧报告不可直接复用。页面还应检查首次提交、再次提交、错误提示和降级标识。

## 数据与演示边界

默认数据包：[AI_Demo_Data_Pack_V2_Large.xlsx](data/AI_Demo_Data_Pack_V2_Large.xlsx)。

- 基础数据：`Customer`、`Product`、`OrderHistory`、`Inventory`、`Favorites`、`ConversationContext`。
- 业务信号：`IndustryTrend`、`HolidayConfig`、`HolidayProduct`、`PriceHistory`。
- V2 数据与配置：`SupplyAvailability`、`EventConfig`、`V2FeaturePolicy`、`V2TestScenarios`；具体字段和用途见架构合同。
- UI 演示门店 C001 已覆盖 P201-P215 的 V2 库存，可从自然语言门店解析进入真实模型、Optimizer 和 Validator 主链路。
- 六场景审计仍使用 `V2TestScenarios` 绑定的 C051 身份；C051 保留为脚本化回归基线，不应改写为 UI 门店。

门店、供应数据及预置场景的覆盖范围不同，不能把工作簿全部记录都视为已支持业务范围。场景日期可能取自演示映射、供应快照或活动窗口，应核对结果的业务日期，不能默认它就是今天。

模型决定定性推荐，本地 Optimizer 计算数量并按约束分配预算；当前策略不代表已证明的全局最优。未知库存不能按零库存解释。合法不采购、约束无法分配和执行失败应区分。

## Linux 部署参考

以下为待按目标服务器配置的步骤，本次未执行服务器部署。示例目录为 `/home/ubuntu/recommend-demo`，应直接包含本仓库 `app.py`，不要误用外层副本。

### 1. 准备环境

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx git
# 将本仓库放到 /home/ubuntu/recommend-demo 后执行
cd /home/ubuntu/recommend-demo
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

服务器 Python 与依赖版本需单独验证，再运行上面的离线测试。

### 2. 配置服务

```bash
sudo cp deploy/procurement-demo.service /etc/systemd/system/procurement-demo.service
sudo nano /etc/systemd/system/procurement-demo.service
```

[服务模板](deploy/procurement-demo.service) 默认从 `/etc/procurement-demo.env` 读取配置，并只监听 `127.0.0.1`：

- 核对 `User`、`WorkingDirectory` 和 `ExecStart` 的实际路径。
- 若更改环境文件路径，同步修改 `EnvironmentFile=`；不要把密钥写进 service 文件。
- 保持 Streamlit 监听回环地址，由 Nginx 代理访问，避免直接暴露 8501 端口。

```bash
if ! sudo test -e /etc/procurement-demo.env; then
    sudo install -m 600 /dev/null /etc/procurement-demo.env
fi
sudo nano /etc/procurement-demo.env
```

以上命令保留已有环境文件，仅在不存在时创建。填入实际配置，例如：

```ini
AI_ENABLED=true
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=replace-with-real-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
EXCEL_FILE=/home/ubuntu/recommend-demo/data/AI_Demo_Data_Pack_V2_Large.xlsx
PROCUREMENT_DEBUG=false
```

模型值需依据本次部署验收确定。然后启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now procurement-demo
sudo systemctl status procurement-demo --no-pager
curl --fail http://127.0.0.1:8501/_stcore/health
```

### 3. 配置 Nginx

```bash
sudo cp deploy/nginx-procurement-demo.conf /etc/nginx/sites-available/procurement-demo
sudo nano /etc/nginx/sites-available/procurement-demo
```

将 `server_name your-domain.com` 改为实际域名或 IP；核对现有站点配置是否冲突。首次启用时执行：

```bash
sudo ln -s /etc/nginx/sites-available/procurement-demo /etc/nginx/sites-enabled/procurement-demo
sudo nginx -t
sudo systemctl reload nginx
```

链接已存在时跳过创建。安全组按需允许 `22`、`80`、`443`，反向代理部署无需向公网开放 `8501`。访问实际站点验证页面及 WebSocket 交互；有域名时另行配置 HTTPS。

### 4. 日常操作

```bash
sudo systemctl restart procurement-demo
sudo journalctl -u procurement-demo -n 100 --no-pager
```

修改服务定义后先执行 `daemon-reload` 再重启；修改环境文件后重启服务。健康检查只证明服务可达，不能替代业务和模型验收。
