---
created: 2026-09-28
tags:
  - bugfix
  - db
  - dump-messages
---

# 修复 dump-messages 对已存在的消息不更新

## 概要

`db.save_message()` 的更新分支调用的是 `message.update()`：在 Peewee 里这只构造了一个 UPDATE 查询对象，并没有执行，而且模型没有单一主键，`save()` 这条路本来也走不通。结果是 `dump-messages` 第二次跑到同一条消息时库里仍是旧内容，还会往标准输出打印一行调试信息 `update message ...`。

按 TDD 先写了走 `Scraper.dump_messages` 整条流程的测试（只 mock Telegram），确认 6 个用例失败，再把 `save_message` 改成「查出已有行 → 调 `save_message_smart(force=True)`」。修复后全量测试 61 通过、3 跳过（需要真实登录的集成测试），复现脚本 `tmp/verify_save_message_update.py` 输出 `update persisted: True`。

## 修改的文件

- `telememo/db.py` — `save_message` 复用 `save_message_smart(force=True)`，删掉了不生效的更新分支和调试 `print`
- `tests/test_dump_messages.py` — 新增，7 个用例：重复导出后内容更新、未编辑消息的统计数刷新、全部数据列回填、扩展列不被清掉、新旧消息混合、不向标准输出打印、dry-run 不写库
- `kb/docs/message-pipeline.md` — 补一句 `dump-messages` 对已有消息的覆盖语义
- `kb/known-issues.md` — 删除已解决的条目；给「统计数不会刷新」条目补上现有绕过办法

## 注意事项

- **语义选择：无条件覆盖，而不是按编辑时间判断。** 旧代码的意图就是「存在则更新」，其中包含浏览数、转发数、回复数，这些变化不会改编辑时间；如果复用不带 `force` 的智能保存，重复导出对没编辑过的消息仍然是空操作。所以 `dump-messages` 现在和 `sync --full` 行为一致。
- 覆盖范围从旧代码想写的 7 列变成 `_message_row` 的全部数据列，因此重复导出也能回填后来新增的列（链接预览、转发来源、媒体尺寸）。扩展列不在 `_message_row` 里，不受影响，有测试覆盖。
- Peewee 的 `instance.update()` 和 `Model.update()` 是同一个类方法，返回查询对象，必须 `.execute()`。对没有单一主键的模型，写入一律用 `Model.update(...).where(...).execute()`。
- 性能没有退化：旧实现的 `get_or_create` 每条消息也要先查一次，现在同样是每条一次查询。
- 测试里替换 `core.TelegramClient` 再构造 `Scraper`，可以避开会话文件检查，不碰真实会话文件。

## 遗留问题

- `sync`（非全量）对从未编辑过的消息仍不刷新统计数，已在 `kb/known-issues.md` 原条目里补充了绕过办法，根因未动。
- `dump-messages` 每条消息单独查一次已有行；如果以后嫌慢，可以像 `sync` 那样按批 `get_messages_by_ids` 后走 `save_messages_batch_smart(force=True)`。目前没有性能问题，未登记。

## 已解决的已知问题

- **入库：`dump-messages` 遇到已存在的消息不会更新** — `save_message` 改为复用 `save_message_smart(force=True)`；由 `tests/test_dump_messages.py` 和复现脚本验证。

## 相关文档

- [消息的形态、入库与展示](../docs/message-pipeline.md) — 本次更新了「同步」一节里 `dump-messages` 的说明
