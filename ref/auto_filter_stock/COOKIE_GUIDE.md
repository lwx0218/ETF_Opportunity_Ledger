# 🍪 同花顺问财 Cookie 获取指南

## 📋 概述

本系统需要同花顺问财的Cookie来获取成交额和热度数据。本指南将详细说明如何获取Cookie。

**Cookie来源**: [同花顺问财](https://www.iwencai.com/unifiedwap/home/index)

---

## 🎯 方法一：使用 Cookie-Editor 插件（推荐）

### 步骤 1: 安装 Cookie-Editor 插件

#### Chrome / Edge 浏览器：
1. 访问 Chrome 网上应用店
2. 搜索 "Cookie-Editor"
3. 点击"添加至Chrome"（或"添加至Edge"）
4. 确认安装

#### Firefox 浏览器：
1. 访问 Firefox 附加组件商店
2. 搜索 "Cookie-Editor"
3. 点击"添加到Firefox"
4. 确认安装

**插件图标**：安装成功后，浏览器工具栏会出现一个饼干🍪图标

### 步骤 2: 访问同花顺问财

打开浏览器，访问：
```
https://www.iwencai.com/unifiedwap/home/index
```

### 步骤 3: 登录账号

1. 点击页面右上角的"登录"按钮
2. 使用以下任一方式登录：
   - 手机号 + 验证码
   - 微信扫码
   - 支付宝扫码
3. 登录成功后，确保页面显示您的用户名

⚠️ **重要**: 必须登录后才能获取有效的Cookie

### 步骤 4: 使用 Cookie-Editor 导出Cookie

1. **点击浏览器工具栏的 Cookie-Editor 图标**（饼干🍪）
   - 会弹出Cookie编辑器窗口
   - 显示当前网站的所有Cookie

2. **点击"Export"（导出）按钮**
   - 通常在窗口右上角或底部
   - 图标可能是 📋 或显示为文字"Export"

3. **选择导出格式**
   - 选择 "Header String" 或 "Netscape" 格式
   - 推荐选择 "Header String"，这样可以直接复制完整的Cookie字符串

4. **复制Cookie字符串**
   - Cookie会自动复制到剪贴板
   - 或手动选中全部内容后复制（Ctrl+A, Ctrl+C / Cmd+A, Cmd+C）

### 步骤 5: 配置到系统

将复制的Cookie字符串配置到 `.env` 文件：

```env
PYWENCAI_COOKIE=v=Ax12345678901234567890...（复制的完整Cookie字符串）
```

**示例Cookie格式**：
```
v=Ax12345678901234567890; s=123456789; other_cookie=value; ...
```

---

## 🎯 方法二：使用浏览器开发者工具

### Chrome / Edge 浏览器

#### 步骤 1: 访问并登录
1. 访问 https://www.iwencai.com/unifiedwap/home/index
2. 登录您的账号

#### 步骤 2: 打开开发者工具
- **Windows**: 按 `F12` 或 `Ctrl + Shift + I`
- **Mac**: 按 `Cmd + Option + I`

#### 步骤 3: 切换到 Application 标签
1. 在开发者工具顶部找到 "Application" 标签
2. 如果没有看到，点击 ">>" 符号查找

#### 步骤 4: 查看 Cookies
1. 在左侧菜单展开 "Storage" → "Cookies"
2. 点击 `https://www.iwencai.com`
3. 右侧会显示所有Cookie

#### 步骤 5: 复制 Cookie
有两种方式：

**方式1 - 复制完整Cookie字符串**：
1. 在 "Console" 标签页执行以下代码：
```javascript
document.cookie
```
2. 复制输出的完整Cookie字符串

**方式2 - 手动拼接**：
1. 找到关键Cookie（如 `v`、`s` 等）
2. 按照格式拼接：`name1=value1; name2=value2; ...`

### Firefox 浏览器

#### 步骤 1-2: 同上

#### 步骤 3: 切换到存储标签
1. 在开发者工具顶部找到 "存储" 或 "Storage" 标签

#### 步骤 4-5: 同Chrome操作

---

## 🎯 方法三：使用 setup_cookie.sh 脚本（Mac/Linux）

如果您在Mac或Linux系统上，可以使用我们提供的脚本：

```bash
bash setup_cookie.sh
```

按照脚本提示：
1. 访问问财网站并登录
2. 使用上述任一方法获取Cookie
3. 粘贴到脚本提示中
4. 脚本会自动配置到 `.env` 文件

---

## 📝 完整Cookie示例

正确的Cookie格式应该类似：

```
v=Ax1234567890abcdef; s=1234567890; tfstk=c1234567890; websitepoptg_api_time=1234567890; other_cookie=value
```

特点：
- 多个Cookie用 `;` 分隔
- 每个Cookie格式为 `名称=值`
- Cookie之间有空格（可选）
- 通常包含几十到上百个字符

---

## ✅ 验证Cookie是否有效

### 方法1: 启动系统查看日志

启动系统后查看日志：

```bash
# Mac
bash start_server.sh

# Windows
start_server.bat
```

**成功的日志**：
```
INFO: Pywencai cookie loaded successfully ✅
INFO: Akshare data source initialized successfully ✅
```

**失败的日志**：
```
ERROR: Pywencai cookie not found! ❌
```

### 方法2: 访问健康检查接口

启动系统后访问：
```
http://localhost:8000/api/v1/health/
```

查看 `cookie_status` 部分：
```json
{
  "cookie_status": {
    "has_env_cookie": true,     ← 应该为 true
    "has_cached_cookie": false,
    "cache_expired": false,
    "cache_file_exists": false
  }
}
```

---

## ⚠️ 常见问题

### Q1: Cookie多长时间会失效？

**A**: 通常7-30天，取决于同花顺的策略。失效后需要重新获取。

### Q2: 为什么我复制的Cookie不起作用？

**A**: 可能的原因：
1. **未登录** - 必须先登录问财网站
2. **复制不完整** - 确保复制了完整的Cookie字符串
3. **格式错误** - Cookie应该是纯文本，不包含引号或其他字符
4. **Cookie已失效** - 重新登录后获取新Cookie

### Q3: Cookie包含个人隐私信息吗？

**A**: Cookie不包含密码等敏感信息，但建议：
- 不要分享给他人
- 定期更新Cookie
- 只在本地使用

### Q4: 可以使用多个账号的Cookie吗？

**A**: 只能使用一个Cookie。如需切换账号，重新获取新Cookie即可。

### Q5: Cookie-Editor 显示的Cookie太多怎么办？

**A**: 
- 使用 "Export" 功能，选择 "Header String" 格式
- 这会自动导出正确格式的完整Cookie字符串
- 直接复制整个导出的内容即可

---

## 🔐 安全建议

1. **不要公开分享Cookie**
   - Cookie相当于临时登录凭证
   - 他人获取后可能访问您的账号

2. **定期更新Cookie**
   - 建议每月重新获取一次
   - 发现异常时立即更新

3. **使用独立账号**
   - 如可能，为系统创建专用的问财账号
   - 不要使用主要账号

4. **安全存储**
   - `.env` 文件不要提交到Git
   - 不要截图包含Cookie的内容

---

## 🎬 快速操作流程

### 使用 Cookie-Editor（推荐）

```
1. 安装 Cookie-Editor 插件 🍪
   ↓
2. 访问并登录问财网站
   https://www.iwencai.com/unifiedwap/home/index
   ↓
3. 点击 Cookie-Editor 图标
   ↓
4. 点击 "Export" → 选择 "Header String"
   ↓
5. Cookie自动复制到剪贴板 ✅
   ↓
6. 粘贴到 .env 文件的 PYWENCAI_COOKIE=
   ↓
7. 保存文件，启动系统 🚀
```

### 使用开发者工具

```
1. 访问并登录问财网站
   ↓
2. 按 F12 打开开发者工具
   ↓
3. Application → Cookies → iwencai.com
   ↓
4. 在 Console 执行: document.cookie
   ↓
5. 复制输出的Cookie字符串
   ↓
6. 粘贴到 .env 文件
   ↓
7. 启动系统 🚀
```

---

## 📞 需要帮助？

如果按照本指南操作后仍然无法获取Cookie：

1. **查看系统日志**: `logs/stock_screening.log`
2. **检查Cookie格式**: 确保是纯文本，包含多个键值对
3. **重新登录**: 退出问财账号，重新登录后再获取
4. **尝试不同浏览器**: Chrome、Edge、Firefox等

---

## 🎉 配置成功！

配置成功后，您会看到：

```
✅ Pywencai cookie loaded successfully
✅ Akshare data source initialized successfully
✅ Application services initialized successfully
```

现在可以访问 http://localhost:8000 开始使用系统了！

---

**最后更新**: 2025-10-12  
**适用版本**: 2.0.0

