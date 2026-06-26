# Stock JSON Clipper V3.1

A股数据与AI分析之间的桥梁。输入股票代码，获取完整技术数据、SVG图表和AI分析提示词。

## 下载

从 [Releases](https://github.com/ABLingss/Stock-JSON-Clipper/releases) 下载：

- **Windows 10/11**: `StockJSONClipper.exe`（绿色免安装）
- **Linux**: 从源码运行

## 功能

### 数据查询
输入代码查询，支持 A股 / 港股。数据源 stock-api 自动灾备（腾讯→新浪→东财）。

### SVG 技术图表
- K线 + 成交量 + MACD + RSI 统一画布
- MACD/RSI 可选开关
- 鼠标任意 X 轴位置悬停显示完整数据
- 点击图表弹出大图

### 多股对比
点 **+** 添加多只股票，并排对比 MA/MACD/RSI/涨跌幅等指标，每只独立图表。

### AI 分析
- **AI分析**: 填了公式就分析公式，没填就快速技术分析
- **深度分析**: 完整K线数据 + 6维度分析框架
- 对比模式自动生成多股排序提示词

### 数据格式
| 输入 | 含义 |
|------|------|
| `000001` | 深市平安银行 |
| `600036` | 沪市 |
| `SH600519` | stock-api 格式（推荐） |
| `HK00700` | 港股腾讯 |

周期：1分/5分/15分/30分/60分/日/周/月

## 从源码运行

```bash
git clone https://github.com/ABLingss/Stock-JSON-Clipper.git
cd Stock-JSON-Clipper
pip install pyperclip pystray pywebview requests Pillow
python main.py
```

## 项目结构

```
main.py              入口
core/                配置、缓存、模块注册、日志
data/                技术指标计算、JSON构建
ui/                  pystray托盘 + WebView面板
modules/prompt/      AI提示词生成
```

## License

GPL-3.0 — 集成了 [stock-api](https://github.com/zhangxiangliang/stock-api) (MIT) 和 [RollerCoaster](https://github.com/YQBaobao/RollerCoaster) (GPL-3.0)。
