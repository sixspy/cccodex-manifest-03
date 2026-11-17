# cc-manifest-lab

CC_Codex 二期（26.11）**数据工程**产品线：**湖区落地清单台**（Litestar + Preact CDN + SQLite）。

## 一句话骨架（自有，非外仓抄题）

**湖区落地批次 → 对象指纹登记 → 清单闭合 → 可见性对账**

与现有七线正交（不是采集目录、ETL 管道、同步源、解析入库、编排流、种子摄取、留存裁撤）。
不碰外仓常见指纹（Feed 归并 / CDC 游标 / 质检签发 / Slicegate 类仓名）。

## 领域

- **所属领域**：数据工程
- **子方向**：数仓与数据湖（落地清单 / 对象登记闭环）

## 技术栈

| 层 | 选型 |
|----|------|
| 后端 | Python 3.12、Litestar、Uvicorn、SQLite |
| 前端 | 原生 JS SPA（全中文，侧栏），靛青竖纹 + 亮青强调；不依赖外网 CDN |
| 测试 | pytest + httpx（本地秒级闭环，优先于 compose） |

## 基线已通主链

1. 湖区落地批次列表（收集中 / 已闭合，含跨区依赖徽标）
2. 向批次登记对象键与内容指纹
3. 闭合清单（对象数固化，拒绝空批）
4. 可见性对账报告（闭合批 vs 开放批 vs 孤儿对象）
5. 跨区依赖冻结：银区批闭合前铜区依赖须齐套；依赖面板 / 批次列表 / 闭合详情三块同动

### 跨区依赖冻结（本期功能）

- **路径已定：提交瞬间重取**。依赖面板展示的是打开瞬间的冻结快照（标注快照时间），仅作展示；
  能否放行闭合以提交瞬间在闭合事务内重取的依赖条数为准——快照过期不拦死、也不放行。
- **判定单源**：`app/services/dependencies.py` 的 `evaluate_batch()` 是面板、列表徽标、
  闭合放行三处共用的唯一判定函数；闭合在 `BEGIN IMMEDIATE` 事务内判定并写入，判定与闭合天然同源。
- **并发互斥**：两名调度同点闭合，写锁保证只有一个成功入账，另一个拿白话 409。
- **留痕回放**：闭合路径的每次判定（含被拦的）落 `dependency_checks` 表，
  闭合快照写入 `close_runs.detail`，详情页「判定回放」可查。

预留切口（未做，供后续功能题）：清单换版生效窗、闭合作废回开放、批量失败闭互斥、清单回灌等。

## 本地（推荐反馈环）

```powershell
cd claude-workspace\cc-manifest-lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
python run.py
```

http://127.0.0.1:6900/login · **admin / 123456**

## Docker

```powershell
docker compose up -d --build
```

端口 **6900**。冒烟：`python ..\scripts\_smoke_lab_access.py --dir .`
