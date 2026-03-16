# 后端并发执行与 CAD 资源池改造方案

更新时间：2026-03-16

## 1. 目标

本方案用于把当前“单队列、单 worker、共享 AutoCAD 用户资源”的后端执行链，升级为“受控并发、可观测、可回滚”的执行架构，满足以下场景：

1. 多个用户同时上传 DWG 时，任务可以排队并有限并发执行。
2. 同一用户可以同时发起主交付流程和纠错流程，两者不必完全串行。
3. CAD 执行链在并发时不再共享同一套 Plotters / Plot Styles / PMP /
   CTB 目录，避免相互踩踏。
4. 后续前端可视化管理界面可以直接读取并控制：
   - 可用 CAD 版本
   - 默认执行 CAD
   - 受管打印资源
   - 槽位状态
   - 队列状态
   - 故障诊断信息

## 2. 当前工程现状

### 2.1 队列执行模型仍然是单队列、单 worker

当前 API 运行时在 `API/app/runtime.py` 中只有一个 `queue.Queue()`、一个
`_worker_thread` 和一个 `_worker_loop()`。这意味着：

1. 多用户上传时，所有任务进入同一个串行队列。
2. 主交付流程和纠错流程虽然是两套执行器，但仍共用同一个总队列。
3. 当前配置中的
   `concurrency.max_workers`、`concurrency.max_jobs`、`module5_export.cad_runner.max_parallel_dxf`
   还没有真正落成并发调度逻辑。

这和当前代码一致，而不是配置表面能力。

### 2.2 任务工作目录已经基本隔离

当前 CAD 执行链的优点是：每个 `source_dxf` 都会创建独立的运行目录，包含：

- `task.json`
- `result.json`
- `runtime_module5.scr`
- `accoreconsole.log`
- `module5_trace.log`
- `cad_stage_output/`

对应代码在：

- `backend/src/cad/cad_dxf_executor.py`
- `backend/src/cad/accoreconsole_runner.py`

这部分已经是后续并发设计的基础，不需要推翻。

### 2.3 当前真正未隔离的是系统级 CAD 共享资源

当前在执行模块5前，会调用 `ensure_plot_resources(...)`，把受管 `PC3 / PMP / CTB`
复制到 AutoCAD 可见目录。对应代码在：

- `backend/src/cad/plot_resource_manager.py`
- `backend/src/cad/cad_dxf_executor.py`

当前实际部署目标仍然是共享目录，例如：

- `%APPDATA%\Autodesk\...\Plotters`
- `%APPDATA%\Autodesk\...\Plotters\PMP Files`
- `%APPDATA%\Autodesk\...\Plotters\Plot Styles`
- `%LOCALAPPDATA%\Autodesk\...\Plotters\Plot Styles`

这解决了“目标机缺少打印资源”的问题，但没有解决并发下的资源隔离问题。

### 2.4 当前 `accoreconsole` 还没有使用独立 profile 启动

当前 `AcCoreConsoleRunner` 启动 `accoreconsole.exe` 时使用的是：

- `/i <source_dxf>`
- `/s <runtime_module5.scr>`
- `/l <locale>`

还没有使用 `/p <profile or arg>` 去绑定独立 AutoCAD profile。

这意味着即使任务目录隔离了，CAD 会话所依赖的打印搜索路径、plotter 支持路径、默认打印器等仍然落在共享用户环境上。

## 3. 外部资料验证后的关键结论

### 3.1 AutoCAD 官方机制支持“按 profile 启动”

Autodesk 官方命令行文档说明 `/p`
可以指定一个 profile 名称，或者一个导出的 ARG 文件；该 profile 在当前会话内生效。[Command Line Switch Reference](https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-Core/files/GUID-8E54B6EC-5B52-4F62-B7FC-0D4E1EDF093A.htm)
这意味着“每个 CAD
worker 槽位绑定一套独立 profile”是官方支持的能力，而不是规避手段。

### 3.2 Profile 本身就保存打印和搜索路径相关设置

Autodesk 官方说明，profile 会保存默认搜索路径、模板路径、打印机默认值等程序设置。[About Saving Program Settings as Profiles](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-Core/files/GUID-59EB0CD9-63AB-4A72-A02C-E7A447A8F729.htm)
这正适合用来承载槽位级的 CAD 环境隔离。

### 3.3 PC3 / PMP / CTB 都是按搜索路径解析的

AutoCAD 的 Files/Options 文档明确给出了：

- Printer Configuration Search Path（PC3）
- Printer Description File Search Path（PMP）
- Plot Style Table Search Path（CTB / STB）
- Print Spooler File Location

并说明多路径会按顺序搜索。[Files Tab (Options Dialog Box)](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-F95EE827-7567-44EA-9D69-E9D0D37EE13F.htm)
这说明后续最佳实践不是继续把资源写进共享用户目录，而是让每个 CAD 槽位的 profile 指向自己的受管 support
root。

