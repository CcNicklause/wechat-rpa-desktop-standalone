# 微信 RPA 图像模板

真实微信客户端在某些版本中只暴露顶层 Qt 窗口，UI Automation 无法读取“搜索框 / 添加朋友 / 发送”等子控件。此目录用于存放图像识别模板，作为 UI Automation 失败后的第二定位策略。

## 原则

- 不使用固定坐标。
- 模板来自当前微信客户端的真实截图。
- 每张模板只裁剪目标元素本身，周围少留 2~6px 边距。
- 尽量使用清晰、稳定的文字或按钮区域。
- 如果微信主题、缩放或版本变化明显，需要重新截取模板。

## 跨平台模板说明（v2）

从 v2 开始，系统通过 **视觉缓存自适应** + **OCR 自学习** 自动适配各平台
（Windows 10/11 与 macOS 12+）。

- 同一个模板文件（`.png`）同时适用于 Windows 与 macOS——模板匹配失败时，
  OCR 轨会采摘文字区域、SSIM 校验后写入 `templates_cache/`，无需人工干预。
- `templates_cache/` 按 `{窗口宽}x{窗口高}_{DPI}_{主题}` 分级存储，
  例如 `971x689_1.25_dark/menu_add_friends.png`。
- 首次冷启动（无缓存）依赖模板库中的默认 `.png` 文件；建议以下两种方式之一：
  1. **Windows**：按下方「截图方式」截取当前微信版本的各控件 PNG。
  2. **macOS**：直接运行 RPA——系统会自动从 OCR 命中结果创建缓存，
     无需手动截图。

## 推荐模板文件名

入口相关：

```text
wechat_add_button.png        微信顶部/列表区的“+”或添加按钮
wechat_plus_button.png       “+”按钮备选模板
wechat_toolbar_add.png       工具栏添加入口备选模板
menu_add_friends.png         弹出菜单里的“添加朋友”
add_friends_menu_item.png    “添加朋友”菜单项备选模板
```

搜索相关：

```text
add_friends_search_box.png   添加朋友页面的搜索输入框
wechat_search_box.png        搜索框备选模板
search_input.png             输入框备选模板
```

添加结果相关：

```text
add_to_contacts_button.png   “添加到通讯录”按钮
add_friend_button.png        “添加好友”按钮
add_contact_button.png       添加按钮备选模板
```

验证消息相关：

```text
verify_message_input.png     验证语输入框
friend_verify_input.png      验证语输入区域备选模板
send_button.png              “发送”按钮
confirm_button.png           “确定”按钮
verify_confirm_button.png    确认按钮备选模板
```

## 截图方式

1. 打开微信到对应界面。
2. 使用截图工具只截取目标按钮/输入框本身。
3. 保存为上面的文件名。
4. 重启后端。
5. 再执行真实 RPA。

如果模板缺失或匹配失败，任务会返回 `VISION_TARGET_NOT_FOUND`，并提示缺少或未匹配的模板名。
