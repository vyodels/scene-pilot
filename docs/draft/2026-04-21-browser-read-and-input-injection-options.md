# 浏览器页面读取与输入注入方案草稿

**状态**: 草稿  
**日期**: 2026-04-21  
**背景**: 基于本轮对 Chrome 扩展、`--remote-debugging-pipe`、`CGEventPostToPid`、macOS Accessibility API、OCR/截图路线的连续讨论，整理当前可行方案、风险点、优缺点与阶段性结论。

---

## 零、结论先行：两档推荐方案

### 目标约束

本次选型的硬约束有三条，缺一不可：

1. 所有输入事件 `isTrusted=true`（`mousemove` / `mousedown` / `mouseup` / `click` / 键盘）
2. **零**自动化/调试类属性暴露，包括但不限于：
   - `navigator.webdriver`
   - CDP domain 开启后的运行时侧信道差异
   - Chrome 调试器通知条
   - 扩展可枚举指纹（`web_accessible_resources`、content script 痕迹等）
3. 输入完全拟人：完整 `mousemove` 轨迹、`mouseenter` / `mouseover` 前摇、符合人类分布的时序节奏

这三条合起来直接排除：

- 所有 Chrome 扩展方案（content script 可被 DOM hook 检测；`chrome.debugger` 有通知条）
- 裸 CDP 输入（`navigator.webdriver` + CDP domain 侧信道）
- `AXPress`（跳过轨迹前摇，拟人度不足）
- 全局 `CGEventPost`（会移动系统光标）

剩下的合格候选只有：输入侧 `CGEventPostToPid` / 虚拟 HID 设备，读取侧 stealth CDP / AX 视觉混合 / 自定义 Chromium。

### 档位一：工程可落地的强拟人组合（近期）

适用场景：需要尽快上线、目标站点不是强定制反爬。

| 链路 | 方案 |
|---|---|
| 输入 | `CGEventPostToPid` + 拟人轨迹/节奏层 |
| 读取 | `--remote-debugging-pipe` + 严格 stealth 栈 |

**输入侧要点**：

- `CGEventPostToPid` 投递到浏览器进程事件队列，`isTrusted=true`、不动系统光标、零 driver/debug 暴露面
- `click` 前必须有 5–20 次 `mousemove`，走贝塞尔/手抖曲线，避免直线到达
- 事件间隔按人类节奏分布（hover 150–400ms、按键 50–150ms、`mousedown`–`mouseup` 间隔 50–120ms）
- 键盘用 `kCGEventKeyDown` / `kCGEventKeyUp` 带 `UnicodeString` 注入；IME 场景单独评估
- 先在 Chrome 活跃态下打通 `mousedown` / `mouseup` / `click` 完整链路，再谈真后台

**读取侧要点**：

- 只用 `DOMSnapshot.captureSnapshot` 一个读 API，不开 `Runtime.enable` / `Debugger.enable` / `Console.enable` 等会改变运行时行为的 domain
- 启动参数配合 `--disable-blink-features=AutomationControlled`
- 用 `Page.addScriptToEvaluateOnNewDocument` 在主文档加载前抹掉 `navigator.webdriver` 等已知指纹
- 所有自有 JS 跑在 isolated world，不污染主世界

**接受的边界**：

- 真后台（其他应用在前台）点击先不承诺
- 对通用反爬库（puppeteer-extra-stealth 覆盖集合）隐蔽性足够，但**无法数学证明**对定制反爬零泄漏
- stealth 栈需要持续跟进反爬迭代

### 档位二：架构上真正零暴露的组合（长期）

适用场景：长期承接强反爬站点（大厂招聘、风控敏感站点），需要架构上可证明不被检测。

| 链路 | 方案 |
|---|---|
| 输入 | DriverKit 虚拟 HID 设备（`IOHIDUserDevice`） |
| 读取 | 自定义 Chromium 私有读通道；过渡期用 AX 树 + 截图 + 视觉模型兜底 |

**输入侧要点**：

- 虚拟 HID 设备在内核 HID 层注入事件，浏览器眼中与真实硬件完全无法区分
- `isTrusted=true` 天然成立，无任何自动化协议痕迹
- 需要 Apple DriverKit entitlement，用户需在系统设置审批系统扩展
- 实现量级比定制 Chromium 轻，但比 `CGEventPostToPid` 重一档

**读取侧要点**：