### 3.4 多实例并发应做“有限槽位”，不应直接无限放开

Autodesk 社区和开发者资料都表明，多实例 `accoreconsole`
并行是可行的，但不同命令和插件链在并发下会出现挂起或不稳定，因此适合采用“有限槽位 + 独立工作目录 + 独立输入输出”的模式，而不是简单增加线程数。[Autodesk Developer Blog: Parallel Aggregation using AccoreConsole](https://blog.autodesk.io/parallel-aggregation-using-accoreconsole/comment-page-1/)
[Autodesk Community: AcCoreConsole IMPORT hangs](https://forums.autodesk.com/t5/visual-lisp-autolisp-and-general/bug-accoreconsole-import-hangs/td-p/9030355)

### 3.5 Office 自动化不应并到 IIS 或无界并发里

微软官方明确不建议在 ASP、ASP.NET、Windows 服务等 server-side 场景里无约束自动化 Office，原因包括用户身份、交互对话框、稳定性和并发压力问题。[Considerations for server-side Automation of Office](https://support.microsoft.com/en-us/topic/considerations-for-server-side-automation-of-office-48bcfe93-8a89-47f1-0bce-017433ad79e2)
这意味着即使 CAD 链后续开放到 2 个槽位，Office
/ 文档生成链也应该更保守，建议单槽位或严格串行。

### 3.6 队列系统的成熟实践是“多队列 + 有界并发”

Celery 官方文档强调，worker 并发数需要按任务类型和资源特性调优，且通常会拆成多 worker
/ 多队列，而不是让所有重任务共享一个无限并发 worker。[Workers Guide — Celery](https://docs.celeryq.dev/en/3.1/userguide/workers.html)
虽然当前工程不一定要引入 Celery，但这个资源池思路是适用的。

## 4. 总体方案

### 4.1 方案原则

1. 保留当前“任务工作目录隔离”。
2. 新增“CAD 资源槽位池”，每个槽位拥有独立 profile 与独立打印支持目录。
3. API 运行时从“单 worker 串行”升级为“多 worker + 资源调度器”。
4. 将主交付流程和纠错流程拆分为独立队列，但共享 CAD 槽位池。
5. Office / 文档链单独建更保守的 worker 池，不与 CAD 共用并发策略。
6. 默认先从很小的并发起步：
   - CAD slots = 2
   - Office slots = 1

### 4.2 执行拓扑

```text
浏览器 / 前端
  -> IIS（静态站点 + /api 反向代理）
     -> FastAPI
        -> 队列调度器
           -> CAD worker pool（2 个槽位）
              -> accoreconsole.exe + 独立 profile + 独立 support root
           -> Office / doc worker pool（1 个槽位）
              -> Word / Excel / PDF 导出
```

## 5. CAD 资源池设计

### 5.1 槽位定义

每个 CAD 槽位（slot）是一个独立执行环境，建议定义：

- `slot_id`
- `cad_version`
- `install_dir`
- `accoreconsole_exe`
- `profile_arg_path`
- `profile_name`
- `support_root`
- `plotters_dir`
- `pmp_dir`
- `plot_styles_dir`
- `spool_dir`
- `temp_dir`
- `status`（idle / busy / unhealthy）
- `current_job_id`
- `last_heartbeat`
- `last_failure`

### 5.2 槽位目录结构

建议统一放到：

```text
storage/runtime/cad-slots/
  slot-01/
    profile/
      fanban-slot-01.arg
    support/
      Plotters/
        打印PDF2.pc3
        tszdef-....pmp
        PMP Files/
          tszdef-....pmp
        Plot Styles/
          fanban_monochrome.ctb
    spool/
    temp/
    logs/
  slot-02/
    ...
```

关键点：

1. `PC3 / PMP / CTB` 在槽位目录里固定复制一份。
2. 不再依赖 `%APPDATA%` 或 `%LOCALAPPDATA%` 下的共享 Plotters / Plot Styles。
3. 任务只借用槽位，不在运行时反复向系统用户目录写资源。

### 5.3 Profile 策略

每个槽位启动前准备自己的 ARG / profile，至少固化这些搜索路径：

- Printer Configuration Search Path -> 槽位 `support/Plotters`
- Printer Description File Search Path -> 槽位 `support/Plotters/PMP Files`
- Plot Style Table Search Path -> 槽位 `support/Plotters/Plot Styles`
- Print Spooler File Location -> 槽位 `spool/`
- 其他必要 support path -> 槽位 `support/`

执行 `accoreconsole` 时通过：

- `/p <slot-profile.arg or profile name>`

把会话绑定到这个槽位，而不是绑定到 Windows 当前用户历史配置。

### 5.4 CAD 版本选择

继续沿用已经在 `fanban_m5` 验证过的策略：

1. 启动时探测本机全部可用 CAD。
2. 支持版本下限放到 `2010` 及以上。
3. 系统默认选最高版本。
4. 可在系统设置中手工切换默认版本。
5. 单任务允许覆盖默认 CAD 版本，但必须命中已有槽位能力。

## 6. 队列与调度设计

### 6.1 队列拆分

建议至少拆成三个逻辑队列：

1. `deliverable_queue`
   - 主交付流程
2. `audit_queue`
   - 纠错 / 审查流程
3. `doc_queue`
   - 封面、目录、计划、文档导出等 Office 链路

### 6.2 worker 池拆分

1. `cad_worker_pool`
   - 负责需要 AutoCAD / accoreconsole 的阶段
   - 并发上限 = CAD 槽位数
2. `doc_worker_pool`
   - 负责 Word / Excel / PDF 文档处理
   - 初始并发建议 = 1
3. `general_api_worker`
   - 只负责任务入队、状态查询、结果聚合
   - 不直接承担重任务执行

### 6.3 调度规则

1. 每个 CAD 槽位同一时刻只允许执行一个 CAD 任务。
2. 一个任务的 CAD 阶段必须完整占用单个槽位，直到该 CAD 阶段结束。
3. 不建议在第一阶段就做“单任务内多个 source_dxf 并发开多个槽位”；先让“任务间并发”成立，再评估“任务内并发”。
4. `deliverable_queue` 与 `audit_queue` 可以并发取任务，但最终都要竞争
   `cad_worker_pool`。
5. `doc_queue` 不和 `cad_worker_pool` 竞争资源。

## 7. 与当前代码的衔接方案

### 7.1 保留的部分

以下现有设计可以直接复用：

1. `CADDXFExecutor.execute_source_dxf(...)` 的任务目录隔离逻辑。
2. `AcCoreConsoleRunner` 的脚本生成和日志采集逻辑。
3. 现有 `result.json / module5_trace.log / accoreconsole.log` 回传方式。
4. `autocad_path_resolver.py` 的 CAD 探测能力。
5. `plot_resource_manager.py` 中“受管资源命名”的经验。

### 7.2 需要改造的部分

#### A. `API/app/runtime.py`

从当前：

- 单 `queue.Queue()`
- 单 `_worker_thread`

改成：

- 多逻辑队列
- 可配置 worker pool
- 单独的资源调度器

#### B. `backend/src/cad/plot_resource_manager.py`

从当前：

- 每任务执行前往共享用户目录部署资源

改成：

- 服务启动时预创建槽位 support root
- 槽位目录内部署受管资源
- 运行时只验证，不向共享系统目录写入

#### C. `backend/src/cad/accoreconsole_runner.py`

从当前：

- `/i /s /l`

改成：

- `/i /s /l /p <slot-profile>`
- 任务执行前显式注入槽位 profile
- 记录当次槽位、profile、CAD 版本

#### D. `backend/src/cad/cad_dxf_executor.py`

从当前：

- 运行中自己确保 plot 资源

改成：

- 从调度器拿到 `slot_context`
- 任务只使用槽位 support root
- 结果里增加 `slot_id / cad_version / profile_arg / managed_pc3 / managed_ctb`

## 8. 前端/管理界面接口设计

### 8.1 系统设置接口

建议新增：

1. `GET /api/system/cad/options`
   - 返回可用 CAD 版本、路径、版本号、健康状态
2. `GET /api/system/plot/resources`
   - 返回受管 `PC3 / PMP / CTB` 状态、哈希、缺失情况
3. `GET /api/system/runtime-config`
   - 返回当前默认 CAD、默认打印资源、槽位配置
4. `PUT /api/system/runtime-config`
   - 修改默认 CAD 与默认打印配置
5. `POST /api/system/rescan`
   - 重新探测 CAD 与打印资源
6. `GET /api/system/cad/slots`
   - 返回每个槽位的实时状态

### 8.2 任务接口增强

在任务详情中补充：

- `queue_name`
- `worker_id`
- `slot_id`
- `cad_version`
- `accoreconsole_exe`
- `profile_arg`
- `pc3_path`
- `pmp_path`
- `ctb_path`
- `fallbacks_used`

这样前端可以直接显示“这次任务到底用了哪一套 CAD / 打印环境”。

## 9. 故障隔离与诊断

### 9.1 槽位健康检查

每个 CAD 槽位应支持：

1. 资源自检
   - `accoreconsole.exe`
   - `打印PDF2.pc3`
   - `PMP`
   - `fanban_monochrome.ctb`
   - profile 文件
2. 心跳
3. 最近一次失败摘要
4. 隔离重建
   - 某个槽位资源损坏后只重建该槽位，不影响其他槽位

### 9.2 蓝屏/异常恢复

不能把蓝屏完全归因于 Python 或 GUI，但系统需要具备恢复策略：

1. 启动时做 bundle / 资源完整性检查。
2. 若槽位 support root 文件缺失或损坏，只重建槽位资源。
3. 若 `accoreconsole` 连续异常退出，将槽位标记为 `unhealthy`，暂停分配新任务。
4. 将 Windows dump、槽位日志、任务日志关联到同一次故障记录中，方便后续追查。

## 10. 分阶段实施顺序

### 阶段 1：先落资源池，不放开并发

目标：在不改变当前单 worker 行为的前提下，先把 CAD 槽位和 profile 机制落地。

完成标准：

1. 至少创建 `slot-01`。
2. `accoreconsole` 改为通过 `/p` 使用槽位 profile。
3. `PC3 / PMP / CTB` 不再部署到共享用户目录。
4. 现有业务结果不变。

### 阶段 2：从单 worker 升级到 2 个 CAD 槽位并发

目标：允许两个需要 CAD 的任务同时运行。

完成标准：

1. `deliverable_queue` 与 `audit_queue` 可以并发出队。
2. `cad_worker_pool` 有 2 个槽位。
3. 同时执行两份 DWG 时，任务记录能清楚标出各自使用的槽位。
4. 现有 PDF / DWG / 文档结果不回退。

### 阶段 3：接入前端管理界面

目标：把系统级执行环境变成可视化、可配置。

完成标准：

1. 前端可查看当前默认 CAD、可用 CAD 列表、槽位状态。
2. 前端可查看当前受管打印资源状态。
3. 管理员可修改默认执行版本与打印设置。
4. 普通任务页面默认继承系统配置，必要时允许单任务覆盖。

### 阶段 4：评估任务内并发

只有在前 3 阶段稳定后，再评估：

- 单个大型任务内多个 `source_dxf` 是否允许并发分发到多个 CAD 槽位。

这一阶段不应提前做。

## 11. 风险与边界

1. 当前最不适合直接放开的不是“代码线程数”，而是共享 AutoCAD 用户环境。
2. 只把 `API/app/runtime.py`
   改成多线程而不做 CAD 槽位和 profile 隔离，会制造更难排查的偶发错误。
3. Office 自动化链路不应与 CAD 并发策略等同对待，应更保守。
4. 本方案默认前端控制的是“执行节点”的 CAD
   / 打印配置，不是浏览器用户自己电脑上的 CAD。

## 12. 推荐结论

推荐最终落地路线如下：

1. IIS 只托管前端静态站点与 `/api` 反向代理。
2. FastAPI + worker 独立运行。
3. 先做 CAD 资源池和 profile 隔离，再做 worker 并发。
4. 初始并发建议：
   - CAD slots = 2
   - Office slots = 1
5. 前端先做“系统环境管理页”，再做“单任务可覆盖”。

这条路线能够最大化复用当前 `fanban_m5`
上已经验证过的经验，同时避免把共享资源问题带到正式后台。

## Sources

- [About Saving Program Settings as Profiles](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-Core/files/GUID-59EB0CD9-63AB-4A72-A02C-E7A447A8F729.htm)
  (Mar 2026)
- [Files Tab (Options Dialog Box)](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-Core/files/GUID-F95EE827-7567-44EA-9D69-E9D0D37EE13F.htm)
  (Mar 2026)
- [Command Line Switch Reference](https://help.autodesk.com/cloudhelp/2021/ENU/AutoCAD-Core/files/GUID-8E54B6EC-5B52-4F62-B7FC-0D4E1EDF093A.htm)
  (Mar 2026)
- [Plotter Configuration Editor](https://help.autodesk.com/cloudhelp/2025/ENU/DWGTrueView/files/GUID-A859CF75-F98D-416C-8BCF-AB7E2AD12D9F.htm)
  (Mar 2026)
- [Considerations for server-side Automation of Office](https://support.microsoft.com/en-us/topic/considerations-for-server-side-automation-of-office-48bcfe93-8a89-47f1-0bce-017433ad79e2)
  (Mar 2026)
- [Workers Guide — Celery](https://docs.celeryq.dev/en/3.1/userguide/workers.html)
  (Mar 2026)
- [Autodesk Developer Blog: Parallel Aggregation using AccoreConsole](https://blog.autodesk.io/parallel-aggregation-using-accoreconsole/comment-page-1/)
  (Mar 2026)
- [Autodesk Community: AcCoreConsole IMPORT hangs](https://forums.autodesk.com/t5/visual-lisp-autolisp-and-general/bug-accoreconsole-import-hangs/td-p/9030355)
  (Mar 2026)
