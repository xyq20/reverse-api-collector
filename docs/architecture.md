# 架构与稳定性约束

## 组件边界

- `CollectorPlugin`：平台业务、鉴权探测、请求构造、响应结构。
- `Transport`：只执行 I/O，不判断业务字段。
- `RunContext`：统一鉴权刷新、请求统计和 Checkpoint 暂存。
- `CollectorRunner`：批次、Pipeline、多个必需 Sink 和生命周期。
- `Sink`：目标系统适配；默认全部为必需输出。

自定义复杂工作流可以直接实现 `CollectorPlugin.collect()`；普通分页接口继承 `ApiCollectorPlugin`。异步导出可复用 `reverse_collector.export.wait_for_export()`，按“读取已有 ticket → 创建 → 轮询 → 流式下载 → 校验”拆分；创建请求必须标记 `retryable=False`。

## 错误必须分类

- 登录失效：`AuthenticationError`，最多刷新一次。
- 限流：`RateLimitError`，遵守 `Retry-After`。
- 网络/5xx：只有幂等请求才自动重试。
- 浏览器环境要求：`HttpIncompatibleError`，允许 Auto Transport 降级。
- 响应结构变化：`PluginError`，必须停止并保留脱敏样例。
- 合法空数据：插件显式返回 `records=[]` 且 `done=True`。

请求失败绝不能转换成空列表，否则分页会静默截断。

## 后续建议扩展

- 通用异步导出 Poller 与流式 Artifact 下载器；
- MySQL、飞书和 Excel 独立 Sink 包；
- 账号级速率限制器和有界工作队列；
- 发现记录差异分析，辅助识别日期、分页和店铺参数；
- 旧程序脱敏响应的 Golden Parser Tests。