- 定制 Chromium 源码新增私有读通道（走 mojo 暴露给 native），**不经过 CDP**
- `navigator.webdriver` 保持 `false`，不启用任何 CDP domain
- 页面侧从 JS 层无任何可观测差异
- 过渡期可用 macOS AX API + `CGWindowListCreateImage` + 视觉模型组合，读取完全发生在浏览器外，浏览器进程无自动化痕迹；代价是对 Canvas / 自绘控件 / 虚拟滚动语义不全

**投入量级**：两块都是 2–6 个月级投入，但之后不再陷入 stealth 猫鼠游戏。

### 推荐路径

- **输入侧直接规划走 DriverKit 虚拟 HID**：比定制 Chromium 轻得多，收益立刻兑现，且输入一旦走虚拟 HID，未来任何新的反自动化检测都天然免疫
- **读取侧先用 stealth CDP 过渡**，同时并行评估定制 Chromium 的可行性；AX + 视觉作为第二兜底
- `CGEventPostToPid` 与 stealth CDP 都属于"现在能用、会被反爬迭代持续蚕食"的资产，**投入无法沉淀**，因此只作为过渡方案，不作为长期主线

---

## 一、本文定位

本文只收敛当前讨论中已经明确的技术边界与选型判断。

本文不是正式规范，不覆盖 `docs/specs/` 下已确认的长期规则；后续如要沉淀为正式方案，需要再结合实际实现与验证结果收敛。

---

## 二、问题拆解

当前需求本质上分成两条能力链路：

1. **页面读取**
   - 尽量完整地拿到页面结构、布局、控件与坐标信息
   - 尽量不被页面 JS / 反爬脚本感知
   - 最好能还原出页面元素的像素级坐标语义

2. **输入注入**
   - 尽量以浏览器认可的“真实事件”方式注入点击/键盘
   - 尽量不抢系统鼠标
   - 尽量不抢焦
   - 最好 `isTrusted=true`
   - 最好页面 JS 无法识别这是自动化输入

这两条链路很难用一个方案同时完美覆盖，因此当前更合理的思路是：

- **读写分离**
- 页面读取和输入注入分别选最优通道

---

## 三、评估维度

后续方案统一按下面几个维度评估：

- 是否会被页面 JS 感知
- 是否能拿到完整页面结构
- 是否能拿到可还原布局/像素坐标的数据
- 是否需要控制 Chrome 启动参数
- 是否能接管用户已有 Chrome 实例
- 是否能产生 `isTrusted=true` 的输入事件
- 是否支持系统前台是别的应用时，Chrome 仍稳定收事件
- 是否有用户可见暴露面（通知条、权限、焦点切换等）

---

## 四、方案一：截图 / OCR / 文字坐标图

### 4.1 核心思路

通过截图拿页面图像，再通过 OCR / 版面分析提取文字、线条、区域坐标，形成类似“二维文本地图”的结构，再基于坐标做交互。

### 4.2 优点

- 读取侧不直接访问 DOM
- 对页面 JS 基本不可见
- 技术组件成熟，容易快速验证
  - `PaddleOCR`
  - `EasyOCR`
  - `Tesseract`
  - `LayoutParser`

### 4.3 缺点

这是一个很强的工程缺陷路线：

- 文字坐标不等于语义控件
- 相同文字在多个区域出现时，很难映射到正确业务目标
- 纯图标控件（关闭、下拉箭头、无文案按钮）难识别
- 动态渲染、虚拟滚动、懒加载区域容易丢失语义
- 最终仍需要额外策略把视觉区域和业务对象绑定起来

### 4.4 当前结论

**不适合作为主方案。**

可以作为截图兜底或辅助观测手段，但不适合作为主要页面理解与坐标来源。

---

## 五、方案二：Chrome 扩展 + Native Messaging

### 5.1 架构

```text
你的程序 ←→ Native Messaging Host ←→ Chrome Extension ←→ 页面 / 浏览器能力
```

### 5.2 这条路真正可拿到什么

要分几类看：

#### A. content script 直接读 DOM / `getBoundingClientRect`

优点：
- 能拿到完整 DOM
- 能拿到元素坐标
- 不需要控制 Chrome 启动参数
- 可接管用户已有 Chrome 实例

缺点：
- 页面 JS 可以 hook / proxy DOM 原型链与相关 API
- 批量读取 `querySelectorAll`、`getBoundingClientRect`、`getComputedStyle` 等行为可被检测

**结论**：
- 数据完整
- 但“不被页面 JS 感知”这一点不成立

