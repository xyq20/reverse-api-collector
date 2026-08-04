# 插件开发检查表

1. 确认账号有权在页面查看目标数据。
2. 使用独立 Profile 运行发现模式。
3. 记录接口 Origin、方法、Query 重复键、Body、响应结构和业务错误码。
4. 找到 Cookie、CSRF、Token 或签名的可靠来源，并实现低成本登录探测。
5. 优先纯 HTTP；需要浏览器 Cookie、指纹或前端环境时使用 Browser Fetch。
6. 为 POST 查询显式设置 `retryable=True`；导出创建、写操作保持 `False`。
7. 严格区分空数据、无权限、限流和响应 Schema 变化。
8. Checkpoint 至少包含下一页 Cursor/Offset；账号、日期和 Schema 由核心身份校验。
9. 为响应解析编写完全离线的脱敏样例测试。
10. 用同日期与页面/官方导出核对记录数、主键集合和核心指标。

千川等异步导出接口应先把 `ExportTicket.id` 写入 Checkpoint，再调用 `wait_for_export()` 继续轮询；进程重启后读取该 ID，不能重复创建导出任务。

不要从整页 HTML 随便取第一个 UUID 当 Token，不要只根据 Cookie 存在判断登录成功，也不要用错误文案作为唯一限流依据。
