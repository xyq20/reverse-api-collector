# 现有项目迁移边界

本脚手架不直接依赖下面三个项目，也不会迁移其中的账号、Cookie、浏览器 Profile、数据库密码或输出文件。它们只作为已验证接口行为的样本。

| 现有项目 | 可提炼到新插件的内容 | 不迁移的内容 |
| --- | --- | --- |
| `dmp-competition` | 达摩盘/生意参谋端点、Token/CSRF 提取规则、指标字段映射、分页参数 | 登录页面选择器、调试脚本、旧 Cookie JSON、浏览器缓存 |
| `dmp-wj-data` | 请求重试边界、达摩盘/阿里妈妈/生意参谋解析器、数据库字段映射 | 账号本地配置、重复 Browser 代码、硬编码数据库连接、业务入口拼接 |
| `jlqc-data-import` | 千川 `statQuery` 请求体、导出状态机、视频字段解析、飞书字段映射 | 页面点击下载链、已下载 Excel、飞书密钥、浏览器 Profile |

## 推荐迁移顺序

1. 先为一个低风险、只读数据集建立插件和离线脱敏响应测试。
2. 用发现模式核对旧端点的请求参数是否仍有效，特别是 CSRF、Token、签名和日期边界。
3. 优先把查询接口做成纯 `http`；若受 Cookie、TLS 指纹或前端上下文限制，再改成 `browser_fetch`。
4. 同一天并行运行旧程序和新插件，只比对记录数、自然主键集合与关键指标，不写入同一目标表。
5. 一致后才切换定时任务；旧项目保留一段时间作为回退入口。

## 对应插件形态

- 达摩盘、生意参谋、阿里妈妈：通常继承 `ApiCollectorPlugin`，实现 Token/CSRF 探测和普通分页。
- 千川数据查询：同样继承 `ApiCollectorPlugin`，POST 请求显式标记 `retryable=True`，并将 offset/cursor 放进 Checkpoint。
- 千川 Excel 导出：实现 `CollectorPlugin.collect()`，先在 Checkpoint 保存 `ExportTicket.id`，之后复用 `wait_for_export()` 轮询，再以流式 HTTP 下载文件并解析。
- MySQL、飞书、Excel：作为独立 Sink 实现，不写入平台采集插件；这样同一采集结果可以同时输出到 JSON、数据库和飞书。

所有新插件都应从 `reverse-collector new-plugin 平台名` 创建，并为解析逻辑增加脱敏样例测试。接口返回空数据、无权限、登录失效、限流和结构变更必须分别处理，不能统一返回空列表。