#### B. `chrome.tabs.captureVisibleTab()`

优点：
- 页面 JS 不可感知
- 能拿到截图

缺点：
- 只有图像，没有结构化坐标语义
- 仍然会回到 OCR 路线的问题

#### C. `chrome.automation`

优点：
- 读取发生在页面 JS 之外
- 可拿到 AX 树
- 可拿到 role / name / location 等语义信息
- 页面 JS 无法直接识别“这是通过 AX API 读出来的”

缺点：
- AX 树覆盖不完整
- 对装饰元素、纯样式层、部分 Canvas/WebGL 区域支持弱
- 很难视为完整页面布局真相

**结论**：
- 适合作为语义辅助
- 不适合作为完整布局与像素坐标真相源

#### D. `chrome.debugger`

优点：
- 扩展内可直接调用 CDP 能力
- 可以拿到 `DOMSnapshot.captureSnapshot` 这一类完整布局数据
- 页面 JS 无法直接感知 CDP 读取本身

缺点：
- 必须声明 `debugger` 权限
- Chrome 会显示“调试器已连接”通知条
- 用户可见暴露面非常硬，无法隐藏

**结论**：
- 功能上强
- 但“隐蔽”目标不成立

### 5.3 `window.chrome.runtime` 暴露面

页面 JS 不能直接通过 `window.chrome.runtime` 看到：

- 扩展名称
- manifest 内容
- Native Messaging 通道
- 扩展内部逻辑

真正的风险点主要在：

1. **`web_accessible_resources`**
   - 如果声明了可访问资源，页面可通过探测 `chrome-extension://...` 资源判断扩展是否存在

2. **content script 改写 DOM**
   - 任何对页面 DOM 的写入、打标、插入节点、属性修改都可被页面观察到

3. **监听 `postMessage` 或引入可观测桥接**
   - 页面可以通过时序或消息通道差异间接判断扩展存在

### 5.4 Chrome 扩展方案的规避建议

如果只是把扩展作为辅助壳，至少要做到：

- 不声明 `web_accessible_resources`
- 不修改页面 DOM
- 不使用 `postMessage` 做桥接
- 不把扩展上架成公开可枚举形态
- content script 尽量只做最少工作

### 5.5 当前结论

**Chrome 扩展方案不能同时满足：**

- 完整像素坐标 / 完整布局恢复
- 页面 JS 不可感知

它可以满足其中一部分，但做不到两者兼得。

---

## 六、方案三：`--remote-debugging-pipe`（CDP 管道）

### 6.1 核心思路

Chrome 启动时带 `--remote-debugging-pipe`，你的程序通过管道而不是本地端口接入 CDP。

```text
你的程序 ←→ fd pipe ←→ Chrome 进程 ←→ 渲染引擎 / 页面
```

### 6.2 优点

- CDP 读取发生在浏览器引擎层，页面 JS 无法直接感知
- 不需要开放本地调试端口
- 可拿到完整 DOM / layout / snapshot / AX 等能力
- 可直接使用 `DOMSnapshot.captureSnapshot` 获取布局与坐标
- 非常适合作为“页面数据真相源”

### 6.3 关键价值

这是当前唯一明确满足下面组合的路线：

- **完整页面结构**
- **完整布局/像素坐标数据**
- **页面 JS 不可感知**

### 6.4 缺点

- 必须控制 Chrome 启动参数
- 不能直接接管用户已经打开的普通实例
- 如果要长期产品化，需要考虑浏览器实例管理与用户工作流整合

### 6.5 读数据能力结论

在“页面读取”这个维度上，当前结论很清晰：

**`--remote-debugging-pipe` 是最强、最干净、最直接的方案。**

### 6.6 写事件能力边界

CDP 虽然也可以注入输入事件，例如：

- `Input.dispatchMouseEvent`
- `Input.dispatchKeyEvent`

但这类事件的核心问题是：

- 页面可通过 `isTrusted` 等机制识别其为非真实用户输入
- 因此不适合作为“可信点击”主通道

### 6.7 当前结论

`--remote-debugging-pipe` 适合作为：

- **读页面数据的主通道**

不适合作为：

- **高可信点击/键盘输入的主通道**

---

## 七、方案四：macOS Accessibility API（AX API）

### 7.1 核心思路

使用 macOS 的辅助功能接口读取 UI 结构，或对目标元素执行 `AXPress` 等动作。

### 7.2 优点

