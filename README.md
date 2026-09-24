# Sample Tube Inventory

纯后端样本管分装库存服务（Python 3.12 + FastAPI + SQLite）。

解决实验台两类问题：

1. **超分**：两个终端拿着同一份旧余额同时分装会凭空多出样本。本服务用
   *乐观修订号 + 行级写事务* 保证同一母管同修订号的并发分装最多一笔成功。
2. **可追溯**：每次分装原子地写入母管扣减、子管建立、谱系边、分装记录和
   修订号递增；历史只能读，不能改。

## 运行

```bash
docker compose up --build
# API: http://localhost:8000  健康检查: GET /health
```

SQLite 文件位于命名卷 `sample-data`（容器内 `/data/inventory.db`，由
`DB_PATH` 指定），容器重启后数据保留。

本地（无 Docker）：

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
pytest
```

## API

### `POST /tubes` — 登记初始样本管（根管）

```json
{ "id": "T1", "initial_amount": 100 }
```

### `POST /splits` — 一次分装

- `parent_id`：母管 id
- `expected_revision`：客户端看到的母管修订号（首管为 0）
- `request_key`：客户端生成的唯一请求键，用于幂等重试
- `children`：1–20 支新子管，`id` 在请求内唯一、`amount` 为正整数微升量

```json
{
  "parent_id": "T1",
  "expected_revision": 0,
  "request_key": "550e8400-…",
  "children": [
    { "id": "S1", "amount": 40 },
    { "id": "S2", "amount": 35 }
  ]
}
```

子管总量超过当前余额返回 `409 INSUFFICIENT_BALANCE`；修订号过期返回
`412 REVISION_CONFLICT`。成功后母管余额扣减、修订号 +1。

**幂等**：相同 `request_key` + 完全相同正文（JSON 键序无关）的重试返回首次
结果且不重复扣减；同键不同正文返回 `409 IDEMPOTENCY_CONFLICT`。

### `GET /tubes/{id}` — 读取任一管

返回：

- `balance` / `revision`：当前余额与修订号
- `root_id` 与 `ancestors`：从根到该管的祖先链（含自身）
- `lineage`：链上的谱系边（母→子、分量、在原请求中的位置）
- `split_records`：链上每一支管的原始分装记录（完整子管清单与数量）

另提供 `GET /tubes`（分页）与 `GET /splits/{id}`。服务不提供任何改写/删除
历史的接口（`PUT/PATCH/DELETE` 返回 405）。

## 错误码

| 状态码 | code | 场景 |
|---|---|---|
| 422 | `VALIDATION_ERROR` | 未知字段、非正整数/非整数微升量、子管数超出 1–20、子管 id 重复、非法 JSON |
| 404 | `TUBE_NOT_FOUND` / `SPLIT_NOT_FOUND` | 管或分装记录不存在 |
| 412 | `REVISION_CONFLICT` | 预期修订号与当前修订号不一致（并发落败方） |
| 409 | `INSUFFICIENT_BALANCE` | 子管总量 > 当前余额 |
| 409 | `IDEMPOTENCY_CONFLICT` | 请求键已用过但正文不同 |
| 409 | `TUBE_ALREADY_EXISTS` | 登记重复 id / 子管 id 已存在 |

## 并发与一致性

- 每个 split 请求以 `BEGIN IMMEDIATE` 获取写锁，事务内读取母管余额/修订号、
  校验、写入 `splits` / `tubes` / `lineage`，再一次性提交；
- `splits.request_key` 有 UNIQUE 约束，即使两个请求同时穿过预检查，也只有
  一个能落库，另一个自动回放原结果或返回 `IDEMPOTENCY_CONFLICT`；
- WAL 模式 + `busy_timeout`，读不阻塞写、写互相排队。

## 测试

`tests/` 覆盖：

- 两个**独立连接/独立 HTTP 客户端**用相同旧修订号竞争同一母管，恰好一笔成功；
- 同键同体并发重试双方都拿到同一结果且只扣一次；
- 服务重启后余额、谱系、分装记录保留，且旧请求键仍可幂等重放；
- 逐层分装（含 20 支扇出与连续 20 次分装）后所有管余额之和恒等于根管初始量；
- 422 / 404 / 409 / 412 各错误码与历史只读约束。
