# Phase 2.5 管理员诊断页与 Smoke 验收

## 1. 前置条件

- PostgreSQL 已启动，`DATABASE_URL` 可连接。
- API 已迁移并启动：
  - `cd apps/api`
  - `alembic upgrade head`
  - `uvicorn app.main:app --host 127.0.0.1 --port 8000`
- 已有管理员与成员账号：
  - `python scripts/create_admin.py <admin_user> <admin_pass>`
  - 成员可在“用户管理”页面创建。

## 2. 前端管理员诊断页

- 路由：`/admin/diagnostics`
- 访问控制：前端 adminOnly 路由守卫 + 后端 admin 鉴权（member 访问接口应 403）。
- 页面能力：
  - trace 列表（含筛选：trace_id/request_id/session_id/is_abstained/failed + 分页）
  - trace 详情抽屉（reason code、retrieval_meta、evidence_bundles、selected_evidence）
  - retry / force reindex 操作
  - trace JSON 导出
  - reason code 聚合统计

## 3. 后端接口（本轮）

- `GET /api/admin/diagnostics/traces`
- `GET /api/admin/diagnostics/traces/{trace_id}`
- `POST /api/admin/diagnostics/files/{file_id}/retry-index`
- `GET /api/admin/diagnostics/traces/{trace_id}/export`
- `GET /api/admin/diagnostics/traces/stats/reasons`

## 4. 一键 Smoke（Phase 2.5）

脚本：`apps/api/scripts/smoke_phase25_admin_diagnostics.py`

示例：

```bash
cd apps/api
python scripts/smoke_phase25_admin_diagnostics.py \
  --base-url http://127.0.0.1:8000 \
  --admin-user admin \
  --admin-pass '***' \
  --member-user member \
  --member-pass '***' \
  --require-db-env
```

覆盖步骤：

1. API `/health` 可达
2. admin/member 登录
3. member 访问 admin diagnostics => 403
4. 上传文件、触发索引、执行 QA
5. admin 查询 trace 列表与详情
6. retry-index 调用
7. trace export 调用
8. reason 统计调用
9. 清理会话与测试文件

## 5. 期望结果

- 脚本输出每一步 `[OK]` 并最终 `[SUMMARY] ... PASSED`。
- 任一步失败应 `[FAIL]` 并返回非 0 退出码。

## 6. 常见问题排查

1. `health` 失败：检查 API 进程、端口、防火墙。
2. 登录失败：确认 admin/member 账号密码与用户状态。
3. `index submit` 失败：检查 embedding 配置与数据库迁移。
4. `qa ask` 失败：检查 settings 中 QA/模型开关与 provider 配置。
5. `member forbidden` 非 403：检查后端 `require_admin` 是否生效。
