# 考勤跨夜班与加班分段核算

面向制造企业薪酬核算员，处理采信、判定、核算、复核与归档。

## 启动

```bash
docker compose up --build -d
```

访问 http://localhost:18252 。初次启动自动运行脏样例，可切换 clean.csv 与 legacy.csv。顶部“运行批次”会重新计算，同源输入复用批次。

## 业务模块

- 打卡采信：`/m1_ingest`、`/api/m1_ingest`
- 班次日历：`/m2_mapping`、`/api/m2_mapping`
- 跨夜配对：`/m3_versions`、`/api/m3_versions`
- 缺卡复核：`/m4_segments`、`/api/m4_segments`
- 工时切段：`/m5_calculate`、`/api/m5_calculate`
- 薪资对账：`/m6_reconcile`、`/api/m6_reconcile`
- 周期归档：`/m7_archive`、`/api/m7_archive`

## 核心规则

跨夜按班次归属日配对，休息区间先扣除，再按法定日期和工时阈值切分倍率。完整数值、边界和异常定义见 `docs/DATA-DICTIONARY.md`。

### 审批额度落段裁决

审批单只写员工与总分钟、不指定片段。本项目裁决为**高倍率优先（RATE_FIRST）**：额度先覆盖倍率最高的片段，同倍率按发生先后；使额度受限时员工可支付金额最大。每个片段逐项给出实际分钟、已批分钟、未批分钟、应付与不付，金额按 Decimal 到分且 `金额=应付+不付`。审批超过实际工时的余量记“批而未用”，不挪用；无匹配加班的审批单隔离为异常。完整裁决、守恒与失效规则见 `docs/APPROVAL-ALLOCATION.md`。

审批或打卡任一更新都会改变运行哈希、产生新批次，旧批次整份保留并标记“已作废”；同输入重复执行命中同一批次，不重复耗用。封存为单事务，对账不平禁止封存与导出，失败回滚并保留旧版与原始依据。页面与导出共用同一份批次结果。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

原始样例在 `sample_data/`（`approvals.csv` 为配套审批单）。测试在 `tests/`。封存文件是单份CSV，含运行清单、对账校验、审批台账与审批异常、计算证据、隔离原因。复核需提交当前版本，陈旧复核返回409；封存走单事务，对账未平返回409。

## 数据与限制

SQLite保存在records命名卷，普通重启与构建不会清除。确认可丢弃本项目数据后，运行 `docker compose down -v` 再启动可重置。单文件上限2MB；不接入外部业务系统；历史规则由本项目样例定义，不代表实际行业标准。
