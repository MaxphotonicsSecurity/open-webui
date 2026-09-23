# 企业 Chatbot 界面定制

## 交付范围

- 左上角和浏览器标题统一为 `MAX chatbot`，前端品牌不再被接口返回的旧 `Open WebUI` 名称覆盖。
- 使用用户提供的 `chatbot.svg`（Sky 玻璃质感对话图标）。`static/static/favicon.svg` 保留原始矢量内容及 Tabler MIT 来源标记；PNG、ICO、启动图、PWA 图标均由它生成。用户头像和模型专属头像不替换。
- LDAP 登录页按 ai-MaaS 的源码移植，保留低调的「管理员入口」邮箱登录。邮箱入口仍遵守后端 `enable_login_form` 配置。
- 底部文案为「认证遇到问题时，请联系集团信息安全部」，下一行为「颜明豪-MX19965 · 吴明东-MX19968」。
- 删除两种聊天起始页的建议，以及所有角色的「关于」、更新检查、更新提醒和更新日志弹窗。旧 `?settings=about` 链接回到「通用」，旧显示偏好不再起作用；弹窗组件及前端请求方法一并移除。

## MaaS 对齐依据

只读取参考项目，不修改 ai-MaaS：

- `apps/portal-web/src/features/auth/LoginPage.vue`：布局、背景、玻璃材质、表单、响应式规则和记住功能生命周期。
- `apps/portal-web/src/design-system/tokens.css`：字体栈、14px 基础字号、140ms 交互过渡和焦点颜色。

桌面卡片为 784 × 520px，等宽双栏；圆角 30px（紧凑窗口 26px），左栏内边距 30px 32px 28px，右栏 26px 30px 22px。主色 `#175cff`、悬停色 `#0b4be0`，完整保留背景渐变与三层模糊光斑。字体栈为 Inter、PingFang SC、Microsoft YaHei、system-ui、-apple-system、sans-serif，无远程字体请求。

820px 以下转为上下布局，520px 以下铺满视口。与 MaaS 的有意差异仅为 Chatbot 品牌/定位文案、提供的图标、管理员邮箱入口和既有 OAuth/自定义页脚兼容。极矮窗口或软键盘展开时允许表单内部滚动，避免操作被裁切。

Open WebUI 自带 Inter 字体文件，而 MaaS 没有。因此登录页通过仅引用系统 Inter 的 `MaaS Inter` 别名保留 MaaS 的字体回退行为，避免同名字体产生不同文字高度；聊天界面不受影响。复选框也恢复 MaaS 保留的浏览器原生外边距，不受 Tailwind 重置影响。

## 记住账号密码

完全由前端实现，不修改 LDAP、邮箱认证或后端数据库：

1. 默认不勾选。勾选后，只有现有认证接口返回成功才写入本地存储。
2. 再次进入登录页时自动读取并填入，密码默认隐藏；不自动提交。
3. 取消勾选立即删除当前认证方式的记录。登录失败不写入新记录。
4. 提交结束、页面隐藏、离开页面时清空输入框中的密码并恢复隐藏；成功保存的记录不会因此删除，与 MaaS 一致。
5. LDAP 和管理员邮箱使用两个独立键，不读取 MaaS 的记录：
   - `max-chatbot.auth.remembered-credentials.ldap.v1`
   - `max-chatbot.auth.remembered-credentials.signin.v1`
6. JSON 格式错误、账号控制字符/超长、密码为空/超长时删除无效记录。存储被禁用或配额不足时不阻断认证。

按用户要求，与 MaaS 一样保存 `{ account, domainPassword }` 到当前站点的 localStorage；这是明文浏览器持久存储，不是密码保险库。仅在受信任的个人设备上勾选。正常认证请求仍会将密码发送给现有登录接口，新增的「记住」逻辑不会额外上传密码。

## 资源、构建与上线

`static/static/` 是前端构建来源，后端启动时复制构建内的静态资源。`backend/open_webui/static/` 同步维护同名图标；`static/favicon.png` 覆盖默认回退图。侧栏和浏览器图标使用 `max-chatbot-2` 缓存版本。

```sh
npm ci
node scripts/generate-enterprise-icons.mjs static/static/favicon.svg
NODE_OPTIONS=--max-old-space-size=8192 npm run build
npm run test:frontend -- --run
```

保留项目 LICENSE 和版权文件。不需要认证数据库迁移。2026-09-22 已应用户要求部署至本机 Docker local 环境（http://localhost:3000）；test、prod 未改动，代码未提交或推送。部署与回滚信息见 [本地部署记录](local-deployment-2026-09-22.md)。

前端已不调用 `/api/version/updates` 或 `/api/changelog`。如果还要禁止独立客户端直接调用后端版本检查接口，可沿用部署配置 `ENABLE_VERSION_UPDATE_CHECK=false`；没有修改后端接口。

## 验证范围

单元测试覆盖记住、读取、取消、认证方式隔离、无效数据和存储异常；Chrome 使用模拟接口测试 LDAP/邮箱登录、校验、显隐、状态切换、失败重试、重复提交、记住与清除、移动布局、深色主题、会话建立、建议移除、「关于」旧链接和更新请求禁用。

本次验证：29 项前端单元测试通过，生产构建通过，10 组构建图标与源资源逐一相同。Chrome 源码对照验证了 13 处关键元素的尺寸、字体和材质，且在 390 × 320 等矮窗口中仍能访问登录和管理员入口。企业登录组件严格设计审计无发现。

以上浏览器回归同时在开发服务和生产构建预览中通过，包含旧偏好开启更新日志/更新通知的场景。删除的旧弹窗与提醒组件为 Git 跟踪文件，可从版本历史恢复。

仓库完整类型检查仍因大量既有错误未通过；新登录组件、认证页面和存储工具没有类型错误。真实 LDAP 服务、生产账号和线上部署没有参与测试。
