# Known Issues

> 当前 app 已知、待后续处理的问题：缺陷、简化实现、未验收项、待建流程。只反映最新状态——解决了就删掉条目，经过记到 `kb/sessions/`。

## 入库：`dump-messages` 遇到已存在的消息不会更新

- 记录：2026-09-28（整理 CLAUDE.md 时对照代码发现；`tmp/verify_save_message_update.py` 已复现）
- `db.save_message()` 的更新分支调用的是 `message.update()`，只构造了查询没有执行，还会向标准输出打印一行 `update message ...`。同一条消息第二次保存后库里仍是旧内容。
- 影响 `dump-messages`（`save_messages_batch`）；`sync` 和 `TelegramService` 走 `save_message_smart`，不受影响。
- 处理方向：让 `save_message` 复用 `save_message_smart`，或删掉这条旧路径。

## 同步：从未编辑过的消息，统计数不会刷新，评论可能每次都重取

- 记录：2026-09-28（读代码得出，未实测）
- `save_message_smart` 只在编辑时间变化时重写行，所以没编辑过的消息其浏览数、转发数、回复数停留在首次入库时的值。
- `sync` 靠「回复数与库里不同」决定是否取评论；库里的回复数不更新，回复数变过的消息在刷新窗口内每次同步都会重新取一遍评论。
- 处理方向：统计列单独更新，不受编辑时间判定约束。

## 评论：取评论时的异常被静默吞掉

- 记录：2026-09-28（读代码得出）
- `TelegramClient.get_comments()` 里两处 `except Exception` 直接 return / break，限流或权限错误表现为「这条消息没有评论」，同步结果里看不出失败。也不符合项目「底层函数只抛不接」的约定。

## 命令行：`--reset-db` 在数据库已经打开之后才删除文件

- 记录：2026-09-28（读代码得出，未实测）
- `cli()` 先 `db.init_db()` 再 `db.delete_db()`。推测后果：连接仍指向已被删除的文件，本次命令写入的数据在进程退出后丢失。
- 处理方向：先删文件再初始化。

## 查看器：每翻一页都联网取原始消息，且不显示链接预览

- 记录：2026-09-28（读代码得出）
- `MessageViewer.load_messages()` 仍向 Telegram 取原始消息来获得转发来源，而转发来源已经存在库里；因此查看器必须登录、离线不可用。
- 传给分组函数的行里没有 `webpage`、`media_width/height`、`fwd_*`，链接预览和媒体尺寸在查看器里拿不到。

## 命令行：提示文案里的 `dump` 命令不存在

- 记录：2026-09-28
- `viewer`、`search`、`dump-comments` 的提示和帮助里写的是 `telememo dump`，实际命令是 `dump-messages`。

## 配置：文档和示例里的环境变量方式并未实现

- 记录：2026-09-28
- `config.py` 的文档字符串称会回退到环境变量，实际只读 `~/.config/telememo/config.py`；`.env.example` 没有任何代码读取。
- 同属遗留：`CHANNELS` 配置项与 `list_channels()`、`get_session_path()`、`Config.db_path` / `Config.session_name` 均无人使用。

## 核心：`Scraper.__aexit__` 调用了两次 `stop()`

- 记录：2026-09-28
- 第二次因为连接标记已清而不生效，无实际影响，属笔误。

## 文档：README 的项目结构、开发指引链接、测试命令已过时

- 记录：2026-09-28
- Project Structure 只列了 5 个模块；Development Guidelines 链接指向不存在的 `claude.md`；测试命令是 `pytest tests/` 而不是 `uv run pytest`，也没提集成测试需要 `ALLOW_LOGIN=1`。
