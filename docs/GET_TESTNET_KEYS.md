# Canopy Testnet 密钥获取指南

> 本文档指引你从 Binance Testnet 获取 API 密钥，并安全存入 Canopy Vault。

---

## 前置条件

- 已安装 Canopy v0.2+
- 拥有 GitHub / Google 账户（用于注册 Binance）

---

## 第一步：注册 Binance Testnet

1. 打开浏览器访问 **[testnet.binance.vision](https://testnet.binance.vision)**
2. 点击右上角 **Register / 注册**
3. 选择 **GitHub** 或 **Google** 快捷登录（推荐 GitHub）
4. 授权后自动完成注册，无需填写个人信息

> ![注册页面截图占位](screenshots/testnet_register.png)

---

## 第二步：创建 API Key

1. 登录后进入 **[API Management](https://testnet.binance.vision/en/api/manage)**
2. 点击 **Create API** 按钮
3. 输入 API Key 标签（如 `Canopy v0.2`）
4. **安全提示**：
   - ✅ 勾选 **Enable Futures**（Canopy 需要合约交易权限）
   - ❌ 不要勾选 **Enable Withdrawals**（提现权限有风险）
   - 如果不需要现货交易，可以不勾选 **Enable Spot & Margin Trading**
5. 完成 2FA 验证（邮箱验证码 or Google Authenticator）
6. 系统生成 **API Key** 和 **Secret Key**

> ![API 创建页面截图占位](screenshots/testnet_create_api.png)

---

## 第三步：保存密钥（仅一次机会）

> ⚠️ **Secret Key 仅显示一次！** 请立即复制保存，关闭页面后无法找回。如丢失只能删除重建。

| 字段 | 示例值（脱敏） | 长度 |
|------|---------------|------|
| API Key | `abc123...xyz` | 64 字符 |
| Secret Key | `def456...uvw` | 64 字符 |

---

## 第四步：存入 Canopy Vault

### 方式一：命令行导入（推荐）

```bash
cd /Users/cccc/Desktop/canopy

# 创建 vault 目录
mkdir -p vault

# 写入 API Key（文件会自动 .gitignore）
echo "YOUR_API_KEY" > vault/binance_testnet_api_key.txt
echo "YOUR_SECRET_KEY" > vault/binance_testnet_secret_key.txt

# 设置权限（仅当前用户可读）
chmod 600 vault/binance_testnet_*.txt
```

### 方式二：环境变量导入

```bash
export CANOPY_BINANCE_API_KEY="YOUR_API_KEY"
export CANOPY_BINANCE_SECRET_KEY="YOUR_SECRET_KEY"

# 验证
python3 -c "import os; print('API Key loaded:', bool(os.getenv('CANOPY_BINANCE_API_KEY')))"
```

### 方式三：Canopy 内置 Vault（v0.2+）

```bash
python3 -m canopy.vault set binance_testnet \
  --api-key "YOUR_API_KEY" \
  --secret-key "YOUR_SECRET_KEY"
```

---

## 第五步：验证连接

```bash
# 测试 API 连接
python3 -m canopy.main --testnet --check-connection

# 预期输出
# [OK] Binance Testnet connected
# [OK] Futures trading enabled
# [OK] Account balance: 10000 USDT (testnet)
```

---

## 常见问题

| 问题 | 解决方案 |
|------|---------|
| API Key 无效 | 检查是否复制完整（64 字符），确认未过期 |
| 权限不足 | 回到 API Management 确认勾选了 "Enable Futures" |
| 连接超时 | 检查网络代理；testnet 域名可能需要科学上网 |
| Secret Key 丢失 | 删除旧 Key → 重新创建 → 更新 Canopy Vault |

---

## 安全提醒

- **不要**将 `vault/` 目录提交到 Git（已配置 `.gitignore`）
- **不要**在聊天记录、截图、录屏中暴露 Secret Key
- 定期更换 API Key（建议每 90 天）
- Testnet 密钥仅用于模拟交易，不涉及真实资产
