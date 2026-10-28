# Keybound Brawler Auto Typer · FF14 × FF7 联动打字游戏自动打字

[English](README.md) | **中文**

FF14（Final Fantasy XIV）× FF7 重制版系列联动活动 **Keybound Brawler** 的自动打字脚本：截屏 → 识别怪物头上的单词 → 自动打字并回车。

> ⚠️ **免责声明**：使用第三方工具自动操作游戏违反 Square Enix 的用户协议，可能导致账号被处罚。本项目仅供学习 OCR / 屏幕自动化技术，使用风险自负。

## 关于这个活动

| | |
|---|---|
| 活动名称 | Keybound Brawler（打字游戏，首期联动 FINAL FANTASY VII REMAKE 系列） |
| 开始时间 | 2026 年 10 月 28 日 |
| 持续时间 | 到资料片 *Evercold* 上线（预计 2027 年 1 月），之后不定期复刻 |
| 地点 | 金碟游乐场新区域 Keybound Square |
| 玩法 | 4 人小队，输入怪物头上的单词攻击敌人，一波一波推进，最后打 Boss（如 Airbuster） |
| 条件 | 15 级以上，已解锁金碟游乐场，完成限时任务 "Keyward Bound"；**必须用键盘** |
| 奖励 | 用 MGC 兑换：蒂法 / 巴雷特（Avalanche）时装、Avalanche 加特林时尚配饰、魔导蝎子坐骑、小巴雷特宠物、/magitype 情感动作、乐谱、肖像框等 |

同一联动的大头是 *Evercold* 里两边开发组合作的 8 人raid系列 *Beyond the Lifestream*。

资料来源：[FFXIV Console Games Wiki](https://ffxiv.consolegameswiki.com/wiki/Keybound_Brawler)、[Nova Crystallis](https://novacrystallis.com/2026/10/keybound-brawler-event-arrives-in-final-fantasy-xiv-on-october-28-featuring-the-final-fantasy-vii-remake-series/)、[MMOHuts](https://mmohuts.com/news/final-fantasy-xiv-adds-a-typing-event-with-final-fantasy-vii-remake-rewards-on-october-28)

## 功能

- **按框的颜色决定顺序**：红 / 金 / 绿框优先，然后蓝框；同色先打离你最近（最靠下）的。灰框、直接写在背景上的字（Boss 技能名、红字提示横幅等）不打
- **禁止打字标志**：出现红色禁止标志 3 秒后停手，消失 3 秒后继续（打到一半也会停住，之后接着打）
- **I / l 分不清**：整句第一个字母先试 `i`，其他位置先试 `l`；没打掉就自动换拼法再试，这类词排在其他词后面打
- 空格、标点都会打；大小写无所谓，统一按小写打
- 只识别屏幕中间区域，忽略 HP、分数、聊天头像、玩家名和输入框

## 使用

### 方式一：直接用 exe（不用装 Python）

去 [Releases](../../releases) 下载 `typer_bot.exe`，双击运行，3 秒内切回游戏。

### 方式二：用 Python 运行

需要 Windows + Python 3.9 ~ 3.12。

```bash
python -m pip install -r requirements.txt
python typer_bot.py
```

### 热键

- **F8** 暂停 / 继续
- **F9** 退出

### 注意

- 游戏要**全屏**并且在**主显示器**上（识别区域按屏幕比例算）
- 游戏如果是管理员身份运行，脚本 / exe 也要用管理员身份运行，不然打不进字
- 打包的 exe 可能被杀毒软件误报

## 调试

截一张整屏图，然后：

```bash
python typer_bot.py --test 截图.png
```

会打印识别到的词、颜色和是否有禁止标志，并生成 `debug.png`（绿框 = 识别区域，红框 = 忽略的输入框）。

常用设置都在 `typer_bot.py` 顶部：

| 设置 | 作用 |
|---|---|
| `REGION` | 识别区域（左, 上, 右, 下，占屏幕比例） |
| `IGNORE_BANDS` | 识别区里挖掉的横条（输入框） |
| `BEFORE_TYPE` / `KEY_DELAY` / `SHIFT_DELAY` | 打字速度，游戏卡字就调大 |
| `SIGN_DELAY` / `SIGN_WAIT` | 禁止标志出现后多久停手 / 消失后多久恢复 |
| `MONITOR` | 第几个显示器 |

## 打包 exe

```bash
python -m pip install pyinstaller
python -m PyInstaller --onefile --console --name typer_bot --collect-all rapidocr_onnxruntime --collect-binaries onnxruntime typer_bot.py
```

建议在只装了 `requirements.txt` 的干净虚拟环境里打包，否则 exe 会把电脑上其他大库一起打进去。

## 原理

1. [mss](https://github.com/BoboTiG/python-mss) 截屏
2. [RapidOCR](https://github.com/RapidAI/RapidOCR)（ONNX Runtime）识别文字
3. 取文字外面一圈的颜色判断框的颜色，OpenCV 轮廓检测找禁止标志
4. Windows `SendInput` 按扫描码发送按键（DirectX 游戏也能收到）
