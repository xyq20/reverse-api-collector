# Reverse API Collector

面向“登录后网页内部接口”的通用数据采集脚手架。核心只负责稳定运行，平台差异放在小型插件中；三个现有项目保持原样，不被本项目导入或修改。

适用的数据流：

```text
浏览器发现接口 → 平台插件构造请求 → HTTP / Browser Fetch → 严格解析
        → 分页、重试、鉴权刷新 → 清洗去重 → JSON / CSV / SQLite / 自定义 Sink
```

## 当前能力

- 独立的发现模式：监听 XHR/Fetch，保存脱敏 JSONL 和有限响应样例。
- `http`、`browser_fetch`、`auto` 三种请求模式。
- Playwright 与 CloakBrowser 持久化 Profile；同一 Profile 有进程锁。
- 401 单次鉴权刷新、429 `Retry-After`、幂等请求指数退避。
- GET、POST 请求体、Cursor 等分页循环保护。
- 原子 Checkpoint，身份不匹配或文件损坏时明确停止。
- 字段改名、必填校验、选择字段和跨批去重。
- JSON、JSONL、CSV、SQLite 输出；插件可增加 MySQL、飞书等 Sink。
- 插件别名、Python `module:Class` 和包 Entry Point 三种加载方式。
- `new-plugin` 生成新平台的最小适配器。

脚手架不会尝试绕过验证码、破解权限或访问账号无权查看的数据。发现记录虽会自动脱敏，提交前仍应人工检查。

## 安装

Windows PowerShell：

```powershell
cd "D:\随便玩玩\reverse-api-collector"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[all]"
.\.venv\Scripts\python.exe -m playwright install chromium
```

只运行纯 HTTP 插件时可以安装更小的依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[http]"
```

## 快速验证

```powershell
.\.venv\Scripts\reverse-collector.exe validate configs\demo.toml
.\.venv\Scripts\reverse-collector.exe run configs\demo.toml
```

结果写入 `output/demo/posts.json`。

## 开发一个新平台

### 1. 发现接口

```powershell
.\.venv\Scripts\reverse-collector.exe discover "https://目标平台/数据页面" `
  --domain "目标接口域名" `
  --profile "profiles/目标平台/账号别名" `
  --output "captures/目标平台.jsonl"
```

浏览器打开后，人工登录并操作一次日期、翻页、导出等动作。完成后回到终端按 Enter。查看端点汇总：

```powershell
.\.venv\Scripts\reverse-collector.exe capture-summary captures\目标平台.jsonl
```

发现模式默认只记录 XHR/Fetch。Authorization、Cookie、CSRF、Token、签名等字段会替换为占位符；大响应和二进制只记录大小与 SHA-256。

### 2. 生成插件

```powershell
.\.venv\Scripts\reverse-collector.exe new-plugin target_platform
```

生成内容位于 `plugins/target_platform/`。主要实现：

- `setup()`：进入正确 Origin，并用低成本接口验证登录状态；
- `first_request()`：从配置和 Checkpoint 构造首个请求；
- `parse_page()`：严格验证响应结构、返回记录和下一页；
- `refresh_auth()`：刷新 Cookie/Token，不把业务错误伪装成空数据。

配置中的插件引用为：

```toml
plugin = "plugins.target_platform.plugin:TargetPlatformPlugin"
```

### 3. 选择请求方式

```toml
[transport]
mode = "auto"
order = ["http", "browser_fetch"]
```

`auto` 并不会对所有错误盲目切换浏览器：

- 缺少请求通道或插件明确判定浏览器环境必需时可以降级；
- 401 先调用插件刷新鉴权，再在同一通道重试；
- 403、400、解析失败等默认直接报错；
- 非幂等导出创建请求默认不重试、不跨通道，避免重复创建任务；
- 如果确实需要，可在该 `RequestSpec` 上显式设置 `fallback_on_auth` 或 `fallback_on_network`。

浏览器内 Fetch 需要页面与接口满足同源/CORS 条件，插件应通过 `required_origin` 元数据指定正确入口页。

## 配置与秘密

任务使用 TOML。字符串支持环境变量：

```toml
[transport.headers]
x-csrf-token = "${PLATFORM_CSRF_TOKEN}"
optional-token = "${OPTIONAL_TOKEN:-}"
```

不要把以下内容提交到项目：

- 账号密码、数据库密码、App Secret；
- Cookie、LocalStorage、浏览器 Profile；
- 未脱敏 HAR、请求/响应样例；
- 现有三个项目中的本地账号配置。

## Checkpoint 与输出语义

顺序固定为：

```text
请求 → 严格解析 → Sink 写入/提交 → Checkpoint 推进
```

跨文件、数据库和外部 SaaS 无法提供真正的全局事务，因此框架采用“至少一次 + 幂等 Sink”。SQLite 配置 `key_fields` 后使用 Upsert。JSON/CSV 默认整次运行完成后原子替换，Checkpoint 只在最终文件落盘后提交。

## 命令

```text
reverse-collector run CONFIG [--interactive]
reverse-collector validate CONFIG
reverse-collector plugins
reverse-collector discover URL [...]
reverse-collector capture-summary CAPTURE.jsonl
reverse-collector new-plugin NAME
```

更完整的扩展契约见 [docs/architecture.md](docs/architecture.md)、[docs/plugin-guide.md](docs/plugin-guide.md) 和 [docs/migrating-existing-samples.md](docs/migrating-existing-samples.md)。