- 页面 JS 无法直接感知“这是 AX API 操作”
- 适合读取可访问性树
- 适合对可访问元素做高层动作
- 在某些场景下，事件可表现为 `isTrusted=true`

### 7.3 缺点

- AX 树不是完整 DOM / layout 真相
- 对部分网页区域覆盖不完整
- 纯图形区域、复杂自定义控件、Canvas 区域经常不是完整可访问对象
- `AXPress` 更像高层语义动作，不等于完整鼠标轨迹

### 7.4 输入侧的核心问题

AX API 的点击更接近“直接触发元素动作”，而不是自然鼠标过程。

因此常见缺陷是：

- 没有完整 `mousemove` 轨迹
- 可能缺少 `mouseenter` / `mouseover` 前摇
- 高级反爬可通过轨迹缺失、时序异常等识别异常行为

### 7.5 当前结论

AX API 适合作为：

- 可访问树读取辅助
- 局部高层动作辅助

但不适合作为“完整页面布局真相源”，也不天然等于“完美拟人输入”。

---

## 八、方案五：`CGEventPostToPid`

### 8.1 核心思路

向目标浏览器进程直接投递鼠标/键盘事件，而不是走全局 HID 流。

```text
真实鼠标 → 系统 HID 流 → 前台窗口
虚拟输入 → CGEventPostToPid(browserPid) → 浏览器进程事件队列
```

这也是本轮讨论中最接近“独立虚拟鼠标/键盘”的思路。

### 8.2 理论优点

- 不移动系统光标
- 不直接干扰真实鼠标
- 不需要把输入走到全局桌面
- 如果浏览器接受事件，页面侧看到的是浏览器正常处理后的事件
- 在部分实验里，`mousemove` / `mouseenter` / `mouseover` 已经被页面接收到，且看到 `isTrusted=true`

### 8.3 当前实验结论

本轮已有的结论必须严格区分：

#### 已验证

- 并不是所有事件都要求页面 `focus`
- 至少在部分场景下，`mousemove` / `mouseenter` / `mouseover` 已被页面接收
- 这些事件里已经观察到：
  - `isTrusted=true`
  - 页面日志中 `hasFocus=false`

#### 未验证通过

- 当系统前台明确切到另一个应用、Chrome 进入“真后台”后，当前实验没有继续稳定把事件打进页面
- `mousedown` / `mouseup` / `click` 还没有形成稳定、可重复的成功结论

### 8.4 当前更准确的结论

不能把这条路表述成：

- “已经证明完全后台可用”
- 也不能表述成“已经证明必须聚焦”

当前更准确的说法是：

> `CGEventPostToPid` 目前只证明了：在某些非 DOM focus 场景下，事件有机会进入页面；但对“别的应用在前台时，Chrome 仍稳定收事件”这一完全后台场景，当前实验应先按未打通处理。

### 8.5 这条路的工程含义

如果目标是：

#### A. Chrome 当前仍是活跃应用 / 活跃窗口

这条路**仍有继续验证价值**：

- 可以继续尝试把 `mousedown` / `mouseup` / `click` 打通
- 这时它仍然可能成为“系统鼠标不动，但页面可收可信事件”的方案

#### B. 其他应用在前台，Chrome 完全后台自动点击

当前应先按：

- **不可用处理**

至少在本机当前实验结论里，不能把它当成已成立能力。

### 8.6 `CGEventPostToPid` 无法“抢焦”怎么办

`CGEventPostToPid` 的职责是：

- 向指定进程投递事件

它本身并不是前台激活 API，因此：

- 它不能替代“把 Chrome 切到前台”这件事
- 如果要让 Chrome 真的变成活跃应用，需要额外调用前台激活接口

例如同类能力通常要靠：

- `NSRunningApplication.activate(...)`
- `AXRaise`
- AppleScript `activate`
- 其它窗口管理 / 进程激活手段

但一旦这么做，代价也很明确：

- Chrome 会被带到前台
- “完全后台、不抢焦”的目标就不成立了

所以这里没有一个“既不抢焦、又靠 `CGEventPostToPid` 主动抢焦”的兼得解。

### 8.7 当前结论

`CGEventPostToPid` 当前最合理的定位是：

- **候选写入方案**
- 但只在“Chrome 仍保持某种活跃态”的条件下有继续验证价值
- 对“真后台点击”不能先假设可用

---

## 九、方案六：自定义 Chromium

### 9.1 核心思路

基于 Chromium 源码定制浏览器，在浏览器内核层直接暴露需要的读取能力、输入能力或自动化接口。

