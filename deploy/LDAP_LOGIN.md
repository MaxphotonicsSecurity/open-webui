# LDAP 用户没有邮箱时登录

LDAP 登录不再要求 AD/LDAP 用户填写 `mail` 属性。继续使用原来的域账号和密码登录即可，无需为员工创建真实邮箱，也无需修改 LDAP 邮箱属性配置。

- 邮箱属性缺失、空字符串、空列表或只有空白字符时，系统生成 `<身份摘要>@ldap.invalid` 作为内部账号地址。这不是可收信邮箱，不会写回 AD。
- 用户仍必须通过 LDAP 搜索、用户名匹配及密码绑定验证；空密码、错误密码及已停用的应用账号仍不能登录。默认角色和分组逻辑保持原有规则。
- 系统在现有用户外部身份字段中记录 LDAP 身份，不需要数据库结构迁移。重复登录、用户名大小写变化，以及之后补填或移除 LDAP 邮箱，均复用已关联账号及其聊天记录。
- 已有真实邮箱账号会在一次成功的 LDAP 登录后建立关联。对于尚未建立关联、邮箱就已经从 AD 删除的旧账号，需要先恢复原邮箱并成功登录一次，再移除邮箱，才能保留原账号关联。
- 占位地址不会自动替换成后补填的真实邮箱。它仅用于应用内部识别账号；用户继续用域账号登录。
- 身份摘要根据 LDAP 返回的完整用户 DN（忽略大小写）生成。移动用户 OU 或修改 CN 导致 DN 改变时，需要管理员迁移已有的 LDAP 身份关联；不要把这种目录迁移视为同一身份的自动合并。
- 若内部占位地址已被无关联的账号占用，或真实邮箱已经关联另一个 LDAP 身份，登录会被拒绝，避免错误合并账号。

## 部署

本次修改在后端源码中，需要将修改同步到服务器并重新构建应用镜像；只重启旧镜像不会生效。在生产服务器仓库根目录执行：

```bash
bash deploy/prod/deploy.sh
```

部署后用一个无 `mail` 属性的测试域账号登录，确认再次登录仍进入同一个账号。若日志是 `User not found in the LDAP server`，则需另行检查用户名、搜索基准和过滤条件，该错误与邮箱是否存在无关。

## 回归测试

在已安装后端依赖的环境中执行。测试使用 ldap3 内存目录和 SQLite 内存数据库，不连接实际 AD 或生产数据库。

```bash
LDAP_TEST_DATA_DIR=$(mktemp -d)
WEBUI_SECRET_KEY=ldap-regression-test-secret-at-least-32-bytes \
  ENABLE_DB_MIGRATIONS=false OFFLINE_MODE=true VECTOR_DB=none \
  DATA_DIR="$LDAP_TEST_DATA_DIR" DATABASE_URL="sqlite:///$LDAP_TEST_DATA_DIR/webui.db" \
  PYTHONPATH=backend python -m unittest discover -s backend/tests -p 'test_ldap_auth.py' -v
```
