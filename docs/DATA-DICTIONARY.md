# 夜班工时与工资

班次属于shift_day；计划结束时间不大于开始时间时跨到次日。打卡是带偏移的时间，先存UTC，再用Asia/Shanghai拆分实际日历日。休息区间按夜班日期归属处理，先从实际工作区间扣除。单班最多18小时，打卡须为整分钟。缺IN或OUT整班隔离，不猜补卡。

按实际日历日判断法定假日、周末，法定假日优先3倍、周末2倍、工作日8小时内1倍、超过8小时1.5倍；正常分钟按同员工同日累计，跨班片段共享阈值。参数holidays可传日期列表，默认仅2026-10-01。金额按片段Decimal计算到分，paid为实发工资，差额为应发减实发。此规则用于样例计算，不替代当地劳动法规。

## 审批落段（RATE_FIRST）

审批单经 `parameters.approvals`（对象列表）或 `parameters.approvals_csv`（字段 `order_id,employee,approved_minutes`）传入，分钟必须为非负整数；空哨兵按 APPROVAL_MISSING 隔离，小数/负数按 APPROVAL_MINUTES 隔离，缺字段按 APPROVAL_SHAPE 隔离，同 order_id 重复整组按 APPROVAL_DUPLICATE 隔离，员工无有效加班按 APPROVAL_UNMATCHED 隔离且额度不耗用。

额度按员工汇总，落段次序为倍率降序、同倍率按片段起始时刻升序、再按段序。逐片段满足 `minutes=approved_minutes+unapproved_minutes` 且已批不超过实际；员工台账满足 `approved=min(quota,actual)` 与 `approved+unused=quota`。`payable=round(amount×approved/minutes)`、`withheld=amount-payable`，分币守恒；只有已批分钟进入应付。审批或打卡改变会改变运行哈希并产生新批次，旧批次标记 superseded 但不删除。封存要求对账全部守恒校验通过，否则返回409且不写入封存标记。

## 通用采信约定

CSV按UTF-8 BOM、UTF-8、GB18030回退，保留逻辑记录结束行号；引号内换行由CSV解析。重复表头单独计数，列数不齐隔离。编码与ID按字符串保形。缺失哨兵为 `-`、`N/A`、`NULL`、`未知` 与空串；不得作为零。数值先NFKC归一、去千分位，再用Decimal。日期采用ISO；时间必须带偏移并转UTC。空文件、全空行、仅表头分别返回EMPTY_FILE、BLANK_FILE、HEADER_ONLY。

重复键为(id,version)，完全相同行去重；同键内容冲突则整组隔离，不取最后一行。行数对账：输入=采纳+隔离+空行+重复表头+完全重复。运行幂等键由输入字节、参数与规则版本计算。

同一员工/归属日/方向的最高版本若有时刻、时薪、班次、休息或实发金额冲突，则整班隔离；选中IN与OUT的时薪、班次起止与休息起止也必须完全一致。
