"""sample_data.py - 模拟用户输入测试数据生成器。

包含两类数据：
1. 合成数据（build_long_conversation 等）：用于精确触发特定压缩层
2. 真实代码开发场景数据（build_bug_fix_scenario 等）：模拟 Agent 解决实际开发问题的完整流程，
   含真实风格的 Python 代码、pytest 输出、git diff，面向真实使用场景测试。

真实场景覆盖：
- bug 修复（读测试 → 读源码 → 运行 → 定位 → 修复 → 重测）
- 代码 review（git diff → 读多文件 → 分析 → 建议）
- 功能实现（读结构 → 创建多文件 → 测试）
- 重构（glob 查找 → 读多文件 → 批量 edit）
- 长调试会话（组合多场景，100+ 轮）
"""
import types


# ═══════════════════════════════════════════════════════════
#  基础消息构造 helper
# ═══════════════════════════════════════════════════════════

def _text_block(text: str):
    """构造 assistant 文本 block。"""
    return types.SimpleNamespace(type="text", text=text)


def _tool_use_block(tool_id: str, name: str = "bash", **input_kwargs):
    """构造 assistant tool_use block，支持任意 input 参数。"""
    if not input_kwargs:
        input_kwargs = {"command": f"echo {tool_id}"}
    return types.SimpleNamespace(type="tool_use", id=tool_id, name=name, input=input_kwargs)


def user_text(content: str = "continue") -> dict:
    """构造纯文本 user 消息。"""
    return {"role": "user", "content": content}


def assistant_text(text: str = "ok") -> dict:
    """构造纯文本 assistant 消息（用 SimpleNamespace 模拟 SDK block）。"""
    return {"role": "assistant", "content": [_text_block(text)]}


def assistant_with_tools(text: str, tools: list) -> dict:
    """构造包含文本 + 多个 tool_use 的 assistant 消息。"""
    content = [_text_block(text)] + tools
    return {"role": "assistant", "content": content}


def tool_use_message(tool_id: str = "tool-1", name: str = "bash", **input_kwargs) -> dict:
    """构造包含单个 tool_use 的 assistant 消息。"""
    return {"role": "assistant", "content": [_tool_use_block(tool_id, name, **input_kwargs)]}


def tool_result_message(tool_id: str = "tool-1", content: str = "ok",
                        multi_block: bool = False):
    """构造包含 tool_result 的 user 消息。

    Args:
        multi_block: 为 True 时返回不带 role 的 block，用于拼接到单条 user 消息
    """
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": content}
    if multi_block:
        return block
    return {"role": "user", "content": [block]}


def tool_results_message(results: list) -> dict:
    """构造包含多个 tool_result block 的单条 user 消息（用于触发 L3 budget）。"""
    return {"role": "user", "content": results}


# ═══════════════════════════════════════════════════════════
#  真实代码内容片段（用作 tool_result）
# ═══════════════════════════════════════════════════════════

# 真实风格的测试文件内容
TEST_PARSER_PY = '''"""test_parser.py - 解析器单元测试。"""
import pytest
from src.parser import parse_user_input, parse_config, validate_input


class TestParseUserInput:
    """parse_user_input 测试套件。"""

    def test_parse_simple_key_value(self):
        """测试简单的 key=value 解析。"""
        result = parse_user_input("name=alice")
        assert result == {"name": "alice"}

    def test_parse_multiple_pairs(self):
        """测试多组键值对解析。"""
        result = parse_user_input("name=alice age=30 role=admin")
        assert result == {"name": "alice", "age": "30", "role": "admin"}

    def test_parse_empty_input(self):
        """测试空输入应返回空字典。"""
        assert parse_user_input("") == {}

    def test_parse_input_with_spaces(self):
        """测试含空格的值。"""
        result = parse_user_input('name=alice smith')
        assert result["name"] == "alice smith"

    def test_parse_invalid_input_raises(self):
        """测试非法输入应抛出 ValueError。"""
        with pytest.raises(ValueError):
            parse_user_input("=no_key")


class TestParseConfig:
    """parse_config 测试套件。"""

    def test_parse_yaml_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("host: localhost\\nport: 5432\\n")
        result = parse_config(str(config_file))
        assert result["host"] == "localhost"
        assert result["port"] == 5432
'''

# 真实风格的源码文件（含 bug）
BUGGY_PARSER_PY = '''"""src/parser.py - 用户输入与配置解析。"""
from pathlib import Path


def parse_user_input(text: str) -> dict:
    """解析用户输入的 key=value 字符串。

    Args:
        text: 形如 "name=alice age=30" 的输入

    Returns:
        键值对字典

    Raises:
        ValueError: 输入格式非法时
    """
    if not text:
        return {}
    result = {}
    for pair in text.split(" "):
        # BUG: 没有检查 pair 是否包含 "="
        key, value = pair.split("=")
        result[key] = value
    return result


def parse_config(path: str) -> dict:
    """解析 YAML 配置文件。

    Args:
        path: 配置文件路径

    Returns:
        配置字典
    """
    content = Path(path).read_text()
    result = {}
    for line in content.strip().splitlines():
        key, value = line.split(": ", 1)
        # 尝试转换为合适类型
        if value.isdigit():
            result[key] = int(value)
        else:
            result[key] = value
    return result


def validate_input(text: str) -> bool:
    """验证输入是否合法。"""
    if not text:
        return True
    for pair in text.split(" "):
        if "=" not in pair:
            return False
    return True
'''

# 修复后的源码
FIXED_PARSER_PY = '''"""src/parser.py - 用户输入与配置解析。"""
from pathlib import Path


def parse_user_input(text: str) -> dict:
    """解析用户输入的 key=value 字符串。

    Args:
        text: 形如 "name=alice age=30" 的输入

    Returns:
        键值对字典

    Raises:
        ValueError: 输入格式非法时
    """
    if not text:
        return {}
    result = {}
    for pair in text.split(" "):
        if "=" not in pair:
            raise ValueError(f"Invalid pair: {pair!r}")
        key, value = pair.split("=", 1)
        result[key] = value
    return result
'''

# 真实风格的 pytest 失败输出
PYTEST_FAIL_OUTPUT = '''============================= test session starts ==============================
platform win32 -- Python 3.8.6, pytest-6.2.5, py-1.11.0, plugg-1.0.0
rootdir: D:\\project, configfile: pytest.ini
plugins: cov-3.0.0, mock-3.7.0
collected 6 items

tests/test_parser.py::TestParseUserInput::test_parse_simple_key_value PASSED [ 12%]
tests/test_parser.py::TestParseUserInput::test_parse_multiple_pairs PASSED [ 25%]
tests/test_parser.py::TestParseUserInput::test_parse_empty_input PASSED [ 37%]
tests/test_parser.py::TestParseUserInput::test_parse_input_with_spaces PASSED [ 50%]
tests/test_parser.py::TestParseUserInput::test_parse_invalid_input_raises FAILED [ 62%]

=================================== FAILURES ===================================
_______________ TestParseUserInput.test_parse_invalid_input_raises _______________

self = <tests.test_parser.TestParseUserInput object at 0x0000023A4B8C5E50>

    def test_parse_invalid_input_raises(self):
        """测试非法输入应抛出 ValueError。"""
        with pytest.raises(ValueError):
>           parse_user_input("=no_key")

src\\parser.py:14: ValueError
''' + 'x' * 200 + '''

During handling of the above exception, another exception occurred:

    pair.split("=") -> ["", "no_key"]，未抛出 ValueError 而是直接赋值
    预期抛出 ValueError，实际返回 {"": "no_key"}

=========================== short test summary info ============================
FAILED tests/test_parser.py::TestParseUserInput::test_parse_invalid_input_raises
========================= 1 failed, 4 passed in 1.23s =========================
'''

# 真实风格的 pytest 通过输出
PYTEST_PASS_OUTPUT = '''============================= test session starts ==============================
platform win32 -- Python 3.8.6, pytest-6.2.5, py-1.11.0, plugg-1.0.0
rootdir: D:\\project, configfile: pytest.ini
plugins: cov-3.0.0, mock-3.7.0
collected 6 items

tests/test_parser.py::TestParseUserInput::test_parse_simple_key_value PASSED [ 16%]
tests/test_parser.py::TestParseUserInput::test_parse_multiple_pairs PASSED [ 33%]
tests/test_parser.py::TestParseUserInput::test_parse_empty_input PASSED [ 50%]
tests/test_parser.py::TestParseUserInput::test_parse_input_with_spaces PASSED [ 66%]
tests/test_parser.py::TestParseUserInput::test_parse_invalid_input_raises PASSED [ 83%]
tests/test_parser.py::TestParseUserInput::test_parse_unicode PASSED [100%]

============================== 6 passed in 1.18s ===============================
'''

# 真实风格的 git diff
GIT_DIFF_PR = '''diff --git a/src/auth/login.py b/src/auth/login.py
index 1a2b3c4..5d6e7f8 100644
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -38,7 +38,13 @@ def login(username: str, password: str) -> Optional[Session]:
     user = db.query(User).filter(User.username == username).first()
     if not user:
         return None
-    if user.password_hash == hash_password(password):
+    # 修复：使用恒定时间比较防止时序攻击
+    import hmac
+    if not hmac.compare_digest(user.password_hash.encode(), hash_password(password).encode()):
+        log_failed_attempt(username)
+        return None
+    if user.is_locked:
+        return None
         session = create_session(user)
         session.last_login = datetime.utcnow()
         db.commit()
diff --git a/src/auth/session.py b/src/auth/session.py
index 9a8b7c6..5d4e3f2 100644
--- a/src/auth/session.py
+++ b/src/auth/session.py
@@ -15,6 +15,7 @@ class Session:
     user_id: int
     token: str
     expires_at: datetime
+    last_login: Optional[datetime] = None

     def is_valid(self) -> bool:
         return self.expires_at > datetime.utcnow()
'''

# 真实风格的 login.py 文件内容
LOGIN_PY = '''"""src/auth/login.py - 用户登录认证。"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from src.models import User
from src.auth.session import Session, create_session
from src.auth.password import hash_password
from src.audit import log_failed_attempt


def login(username: str, password: str, db: DBSession) -> Optional[Session]:
    """用户登录，验证密码并创建会话。

    Args:
        username: 用户名
        password: 明文密码
        db: 数据库会话

    Returns:
        登录成功返回 Session，失败返回 None
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if user.password_hash == hash_password(password):
        session = create_session(user)
        session.last_login = datetime.utcnow()
        db.commit()
        return session
    return None


def logout(session: Session, db: DBSession) -> None:
    """注销会话。"""
    session.expires_at = datetime.utcnow()
    db.commit()


def refresh_session(session: Session, db: DBSession) -> Session:
    """刷新会话过期时间。"""
    session.expires_at = datetime.utcnow() + timedelta(hours=24)
    db.commit()
    return session
'''

# 真实风格的 UserService 大类（用于重构场景）
USER_SERVICE_PY = '''"""src/services/user.py - 用户服务（待重构）。"""
from typing import List, Optional
from sqlalchemy.orm import Session as DBSession
from src.models import User, UserProfile
from src.auth.password import hash_password


class UserService:
    """用户服务：混合了认证与资料管理职责，需要拆分。"""

    def __init__(self, db: DBSession):
        self.db = db

    # ===== 认证相关方法 =====
    def register(self, username: str, password: str, email: str) -> User:
        """注册新用户。"""
        if self.db.query(User).filter(User.username == username).first():
            raise ValueError("用户名已存在")
        user = User(
            username=username,
            password_hash=hash_password(password),
            email=email,
        )
        self.db.add(user)
        self.db.commit()
        return user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """验证用户凭据。"""
        user = self.db.query(User).filter(User.username == username).first()
        if user and user.password_hash == hash_password(password):
            return user
        return None

    def change_password(self, user_id: int, old_password: str, new_password: str) -> bool:
        """修改密码。"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user or user.password_hash != hash_password(old_password):
            return False
        user.password_hash = hash_password(new_password)
        self.db.commit()
        return True

    def reset_password(self, email: str) -> str:
        """重置密码，返回临时密码。"""
        user = self.db.query(User).filter(User.email == email).first()
        if not user:
            raise ValueError("邮箱不存在")
        import secrets
        temp = secrets.token_urlsafe(12)
        user.password_hash = hash_password(temp)
        self.db.commit()
        return temp

    # ===== 资料管理方法 =====
    def get_profile(self, user_id: int) -> Optional[UserProfile]:
        """获取用户资料。"""
        return self.db.query(UserProfile).filter(UserProfile.user_id == user_id).first()

    def update_profile(self, user_id: int, **fields) -> Optional[UserProfile]:
        """更新用户资料。"""
        profile = self.get_profile(user_id)
        if not profile:
            return None
        for key, value in fields.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        self.db.commit()
        return profile

    def list_users(self, offset: int = 0, limit: int = 20) -> List[User]:
        """分页列出用户。"""
        return self.db.query(User).offset(offset).limit(limit).all()

    def delete_user(self, user_id: int) -> bool:
        """删除用户。"""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        self.db.delete(user)
        self.db.commit()
        return True
'''

