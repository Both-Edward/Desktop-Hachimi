# Desktop Hachimi 🐾

<div align="center">
    <img src="/ico/Desktop Hachimi ico.ico" width="150" height="150" />
</div>

**VERSION**: 1.0.0  

---

## 安装依赖

```bash
pip install Pillow pystray
```

> **注意**：需要 Python 3.8+

---

## 运行

```bash
python main.py
```

---

## 目录结构

```
Desktop-Hachimi/
├── main.py
├── requirements.txt
├── config.json          ← 自动生成，保存用户设置
├── ico/
│   └── Desktop Hachimi ico.ico   ← 软件图标（需自行放置）
└── Pets/
    └── Ameath/          ← 默认桌宠文件夹（需自行放置gif/ico）
        ├── Ameath.ico   ← 桌宠图标
        ├── Ameath.gif   ← 动感状态
        ├── drag.gif     ← 拖拽状态
        ├── idle.gif     ← 非移动状态（单图）
        │   或 idle1.gif, idle2.gif ...
        ├── move.gif     ← 移动状态（单图）
        │   或 move1.gif, move2.gif ...
        ├── weights.json ← 状态权重
        └── flip.json    ← 运动方向反转配置（可选）
```

---

## weights.json 格式示例

```json
{
  "dynamic_weight": 3,
  "idle_weight": [2],
  "move_weight": [1]
}
```

若有多个 idle/move，则 weight 数组长度对应文件数量：

```json
{
  "dynamic_weight": 3,
  "idle_weight": [2, 3],
  "move_weight": [1, 2, 1]
}
```

---

## flip.json 格式示例

```json
{
  "move": {
    "enabled": true,
    "default_dir": "left"
  },
  "move2": {
    "enabled": true,
    "default_dir": "right"
  }
}
```

`default_dir` 为 `"left"` 时：向左运动不翻转，向右运动翻转图片。

---

## 系统托盘菜单说明

右键任务栏托盘图标，可以：

| 菜单项 | 功能 |
|--------|------|
| 切换桌宠 | 在 Pets/ 下的所有桌宠中选择 |
| 桌宠大小 | x0.1 ~ x2.0，步进 0.1 |
| 透明度 | 10% ~ 100%，步进 10% |
| 速度 | 1 ~ 10 档 |
| 鼠标跟随 | 开启后桌宠跟随鼠标移动 |
| 最上层显示 | 桌宠显示在所有窗口最前 |
| 创建桌宠 | 打开创建向导 |
| 关于 | 软件信息与更新 |
| 退出 | 关闭程序 |

---

## 未来适配计划

- [ ] LLM Agent
- [ ] TTS Agent
- [ ] Linux (GTK tray)
- [ ] macOS (rumps / AppKit tray)

---

## 打包为 Windows 安装包（后续步骤）

1. 安装 PyInstaller：`pip install pyinstaller`
2. 打包：`pyinstaller --noconsole --onefile --icon="ico/Desktop Hachimi ico.ico" main.py`
3. 使用 Inno Setup 或 NSIS 将 dist/ 下的内容制作成安装程序