### 9.2 优点

- 天花板最高
- 可以从根上控制暴露面
- 可以不依赖扩展、`debugger` 权限或公开调试通道
- 从长期产品角度最接近完全可控

### 9.3 缺点

- 工程成本极高
- 首次编译、持续跟进、版本维护都很重
- 不适合作为当前阶段的快速验证路线

### 9.4 当前结论

这是长期路线，不适合作为当前阶段主线验证方案。

---

## 十、方案对比总表

| 方案 | 页面 JS 可感知性 | 页面数据完整性 | 像素/布局坐标 | 可接管已有 Chrome | `isTrusted` 输入潜力 | 完全后台点击潜力 | 备注 |
|---|---|---:|---:|---:|---:|---:|---|
| 截图 + OCR | 低 | 低到中 | 弱 | 是 | 不涉及 | 不涉及 | 语义断层大 |
| 扩展 + content script | 高 | 高 | 高 | 是 | 不涉及 | 不涉及 | 读取行为可被 hook |
| 扩展 + `chrome.automation` | 低 | 中 | 中 | 是 | 中 | 弱 | AX 树不完整 |
| 扩展 + `chrome.debugger` | 低 | 高 | 高 | 是 | 不涉及 | 不涉及 | 有通知条和 `debugger` 权限 |
| `--remote-debugging-pipe` | 低 | 高 | 高 | 否 | 低 | 低 | 读数据最优 |
| AX API | 低 | 中 | 中 | 是 | 中到高 | 弱 | 更像高层语义动作 |
| `CGEventPostToPid` | 中到低（取决于场景） | 不涉及 | 不涉及 | 是 | 高潜力 | 当前未打通 | 写事件候选，但后台能力未证实 |
| 自定义 Chromium | 低 | 高 | 高 | 否（通常） | 高潜力 | 视实现 | 长期重投入 |

---

## 十一、当前阶段最稳的判断

### 11.1 如果目标是“读页面真相”

当前最优结论是：

- **主方案：`--remote-debugging-pipe`**

原因：

- 页面 JS 不可感知
- 能拿到完整 DOM / layout / snapshot / 坐标
- 是目前最接近“页面真相源”的方案

### 11.2 如果目标是“可信点击”

当前没有已经完全验证成功的完美方案。

更准确的口径是：

- **`CGEventPostToPid` 有继续验证价值，但不能先假设真后台可用**
- **AX API 可作为补充，但不是完整鼠标拟人路径**
- **CDP 输入不适合承担可信点击主通道**

### 11.3 如果目标是“又要完整读取，又要完全后台可信点击”

当前没有一条已经被证明可稳定成立的低成本方案。

在现阶段，最现实的系统级组合是：

- **读取：`--remote-debugging-pipe`**
- **写入：继续验证 `CGEventPostToPid` 在 Chrome 活跃态下的 click 链路**

同时必须接受当前边界：

- 真后台点击能力尚未证实
- 不能在设计上把它当作既成事实

---

## 十二、建议的后续验证顺序

### 12.1 第一优先级：固化读取主通道

先把下面链路作为稳定能力做实：

- `--remote-debugging-pipe`
- `DOMSnapshot.captureSnapshot`
- 抽取可还原页面坐标的数据结构

目标：

- 先把“页面真相读取”这件事彻底打稳

### 12.2 第二优先级：缩小写入不确定性

围绕 `CGEventPostToPid` 重点只验证一件事：

- Chrome 处于活跃态时，能否稳定打通：
  - `mousemove`
  - `mousedown`
  - `mouseup`
  - `click`

目标：

- 先确认它是否至少能在“Chrome 活跃、系统鼠标不动”的场景稳定可用

### 12.3 第三优先级：再判断是否值得追真后台点击

如果第二步都没稳定打通：

- 就不应继续把“完全后台自动点击”作为当前阶段主承诺

如果第二步稳定成立，再决定是否继续追：

- 真后台
- 其它应用前台时的输入投递
- 更高层的窗口激活 / 切换策略

---

## 十三、阶段性结论

当前可以先收口成一句话：

> 对页面读取，`--remote-debugging-pipe` 是目前最可行、最干净的主方案；对可信输入，`CGEventPostToPid` 仍值得继续验证，但对“Chrome 真后台点击”不能先假设成立，Chrome 扩展方案也无法同时满足“完整像素坐标”和“页面 JS 不可感知”这两个条件。