# 真实风格的 routes/user.py
ROUTES_USER_PY = '''"""src/routes/user.py - 用户相关路由。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register")
def register(username: str, password: str, email: str, db: Session = Depends(get_db)):
    service = UserService(db)
    try:
        user = service.register(username, password, email)
        return {"id": user.id, "username": user.username}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db)):
    service = UserService(db)
    profile = service.get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="User not found")
    return profile


def get_db():
    from src.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

# glob 文件列表输出
GLOB_OUTPUT = '''src/__init__.py
src/models/__init__.py
src/models/user.py
src/models/order.py
src/services/__init__.py
src/services/user.py
src/services/order.py
src/services/payment.py
src/routes/__init__.py
src/routes/user.py
src/routes/order.py
src/auth/__init__.py
src/auth/login.py
src/auth/session.py
src/auth/password.py
src/db.py
src/config.py
src/parser.py
src/utils.py
tests/__init__.py
tests/test_parser.py
tests/test_user_service.py
tests/test_auth.py
'''

# 真实风格的 review 总结
REVIEW_SUMMARY = """代码 Review 总结（PR #42: feature/login-refactor）：

## 优点
1. 修复了时序攻击漏洞，使用 hmac.compare_digest 是正确的做法
2. 增加了账户锁定检查，提升了安全性
3. session 模型新增 last_login 字段，便于审计

## 问题
### 严重（必须修改）
- src/auth/login.py:42 `log_failed_attempt` 在密码错误时未调用，应在 `if not hmac.compare_digest` 分支内调用
- src/auth/login.py:45 `user.is_locked` 检查应在密码验证之前，避免锁定账户被暴力破解

### 建议（可选）
- src/auth/session.py:18 `last_login` 字段建议添加默认值注释
- 建议新增 `LoginAttempt` 模型记录失败尝试，便于风控分析
- `login` 函数过长，建议拆分 `_verify_password` 和 `_check_lock_status`

## 测试覆盖
- tests/test_auth.py 应补充：
  - 锁定账户登录测试
  - 时序攻击测试（响应时间一致性）
  - 失败登录审计测试

总体评价：方向正确，需修复 2 个严重问题后可合并。
"""

# 真实风格的注册功能新文件
REGISTER_ROUTE_PY = '''"""src/routes/register.py - 用户注册路由。"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, validator
from src.services.user import UserService
from src.services.email import send_verification_email

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """注册请求模型。"""
    username: str
    password: str
    email: EmailStr

    @validator("username")
    def validate_username(cls, v):
        if len(v) < 3 or len(v) > 20:
            raise ValueError("用户名长度需在 3-20 之间")
        return v

    @validator("password")
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("密码至少 8 位")
        return v


@router.post("/register")
def register(req: RegisterRequest, background: BackgroundTasks,
             db: Session = Depends(get_db)):
    """用户注册，发送验证邮件。"""
    service = UserService(db)
    try:
        user = service.register(req.username, req.password, req.email)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 后台发送验证邮件
    background.add_task(send_verification_email, user.id, user.email)
    return {"id": user.id, "username": user.username, "message": "验证邮件已发送"}


def get_db():
    from src.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

# 真实风格的邮件服务
EMAIL_SERVICE_PY = '''"""src/services/email.py - 邮件服务。"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from src.config import get_config
from src.models import User, EmailVerification
from sqlalchemy.orm import Session
import secrets
from datetime import datetime, timedelta


def send_verification_email(user_id: int, email: str, db: Session = None) -> bool:
    """发送邮箱验证邮件。

    Args:
        user_id: 用户 ID
        email: 收件邮箱
        db: 数据库会话

    Returns:
        是否发送成功
    """
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=24)

    if db:
        verification = EmailVerification(
            user_id=user_id, token=token, expires_at=expires
        )
        db.add(verification)
        db.commit()

    config = get_config()
    subject = "【项目】请验证您的邮箱"
    body = f"""您好，

感谢注册。请点击以下链接验证邮箱（24 小时内有效）：

{config.base_url}/verify?token={token}

如非本人操作，请忽略此邮件。
"""
    return _send_mail(email, subject, body)


def _send_mail(to: str, subject: str, body: str) -> bool:
    """发送邮件（内部方法）。"""
    config = get_config()
    msg = MIMEMultipart()
    msg["From"] = config.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP(config.mail_host, config.mail_port) as server:
            server.starttls()
            server.login(config.mail_user, config.mail_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"邮件发送失败: {e}")
        return False


def verify_email(token: str, db: Session) -> bool:
    """验证邮箱 token。"""
    record = db.query(EmailVerification).filter(
        EmailVerification.token == token
    ).first()
    if not record or record.expires_at < datetime.utcnow():
        return False
    record.verified = True
    user = db.query(User).filter(User.id == record.user_id).first()
    if user:
        user.email_verified = True
    db.commit()
    return True
'''


# ═══════════════════════════════════════════════════════════
#  真实场景 1：Bug 修复
# ═══════════════════════════════════════════════════════════

def build_bug_fix_scenario() -> list:
    """模拟 bug 修复完整流程。

    流程：读测试 → 读源码 → 运行测试（失败）→ 定位 bug → 编辑修复 → 重测（通过）→ 再扩展测试 → 运行全套
    含真实风格的 Python 代码与 pytest 输出。
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"bugfix-{tid}"

    # 用户报告 bug
    msgs.append(user_text(
        "tests/test_parser.py::TestParseUserInput::test_parse_invalid_input_raises 失败了，"
        "报错显示 parse_user_input('=no_key') 没有抛 ValueError 而是返回了 {'': 'no_key'}，"
        "请修复这个 bug。另外顺便检查一下其他边界情况。"
    ))

    # assistant 读测试文件
    msgs.append(assistant_with_tools(
        "我来看看测试文件，了解期望的行为。",
        [_tool_use_block(nid(), "read_file", path="tests/test_parser.py")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", TEST_PARSER_PY))

    # assistant 读源码
    msgs.append(assistant_with_tools(
        "测试期望 parse_user_input('=no_key') 抛出 ValueError。现在我读一下源码看实现。",
        [_tool_use_block(nid(), "read_file", path="src/parser.py")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", BUGGY_PARSER_PY))

    # assistant 运行测试确认 bug
    msgs.append(assistant_with_tools(
        "我看到源码第 14 行 `key, value = pair.split('=')` 没有检查 pair 是否包含 '='，"
        "导致 '=no_key' 被解析成 key='' value='no_key'。先运行测试确认。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/test_parser.py -v")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", PYTEST_FAIL_OUTPUT))

    # assistant 修复 bug
    msgs.append(assistant_with_tools(
        "确认 bug。我用 edit_file 修复：在 split 前检查 '=' 是否存在。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/parser.py",
                         old_text="        # BUG: 没有检查 pair 是否包含 \"=\"\n        key, value = pair.split(\"=\")",
                         new_text="        if \"=\" not in pair:\n            raise ValueError(f\"Invalid pair: {pair!r}\")\n        key, value = pair.split(\"=\", 1)")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", "Edited src/parser.py"))

    # assistant 重测
    msgs.append(assistant_with_tools(
        "修复完成，重新运行测试验证。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/test_parser.py -v")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", PYTEST_PASS_OUTPUT))

    # assistant 扩展测试（添加 unicode 测试）
    msgs.append(assistant_with_tools(
        "测试通过了。我再补充一个 unicode 输入的测试用例，增强覆盖。",
        [_tool_use_block(nid(), "edit_file",
                         path="tests/test_parser.py",
                         old_text="    def test_parse_unicode(self):",
                         new_text="    def test_parse_unicode(self):\n        \"\"\"测试 unicode 输入。\"\"\"\n        result = parse_user_input(\"名字=张三\")\n        assert result == {\"名字\": \"张三\"}\n\n    def test_parse_unicode_placeholder(self):")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", "Edited tests/test_parser.py"))

    # 再读源码确认
    msgs.append(assistant_with_tools(
        "我再读一遍修复后的源码，确认逻辑正确。",
        [_tool_use_block(nid(), "read_file", path="src/parser.py")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}", FIXED_PARSER_PY))

    # 运行全套测试
    msgs.append(assistant_with_tools(
        "运行全套测试确认无回归。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/ -v --cov=src")]
    ))
    msgs.append(tool_result_message(f"bugfix-{tid}",
                                    PYTEST_PASS_OUTPUT + "\n--- coverage ---\n"
                                    "src/parser.py      100%\nsrc/models.py       92%\n"
                                    "TOTAL               95%\n"))

    # assistant 总结
    msgs.append(assistant_text(
        "Bug 修复完成。根本原因：parse_user_input 在 split('=') 前未校验 pair 格式，"
        "导致 '=no_key' 被错误解析。修复方式：先检查 '=' 是否存在，不存在则抛 ValueError；"
        "同时把 split('=') 改为 split('=', 1) 避免值中含 '=' 时出错。"
        "补充了 unicode 测试用例，覆盖率 95%。"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 2：代码 Review
# ═══════════════════════════════════════════════════════════

def build_code_review_scenario() -> list:
    """模拟代码 review 完整流程。

    流程：git diff → 读多个相关文件 → git log → 分析 → 输出 review 总结
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"review-{tid}"

    msgs.append(user_text(
        "请 review 一下 PR #42（feature/login-refactor 分支），"
        "重点关注安全性和代码质量。这个 PR 改动了登录逻辑。"
    ))

    # git diff
    msgs.append(assistant_with_tools(
        "我先看一下这个 PR 的改动内容。",
        [_tool_use_block(nid(), "bash",
                         command="git diff main...feature/login-refactor")]
    ))
    msgs.append(tool_result_message(f"review-{tid}", GIT_DIFF_PR))

    # 读 login.py 完整文件
    msgs.append(assistant_with_tools(
        "diff 显示 login.py 改动了密码验证逻辑。我读一下完整文件理解上下文。",
        [_tool_use_block(nid(), "read_file", path="src/auth/login.py")]
    ))
    msgs.append(tool_result_message(f"review-{tid}", LOGIN_PY))

    # 读 session.py
    msgs.append(assistant_with_tools(
        "session.py 新增了 last_login 字段，我读一下完整定义。",
        [_tool_use_block(nid(), "read_file", path="src/auth/session.py")]
    ))
    msgs.append(tool_result_message(f"review-{tid}",
        "src/auth/session.py 内容：\\n" + LOGIN_PY.split('"""')[0] +
        "class Session:\\n    user_id: int\\n    token: str\\n    expires_at: datetime\\n"
        "    last_login: Optional[datetime] = None\\n\\n    def is_valid(self):\\n"
        "        return self.expires_at > datetime.utcnow()\\n"))

    # git log
    msgs.append(assistant_with_tools(
        "看一下这个分支的提交历史，了解改动演进。",
        [_tool_use_block(nid(), "bash",
                         command="git log --oneline feature/login-refactor")]
    ))
    msgs.append(tool_result_message(f"review-{tid}",
        "a1b2c3d 修复时序攻击漏洞\\n"
        "b2c3d4e 增加账户锁定检查\\n"
        "c3d4e5f session 新增 last_login 字段\\n"
        "d4e5f6a 重构 login 函数\\n"
        "e5f6a7b 添加 log_failed_attempt 调用\\n"))

    # 读测试文件
    msgs.append(assistant_with_tools(
        "看一下测试覆盖情况。",
        [_tool_use_block(nid(), "read_file", path="tests/test_auth.py")]
    ))
    msgs.append(tool_result_message(f"review-{tid}",
        "tests/test_auth.py 内容：\\n"
        "def test_login_success(): ...\\n"
        "def test_login_wrong_password(): ...\\n"
        "def test_login_nonexistent_user(): ...\\n"
        "# 缺少：锁定账户测试、时序攻击测试、失败审计测试\\n"))

    # 运行测试
    msgs.append(assistant_with_tools(
        "运行测试看当前覆盖。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/test_auth.py -v --cov=src/auth")]
    ))
    msgs.append(tool_result_message(f"review-{tid}",
        "3 passed in 0.89s\\n--- coverage ---\\n"
        "src/auth/login.py    78%\\nsrc/auth/session.py  100%\\n"
        "src/auth/password.py 95%\\n"))

    # 输出 review 总结
    msgs.append(assistant_text(REVIEW_SUMMARY))

    # 用户追问
    msgs.append(user_text(
        "关于第 1 个严重问题，log_failed_attempt 应该放在哪里？能帮我写一下修复代码吗？"
    ))

    # assistant 给出修复建议
    msgs.append(assistant_with_tools(
        "log_failed_attempt 应该在密码验证失败的分支内调用。修复如下：",
        [_tool_use_block(nid(), "edit_file",
                         path="src/auth/login.py",
                         old_text="    if not hmac.compare_digest(user.password_hash.encode(), hash_password(password).encode()):\n        log_failed_attempt(username)\n        return None",
                         new_text="    if not hmac.compare_digest(user.password_hash.encode(), hash_password(password).encode()):\n        log_failed_attempt(username, ip_address=request.remote_addr)\n        return None")]
    ))
    msgs.append(tool_result_message(f"review-{tid}", "Edited src/auth/login.py"))

    msgs.append(assistant_text(
        "修复说明：log_failed_attempt 现在在密码验证失败分支内调用，"
        "并补充了 ip_address 参数便于风控分析。建议同时把 user.is_locked 检查移到密码验证之前，"
        "避免锁定账户被暴力破解时仍执行密码哈希计算。"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 3：功能实现
# ═══════════════════════════════════════════════════════════

def build_feature_impl_scenario() -> list:
    """模拟功能实现完整流程。

    流程：读项目结构 → 读现有模型 → 创建路由 → 创建邮件服务 → 写测试 → 运行测试 → 修复 → 重测
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"impl-{tid}"

    msgs.append(user_text(
        "请实现用户注册功能，要求：1) 用户名 3-20 字符，密码至少 8 位；"
        "2) 邮箱格式校验；3) 注册后发送验证邮件（后台异步）；4) 提供邮箱验证接口。"
    ))

    # glob 查看项目结构
    msgs.append(assistant_with_tools(
        "我先看一下项目结构，了解现有代码组织。",
        [_tool_use_block(nid(), "glob", pattern="src/**/*.py")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", GLOB_OUTPUT))

    # 读现有 user service
    msgs.append(assistant_with_tools(
        "读一下现有的 UserService，看能否复用 register 方法。",
        [_tool_use_block(nid(), "read_file", path="src/services/user.py")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", USER_SERVICE_PY))

    # 读现有 routes/user.py
    msgs.append(assistant_with_tools(
        "读一下现有路由风格，保持一致。",
        [_tool_use_block(nid(), "read_file", path="src/routes/user.py")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", ROUTES_USER_PY))

    # 创建注册路由
    msgs.append(assistant_with_tools(
        "UserService 已有 register 方法，我创建注册路由，使用 Pydantic 校验输入，"
        "BackgroundTasks 异步发邮件。",
        [_tool_use_block(nid(), "write_file",
                         path="src/routes/register.py", content=REGISTER_ROUTE_PY)]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", "Wrote 1850 bytes to src/routes/register.py"))

    # 创建邮件服务
    msgs.append(assistant_with_tools(
        "创建邮件服务，包含发送验证邮件和验证 token 两个方法。",
        [_tool_use_block(nid(), "write_file",
                         path="src/services/email.py", content=EMAIL_SERVICE_PY)]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", "Wrote 2100 bytes to src/services/email.py"))

    # 写测试
    msgs.append(assistant_with_tools(
        "写测试覆盖注册流程：成功注册、用户名冲突、密码过短、邮箱格式错误。",
        [_tool_use_block(nid(), "write_file",
                         path="tests/test_register.py",
                         content="import pytest\\nfrom fastapi.testclient import TestClient\\n"
                                 "from src.app import app\\n\\nclient = TestClient(app)\\n\\n"
                                 "def test_register_success():\\n    resp = client.post('/auth/register',"
                                 " json={'username':'alice','password':'pass1234','email':'a@b.com'})\\n"
                                 "    assert resp.status_code == 200\\n\\n"
                                 "def test_register_short_password():\\n    resp = client.post('/auth/register',"
                                 " json={'username':'al','password':'x','email':'a@b.com'})\\n"
                                 "    assert resp.status_code == 422\\n")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", "Wrote 680 bytes to tests/test_register.py"))

    # 运行测试
    msgs.append(assistant_with_tools(
        "运行测试验证实现。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/test_register.py -v")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}",
        "============================= test session starts ==============================\\n"
        "collected 4 items\\n\\n"
        "tests/test_register.py::test_register_success FAILED                       [ 25%]\\n"
        "tests/test_register.py::test_register_short_password PASSED                [ 50%]\\n"
        "tests/test_register.py::test_register_duplicate_username PASSED            [ 75%]\\n"
        "tests/test_register.py::test_register_invalid_email PASSED                 [100%]\\n\\n"
        "FAILED tests/test_register.py::test_register_success\\n"
        "assert resp.status_code == 200, got 500\\n"
        "Error: NameError: name 'get_db' is not defined\\n"
        "1 failed, 3 passed in 0.92s\\n"))

    # 修复 bug
    msgs.append(assistant_with_tools(
        "test_register_success 失败，原因是 register.py 引用了未定义的 get_db。我修复一下。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/routes/register.py",
                         old_text="def get_db():\n    from src.db import SessionLocal",
                         new_text="def get_db():\n    from src.db import SessionLocal\n    db = SessionLocal()\n    try:\n        yield db\n    finally:\n        db.close()\n\n# 顶部添加 import\\nfrom src.db import get_db")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", "Edited src/routes/register.py"))

    # 重测
    msgs.append(assistant_with_tools(
        "重新运行测试。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/test_register.py -v")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}",
        "4 passed in 0.85s\\n"))

    # 添加邮箱验证接口
    msgs.append(assistant_with_tools(
        "现在添加邮箱验证接口。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/routes/register.py",
                         old_text="def get_db():",
                         new_text="@router.get('/verify')\\n"
                                  "def verify_email(token: str, db: Session = Depends(get_db)):\\n"
                                  "    \"\"\"验证邮箱 token。\"\"\"\\n"
                                  "    from src.services.email import verify_email as do_verify\\n"
                                  "    if do_verify(token, db):\\n"
                                  "        return {'message': '验证成功'}\\n"
                                  "    raise HTTPException(status_code=400, detail='token 无效或已过期')\\n\\n"
                                  "def get_db():")]
    ))
    msgs.append(tool_result_message(f"impl-{tid}", "Edited src/routes/register.py"))

    msgs.append(assistant_text(
        "用户注册功能实现完成。包含：1) /auth/register 接口，Pydantic 校验用户名/密码/邮箱；"
        "2) BackgroundTasks 异步发送验证邮件；3) /auth/verify 接口验证 token；"
        "4) 4 个测试用例全部通过。复用了 UserService.register 方法，新增 EmailService 处理邮件。"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 4：重构
# ═══════════════════════════════════════════════════════════

def build_refactor_scenario() -> list:
    """模拟重构完整流程。

    流程：grep 查找引用 → 读源文件 → 读路由 → 拆分 auth 方法 → 创建新类 → 更新引用 → 测试
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"refac-{tid}"

    msgs.append(user_text(
        "UserService 类同时承担了认证和资料管理职责，违反单一职责原则。"
        "请拆分成 UserAuthService（注册/登录/改密/重置）和 UserProfileService（资料/列表/删除）。"
        "确保所有引用更新，测试不回归。"
    ))

    # grep 查找引用
    msgs.append(assistant_with_tools(
        "先查找所有引用 UserService 的地方。",
        [_tool_use_block(nid(), "bash",
                         command="grep -rn 'UserService' src/ tests/ --include='*.py'")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}",
        "src/routes/user.py:5: from src.services.user import UserService\\n"
        "src/routes/user.py:9: service = UserService(db)\\n"
        "src/routes/user.py:17: service = UserService(db)\\n"
        "src/routes/auth.py:3: from src.services.user import UserService\\n"
        "src/routes/auth.py:8: service = UserService(db)\\n"
        "tests/test_user_service.py:4: from src.services.user import UserService\\n"
        "tests/test_user_service.py:12: self.service = UserService(self.db)\\n"
        "7 处引用，涉及 3 个文件。\\n"))

    # 读源文件
    msgs.append(assistant_with_tools(
        "读一下 UserService 完整实现。",
        [_tool_use_block(nid(), "read_file", path="src/services/user.py")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", USER_SERVICE_PY))

    # 读路由
    msgs.append(assistant_with_tools(
        "读一下 routes/user.py 看引用方式。",
        [_tool_use_block(nid(), "read_file", path="src/routes/user.py")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", ROUTES_USER_PY))

    # 读测试
    msgs.append(assistant_with_tools(
        "读一下测试文件。",
        [_tool_use_block(nid(), "read_file", path="tests/test_user_service.py")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}",
        "tests/test_user_service.py 内容：\\n"
        "class TestUserService:\\n    def setup_method(self):\\n"
        "        self.service = UserService(self.db)\\n"
        "    def test_register(self): ...\\n"
        "    def test_authenticate(self): ...\\n"
        "    def test_change_password(self): ...\\n"
        "    def test_get_profile(self): ...\\n"
        "    def test_update_profile(self): ...\\n"
        "    def test_list_users(self): ...\\n"
        "    def test_delete_user(self): ...\\n"))

    # 创建 UserAuthService
    msgs.append(assistant_with_tools(
        "我先创建 UserAuthService，包含认证相关方法。",
        [_tool_use_block(nid(), "write_file",
                         path="src/services/user_auth.py",
                         content='"""src/services/user_auth.py - 用户认证服务。"""\n'
                                 "from typing import Optional\\n"
                                 "import secrets\\n"
                                 "from sqlalchemy.orm import Session as DBSession\\n"
                                 "from src.models import User\\n"
                                 "from src.auth.password import hash_password\\n\\n\\n"
                                 "class UserAuthService:\\n"
                                 "    def __init__(self, db: DBSession):\\n"
                                 "        self.db = db\\n\\n"
                                 "    def register(self, username, password, email): ...\\n"
                                 "    def authenticate(self, username, password): ...\\n"
                                 "    def change_password(self, user_id, old, new): ...\\n"
                                 "    def reset_password(self, email): ...\\n")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "Wrote 980 bytes to src/services/user_auth.py"))

    # 创建 UserProfileService
    msgs.append(assistant_with_tools(
        "创建 UserProfileService，包含资料管理方法。",
        [_tool_use_block(nid(), "write_file",
                         path="src/services/user_profile.py",
                         content='"""src/services/user_profile.py - 用户资料服务。"""\n'
                                 "from typing import List, Optional\\n"
                                 "from sqlalchemy.orm import Session as DBSession\\n"
                                 "from src.models import User, UserProfile\\n\\n\\n"
                                 "class UserProfileService:\\n"
                                 "    def __init__(self, db: DBSession):\\n"
                                 "        self.db = db\\n\\n"
                                 "    def get_profile(self, user_id): ...\\n"
                                 "    def update_profile(self, user_id, **fields): ...\\n"
                                 "    def list_users(self, offset=0, limit=20): ...\\n"
                                 "    def delete_user(self, user_id): ...\\n")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "Wrote 720 bytes to src/services/user_profile.py"))

    # 更新 user.py 移除 auth 方法
    msgs.append(assistant_with_tools(
        "更新 user.py，移除认证方法，仅保留资料管理。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/services/user.py",
                         old_text="class UserService:",
                         new_text="# 已废弃，请使用 UserAuthService 或 UserProfileService\\n"
                                  "class UserService:")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "Edited src/services/user.py"))

    # 更新 routes/user.py
    msgs.append(assistant_with_tools(
        "更新 routes/user.py 使用 UserProfileService。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/routes/user.py",
                         old_text="from src.services.user import UserService",
                         new_text="from src.services.user_profile import UserProfileService")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "Edited src/routes/user.py"))

    # 更新 routes/auth.py
    msgs.append(assistant_with_tools(
        "更新 routes/auth.py 使用 UserAuthService。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/routes/auth.py",
                         old_text="from src.services.user import UserService",
                         new_text="from src.services.user_auth import UserAuthService")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "Edited src/routes/auth.py"))

    # 运行测试
    msgs.append(assistant_with_tools(
        "运行测试确认无回归。",
        [_tool_use_block(nid(), "bash", command="python -m pytest tests/ -v")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}",
        "7 passed in 1.45s\\n所有测试通过。\\n"))

    # 运行 lint
    msgs.append(assistant_with_tools(
        "运行 lint 确认代码风格。",
        [_tool_use_block(nid(), "bash", command="python -m flake8 src/services/ --max-line-length=100")]
    ))
    msgs.append(tool_result_message(f"refac-{tid}", "0 issues found.\\n"))

    msgs.append(assistant_text(
        "重构完成。UserService 拆分为：\\n"
        "1. UserAuthService（src/services/user_auth.py）：register / authenticate / change_password / reset_password\\n"
        "2. UserProfileService（src/services/user_profile.py）：get_profile / update_profile / list_users / delete_user\\n"
        "更新了 3 个引用文件，7 个测试全部通过，flake8 无问题。原 UserService 保留为废弃 stub 便于渐进迁移。"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 5：生产事故排查（60+ 轮，含大日志，触发 L1+L2+L3+L4）
# ═══════════════════════════════════════════════════════════

# 生产事故排查场景用到的源码片段
ORDER_SERVICE_PY = '''"""src/services/order.py - 订单服务。"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session as DBSession
from src.models import Order, OrderItem, Product, User
from src.services.payment import PaymentService
from src.services.inventory import InventoryService
from src.services.email import EmailService
from src.audit import log_event


class OrderService:
    """订单服务：处理订单创建、查询、取消等业务逻辑。"""

    def __init__(self, db: DBSession):
        self.db = db
        self.payment = PaymentService(db)
        self.inventory = InventoryService(db)
        self.email = EmailService()

    def create_order(self, user_id: int, items: List[dict]) -> Order:
        """创建订单。

        Args:
            user_id: 用户 ID
            items: 商品列表 [{"product_id": 1, "quantity": 2}, ...]

        Returns:
            创建的订单对象

        Raises:
            ValueError: 商品不存在或库存不足
        """
        # 验证用户
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User {user_id} not found")

        # 验证商品并锁定库存
        order_items = []
        total = 0.0
        for item in items:
            product = self.db.query(Product).filter(Product.id == item["product_id"]).first()
            if not product:
                raise ValueError(f"Product {item['product_id']} not found")
            if not self.inventory.check_and_reserve(product.id, item["quantity"]):
                raise ValueError(f"Insufficient stock for product {product.id}")
            order_item = OrderItem(
                product_id=product.id,
                quantity=item["quantity"],
                unit_price=product.price,
            )
            order_items.append(order_item)
            total += product.price * item["quantity"]

        # 创建订单
        order = Order(
            user_id=user_id,
            total_amount=total,
            status="pending",
            items=order_items,
        )
        self.db.add(order)
        self.db.commit()
        log_event("order_created", {"order_id": order.id, "user_id": user_id})
        return order

    def process_payment(self, order_id: int, payment_method: str) -> bool:
        """处理订单支付。"""
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order.status != "pending":
            raise ValueError(f"Order {order_id} status is {order.status}, not pending")

        # BUG: 没有捕获支付服务的异常，导致 500 错误
        result = self.payment.charge(order.total_amount, payment_method)
        if result.success:
            order.status = "paid"
            order.paid_at = datetime.utcnow()
            self.db.commit()
            self.email.send_order_confirmation(order)
            log_event("order_paid", {"order_id": order.id})
            return True
        else:
            order.status = "payment_failed"
            self.db.commit()
            return False
'''

INVENTORY_SERVICE_PY = '''"""src/services/inventory.py - 库存服务。"""
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from src.models import Product, InventoryLog
from src.cache import redis_client
import json


class InventoryService:
    """库存服务：管理商品库存，支持缓存和并发预留。"""

    def __init__(self, db: DBSession):
        self.db = db
        self.cache = redis_client

    def get_stock(self, product_id: int) -> int:
        """获取商品当前库存（优先读缓存）。"""
        cache_key = f"stock:{product_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return int(cached)
        # 缓存未命中，查数据库
        product = self.db.query(Product).filter(Product.id == product_id).first()
        stock = product.stock if product else 0
        self.cache.set(cache_key, stock, ex=300)  # 缓存 5 分钟
        return stock

    def check_and_reserve(self, product_id: int, quantity: int) -> bool:
        """检查并预留库存。

        使用 Redis 原子操作避免超卖。
        """
        cache_key = f"stock:{product_id}"
        # BUG: 没有使用 Redis 原子 DECR，而是先 GET 再 SET，存在竞态条件
        current = self.get_stock(product_id)
        if current < quantity:
            return False
        new_stock = current - quantity
        self.cache.set(cache_key, new_stock, ex=300)
        # 同步到数据库
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.stock = new_stock
            self.db.add(InventoryLog(
                product_id=product_id,
                change=-quantity,
                type="reserve",
            ))
            self.db.commit()
        return True

    def release_reserve(self, product_id: int, quantity: int) -> bool:
        """释放预留库存（订单取消时调用）。"""
        cache_key = f"stock:{product_id}"
        current = self.get_stock(product_id)
        new_stock = current + quantity
        self.cache.set(cache_key, new_stock, ex=300)
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if product:
            product.stock = new_stock
            self.db.add(InventoryLog(
                product_id=product_id,
                change=quantity,
                type="release",
            ))
            self.db.commit()
        return True
'''

PAYMENT_SERVICE_PY = '''"""src/services/payment.py - 支付服务。"""
from typing import Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session as DBSession
from src.models import Payment, PaymentLog
from src.gateway import stripe_gateway, alipay_gateway
import time


@dataclass
class PaymentResult:
    """支付结果。"""
    success: bool
    transaction_id: Optional[str] = None
    error: Optional[str] = None


class PaymentService:
    """支付服务：封装第三方支付网关。"""

    def __init__(self, db: DBSession):
        self.db = db

    def charge(self, amount: float, method: str) -> PaymentResult:
        """发起扣款。

        Args:
            amount: 金额（元）
            method: 支付方式（stripe / alipay）

        Returns:
            PaymentResult
        """
        if amount <= 0:
            return PaymentResult(success=False, error="Amount must be positive")
        if amount > 10000:
            return PaymentResult(success=False, error="Amount exceeds single transaction limit")

        # 记录支付请求
        payment = Payment(
            amount=amount,
            method=method,
            status="processing",
        )
        self.db.add(payment)
        self.db.commit()

        try:
            if method == "stripe":
                result = stripe_gateway.charge(payment.id, amount)
            elif method == "alipay":
                result = alipay_gateway.charge(payment.id, amount)
            else:
                payment.status = "failed"
                self.db.commit()
                return PaymentResult(success=False, error=f"Unsupported method: {method}")

            if result["success"]:
                payment.status = "success"
                payment.transaction_id = result["transaction_id"]
                self.db.commit()
                return PaymentResult(success=True, transaction_id=result["transaction_id"])
            else:
                payment.status = "failed"
                self.db.commit()
                return PaymentResult(success=False, error=result.get("error", "Unknown error"))

        except Exception as e:
            payment.status = "error"
            self.db.add(PaymentLog(
                payment_id=payment.id,
                message=f"Exception: {e}",
            ))
            self.db.commit()
            raise  # BUG: 应该返回 PaymentResult 而不是 raise，导致上层 500
'''

CONFIG_PY = '''"""src/config.py - 应用配置。"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """应用配置（从环境变量读取）。"""

    # 数据库
    DB_HOST = os.getenv("DB_HOST", "localhost")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME", "app_db")
    DB_USER = os.getenv("DB_USER", "app")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "")

    # Redis
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_DB = int(os.getenv("REDIS_DB", "0"))

    # 支付网关
    STRIPE_API_KEY = os.getenv("STRIPE_API_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    ALIPAY_APP_ID = os.getenv("ALIPAY_APP_ID", "")
    ALIPAY_PRIVATE_KEY = os.getenv("ALIPAY_PRIVATE_KEY", "")

    # 业务参数
    MAX_ORDER_AMOUNT = float(os.getenv("MAX_ORDER_AMOUNT", "10000"))
    ORDER_TIMEOUT_MINUTES = int(os.getenv("ORDER_TIMEOUT_MINUTES", "30"))
    INVENTORY_CACHE_TTL = int(os.getenv("INVENTORY_CACHE_TTL", "300"))

    # 日志
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "/var/log/app/app.log")
'''

STACK_TRACE_OUTPUT = '''Traceback (most recent call last):
  File "/app/src/routes/order.py", line 45, in create_order
    result = order_service.process_payment(order.id, payment_method)
  File "/app/src/services/order.py", line 78, in process_payment
    result = self.payment.charge(order.total_amount, payment_method)
  File "/app/src/services/payment.py", line 65, in charge
    raise  # BUG: 应该返回 PaymentResult 而不是 raise
  File "/app/src/gateway/stripe.py", line 28, in charge
    response = self.client.charges.create(
  File "/app/.venv/lib/python3.11/site-packages/stripe/api_resources/abstract/createable_api_resource.py", line 23, in create
    response, api_key = requestor.request("post", url, params, headers)
  File "/app/.venv/lib/python3.11/site-packages/stripe/api_requestor.py", line 121, in request
    resp = self.interpret_response(rbody, rcode, rheaders)
  File "/app/.venv/lib/python3.11/site-packages/stripe/api_requestor.py", line 373, in interpret_response
    self.handle_error_response(rbody, rcode, resp.data, resp.headers)
  File "/app/.venv/lib/python3.11/site-packages/stripe/error.py", line 131, in handle_error_response
    raise exceptions.CardError.from_dict(resp.data, headers=resp.headers)
stripe.error.CardError: Your card was declined. Request id: req_abc123

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/app/src/routes/order.py", line 45, in create_order
    result = order_service.process_payment(order.id, payment_method)
  File "/app/src/services/order.py", line 78, in process_payment
    result = self.payment.charge(order.total_amount, payment_method)
  File "/app/src/services/payment.py", line 70, in charge
    raise
stripe.error.CardError: Your card was declined.
'''


def build_production_incident_scenario() -> list:
    """模拟生产事故排查完整流程（60+ 轮，含大日志和堆栈）。

    流程：
    1. 用户报告 /api/orders 接口 500 错误
    2. Agent 读取应用日志（50KB，触发 L3）
    3. 定位到 payment 相关错误
    4. 读取订单服务、支付服务、库存服务源码
    5. 读取配置文件
    6. 分析堆栈跟踪
    7. 发现两个 bug：支付服务异常未捕获 + 库存竞态条件
    8. 修复支付服务（捕获异常返回 PaymentResult）
    9. 修复库存服务（使用 Redis 原子 DECR）
    10. 读取修复后的代码确认
    11. 运行测试验证
    12. 搜索其他受影响的调用点
    13. 添加集成测试
    14. 运行全套测试
    15. 总结根因和修复方案

    数据规模：60+ 消息，含 50KB 日志 tool_result，总量 > 80KB
    触发层级：L1（>50消息）+ L2（多 tool_result）+ L3（50KB 日志）+ L4（总量>50KB）
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"incident-{tid}"

    # === 阶段 1：问题报告与初步排查 ===
    msgs.append(user_text(
        "生产环境告警：/api/orders POST 接口在过去 30 分钟内返回了 47 次 500 错误，"
        "影响约 23 个订单。监控显示错误从 09:15 开始集中出现。"
        "请排查根因并修复。日志在 /var/log/app/app.log。"
    ))

    # 读取应用日志（50KB，触发 L3 budget）
    msgs.append(assistant_with_tools(
        "我先读取应用日志，定位 09:15 之后的错误。",
        [_tool_use_block(nid(), "bash",
                         command="tail -n 5000 /var/log/app/app.log | grep -A5 'ERROR'")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", APP_LOG_CONTENT))

    # 读取错误统计
    msgs.append(assistant_with_tools(
        "日志显示大量 payment 相关的 ERROR。我统计一下错误类型分布。",
        [_tool_use_block(nid(), "bash",
                         command="grep 'ERROR' /var/log/app/app.log | awk '{print $4}' | sort | uniq -c | sort -rn | head -20")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    "  47 api.order ERROR order_id=null status=500\n"
                                    "  12 db ERROR connection_pool_exhausted\n"
                                    "   8 cache ERROR redis_timeout\n"
                                    "   3 gateway.stripe ERROR card_declined"))

    # 读取堆栈跟踪
    msgs.append(assistant_with_tools(
        "主要错误来自 api.order，47 次 500。我提取其中一个完整的堆栈跟踪。",
        [_tool_use_block(nid(), "bash",
                         command="grep -A30 'Traceback' /var/log/app/app.log | head -60")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", STACK_TRACE_OUTPUT))

    # === 阶段 2：代码定位与分析 ===
    msgs.append(user_text(
        "堆栈显示问题出在 payment.charge 抛出了 stripe.error.CardError，"
        "但上层 order.process_payment 没有捕获，导致 500。请深入分析。"
    ))

    # 读取订单服务源码
    msgs.append(assistant_with_tools(
        "我先读取订单服务源码，看 process_payment 的实现。",
        [_tool_use_block(nid(), "read_file", path="src/services/order.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", ORDER_SERVICE_PY))

    # 读取支付服务源码
    msgs.append(assistant_with_tools(
        "process_payment 第 78 行直接调用 self.payment.charge()，没有 try/except。"
        "我读取支付服务看 charge() 的实现。",
        [_tool_use_block(nid(), "read_file", path="src/services/payment.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", PAYMENT_SERVICE_PY))

    # 读取库存服务源码
    msgs.append(assistant_with_tools(
        "支付服务的 charge() 第 70 行 `raise` 重新抛出了异常，这就是 500 的根因。"
        "另外我注意到日志中有 12 次 connection_pool_exhausted，可能还有其他问题。"
        "我先读取库存服务，看是否有并发问题。",
        [_tool_use_block(nid(), "read_file", path="src/services/inventory.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", INVENTORY_SERVICE_PY))

    # 读取配置
    msgs.append(assistant_with_tools(
        "库存服务的 check_and_reserve 用 GET+SET 而非原子 DECR，存在竞态条件。"
        "我读取配置确认 Redis 和数据库参数。",
        [_tool_use_block(nid(), "read_file", path="src/config.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", CONFIG_PY))

    # 搜索 process_payment 的其他调用点
    msgs.append(assistant_with_tools(
        "我搜索 process_payment 的所有调用点，确认修复范围。",
        [_tool_use_block(nid(), "bash",
                         command="grep -rn 'process_payment\\|payment.charge' src/ tests/ --include='*.py'")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    "src/services/order.py:62:    def process_payment(self, order_id: int, payment_method: str) -> bool:\n"
                                    "src/services/order.py:78:        result = self.payment.charge(order.total_amount, payment_method)\n"
                                    "src/routes/order.py:45:    result = order_service.process_payment(order.id, payment_method)\n"
                                    "src/tasks/payment_retry.py:18:    order_service.process_payment(order.id, method)\n"
                                    "tests/test_order_service.py:89:    def test_process_payment_success(self):\n"
                                    "tests/test_order_service.py:102:    def test_process_payment_card_declined(self):\n"
                                    "tests/test_order_service.py:115:    def test_process_payment_timeout(self):"))

    # 读取路由文件
    msgs.append(assistant_with_tools(
        "有 2 个调用点（routes/order.py 和 tasks/payment_retry.py）。"
        "我读取路由文件看错误处理。",
        [_tool_use_block(nid(), "read_file", path="src/routes/order.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    '"""src/routes/order.py - 订单路由。"""\n'
                                    'from flask import Blueprint, request, jsonify\n'
                                    'from src.services.order import OrderService\n\n'
                                    'bp = Blueprint("orders", __name__)\n\n\n'
                                    '@bp.route("/api/orders", methods=["POST"])\n'
                                    'def create_order():\n'
                                    '    """创建订单接口。"""\n'
                                    '    data = request.get_json()\n'
                                    '    user_id = data.get("user_id")\n'
                                    '    items = data.get("items", [])\n'
                                    '    payment_method = data.get("payment_method")\n'
                                    '    try:\n'
                                    '        order_service = OrderService(db.session)\n'
                                    '        order = order_service.create_order(user_id, items)\n'
                                    '        result = order_service.process_payment(order.id, payment_method)\n'
                                    '        if result:\n'
                                    '            return jsonify({"order_id": order.id, "status": "paid"}), 200\n'
                                    '        else:\n'
                                    '            return jsonify({"order_id": order.id, "status": "payment_failed"}), 400\n'
                                    '    except ValueError as e:\n'
                                    '        return jsonify({"error": str(e)}), 400\n'
                                    '    # BUG: 没有捕获 stripe.error.CardError 等第三方异常'))

    # === 阶段 3：修复 bug ===
    msgs.append(user_text(
        "分析清楚了。有两个 bug 需要修复：\n"
        "1. payment.py 的 charge() 不应该 raise，应该返回 PaymentResult(success=False)\n"
        "2. inventory.py 的 check_and_reserve() 应该用 Redis 原子 DECR 避免竞态\n"
        "请修复这两个 bug。"
    ))

    # 修复支付服务
    msgs.append(assistant_with_tools(
        "先修复支付服务：把 raise 改为返回 PaymentResult。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/services/payment.py",
                         old_text="        except Exception as e:\n            payment.status = \"error\"\n            self.db.add(PaymentLog(\n                payment_id=payment.id,\n                message=f\"Exception: {e}\",\n            ))\n            self.db.commit()\n            raise  # BUG: 应该返回 PaymentResult 而不是 raise",
                         new_text="        except Exception as e:\n            payment.status = \"error\"\n            self.db.add(PaymentLog(\n                payment_id=payment.id,\n                message=f\"Exception: {e}\",\n            ))\n            self.db.commit()\n            return PaymentResult(success=False, error=str(e))")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", "Edited src/services/payment.py"))

    # 修复库存服务
    msgs.append(assistant_with_tools(
        "修复库存服务：用 Redis 原子 DECRBY 替代 GET+SET。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/services/inventory.py",
                         old_text="        # BUG: 没有使用 Redis 原子 DECR，而是先 GET 再 SET，存在竞态条件\n        current = self.get_stock(product_id)\n        if current < quantity:\n            return False\n        new_stock = current - quantity\n        self.cache.set(cache_key, new_stock, ex=300)",
                         new_text="        # 使用 Redis 原子 DECRBY 避免竞态条件\n        pipe = self.cache.pipeline()\n        pipe.decrby(cache_key, quantity)\n        pipe.expire(cache_key, 300)\n        results = pipe.execute()\n        new_stock = results[0]\n        if new_stock < 0:\n            # 库存不足，回滚\n            pipe.incrby(cache_key, quantity)\n            pipe.execute()\n            return False")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", "Edited src/services/inventory.py"))

    # 读取修复后的支付服务确认
    msgs.append(assistant_with_tools(
        "我读取修复后的支付服务确认修改正确。",
        [_tool_use_block(nid(), "read_file", path="src/services/payment.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    PAYMENT_SERVICE_PY.replace(
                                        "            raise  # BUG: 应该返回 PaymentResult 而不是 raise",
                                        "            return PaymentResult(success=False, error=str(e))")))

    # 读取修复后的库存服务确认
    msgs.append(assistant_with_tools(
        "读取修复后的库存服务确认。",
        [_tool_use_block(nid(), "read_file", path="src/services/inventory.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    INVENTORY_SERVICE_PY.replace(
                                        "        # BUG: 没有使用 Redis 原子 DECR，而是先 GET 再 SET，存在竞态条件\n        current = self.get_stock(product_id)\n        if current < quantity:\n            return False\n        new_stock = current - quantity\n        self.cache.set(cache_key, new_stock, ex=300)",
                                        "        # 使用 Redis 原子 DECRBY 避免竞态条件\n        pipe = self.cache.pipeline()\n        pipe.decrby(cache_key, quantity)\n        pipe.expire(cache_key, 300)\n        results = pipe.execute()\n        new_stock = results[0]\n        if new_stock < 0:\n            pipe.incrby(cache_key, quantity)\n            pipe.execute()\n            return False")))

    # === 阶段 4：测试验证 ===
    msgs.append(assistant_with_tools(
        "修复完成。我运行相关单元测试验证。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/test_order_service.py tests/test_payment_service.py tests/test_inventory_service.py -v")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    "============================= test session starts ==============================\n"
                                    "collected 18 items\n\n"
                                    "tests/test_order_service.py::test_create_order PASSED\n"
                                    "tests/test_order_service.py::test_process_payment_success PASSED\n"
                                    "tests/test_order_service.py::test_process_payment_card_declined PASSED\n"
                                    "tests/test_order_service.py::test_process_payment_timeout PASSED\n"
                                    "tests/test_payment_service.py::test_charge_success PASSED\n"
                                    "tests/test_payment_service.py::test_charge_card_declined PASSED .\n"
                                    "tests/test_payment_service.py::test_charge_network_error PASSED\n"
                                    "tests/test_inventory_service.py::test_get_stock PASSED\n"
                                    "tests/test_inventory_service.py::test_check_and_reserve_success PASSED\n"
                                    "tests/test_inventory_service.py::test_check_and_reserve_insufficient PASSED\n"
                                    "tests/test_inventory_service.py::test_concurrent_reserve PASSED\n"
                                    "\n============================== 18 passed in 2.34s ==============================="))

    # 搜索是否还有其他 raise 需要修复
    msgs.append(assistant_with_tools(
        "测试全部通过。我搜索是否还有其他类似的 raise 模式需要修复。",
        [_tool_use_block(nid(), "bash",
                         command="grep -rn 'raise$' src/services/ --include='*.py'")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    "src/services/payment.py:70:            return PaymentResult(success=False, error=str(e))\n"
                                    "# 已修复，无其他裸 raise"))

    # 读取 retry 任务
    msgs.append(assistant_with_tools(
        "确认没有其他裸 raise。我读取 payment_retry.py 确认它也能正确处理。",
        [_tool_use_block(nid(), "read_file", path="src/tasks/payment_retry.py")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}",
                                    '"""src/tasks/payment_retry.py - 支付重试任务。"""\n'
                                    'from celery import shared_task\n'
                                    'from src.services.order import OrderService\n\n\n'
                                    '@shared_task\n'
                                    'def retry_payment(order_id: int, method: str):\n'
                                    '    """重试失败的支付。"""\n'
                                    '    order_service = OrderService(db.session)\n'
                                    '    try:\n'
                                    '        result = order_service.process_payment(order_id, method)\n'
                                    '        if not result:\n'
                                    '            # 记录重试失败\n'
                                    '            order_service.mark_payment_retry_failed(order_id)\n'
                                    '    except Exception as e:\n'
                                    '        # 记录异常但不 raise（Celery 会自动重试）\n'
                                    '        order_service.log_retry_error(order_id, str(e))\n'
                                    '    finally:\n'
                                    '        db.session.close()'))

    # 添加集成测试
    msgs.append(assistant_with_tools(
        "retry 任务已有 try/except，没问题。我添加一个集成测试覆盖卡被拒绝场景。",
        [_tool_use_block(nid(), "edit_file",
                         path="tests/test_order_integration.py",
                         old_text="# TODO: 添加集成测试",
                         new_text="def test_order_with_declined_card_returns_400_not_500():\n"
                                  '    """集成测试：卡被拒绝时应返回 400 而非 500。"""\n'
                                  "    from unittest.mock import patch\n"
                                  "    with patch('src.gateway.stripe_gateway.charge') as mock:\n"
                                  "        mock.side_effect = stripe.error.CardError('declined', 'param', 'code')\n"
                                  "        response = client.post('/api/orders', json={\n"
                                  "            'user_id': 1,\n"
                                  "            'items': [{'product_id': 1, 'quantity': 1}],\n"
                                  "            'payment_method': 'stripe',\n"
                                  "        })\n"
                                  "        assert response.status_code == 400\n"
                                  "        assert 'payment_failed' in response.json['status']\n"
                                  "\n"
                                  "def test_concurrent_order_no_oversell():\n"
                                  '    """并发下单不应超卖。"""\n'
                                  "    from concurrent.futures import ThreadPoolExecutor\n"
                                  "    with ThreadPoolExecutor(max_workers=10) as pool:\n"
                                  "        futures = [pool.submit(create_order, user_id=1, "
                                  "items=[{'product_id': 1, 'quantity': 1}]) for _ in range(10)]\n"
                                  "        results = [f.result() for f in futures]\n"
                                  "    success_count = sum(1 for r in results if r.get('status') == 'paid')\n"
                                  "    assert success_count <= initial_stock  # 不超卖")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", "Edited tests/test_order_integration.py"))

    # 运行全套测试
    msgs.append(assistant_with_tools(
        "运行全套测试确认无回归。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/ -v --cov=src --cov-report=term-missing")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", TEST_REPORT_CONTENT))

    # 检查修复后的日志
    msgs.append(assistant_with_tools(
        "测试通过。我检查修复后是否还有 500 错误。",
        [_tool_use_block(nid(), "bash",
                         command="tail -n 100 /var/log/app/app.log | grep -c 'status=500'")]
    ))
    msgs.append(tool_result_message(f"incident-{tid}", "0"))

    # === 阶段 5：总结 ===
    msgs.append(assistant_text(
        "生产事故排查完成。根因分析和修复总结：\n\n"
        "## 根因\n"
        "1. **支付服务异常未捕获**（主因）：PaymentService.charge() 在第 70 行 `raise` 重新抛出第三方异常"
        "（stripe.error.CardError），上层 OrderService.process_payment() 没有 try/except，"
        "导致 /api/orders 返回 500。影响 47 个订单。\n"
        "2. **库存竞态条件**（潜在问题）：InventoryService.check_and_reserve() 用 Redis GET+SET "
        "而非原子 DECRBY，高并发下可能超卖。\n\n"
        "## 修复\n"
        "1. payment.py: `raise` → `return PaymentResult(success=False, error=str(e))`\n"
        "2. inventory.py: GET+SET → Redis pipeline DECRBY + expire，失败时回滚\n\n"
        "## 验证\n"
        "- 18 个单元测试全部通过（含新增并发测试）\n"
        "- 245 个测试全套通过，覆盖率 88%\n"
        "- 修复后日志中 500 错误数：0\n"
        "- 搜索确认无其他裸 raise"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 6：大规模测试套件调试（60+ 轮，含大测试报告）
# ═══════════════════════════════════════════════════════════

# 测试套件调试场景用到的源码
VALIDATOR_PY = '''"""src/validators.py - 输入验证器。"""
import re
from typing import Any, List, Optional
from email_validator import validate_email as _validate_email


class ValidationError(Exception):
    """验证错误。"""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


class UserValidator:
    """用户数据验证器。"""

    # BUG: 用户名正则不允许中文，但产品需求要求支持
    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")

    def validate_username(self, username: str) -> str:
        """验证用户名。"""
        if not username:
            raise ValidationError("username", "用户名不能为空")
        if not self.USERNAME_PATTERN.match(username):
            raise ValidationError("username", "用户名只能包含字母、数字、下划线，长度 3-20")
        return username

    def validate_email(self, email: str) -> str:
        """验证邮箱。"""
        if not email:
            raise ValidationError("email", "邮箱不能为空")
        try:
            result = _validate_email(email, check_deliverability=False)
            return result.email
        except Exception:
            raise ValidationError("email", "邮箱格式无效")

    def validate_password(self, password: str) -> str:
        """验证密码强度。"""
        if len(password) < 8:
            raise ValidationError("password", "密码至少 8 位")
        if not re.search(r"[A-Z]", password):
            raise ValidationError("password", "密码必须包含大写字母")
        if not re.search(r"[a-z]", password):
            raise ValidationError("password", "密码必须包含小写字母")
        if not re.search(r"[0-9]", password):
            raise ValidationError("password", "密码必须包含数字")
        # BUG: 没有检查特殊字符，但需求要求
        return password

    def validate_age(self, age: Any) -> int:
        """验证年龄。"""
        try:
            age_int = int(age)
        except (TypeError, ValueError):
            raise ValidationError("age", "年龄必须是整数")
        if age_int < 0 or age_int > 150:
            raise ValidationError("age", "年龄必须在 0-150 之间")
        # BUG: 未成年注册需要家长同意，但没有检查
        return age_int

    def validate_profile(self, data: dict) -> dict:
        """验证完整用户资料。"""
        result = {}
        result["username"] = self.validate_username(data.get("username", ""))
        result["email"] = self.validate_email(data.get("email", ""))
        result["password"] = self.validate_password(data.get("password", ""))
        if "age" in data:
            result["age"] = self.validate_age(data["age"])
        return result
'''

ORDER_VALIDATOR_PY = '''"""src/order_validator.py - 订单验证器。"""
from typing import List
from src.validators import ValidationError


class OrderValidator:
    """订单数据验证器。"""

    def validate_items(self, items: List[dict]) -> List[dict]:
        """验证订单商品列表。"""
        if not items:
            raise ValidationError("items", "商品列表不能为空")
        if len(items) > 50:
            raise ValidationError("items", "单个订单最多 50 种商品")

        result = []
        for i, item in enumerate(items):
            if "product_id" not in item:
                raise ValidationError(f"items[{i}]", "缺少 product_id")
            if "quantity" not in item:
                raise ValidationError(f"items[{i}]", "缺少 quantity")

            try:
                product_id = int(item["product_id"])
                if product_id <= 0:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValidationError(f"items[{i}]", "product_id 必须是正整数")

            try:
                quantity = int(item["quantity"])
                if quantity <= 0 or quantity > 99:
                    raise ValueError()
            except (TypeError, ValueError):
                raise ValidationError(f"items[{i}]", "quantity 必须是 1-99 的整数")

            result.append({"product_id": product_id, "quantity": quantity})
        return result

    def validate_payment_method(self, method: str) -> str:
        """验证支付方式。"""
        valid_methods = ["stripe", "alipay", "wechat", "balance"]
        if method not in valid_methods:
            raise ValidationError("payment_method",
                                  f"不支持的支付方式，可选：{', '.join(valid_methods)}")
        return method

    def validate_order(self, data: dict) -> dict:
        """验证完整订单数据。"""
        result = {}
        result["items"] = self.validate_items(data.get("items", []))
        result["payment_method"] = self.validate_payment_method(
            data.get("payment_method", ""))
        if "coupon_code" in data:
            result["coupon_code"] = self.validate_coupon(data["coupon_code"])
        return result

    def validate_coupon(self, code: str) -> str:
        """验证优惠券码。"""
        if not code:
            raise ValidationError("coupon_code", "优惠券码不能为空")
        if len(code) > 20:
            raise ValidationError("coupon_code", "优惠券码最长 20 字符")
        # BUG: 没有验证格式，应该检查是否为有效券码
        return code
'''

LARGE_TEST_OUTPUT = '''============================= test session starts ==============================
platform win32 -- Python 3.11.5, pytest-7.4.0, plugg-1.0.0
rootdir: D:\\project, configfile: pytest.ini
plugins: cov-4.1.0, mock-3.12.0, xdist-3.5.0, asyncio-0.21.0
collected 245 items

tests/test_user_validator.py::TestUserValidator::test_valid_username PASSED
tests/test_user_validator.py::TestUserValidator::test_username_too_short FAILED
tests/test_user_validator.py::TestUserValidator::test_username_too_long FAILED
tests/test_user_validator.py::TestUserValidator::test_username_chinese FAILED
tests/test_user_validator.py::TestUserValidator::test_username_special_chars PASSED
tests/test_user_validator.py::TestUserValidator::test_valid_email PASSED
tests/test_user_validator.py::TestUserValidator::test_invalid_email PASSED
tests/test_user_validator.py::TestUserValidator::test_empty_email PASSED
tests/test_user_validator.py::TestUserValidator::test_password_weak FAILED
tests/test_user_validator.py::TestUserValidator::test_password_no_special FAILED
tests/test_user_validator.py::TestUserValidator::test_password_valid PASSED
tests/test_user_validator.py::TestUserValidator::test_age_valid PASSED
tests/test_user_validator.py::TestUserValidator::test_age_negative PASSED
tests/test_user_validator.py::TestUserValidator::test_age_too_old PASSED
tests/test_user_validator.py::TestUserValidator::test_age_minor PASSED
tests/test_user_validator.py::TestUserValidator::test_age_string PASSED

tests/test_order_validator.py::TestOrderValidator::test_valid_items PASSED
tests/test_order_validator.py::TestOrderValidator::test_empty_items PASSED
tests/test_order_validator.py::TestOrderValidator::test_too_many_items PASSED
tests/test_order_validator.py::TestOrderValidator::test_invalid_product_id PASSED
tests/test_order_validator.py::TestOrderValidator::test_invalid_quantity PASSED
tests/test_order_validator.py::TestOrderValidator::test_valid_payment_method PASSED
tests/test_order_validator.py::TestOrderValidator::test_invalid_payment_method PASSED
tests/test_order_validator.py::TestOrderValidator::test_valid_coupon PASSED
tests/test_order_validator.py::TestOrderValidator::test_invalid_coupon FAILED

=================================== FAILURES ===================================
_____________________ TestUserValidator.test_username_too_short _____________________

    def test_username_too_short(self):
        """用户名太短应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
>           validator.validate_username("ab")
E           AssertionError: ValidationError not raised

src/validators.py:23: AssertionError
_____________________ TestUserValidator.test_username_chinese _____________________

    def test_username_chinese(self):
        """中文用户名应通过验证（产品需求 v2.0）。"""
>       validator.validate_username("张三")
E       ValidationError: username: 用户名只能包含字母、数字、下划线，长度 3-20

src/validators.py:23: ValidationError
_____________________ TestUserValidator::test_password_no_special _____________________

    def test_password_no_special(self):
        """密码必须包含特殊字符（安全需求 v1.5）。"""
        with pytest.raises(ValidationError):
>           validator.validate_password("Abcd1234")
E           AssertionError: ValidationError not raised

src/validators.py:42: AssertionError
_____________________ TestOrderValidator::test_invalid_coupon _____________________

    def test_invalid_coupon(self):
        """无效优惠券码应抛出 ValidationError。"""
        with pytest.raises(ValidationError):
>           validator.validate_coupon("INVALID")
E       AssertionError: ValidationError not raised

src/order_validator.py:58: AssertionError
========================= 5 failed, 240 passed in 3.45s ==========================
'''


def build_test_suite_debugging_scenario() -> list:
    """模拟大规模测试套件调试完整流程（60+ 轮，含大测试报告）。

    流程：
    1. CI 报告 5 个测试失败
    2. Agent 读取完整测试输出（大文件，触发 L3）
    3. 逐个分析失败原因
    4. 读取验证器源码
    5. 修复每个 bug（用户名正则、密码特殊字符、优惠券格式等）
    6. 读取测试文件
    7. 补充测试用例
    8. 运行测试验证
    9. 运行全套测试
    10. 代码审查

    数据规模：60+ 消息，含 25KB+ 测试报告，总量 > 50KB
    触发层级：L1（>50消息）+ L2（多 tool_result）+ L4（总量>50KB）
    """
    msgs = []
    tid = 0
    def nid():
        nonlocal tid
        tid += 1
        return f"testdbg-{tid}"

    # === 阶段 1：CI 失败报告 ===
    msgs.append(user_text(
        "CI 流水线报告 5 个测试失败，都在验证器相关测试中：\n"
        "- test_username_too_short: ValidationError 未抛出\n"
        "- test_username_too_long: ValidationError 未抛出\n"
        "- test_username_chinese: 中文用户名应通过但抛了异常\n"
        "- test_password_no_special: 缺少特殊字符应抛出但没抛\n"
        "- test_invalid_coupon: 无效券码应抛出但没抛\n\n"
        "请修复这些失败的测试。"
    ))

    # 读取完整测试输出
    msgs.append(assistant_with_tools(
        "我先读取完整的 CI 测试输出，了解失败详情。",
        [_tool_use_block(nid(), "bash", command="cat pytest_output.txt")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", LARGE_TEST_OUTPUT))

    # 读取用户验证器源码
    msgs.append(assistant_with_tools(
        "5 个失败：3 个在 UserValidator，1 个在密码验证，1 个在优惠券验证。"
        "我先读取用户验证器源码。",
        [_tool_use_block(nid(), "read_file", path="src/validators.py")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", VALIDATOR_PY))

    # 读取订单验证器源码
    msgs.append(assistant_with_tools(
        "现在读取订单验证器源码，看优惠券验证的问题。",
        [_tool_use_block(nid(), "read_file", path="src/order_validator.py")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", ORDER_VALIDATOR_PY))

    # 读取测试文件
    msgs.append(assistant_with_tools(
        "我读取测试文件，了解测试期望。",
        [_tool_use_block(nid(), "read_file", path="tests/test_user_validator.py")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    '"""tests/test_user_validator.py"""\n'
                                    "import pytest\n"
                                    "from src.validators import ValidationError, UserValidator\n\n\n"
                                    "class TestUserValidator:\n"
                                    "    def setup_method(self):\n"
                                    "        self.validator = UserValidator()\n\n"
                                    "    def test_username_too_short(self):\n"
                                    "        with pytest.raises(ValidationError):\n"
                                    "            self.validator.validate_username('ab')\n\n"
                                    "    def test_username_too_long(self):\n"
                                    "        with pytest.raises(ValidationError):\n"
                                    "            self.validator.validate_username('a' * 21)\n\n"
                                    "    def test_username_chinese(self):\n"
                                    "        # 产品需求 v2.0：支持中文用户名\n"
                                    "        result = self.validator.validate_username('张三')\n"
                                    "        assert result == '张三'\n\n"
                                    "    def test_password_no_special(self):\n"
                                    "        with pytest.raises(ValidationError):\n"
                                    "            self.validator.validate_password('Abcd1234')\n\n"
                                    "    def test_password_valid(self):\n"
                                    "        result = self.validator.validate_password('Abcd1234!')\n"
                                    "        assert result == 'Abcd1234!'"))

    # === 阶段 2：逐个修复 ===
    msgs.append(user_text("分析清楚了，请逐个修复这些 bug。"))

    # 修复 1: 用户名正则（支持中文）
    msgs.append(assistant_with_tools(
        "Bug 1: 用户名正则不支持中文。修改正则以支持中文（\\\\u4e00-\\\\u9fff）。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/validators.py",
                         old_text='    # BUG: 用户名正则不允许中文，但产品需求要求支持\n    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")',
                         new_text='    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\\u4e00-\\u9fff]{3,20}$")')]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "Edited src/validators.py"))

    # 修复 2: 用户名长度检查（正则 {3,20} 在中文时按字符数算，但 Python re 默认按字符）
    msgs.append(assistant_with_tools(
        "Bug 2: test_username_too_short 和 too_long 失败。"
        "检查发现正则 {3,20} 应该正确。我运行测试确认。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/test_user_validator.py::TestUserValidator::test_username_too_short tests/test_user_validator.py::TestUserValidator::test_username_too_long -v")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_short PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_long PASSED\n"
                                    "2 passed in 0.12s"))

    # 修复 3: 密码特殊字符检查
    msgs.append(assistant_with_tools(
        "Bug 3: 密码缺少特殊字符检查。添加特殊字符验证。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/validators.py",
                         old_text="        if not re.search(r\"[0-9]\", password):\n            raise ValidationError(\"password\", \"密码必须包含数字\")\n        # BUG: 没有检查特殊字符，但需求要求\n        return password",
                         new_text="        if not re.search(r\"[0-9]\", password):\n            raise ValidationError(\"password\", \"密码必须包含数字\")\n        if not re.search(r\"[!@#$%^&*()_+\\-=\\[\\]{};:'\\\",.<>/?]\", password):\n            raise ValidationError(\"password\", \"密码必须包含特殊字符\")\n        return password")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "Edited src/validators.py"))

    # 修复 4: 优惠券格式验证
    msgs.append(assistant_with_tools(
        "Bug 4: 优惠券没有格式验证。添加格式检查（大写字母+数字，8-20 位）。",
        [_tool_use_block(nid(), "edit_file",
                         path="src/order_validator.py",
                         old_text="        # BUG: 没有验证格式，应该检查是否为有效券码\n        return code",
                         new_text="        import re\n        if not re.match(r'^[A-Z0-9]{8,20}$', code):\n            raise ValidationError(\"coupon_code\", \"优惠券码格式无效\")\n        return code")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "Edited src/order_validator.py"))

    # === 阶段 3：验证修复 ===
    msgs.append(assistant_with_tools(
        "4 个修复完成。运行之前失败的 5 个测试验证。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/test_user_validator.py tests/test_order_validator.py -v")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    "============================= test session starts ==============================\n"
                                    "collected 24 items\n\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_valid_username PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_short PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_long PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_chinese PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_special_chars PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_valid_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_invalid_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_empty_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_weak PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_no_special PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_valid PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_valid_items PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_empty_items PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_too_many_items PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_invalid_product_id PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_invalid_quantity PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_valid_payment_method PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_invalid_payment_method PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_valid_coupon PASSED\n"
                                    "tests/test_order_validator.py::TestOrderValidator::test_invalid_coupon PASSED\n"
                                    "\n============================== 24 passed in 0.89s ==============================="))

    # === 阶段 4：补充测试用例 ===
    msgs.append(user_text("测试全部通过了。请补充一些边界测试用例，增强覆盖率。"))

    # 读取现有测试确认覆盖
    msgs.append(assistant_with_tools(
        "我先检查现有测试覆盖率，找出未覆盖的路径。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/test_user_validator.py tests/test_order_validator.py --cov=src/validators --cov=src/order_validator --cov-report=term-missing")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    "Name                          Stmts   Miss  Cover   Missing\n"
                                    "-----------------------------------------------------------------\n"
                                    "src/validators.py                45      5    89%   38-42, 55\n"
                                    "src/order_validator.py           35      3    91%   48-50\n"
                                    "-----------------------------------------------------------------\n"
                                    "TOTAL                            80      8    90%"))

    # 补充测试
    msgs.append(assistant_with_tools(
        "validators.py 第 38-42 行（密码特殊字符）和第 55 行（未成年检查）未覆盖。"
        "我补充测试用例。",
        [_tool_use_block(nid(), "edit_file",
                         path="tests/test_user_validator.py",
                         old_text="    def test_password_valid(self):",
                         new_text="    def test_password_no_uppercase(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_password('abcd1234!')\n\n"
                                  "    def test_password_no_lowercase(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_password('ABCD1234!')\n\n"
                                  "    def test_password_no_digit(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_password('Abcdefgh!')\n\n"
                                  "    def test_username_with_chinese_and_alnum(self):\n"
                                  "        result = self.validator.validate_username('张三123')\n"
                                  "        assert result == '张三123'\n\n"
                                  "    def test_password_valid(self):")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "Edited tests/test_user_validator.py"))

    # 补充订单验证器测试
    msgs.append(assistant_with_tools(
        "补充订单验证器的边界测试。",
        [_tool_use_block(nid(), "edit_file",
                         path="tests/test_order_validator.py",
                         old_text="    def test_invalid_coupon(self):",
                         new_text="    def test_coupon_too_long(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_coupon('A' * 21)\n\n"
                                  "    def test_coupon_lowercase(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_coupon('abc12345')\n\n"
                                  "    def test_items_with_zero_quantity(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_items([{'product_id': 1, 'quantity': 0}])\n\n"
                                  "    def test_items_with_negative_product_id(self):\n"
                                  "        with pytest.raises(ValidationError):\n"
                                  "            self.validator.validate_items([{'product_id': -1, 'quantity': 1}])\n\n"
                                  "    def test_invalid_coupon(self):")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "Edited tests/test_order_validator.py"))

    # 运行新测试
    msgs.append(assistant_with_tools(
        "运行补充的测试用例验证。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/test_user_validator.py tests/test_order_validator.py -v --cov=src/validators --cov=src/order_validator --cov-report=term-missing")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    "============================= test session starts ==============================\n"
                                    "collected 32 items\n\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_valid_username PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_short PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_too_long PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_chinese PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_username_special_chars PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_valid_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_invalid_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_empty_email PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_weak PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_no_uppercase PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_no_lowercase PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_no_digit PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_no_special PASSED\n"
                                    "tests/test_user_validator.py::TestUserValidator::test_password_valid PASSED\n"
                                    "tests/test_order_validator.py ... 8 passed\n"
                                    "\n------------------------------ coverage ------------------------------\n"
                                    "Name                          Stmts   Miss  Cover   Missing\n"
                                    "-----------------------------------------------------------------\n"
                                    "src/validators.py                45      0   100%\n"
                                    "src/order_validator.py           35      0   100%\n"
                                    "-----------------------------------------------------------------\n"
                                    "TOTAL                            80      0   100%\n"
                                    "\n============================== 32 passed in 1.02s ==============================="))

    # === 阶段 5：全套测试 ===
    msgs.append(assistant_with_tools(
        "覆盖率 100%。运行全套测试确认无回归。",
        [_tool_use_block(nid(), "bash",
                         command="python -m pytest tests/ -v --cov=src --cov-report=term-missing --cov-branch")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", TEST_REPORT_CONTENT))

    # 代码风格检查
    msgs.append(assistant_with_tools(
        "运行 flake8 检查代码风格。",
        [_tool_use_block(nid(), "bash", command="flake8 src/validators.py src/order_validator.py")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}", "(no output)"))

    # 搜索是否还有其他类似的验证遗漏
    msgs.append(assistant_with_tools(
        "我搜索是否还有其他验证器缺少特殊字符检查。",
        [_tool_use_block(nid(), "bash",
                         command="grep -rn 'def validate' src/ --include='*.py'")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    "src/validators.py:15:    def validate_username(self, username: str) -> str:\n"
                                    "src/validators.py:25:    def validate_email(self, email: str) -> str:\n"
                                    "src/validators.py:35:    def validate_password(self, password: str) -> str:\n"
                                    "src/validators.py:48:    def validate_age(self, age: Any) -> int:\n"
                                    "src/validators.py:58:    def validate_profile(self, data: dict) -> dict:\n"
                                    "src/order_validator.py:10:    def validate_items(self, items: List[dict]) -> List[dict]:\n"
                                    "src/order_validator.py:38:    def validate_payment_method(self, method: str) -> str:\n"
                                    "src/order_validator.py:46:    def validate_order(self, data: dict) -> dict:\n"
                                    "src/order_validator.py:52:    def validate_coupon(self, code: str) -> str:"))

    # 读取修复后的源码确认
    msgs.append(assistant_with_tools(
        "确认修复后的验证器源码。",
        [_tool_use_block(nid(), "read_file", path="src/validators.py")]
    ))
    msgs.append(tool_result_message(f"testdbg-{tid}",
                                    VALIDATOR_PY.replace(
                                        '    # BUG: 用户名正则不允许中文，但产品需求要求支持\n    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,20}$")',
                                        '    USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\\u4e00-\\u9fff]{3,20}$")').replace(
                                        "        # BUG: 没有检查特殊字符，但需求要求\n        return password",
                                        '        if not re.search(r"[!@#$%^&*()_+\\-=\\[\\]{};:\'\\\",.<>/?]", password):\n            raise ValidationError("password", "密码必须包含特殊字符")\n        return password')))

    # === 阶段 6：总结 ===
    msgs.append(assistant_text(
        "测试套件调试完成。修复了 5 个失败测试，补充了 8 个边界测试用例：\n\n"
        "## 修复清单\n"
        "1. **用户名正则**：添加 \\\\u4e00-\\\\u9fff 支持中文用户名（产品需求 v2.0）\n"
        "2. **密码特殊字符**：添加 [!@#$%^&*...] 特殊字符检查（安全需求 v1.5）\n"
        "3. **优惠券格式**：添加 ^[A-Z0-9]{8,20}$ 正则验证\n\n"
        "## 新增测试\n"
        "- test_password_no_uppercase / no_lowercase / no_digit\n"
        "- test_username_with_chinese_and_alnum\n"
        "- test_coupon_too_long / coupon_lowercase\n"
        "- test_items_with_zero_quantity / negative_product_id\n\n"
        "## 结果\n"
        "- 32 个验证器测试全部通过\n"
        "- 245 个全套测试全部通过\n"
        "- 验证器覆盖率：89% → 100%\n"
        "- flake8 无问题"
    ))
    return msgs


# ═══════════════════════════════════════════════════════════
#  真实场景 7：长调试会话（组合多场景，100+ 轮）
# ═══════════════════════════════════════════════════════════

def build_long_debug_session() -> list:
    """模拟一天的真实调试会话，组合多个场景，100+ 轮。

    顺序：bug 修复 → review → 功能实现 → 重构 → 第二个 bug 修复
    每个场景之间用 user_text 分隔，模拟用户连续提出多个任务。
    """
    msgs = []
    # 场景 1: bug 修复
    msgs.extend(build_bug_fix_scenario())
    msgs.append(user_text("好的，bug 修复完成。接下来帮我 review 一个 PR。"))

    # 场景 2: 代码 review
    msgs.extend(build_code_review_scenario())
    msgs.append(user_text("review 完成。现在请帮我实现一个新功能。"))

    # 场景 3: 功能实现
    msgs.extend(build_feature_impl_scenario())
    msgs.append(user_text("功能实现完成。还有一个重构任务。"))

    # 场景 4: 重构
    msgs.extend(build_refactor_scenario())
    msgs.append(user_text("重构完成。最后还有一个 bug 需要修复。"))

    # 场景 5: 第二个 bug 修复（简化版，触发更多 tool_result）
    msgs.extend(build_bug_fix_scenario())

    return msgs


def _build_app_log_content(size: int = 50000) -> str:
    """生成真实风格的应用日志内容，约 size 字符。

    模拟一个生产环境的应用日志，包含 INFO/WARN/ERROR/DEBUG 等级别，
    涵盖请求处理、数据库查询、缓存命中/未命中、外部 API 调用等典型事件。
    """
    import datetime
    lines = []
    levels = ["INFO", "WARN", "ERROR", "DEBUG"]
    components = ["api.auth", "api.user", "api.order", "db", "cache",
                  "middleware", "scheduler", "mailer", "worker"]
    paths = ["/api/users", "/api/orders", "/api/auth/login", "/api/auth/register",
             "/api/items", "/api/payments", "/api/admin/users"]
    current_size = 0
    line_idx = 0
    base_time = datetime.datetime(2026, 8, 5, 9, 0, 0)
    while current_size < size:
        ts = (base_time + datetime.timedelta(seconds=line_idx * 3)).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        level = levels[line_idx % len(levels)]
        comp = components[line_idx % len(components)]
        path = paths[line_idx % len(paths)]
        req_id = f"req-{0x1a2b + line_idx:08x}"
        if level == "INFO":
            if comp.startswith("api"):
                msg = f"{ts} [{level}] {comp} {req_id} {path} 200 status=200 ms={50 + (line_idx % 200)}"
            elif comp == "db":
                msg = f"{ts} [{level}] {comp} {req_id} query=SELECT * FROM users WHERE id=? params=(42,) ms={5 + (line_idx % 30)}"
            elif comp == "cache":
                hit = "HIT" if line_idx % 3 else "MISS"
                msg = f"{ts} [{level}] {comp} {req_id} key=user:42:profile action={hit} ms=1"
            elif comp == "middleware":
                msg = f"{ts} [{level}] {comp} {req_id} auth=ok user_id=42 role=admin ip=10.0.{line_idx % 255}.{(line_idx*7) % 255}"
            elif comp == "scheduler":
                msg = f"{ts} [{level}] {comp} job=cleanup-expired-sessions next_run=3600s"
            elif comp == "mailer":
                msg = f"{ts} [{level}] {comp} {req_id} to=user@example.com subject=verify template=welcome"
            elif comp == "worker":
                msg = f"{ts} [{level}] {comp} queue=email-queue picked task=email-{line_idx:05d}"
            else:
                msg = f"{ts} [{level}] {comp} {req_id} action=process"
        elif level == "WARN":
            if comp == "cache":
                msg = f"{ts} [{level}] {comp} {req_id} cache_size=1024MB threshold=900MB evicting=50 keys"
            elif comp == "db":
                msg = f"{ts} [{level}] {comp} {req_id} slow_query=2.3s query=SELECT * FROM orders JOIN items ON..."
            elif comp == "api.auth":
                msg = f"{ts} [{level}] {comp} {req_id} failed_login user=alice ip=10.0.0.5 attempts=3"
            else:
                msg = f"{ts} [{level}] {comp} {req_id} deprecated=true fallback=enabled"
        elif level == "ERROR":
            if comp == "api.order":
                msg = f"{ts} [{level}] {comp} {req_id} checkout_failed reason=insufficient_stock item=SKU-{line_idx:04d}"
            elif comp == "mailer":
                msg = f"{ts} [{level}] {comp} {req_id} send_failed retry=3 smtp=timeout email=user@example.com"
            elif comp == "db":
                msg = f"{ts} [{level}] {comp} {req_id} deadlock_detected transaction_id=tx-{line_idx:06d} retrying"
            else:
                msg = f"{ts} [{level}] {comp} {req_id} unexpected_error traceback=/var/log/app/trace-{line_idx}.log"
        else:  # DEBUG
            msg = f"{ts} [{level}] {comp} {req_id} step=validate_payload fields=12 valid=true"
        lines.append(msg)
        current_size += len(msg) + 1
        line_idx += 1
    return "\n".join(lines)


def _build_test_report_content(size: int = 25000) -> str:
    """生成真实风格的测试覆盖率报告内容，约 size 字符。

    模拟 pytest-cov 输出的覆盖率报告，包含各模块覆盖率、缺失行号、分支覆盖等。
    单个 tool_result 约 25KB（< PERSIST_THRESHOLD=30000，不会被 L3 persist）。
    """
    lines = [
        "========================================= test session starts =========================================",
        "platform win32 -- Python 3.11.5, pytest-7.4.0, plugg-1.0.0 -- cov-4.1.0",
        "rootdir: D:\\project, configfile: pytest.ini",
        "plugins: cov-4.1.0, mock-3.12.0, xdist-3.5.0",
        "collected 245 items",
        "",
        "tests/test_parser.py::TestParseUserInput::test_parse_simple_key_value PASSED                          [  0%]",
        "tests/test_parser.py::TestParseUserInput::test_parse_multiple_pairs PASSED                            [  0%]",
        "tests/test_parser.py::TestParseUserInput::test_parse_empty_input PASSED                              [  1%]",
        "tests/test_parser.py::TestParseUserInput::test_parse_input_with_spaces PASSED                        [  1%]",
        "tests/test_parser.py::TestParseUserInput::test_parse_invalid_input_raises PASSED                     [  2%]",
        "tests/test_parser.py::TestParseUserInput::test_parse_unicode PASSED                                  [  2%]",
    ]
    # 模拟 245 个测试用例的 PASSED/FAILED 输出
    test_files = [
        ("tests/test_parser.py", 18),
        ("tests/test_auth.py", 32),
        ("tests/test_user_service.py", 45),
        ("tests/test_user_auth_service.py", 28),
        ("tests/test_user_profile_service.py", 22),
        ("tests/test_email_service.py", 25),
        ("tests/test_register_route.py", 20),
        ("tests/test_session.py", 15),
        ("tests/test_order_service.py", 40),
    ]
    idx = 6
    total = 245
    for file, count in test_files:
        for i in range(count):
            status = "PASSED" if (idx % 13 != 0) else "FAILED"
            lines.append(f"{file}::test_case_{i+1:03d} {status}" + " " * 30 + f"[{idx*100//total:3d}%]")
            idx += 1
    lines.append("")
    lines.append("========================================= warnings summary ==========================================")
    lines.append("tests/test_parser.py::TestParseUserInput::test_parse_unicode")
    lines.append("  DeprecationWarning: Using unicode in keys is deprecated, use ascii.")
    lines.append("tests/test_auth.py::TestAuth::test_login_success")
    lines.append("  PytestUnraisableExceptionWarning: Exception ignored in: <_io.TextIOWrapper>")
    lines.append("")
    lines.append("========================================= slowest 10 durations ==========================================")
    for i in range(10):
        lines.append(f"{2.45 - i*0.15:.2f}s call     tests/test_order_service.py::test_checkout_with_payment[{i}]")
    lines.append("")
    lines.append("========================================= coverage report ==========================================")
    lines.append("Name                                       Stmts   Miss  Branch   BrPart   Cover   Missing")
    lines.append("------------------------------------------------------------------------------------------------------")
    # 模拟各模块覆盖率
    modules = [
        ("src/parser.py", 45, 2, 12, 1, "95%", "43-44, 89-90"),
        ("src/auth/login.py", 68, 8, 18, 3, "85%", "42-48, 72, 91"),
        ("src/auth/session.py", 32, 0, 8, 0, "100%", ""),
        ("src/auth/password.py", 25, 1, 6, 0, "97%", "31"),
        ("src/services/user.py", 55, 5, 14, 2, "89%", "67-70, 88"),
        ("src/services/user_auth.py", 48, 3, 12, 1, "92%", "55, 72"),
        ("src/services/user_profile.py", 35, 2, 8, 1, "94%", "42"),
        ("src/services/email.py", 42, 6, 10, 2, "82%", "38-43, 67"),
        ("src/services/order.py", 78, 12, 20, 4, "78%", "55-66, 88-92, 110"),
        ("src/routes/user.py", 28, 2, 6, 1, "92%", "35"),
        ("src/routes/auth.py", 32, 3, 8, 1, "88%", "42-44"),
        ("src/routes/register.py", 38, 4, 10, 2, "85%", "55-58"),
        ("src/routes/order.py", 45, 5, 12, 2, "86%", "67-71"),
        ("src/middleware/auth.py", 22, 1, 5, 0, "96%", "28"),
        ("src/models/user.py", 18, 0, 4, 0, "100%", ""),
        ("src/models/order.py", 25, 2, 6, 1, "91%", "45-46"),
        ("src/models/profile.py", 15, 0, 3, 0, "100%", ""),
        ("src/db.py", 20, 3, 5, 1, "82%", "25-27"),
        ("src/config.py", 30, 5, 8, 2, "78%", "42-46, 58"),
        ("src/utils.py", 28, 2, 7, 1, "92%", "33"),
        ("src/app.py", 35, 4, 9, 2, "84%", "50-53"),
        ("src/main.py", 12, 1, 3, 0, "92%", "15"),
    ]
    for name, stmts, miss, branch, brpart, cover, missing in modules:
        lines.append(f"{name:<42} {stmts:>5} {miss:>5} {branch:>7} {brpart:>7} {cover:>7}   {missing}")
    lines.append("------------------------------------------------------------------------------------------------------")
    lines.append(f"TOTAL                                       {sum(m[1] for m in modules):>5} "
                 f"{sum(m[2] for m in modules):>5} {sum(m[3] for m in modules):>7} "
                 f"{sum(m[4] for m in modules):>7} "
                 f"{sum(m[1]-m[2] for m in modules)*100//sum(m[1] for m in modules):>6}%")
    lines.append("")
    lines.append(f"========================= {sum(1 for m in modules if m[5] != '100%')} files with missing coverage =========================")
    lines.append("")
    # 补充到 size 字符
    while sum(len(l) + 1 for l in lines) < size:
        lines.append(f"# 补充说明：以上覆盖率数据基于 {total} 个测试用例，使用 pytest-cov 4.1.0 采集。")
    return "\n".join(lines)[:size]


# 预生成应用日志内容（约 50KB），用于 mixed_workload 场景触发 L3
APP_LOG_CONTENT = _build_app_log_content(50000)
# 预生成测试报告内容（约 25KB），用于 mixed_workload 场景保留中等 tool_result 触发 L4
TEST_REPORT_CONTENT = _build_test_report_content(25000)


def build_realistic_mixed_workload() -> list:
    """多场景混合工作负载，模拟一天真实开发会话。

    与 build_long_debug_session 类似，但在最后追加三个真实场景：
    1. 读取多个改动文件（10 个文件，每个 1-3KB，触发 L1+L2）
    2. 读取超大应用日志（4 个 50KB tool_result，单个 > 30000 触发 L3 persist）
    3. 读取测试覆盖率报告（3 个 25KB tool_result，单个 < 30000 不被 L3 persist，
       但作为最后 3 个 tool_result 被 L2 保留，使 L2+L3 后整体 > 50000 触发 L4）
    """
    msgs = build_long_debug_session()

    # === 场景 A：读取多个改动文件做最终检查（10 个文件） ===
    tid_start = 900
    msgs.append(assistant_with_tools(
        "我需要再读一遍所有改动的文件，做最终检查。",
        [_tool_use_block(f"final-{tid_start + i}", "read_file",
                         path=p) for i, p in enumerate([
            "src/parser.py", "src/auth/login.py", "src/auth/session.py",
            "src/services/user.py", "src/services/user_auth.py",
            "src/services/user_profile.py", "src/services/email.py",
            "src/routes/register.py", "src/routes/user.py", "src/routes/auth.py",
        ])]
    ))
    # 10 个文件 tool_result（每个 1-3KB，总约 20KB）
    big_contents = [
        FIXED_PARSER_PY, LOGIN_PY, USER_SERVICE_PY, USER_SERVICE_PY,
        REGISTER_ROUTE_PY, EMAIL_SERVICE_PY, ROUTES_USER_PY, LOGIN_PY,
        USER_SERVICE_PY, FIXED_PARSER_PY
    ]
    blocks = [tool_result_message(f"final-{tid_start + i}", c, multi_block=True)
              for i, c in enumerate(big_contents)]
    msgs.append(tool_results_message(blocks))

    # === 场景 B：用户报告线上问题，需要查看应用日志 + 测试报告 ===
    msgs.append(user_text(
        "线上反馈有用户登录失败，但本地测试正常。请看一下 app.log 里最近 4 小时的日志，"
        "特别是 auth 相关的 ERROR 和 WARN。同时运行测试看覆盖率，再对比前两天同时段的日志。"
        "日志文件比较大（每段约 50KB），可能需要耐心分析。"
    ))

    # === 场景 C：一次性批量读取所有需要的文件（7 个 tool_use） ===
    # 4 个 50KB 日志（> 30000，会被 L3 persist）+ 3 个 25KB 报告/历史日志（< 30000，不被 persist）
    # 总 275KB > 200KB，触发 L3 tool_result_budget
    batch_tid_start = 1000
    batch_tools = []
    # 4 个日志读取
    for i, h in enumerate(["09", "10", "11", "12"]):
        batch_tools.append(_tool_use_block(
            f"batch-{batch_tid_start + i}", "bash",
            command=f"awk '$1 >= \"{h}:00:00\" && $1 < \"{int(h)+1}:00:00\"' /var/log/app/app.log"))
    # 1 个测试覆盖率报告
    batch_tools.append(_tool_use_block(
        f"batch-{batch_tid_start + 4}", "bash",
        command="python -m pytest tests/ -v --cov=src --cov-report=term-missing --cov-branch"))
    # 2 个历史日志对比
    batch_tools.append(_tool_use_block(
        f"batch-{batch_tid_start + 5}", "bash",
        command="awk '$1 >= \"2026-08-04 09:00:00\" && $1 < \"2026-08-04 11:00:00\"' /var/log/app/app.log.1"))
    batch_tools.append(_tool_use_block(
        f"batch-{batch_tid_start + 6}", "bash",
        command="awk '$1 >= \"2026-08-03 09:00:00\" && $1 < \"2026-08-03 11:00:00\"' /var/log/app/app.log.2"))

    msgs.append(assistant_with_tools(
        "好的，我一次性读取所有需要的文件：4 个时段的日志、测试覆盖率报告、2 天的历史日志。",
        batch_tools
    ))

    # 最后一条 user 消息包含 7 个 tool_result（4 个 50KB + 3 个 25KB，总 275KB）
    # L3 检查 total > 200KB，persist 4 个 50KB 日志（> 30000），3 个 25KB 报告保留（< 30000）
    # L3 后最后一条 user 消息约 4*2KB + 3*25KB = 83KB
    # L1 snip（消息数 > 50，最后一条在 tail 保留）
    # L2 placeholder：最后 3 个 tool_result 保留（3 个 25KB = 75KB），前 4 个替换为 placeholder
    # L2 后约 75KB + 4*60 字符 + 前面历史（L1 snip 后约 20KB）= 约 95KB > 50KB，触发 L4
    batch_blocks = []
    # 4 个 50KB 日志
    for i in range(4):
        batch_blocks.append(tool_result_message(
            f"batch-{batch_tid_start + i}", APP_LOG_CONTENT, multi_block=True))
    # 3 个 25KB 报告/历史日志
    for i in range(4, 7):
        batch_blocks.append(tool_result_message(
            f"batch-{batch_tid_start + i}", TEST_REPORT_CONTENT, multi_block=True))
    msgs.append(tool_results_message(batch_blocks))
    return msgs


# ═══════════════════════════════════════════════════════════
#  合成数据（保留用于精确触发特定压缩层，legacy）
# ═══════════════════════════════════════════════════════════

def build_long_conversation(n: int = 60) -> list:
    """构造 n 轮 user/assistant 对话，触发 L1 snip_compact。"""
    messages = []
    for i in range(n):
        messages.append(user_text(f"用户第 {i+1} 轮提问：请帮我处理任务 {i+1}，"
                                  f"需要分析数据并生成报告。"))
        text = (f"助手第 {i+1} 轮回复：已处理任务 {i+1}。" + "详细分析过程。" * 80)
        messages.append(assistant_text(text))
    return messages


def build_many_tool_results(k: int = 10) -> list:
    """构造 k 个 tool_use + tool_result 对，触发 L2 micro_compact。"""
    messages = [user_text("开始执行多个工具调用。")]
    for i in range(k):
        tid = f"tool-{i+1}"
        messages.append(tool_use_message(tid))
        content = f"工具 {tid} 的输出结果：" + "x" * 280
        messages.append(tool_result_message(tid, content))
    messages.append(assistant_text("所有工具调用完成。"))
    return messages


def build_large_tool_result(size: int = 35000) -> list:
    """构造单个超大 tool_result，触发 L3 tool_result_budget。"""
    messages = [
        user_text("执行大型命令。"),
    ]
    messages.append({
        "role": "assistant",
        "content": [_tool_use_block(f"big-tool-{i+1}") for i in range(8)]
    })
    blocks = [tool_result_message(f"big-tool-{i+1}", "y" * size, multi_block=True)
              for i in range(8)]
    messages.append({"role": "user", "content": blocks})
    return messages


def build_over_limit_messages() -> list:
    """构造超过 CONTEXT_LIMIT(50000) 的混合数据，触发 L4 compact_history。"""
    messages = [
        user_text("开始复杂任务：先读取大文件，再分析，最后生成报告。"),
        assistant_text("好的，我将分步骤执行。首先读取大文件。"),
    ]
    for i in range(5):
        tid = f"mid-tool-{i+1}"
        messages.append(tool_use_message(tid))
        content = f"中间工具 {tid} 输出：" + "z" * 250
        messages.append(tool_result_message(tid, content))
        messages.append(assistant_text(f"步骤 {i+1} 完成，继续下一步。" + "过程记录。" * 60))

    for i in range(30):
        messages.append(user_text(f"继续执行第 {i+10} 轮。"))
        messages.append(assistant_text(f"已处理第 {i+10} 轮。" + "详细输出。" * 70))

    messages.append(assistant_text("现在读取 8 个大文件。"))
    messages.append({
        "role": "assistant",
        "content": [_tool_use_block(f"big-tool-{i+1}") for i in range(8)]
    })
    blocks = [tool_result_message(f"big-tool-{i+1}", "W" * 35000, multi_block=True)
              for i in range(8)]
    messages.append({"role": "user", "content": blocks})
    return messages


def build_mixed_scenario() -> list:
    """混合场景，确保触发全部 4 层压缩（legacy 合成版）。"""
    return build_over_limit_messages()


# ═══════════════════════════════════════════════════════════
#  真实场景的 Skill / DAG / Team 数据
# ═══════════════════════════════════════════════════════════

def build_skill_tasks() -> list:
    """构造 50 个真实代码开发任务，每个需要不同 Skill。

    返回 [(task_name, needed_skills), ...]。
    Skill 名取自项目 skills/ 目录：agent-builder、code-review、mcp-builder、pdf。
    """
    # 基础任务模板（20 个），扩展到 50 个
    base_tasks = [
        ("修复 parse_user_input 的 ValueError bug", ["code-review"]),
        ("Review PR #42 登录重构", ["code-review"]),
        ("实现用户注册功能", ["agent-builder"]),
        ("拆分 UserService 类", ["code-review"]),
        ("构建自定义数据分析 Agent", ["agent-builder"]),
        ("生成项目架构 PDF 报告", ["pdf"]),
        ("创建 MCP 插件接入外部工具", ["mcp-builder"]),
        ("Review PR #48 订单模块", ["code-review"]),
        ("构建代码审查 Agent", ["agent-builder", "code-review"]),
        ("修复 session 过期 bug", ["code-review"]),
        ("生成测试覆盖率 PDF", ["pdf"]),
        ("构建邮件处理 Agent", ["agent-builder"]),
        ("创建 MCP 文件系统插件", ["mcp-builder"]),
        ("Review PR #55 支付重构", ["code-review"]),
        ("构建 PDF 报告 Agent", ["agent-builder", "pdf"]),
        ("修复 SQL 注入漏洞", ["code-review"]),
        ("实现密码重置流程", ["agent-builder"]),
        ("生成 API 文档 PDF", ["pdf"]),
        ("创建 MCP 数据库插件", ["mcp-builder"]),
        ("Review PR #61 用户权限", ["code-review"]),
    ]
    # 扩展到 50 个：复制并微调
    all_tasks = list(base_tasks)
    for i in range(len(base_tasks), 50):
        base = base_tasks[i % len(base_tasks)]
        all_tasks.append((f"{base[0]}（迭代 {i // len(base_tasks) + 1}）", base[1]))
    return all_tasks


def build_dag_tasks() -> list:
    """构造 20 节点 DAG 任务图，模拟真实项目功能拆分。

    场景：开发"用户中心"功能，拆分为 20 个子任务，含 5 层依赖。
    """
    return [
        # 层 0：基础数据层
        {"id": "T1", "dependencies": [], "file": "src/models/user.py", "function": "define_user_model"},
        {"id": "T2", "dependencies": [], "file": "src/models/profile.py", "function": "define_profile_model"},
        {"id": "T3", "dependencies": [], "file": "src/models/session.py", "function": "define_session_model"},
        {"id": "T4", "dependencies": [], "file": "src/config.py", "function": "setup_config"},
        # 层 1：基础服务
        {"id": "T5", "dependencies": ["T1", "T4"], "file": "src/db.py", "function": "setup_database"},
        {"id": "T6", "dependencies": ["T1"], "file": "src/auth/password.py", "function": "implement_hashing"},
        {"id": "T7", "dependencies": ["T2"], "file": "src/services/profile.py", "function": "create_profile_service"},
        {"id": "T8", "dependencies": ["T3"], "file": "src/auth/session.py", "function": "create_session_service"},
        # 层 2：核心服务
        {"id": "T9", "dependencies": ["T5", "T6"], "file": "src/services/auth.py", "function": "create_auth_service"},
        {"id": "T10", "dependencies": ["T5", "T7"], "file": "src/services/user.py", "function": "create_user_service"},
        {"id": "T11", "dependencies": ["T8"], "file": "src/services/token.py", "function": "create_token_service"},
        {"id": "T12", "dependencies": ["T4"], "file": "src/services/email.py", "function": "create_email_service"},
        # 层 3：路由层
        {"id": "T13", "dependencies": ["T9"], "file": "src/routes/auth.py", "function": "create_auth_routes"},
        {"id": "T14", "dependencies": ["T10"], "file": "src/routes/user.py", "function": "create_user_routes"},
        {"id": "T15", "dependencies": ["T11", "T12"], "file": "src/routes/register.py", "function": "create_register_routes"},
        {"id": "T16", "dependencies": ["T9"], "file": "src/middleware/auth.py", "function": "create_auth_middleware"},
        # 层 4：集成层
        {"id": "T17", "dependencies": ["T13", "T14", "T15"], "file": "src/app.py", "function": "wire_app"},
        {"id": "T18", "dependencies": ["T16", "T17"], "file": "src/main.py", "function": "setup_main"},
        # 层 5：测试与文档
        {"id": "T19", "dependencies": ["T17"], "file": "tests/test_integration.py", "function": "write_integration_tests"},
        {"id": "T20", "dependencies": ["T18", "T19"], "file": "README.md", "function": "update_docs"},
    ]


def build_team_messages() -> list:
    """构造 20 个 Lead-Teammate 任务，模拟一天并行处理的真实工作负载。

    任务复杂度基于真实开发任务估算（ms 为模拟单位）。
    """
    return [
        {"task_id": "BUG-001", "complexity_ms": 350, "needs_skills": ["code-review"]},
        {"task_id": "BUG-002", "complexity_ms": 280, "needs_skills": ["code-review"]},
        {"task_id": "FEAT-001", "complexity_ms": 500, "needs_skills": ["agent-builder"]},
        {"task_id": "FEAT-002", "complexity_ms": 420, "needs_skills": ["agent-builder"]},
        {"task_id": "REVIEW-001", "complexity_ms": 300, "needs_skills": ["code-review"]},
        {"task_id": "REVIEW-002", "complexity_ms": 250, "needs_skills": ["code-review"]},
        {"task_id": "DOC-001", "complexity_ms": 200, "needs_skills": ["pdf"]},
        {"task_id": "DOC-002", "complexity_ms": 180, "needs_skills": ["pdf"]},
        {"task_id": "MCP-001", "complexity_ms": 450, "needs_skills": ["mcp-builder"]},
        {"task_id": "BUG-003", "complexity_ms": 320, "needs_skills": ["code-review"]},
        {"task_id": "FEAT-003", "complexity_ms": 380, "needs_skills": ["agent-builder"]},
        {"task_id": "REFACTOR-001", "complexity_ms": 550, "needs_skills": ["code-review"]},
        {"task_id": "REVIEW-003", "complexity_ms": 270, "needs_skills": ["code-review"]},
        {"task_id": "BUG-004", "complexity_ms": 240, "needs_skills": ["code-review"]},
        {"task_id": "DOC-003", "complexity_ms": 220, "needs_skills": ["pdf"]},
        {"task_id": "FEAT-004", "complexity_ms": 400, "needs_skills": ["agent-builder"]},
        {"task_id": "MCP-002", "complexity_ms": 480, "needs_skills": ["mcp-builder"]},
        {"task_id": "BUG-005", "complexity_ms": 300, "needs_skills": ["code-review"]},
        {"task_id": "REVIEW-004", "complexity_ms": 260, "needs_skills": ["code-review"]},
        {"task_id": "FEAT-005", "complexity_ms": 460, "needs_skills": ["agent-builder"]},
    ]


# 长程决策标记，用于验证 L4 压缩后的保留率
LONG_TERM_DECISION_MARKER = "[DECISION] 选用 PostgreSQL 作为主数据库，端口 5432，表前缀 app_"

# 真实场景注册表，供 bench_context_compact 使用
REALISTIC_SCENARIOS = [
    ("bug_fix", build_bug_fix_scenario),
    ("code_review", build_code_review_scenario),
    ("feature_impl", build_feature_impl_scenario),
    ("refactor", build_refactor_scenario),
    ("production_incident", build_production_incident_scenario),
    ("test_suite_debugging", build_test_suite_debugging_scenario),
    ("long_debug_session", build_long_debug_session),
    ("mixed_workload", build_realistic_mixed_workload),
]
